"""Operation boundaries use mocked clients; none of these tests deploy or delete AWS resources."""

import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

import aws_session
import cleanup
import collect_evidence
import demo_crud
import environment
import preflight
import pytest
import run_live_tests
import seed_targets
from botocore.exceptions import ClientError

ACCOUNT, REGION = "111111111111", "us-east-2"
CONNECTION = f"arn:aws:codeconnections:{REGION}:{ACCOUNT}:connection/test-connection"


def aws_error(code="AccessDeniedException", message="do not export this sensitive message", status=403):
    return ClientError({"Error": {"Code": code, "Message": message},
                        "ResponseMetadata": {"HTTPStatusCode": status}}, "TestOperation")


def session_with(**services):
    session = Mock()
    session.client.side_effect = lambda service, **kwargs: services[service]
    return session


def stack_client(names):
    cfn = Mock()

    def describe(StackName):
        if StackName not in names:
            raise aws_error("ValidationError", "Stack does not exist", 400)
        return {"Stacks": [{"StackId": "immutable:" + StackName, "StackStatus": "CREATE_COMPLETE"}]}

    cfn.describe_stacks.side_effect = describe
    cfn.get_paginator.return_value.paginate.return_value = [{"StackResourceSummaries": []}]
    return cfn


@pytest.mark.parametrize("account", [None, "", "123", "11111111111x"])
def test_account_is_required_before_client_creation(account, monkeypatch):
    factory = Mock()
    monkeypatch.setattr(aws_session.boto3, "Session", factory)
    with pytest.raises(ValueError, match="12-digit"):
        aws_session.checked_session(account, REGION)
    factory.assert_not_called()


def test_wrong_aws_account_is_rejected(monkeypatch):
    sts = Mock()
    sts.get_caller_identity.return_value = {"Account": "222222222222"}
    session = session_with(sts=sts)
    monkeypatch.setattr(aws_session.boto3, "Session", lambda **kwargs: session)
    with pytest.raises(ValueError, match="does not match"):
        aws_session.checked_session(ACCOUNT, REGION)
    assert session.client.call_count == 1


def test_checked_session_uses_explicit_region_and_bounded_requests(monkeypatch):
    sts = Mock()
    sts.get_caller_identity.return_value = {"Account": ACCOUNT}
    session, factory = session_with(sts=sts), Mock()
    factory.return_value = session
    monkeypatch.setattr(aws_session.boto3, "Session", factory)
    assert aws_session.checked_session(ACCOUNT, REGION) is session
    factory.assert_called_once_with(region_name=REGION)
    assert session.client.call_args.kwargs["config"].read_timeout == 10


def test_receipt_serializes_aws_datetime_and_dynamodb_decimal(tmp_path):
    output = tmp_path / "receipts" / "test.json"
    report = {"time": datetime(2026, 10, 10, tzinfo=timezone.utc), "version": Decimal("2"), "latency": Decimal("1.25")}
    aws_session.write_report(report, output)
    saved = json.loads(output.read_text())
    assert saved == {"time": "2026-10-10T00:00:00+00:00", "version": 2, "latency": 1.25}


def test_error_receipt_does_not_export_aws_messages():
    record = aws_session.error_record(aws_error())
    assert record == {"status": "unavailable", "error": "AccessDeniedException"}
    assert "sensitive" not in json.dumps(record)


@pytest.mark.parametrize("service", ["codeconnections", "codestar-connections"])
def test_preflight_accepts_both_connection_arn_generations(service):
    assert preflight.connection_location(CONNECTION.replace("codeconnections", service)) == (REGION, ACCOUNT)


def test_preflight_rejects_host_arn():
    with pytest.raises(ValueError, match="not a host"):
        preflight.connection_location(CONNECTION.replace("connection/", "host/"))


@pytest.mark.parametrize("status,provider", [("PENDING", "GitHub"), ("ERROR", "GitHub"), ("AVAILABLE", "Bitbucket")])
def test_preflight_fails_unready_or_wrong_provider_connection(status, provider):
    cfn, connections = Mock(), Mock()
    cfn.describe_stacks.return_value = {"Stacks": [{"StackStatus": "CREATE_COMPLETE"}]}
    connections.get_connection.return_value = {"Connection": {"ConnectionStatus": status, "ProviderType": provider}}
    report = preflight.readiness(session_with(cloudformation=cfn, codeconnections=connections),
                                 ACCOUNT, REGION, CONNECTION)
    assert report["ok"] is False and report["checks"][1]["status"] == "failed"


def test_preflight_permission_failure_is_not_treated_as_pass():
    cfn = Mock()
    cfn.describe_stacks.side_effect = aws_error()
    report = preflight.readiness(session_with(cloudformation=cfn), ACCOUNT, REGION)
    assert not report["ok"] and report["checks"][0]["status"] == "unavailable"


def test_preflight_identity_only_does_not_read_bootstrap_or_connections():
    session = Mock()
    report = preflight.readiness(session, ACCOUNT, REGION, identity_only=True)
    assert report["ok"] is True and report["checks"] == []
    session.client.assert_not_called()


def test_wrong_region_connection_is_rejected_before_connection_call():
    session = Mock()
    with pytest.raises(ValueError, match="account and region"):
        preflight.readiness(session, ACCOUNT, "ap-southeast-2", CONNECTION, identity_only=True)
    session.client.assert_not_called()


def test_metric_absence_is_no_data_not_a_performance_pass():
    cw = Mock()
    cw.get_metric_statistics.return_value = {"Datapoints": []}
    now = datetime.now(timezone.utc)
    result = collect_evidence.metric(session_with(cloudwatch=cw), "beta", "api", "DynamoDBReadMs", now, now)
    assert result["interpretation"] == "no_data"
    assert result["datapoints"] == []


def test_evidence_sorts_metric_timestamps():
    cw = Mock()
    cw.get_metric_statistics.return_value = {"Datapoints": [{"Timestamp": 2}, {"Timestamp": 1}]}
    result = collect_evidence.metric(session_with(cloudwatch=cw), "beta", "api", "DynamoDBReadMs", 0, 3)
    assert [item["Timestamp"] for item in result["datapoints"]] == [1, 2]


def test_observed_alarm_is_not_renamed_as_a_pass():
    assert collect_evidence.observe(lambda: {"StateValue": "ALARM"}) == {
        "status": "observed", "data": {"StateValue": "ALARM"}}


def test_evidence_permission_denial_preserves_unavailable_status():
    denied = Mock(side_effect=aws_error())
    assert collect_evidence.observe(denied)["status"] == "unavailable"


def test_cleanup_inventory_uses_only_allowlisted_stack_names():
    cfn = stack_client({"WebHealth-beta"})
    result = cleanup.inventory_stacks(cfn)
    assert result[0]["id"] == "immutable:WebHealth-beta"
    assert [call.kwargs["StackName"] for call in cfn.describe_stacks.call_args_list] == list(cleanup.STACKS)


def test_cleanup_legacy_stack_requires_explicit_flag():
    cfn = stack_client({"VshydzaiStack"})
    assert cleanup.inventory_stacks(cfn) == []
    assert cleanup.inventory_stacks(cfn, include_legacy=True)[0]["name"] == "VshydzaiStack"


def test_cleanup_inventory_denial_aborts_instead_of_skipping_stack():
    cfn = Mock()
    cfn.describe_stacks.side_effect = aws_error()
    with pytest.raises(ClientError):
        cleanup.inventory_stacks(cfn)


def test_cleanup_preview_cannot_delete_stacks():
    cfn = stack_client({"WebHealth-beta"})
    report = cleanup.cleanup(session_with(cloudformation=cfn), ACCOUNT, REGION)
    assert report["mode"] == "preview" and report["verified"] is False
    cfn.delete_stack.assert_not_called()


def test_active_pipeline_executions_are_paginated():
    pipeline = Mock()
    pipeline.get_paginator.return_value.paginate.return_value = [
        {"pipelineExecutionSummaries": [{"pipelineExecutionId": "done", "status": "Succeeded"}]},
        {"pipelineExecutionSummaries": [{"pipelineExecutionId": "active", "status": "InProgress"}]}]
    assert cleanup.active_executions(pipeline) == ["active"]


def test_cleanup_stops_gracefully_and_rechecks_new_executions(monkeypatch):
    pipeline = Mock()
    paginator = pipeline.get_paginator.return_value
    paginator.paginate.side_effect = [
        [{"pipelineExecutionSummaries": [{"pipelineExecutionId": "first", "status": "InProgress"}]}],
        [{"pipelineExecutionSummaries": [{"pipelineExecutionId": "second", "status": "InProgress"}]}],
        [{"pipelineExecutionSummaries": []}]]
    pipeline.get_pipeline_execution.return_value = {"pipelineExecution": {"status": "InProgress"}}
    monkeypatch.setattr(cleanup.time, "sleep", lambda seconds: None)
    assert cleanup.stop_pipeline(pipeline) == ["first", "second"]
    assert all(call.kwargs["abandon"] is False for call in pipeline.stop_pipeline_execution.call_args_list)


def test_cleanup_timeout_does_not_allow_stack_deletion(monkeypatch):
    pipeline = Mock()
    pipeline.get_paginator.return_value.paginate.return_value = [
        {"pipelineExecutionSummaries": [{"pipelineExecutionId": "active", "status": "Stopping"}]}]
    pipeline.get_pipeline_execution.return_value = {"pipelineExecution": {"status": "Stopping"}}
    with pytest.raises(RuntimeError, match="no stack deleted"):
        cleanup.stop_pipeline(pipeline, timeout=0)
    pipeline.stop_pipeline_execution.assert_not_called()


def test_pipeline_stop_race_is_accepted_only_after_recheck(monkeypatch):
    pipeline = Mock()
    pipeline.get_paginator.return_value.paginate.side_effect = [
        [{"pipelineExecutionSummaries": [{"pipelineExecutionId": "active", "status": "InProgress"}]}],
        [{"pipelineExecutionSummaries": []}]]
    pipeline.get_pipeline_execution.side_effect = [
        {"pipelineExecution": {"status": "InProgress"}}, {"pipelineExecution": {"status": "Stopping"}}]
    pipeline.stop_pipeline_execution.side_effect = aws_error("PipelineExecutionNotStoppableException")
    monkeypatch.setattr(cleanup.time, "sleep", lambda seconds: None)
    assert cleanup.stop_pipeline(pipeline) == ["active"]


def test_cleanup_log_verification_reads_all_pages():
    logs = Mock()
    logs.get_paginator.return_value.paginate.return_value = [
        {"logGroups": [{"logGroupName": "/aws/lambda/other"}]}, {"logGroups": [{"logGroupName": "/aws/lambda/owned"}]}]
    session = session_with(**{"lambda": Mock(), "dynamodb": Mock(), "logs": logs, "s3": Mock()})
    with pytest.raises(RuntimeError, match="owned"):
        cleanup.verify_removed(session, [{"ResourceType": "AWS::Logs::LogGroup", "PhysicalResourceId": "/aws/lambda/owned"}])


def test_bucket_access_denied_is_not_proof_of_deletion():
    s3 = Mock()
    s3.head_bucket.side_effect = aws_error()
    session = session_with(**{"lambda": Mock(), "dynamodb": Mock(), "logs": Mock(), "s3": s3})
    with pytest.raises(ClientError):
        cleanup.verify_removed(session, [{"ResourceType": "AWS::S3::Bucket", "PhysicalResourceId": "owned-bucket"}])


def test_bucket_not_found_is_verified_as_removed():
    s3 = Mock()
    s3.head_bucket.side_effect = aws_error("404", "Not Found", 404)
    session = session_with(**{"lambda": Mock(), "dynamodb": Mock(), "logs": Mock(), "s3": s3})
    assert cleanup.verify_removed(session, [{"ResourceType": "AWS::S3::Bucket", "PhysicalResourceId": "owned-bucket"}]) == [
        {"resource": "owned-bucket", "type": "AWS::S3::Bucket", "removed": True}]


def test_missing_live_stack_outputs_fail_with_clear_message(monkeypatch):
    cfn = Mock()
    cfn.describe_stacks.return_value = {"Stacks": [{"Outputs": []}]}
    monkeypatch.setattr(environment, "checked_session", lambda *args, **kwargs: session_with(cloudformation=cfn))
    with pytest.raises(ValueError, match="missing required live outputs"):
        environment.load_environment()


def test_live_runner_preserves_environment_specific_report_and_failure_exit(monkeypatch):
    run = Mock(return_value=Mock(returncode=1))
    monkeypatch.setattr(run_live_tests.subprocess, "run", run)
    monkeypatch.setattr(run_live_tests, "load_environment", lambda stack: {"API_URL": "https://test.invalid/"})
    assert run_live_tests.main(["--stack", "WebHealth-gamma"]) == 1
    assert "--junitxml=test-results/live-WebHealth-gamma.xml" in run.call_args.args[0]
    assert "junit_family=legacy" in run.call_args.args[0]
    assert run.call_args.kwargs["env"]["API_URL"] == "https://test.invalid/"


def reply(status=200, body=None):
    response = Mock(status_code=status, content=b"body" if body is not None else b"")
    response.json.return_value = body
    return response


def test_seeding_reads_all_pages_and_avoids_existing_and_duplicate_urls(monkeypatch):
    get, post = Mock(), Mock(return_value=reply(201, {"id": "new"}))
    get.side_effect = [reply(body={"items": [{"url": "https://existing.test/"}], "next_cursor": "next"}),
                       reply(body={"items": [], "next_cursor": None})]
    monkeypatch.setattr(seed_targets.requests, "get", get)
    monkeypatch.setattr(seed_targets.requests, "post", post)
    sites = [{"name": "Old", "url": "https://existing.test/"}, {"name": "New", "url": "https://new.test/"}]
    assert seed_targets.seed("https://api.test/targets", sites + sites) == [{"id": "new"}]
    post.assert_called_once()
    assert get.call_args_list[1].kwargs["params"] == {"cursor": "next"}


def test_seeding_pagination_limit_fails_before_creating_any_target(monkeypatch):
    get, post = Mock(return_value=reply(body={"items": [], "next_cursor": "again"})), Mock()
    monkeypatch.setattr(seed_targets.requests, "get", get)
    monkeypatch.setattr(seed_targets.requests, "post", post)
    with pytest.raises(RuntimeError, match="pagination"):
        seed_targets.seed("https://api.test/targets", [{"url": "https://new.test/"}])
    assert get.call_count == 100
    post.assert_not_called()


def test_seeding_requires_created_status_not_just_any_success(monkeypatch):
    monkeypatch.setattr(seed_targets.requests, "get", lambda *a, **kw: reply(body={"items": [], "next_cursor": None}))
    monkeypatch.setattr(seed_targets.requests, "post", lambda *a, **kw: reply(202, {"id": "pending"}))
    with pytest.raises(RuntimeError, match="201"):
        seed_targets.seed("https://api.test/targets", [{"url": "https://new.test/"}])


def test_seed_command_uses_the_selected_stack_and_packaged_seed(monkeypatch):
    loaded, seeded = Mock(return_value={"API_URL": "https://api.test/"}), Mock(return_value=[{"id": "new"}])
    monkeypatch.setattr(seed_targets, "load_environment", loaded)
    monkeypatch.setattr(seed_targets, "seed", seeded)
    assert seed_targets.main(["--stack", "WebHealth-gamma"]) == 0
    loaded.assert_called_once_with("WebHealth-gamma")
    assert seeded.call_args.args[0] == "https://api.test/targets"
    assert len(seeded.call_args.args[1]) == 2


def test_demo_verifies_crud_statuses_and_removes_only_its_own_target(monkeypatch):
    request = Mock(side_effect=[reply(201, {"id": "own-id"}), reply(body={"items": []}),
                                reply(body={"id": "own-id"}), reply(body={"name": "Updated"}), reply(204)])
    monkeypatch.setattr(demo_crud.requests, "request", request)
    monkeypatch.setattr(demo_crud.requests, "get", lambda *a, **kw: reply(404))
    assert demo_crud.demonstrate("https://api.test/targets") == "own-id"
    assert [call.args[0] for call in request.call_args_list] == ["POST", "GET", "GET", "PUT", "DELETE"]
    assert request.call_args.args[1] == "https://api.test/targets/own-id"


def test_demo_failure_still_removes_its_created_record(monkeypatch):
    request = Mock(side_effect=[reply(201, {"id": "own-id"}), RuntimeError("primary failure"), reply(204)])
    monkeypatch.setattr(demo_crud.requests, "request", request)
    with pytest.raises(RuntimeError, match="primary failure"):
        demo_crud.demonstrate("https://api.test/targets")
    assert request.call_args.args[:2] == ("DELETE", "https://api.test/targets/own-id")


def test_demo_reports_both_primary_and_cleanup_failures(monkeypatch):
    request = Mock(side_effect=[reply(201, {"id": "own-id"}), RuntimeError("primary"), RuntimeError("removal")])
    monkeypatch.setattr(demo_crud.requests, "request", request)
    with pytest.raises(ExceptionGroup) as failure:
        demo_crud.demonstrate("https://api.test/targets")
    assert [str(exc) for exc in failure.value.exceptions] == ["primary", "removal"]


def test_demo_checks_deleted_record_even_when_python_assertions_are_disabled(monkeypatch):
    request = Mock(side_effect=[reply(201, {"id": "own-id"}), reply(), reply(), reply(), reply(204)])
    monkeypatch.setattr(demo_crud.requests, "request", request)
    monkeypatch.setattr(demo_crud.requests, "get", lambda *a, **kw: reply(200))
    with pytest.raises(RuntimeError, match="did not return 404"):
        demo_crud.demonstrate("https://api.test/targets")


def test_demo_rejects_unexpected_success_status(monkeypatch):
    monkeypatch.setattr(demo_crud.requests, "request", lambda *a, **kw: reply(202))
    with pytest.raises(RuntimeError, match="Expected 201"):
        demo_crud.call("POST", "https://api.test/targets", expected=201)


def test_demo_command_uses_selected_environment(monkeypatch):
    demonstrated = Mock()
    monkeypatch.setattr(demo_crud, "load_environment", lambda stack: {"API_URL": "https://api.test/"})
    monkeypatch.setattr(demo_crud, "demonstrate", demonstrated)
    assert demo_crud.main(["--stack", "WebHealth-beta"]) == 0
    demonstrated.assert_called_once_with("https://api.test/targets")


def test_live_environment_sets_both_region_variables(monkeypatch):
    cfn = Mock()
    cfn.describe_stacks.return_value = {"Stacks": [{"Outputs": [
        {"OutputKey": key, "OutputValue": "value-" + key} for key in environment.OUTPUT_ENV]}]}
    monkeypatch.setattr(environment, "checked_session", lambda *a, **kw: session_with(cloudformation=cfn))
    config = environment.load_environment("WebHealth-prod", region=REGION, account=ACCOUNT)
    assert config["AWS_REGION"] == config["AWS_DEFAULT_REGION"] == REGION


def test_unknown_environment_is_rejected_before_aws_access(monkeypatch):
    checked = Mock()
    monkeypatch.setattr(environment, "checked_session", checked)
    with pytest.raises(ValueError, match="environment stack"):
        environment.load_environment("shared-production-stack")
    checked.assert_not_called()


def test_preflight_missing_pipeline_connection_fails_before_aws(monkeypatch):
    monkeypatch.delenv("CONNECTION_ARN", raising=False)
    checked = Mock()
    monkeypatch.setattr(preflight, "checked_session", checked)
    with pytest.raises(SystemExit) as error:
        preflight.main(["--pipeline"])
    assert error.value.code == 2
    checked.assert_not_called()


def test_unwritable_cleanup_checkpoint_blocks_deletion():
    cfn = stack_client({"WebHealth-beta"})
    with pytest.raises(OSError):
        cleanup.cleanup(session_with(cloudformation=cfn), ACCOUNT, REGION, execute=True,
                        checkpoint=Mock(side_effect=OSError("not writable")))
    cfn.delete_stack.assert_not_called()
