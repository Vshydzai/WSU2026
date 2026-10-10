import io
import json
from datetime import datetime, timezone
from unittest.mock import Mock

import canary_traffic
import deployment_hook
import pytest
import release_manager
from botocore.exceptions import ClientError, ReadTimeoutError


def deployment(status="Succeeded"):
    return {"status": status, "deploymentId": "d-test", "applicationName": "app", "deploymentGroupName": "group",
            "completeTime": datetime.now(timezone.utc),
            "revision": {"appSpecContent": {"content": json.dumps({"Resources": [{
                "Function": {"Type": "AWS::Lambda::Function", "Properties": {
                    "Name": "crawler", "Alias": "live", "CurrentVersion": "1", "TargetVersion": "2"}}}]})}}}


@pytest.fixture
def rollback_clients(monkeypatch):
    monkeypatch.setenv("ALARM_FUNCTION_MAP", json.dumps({"CrawlerErrors": "crawler"}))
    monkeypatch.setenv("FUNCTION_GROUP_MAP", json.dumps({"crawler": {"application": "app", "group": "group"}}))
    table, functions, deploy, cloudwatch = Mock(), Mock(), Mock(), Mock()
    table.get_item.return_value = {"Item": {"id": "crawler", "current_version": "2", "previous_version": "1"}}
    functions.get_alias.return_value = {"FunctionVersion": "2", "RevisionId": "revision"}
    deploy.list_deployments.return_value = {"deployments": []}
    cloudwatch.describe_alarms.return_value = {"MetricAlarms": [{"StateValue": "ALARM"}]}
    return table, functions, deploy, cloudwatch


def test_operational_rollback_restores_previous_version_with_revision_guard(rollback_clients):
    result = release_manager.rollback("CrawlerErrors", *rollback_clients)
    assert result["version"] == "1"
    rollback_clients[1].update_alias.assert_called_once_with(
        FunctionName="crawler", Name="live", RevisionId="revision", FunctionVersion="1",
        RoutingConfig={"AdditionalVersionWeights": {}})


def test_recovered_alarm_does_not_roll_back(rollback_clients):
    rollback_clients[3].describe_alarms.return_value = {"MetricAlarms": [{"StateValue": "OK"}]}
    assert release_manager.rollback("CrawlerErrors", *rollback_clients)["action"] == "alarm_recovered"
    rollback_clients[1].update_alias.assert_not_called()


def test_active_codedeploy_release_prevents_competing_alias_update(rollback_clients):
    rollback_clients[2].list_deployments.return_value = {"deployments": ["active"]}
    result = release_manager.rollback("CrawlerErrors", *rollback_clients)
    assert result["action"] == "codedeploy_owns_active_release"
    rollback_clients[1].update_alias.assert_not_called()


def test_duplicate_rollback_event_preserves_restored_alias(rollback_clients):
    rollback_clients[1].get_alias.return_value = {"FunctionVersion": "1"}
    assert release_manager.rollback("CrawlerErrors", *rollback_clients)["action"] == "alias_already_changed"


def test_unknown_alarm_does_not_touch_resources(rollback_clients):
    assert release_manager.rollback("Other", *rollback_clients)["action"] == "ignored"
    rollback_clients[0].get_item.assert_not_called()


def test_first_release_has_no_rollback_candidate(rollback_clients):
    rollback_clients[0].get_item.return_value = {"Item": {"current_version": "1", "previous_version": "1"}}
    assert release_manager.rollback("CrawlerErrors", *rollback_clients)["action"] == "no_previous_version"


def test_weighted_alias_prevents_operational_rollback(rollback_clients):
    rollback_clients[1].get_alias.return_value = {
        "FunctionVersion": "2", "RoutingConfig": {"AdditionalVersionWeights": {"3": .1}}}
    assert release_manager.rollback("CrawlerErrors", *rollback_clients)["action"] == "alias_already_changed"


def test_candidate_hook_checks_new_version_and_reports_success(monkeypatch):
    deploy, functions = Mock(), Mock()
    deploy.get_deployment.return_value = {"deploymentInfo": deployment()}
    functions.invoke.return_value = {"Payload": io.BytesIO(b'{"ok":true}')}
    monkeypatch.setenv("ALLOWED_FUNCTIONS", '["crawler"]')
    monkeypatch.setattr(deployment_hook.boto3, "client", lambda service, **kw:
                        deploy if service == "codedeploy" else functions)
    result = deployment_hook.lambda_handler({"DeploymentId": "d", "LifecycleEventHookExecutionId": "h"}, None)
    assert result["status"] == "Succeeded"
    assert functions.invoke.call_args.kwargs["Qualifier"] == "2"
    assert deploy.put_lifecycle_event_hook_execution_status.call_args.kwargs["status"] == "Succeeded"


def test_candidate_hook_failure_blocks_release(monkeypatch):
    deploy, functions = Mock(), Mock()
    deploy.get_deployment.return_value = {"deploymentInfo": deployment()}
    functions.invoke.return_value = {"FunctionError": "Unhandled", "Payload": io.BytesIO(b'{"errorMessage":"broken"}')}
    monkeypatch.setenv("ALLOWED_FUNCTIONS", '["crawler"]')
    monkeypatch.setattr(deployment_hook.boto3, "client", lambda service, **kw:
                        deploy if service == "codedeploy" else functions)
    assert deployment_hook.lambda_handler({"DeploymentId": "d", "LifecycleEventHookExecutionId": "h"},
                                         None)["status"] == "Failed"


def test_successful_release_records_current_and_previous_versions(aws_tables, monkeypatch):
    table = aws_tables["TestReleaseState"]
    monkeypatch.setenv("RELEASE_TABLE_NAME", "TestReleaseState")
    monkeypatch.setenv("ALLOWED_FUNCTIONS", '["crawler"]')
    monkeypatch.setenv("FUNCTION_GROUP_MAP", json.dumps({"crawler": {"application": "app", "group": "group"}}))
    real_resource = release_manager.boto3.resource
    deploy, functions = Mock(), Mock()
    deploy.get_deployment.return_value = {"deploymentInfo": deployment()}
    functions.get_alias.return_value = {"FunctionVersion": "2"}
    monkeypatch.setattr(release_manager.boto3, "client", lambda service, **kw:
                        deploy if service == "codedeploy" else functions)
    monkeypatch.setattr(release_manager.boto3, "resource", real_resource)
    assert release_manager.lambda_handler({"source": "aws.codedeploy", "detail": {"deploymentId": "d"}}, None)[
        "action"] == "release_recorded"
    item = table.get_item(Key={"id": "crawler"})["Item"]
    assert item["previous_version"] == "1" and item["current_version"] == "2"


def test_canary_traffic_stops_when_deployment_finishes(monkeypatch):
    deploy, functions = Mock(), Mock()
    deploy.get_deployment.side_effect = [
        {"deploymentInfo": deployment("InProgress")},
        {"deploymentInfo": deployment("InProgress")},
        {"deploymentInfo": deployment("Succeeded")}]
    functions.invoke.side_effect = [{"Payload": io.BytesIO(b'{"ok":true}')} for _ in range(2)]
    functions.get_alias.return_value = {"FunctionVersion": "1", "RoutingConfig": {"AdditionalVersionWeights": {"2": .1}}}
    monkeypatch.setenv("ALLOWED_FUNCTIONS", '["crawler"]')
    monkeypatch.setattr(canary_traffic.boto3, "client", lambda service, **kw:
                        deploy if service == "codedeploy" else functions)
    monkeypatch.setattr(canary_traffic.time, "sleep", lambda seconds: None)
    result = canary_traffic.lambda_handler({"detail": {"deploymentId": "d"}}, None)
    assert result["probes"] == 1
    assert functions.invoke.call_args.kwargs["Qualifier"] == "live"
    assert [call.kwargs["Qualifier"] for call in functions.invoke.call_args_list] == ["2", "live"]
    assert result["reason"] == "deployment_finished"


def test_successful_codedeploy_rollback_never_records_bad_version_as_previous(aws_tables, monkeypatch):
    monkeypatch.setenv("RELEASE_TABLE_NAME", "TestReleaseState")
    deploy = Mock()
    info = deployment()
    info["rollbackInfo"] = {"rollbackTriggeringDeploymentId": "failed-release"}
    deploy.get_deployment.return_value = {"deploymentInfo": info}
    monkeypatch.setattr(release_manager.boto3, "client", lambda *a, **kw: deploy)
    result = release_manager.lambda_handler({"source": "aws.codedeploy", "detail": {"deploymentId": "d"}}, None)
    assert result["action"] == "ignored"
    assert aws_tables["TestReleaseState"].scan()["Items"] == []


@pytest.mark.parametrize("field,value", [("Alias", "other"), ("CurrentVersion", "$LATEST"),
                                         ("TargetVersion", "0"), ("TargetVersion", "2.0"),
                                         ("TargetVersion", "live"), ("Name", "")])
def test_appspec_rejects_unexpected_alias_or_unpublished_version(field, value):
    info = deployment()
    spec = json.loads(info["revision"]["appSpecContent"]["content"])
    spec["Resources"][0]["Function"]["Properties"][field] = value
    info["revision"]["appSpecContent"]["content"] = json.dumps(spec)
    with pytest.raises(ValueError):
        deployment_hook.deployment_target(info)


def test_appspec_rejects_multiple_lambda_targets():
    info = deployment()
    spec = json.loads(info["revision"]["appSpecContent"]["content"])
    spec["Resources"] *= 2
    info["revision"]["appSpecContent"]["content"] = json.dumps(spec)
    with pytest.raises(ValueError, match="exactly one"):
        deployment_hook.deployment_target(info)


@pytest.mark.parametrize("body", [b"not-json", b"[]", b"null", b'{"ok":1}', b'{"ok":false}'])
def test_probe_rejects_bad_responses_and_closes_stream(body):
    functions, stream = Mock(), io.BytesIO(body)
    functions.invoke.return_value = {"Payload": stream}
    assert not deployment_hook.probe(functions, "crawler", "2", True)
    assert stream.closed


def test_probe_transport_failure_fails_closed():
    functions = Mock()
    functions.invoke.side_effect = ReadTimeoutError(endpoint_url="https://lambda.test")
    assert not deployment_hook.probe(functions, "crawler", "2", True)


def test_canary_detects_candidate_failure_even_when_live_alias_is_healthy(monkeypatch):
    deploy, functions, emitted = Mock(), Mock(), Mock()
    deploy.get_deployment.return_value = {"deploymentInfo": deployment("InProgress")}
    functions.invoke.side_effect = [{"FunctionError": "Unhandled", "Payload": io.BytesIO(b'{"error":"fault"}')},
                                    {"Payload": io.BytesIO(b'{"ok":true}')}]
    functions.get_alias.return_value = {"FunctionVersion": "1", "RoutingConfig": {"AdditionalVersionWeights": {"2": .1}}}
    monkeypatch.setenv("ALLOWED_FUNCTIONS", '["crawler"]')
    monkeypatch.setattr(canary_traffic.boto3, "client", lambda service, **kw:
                        deploy if service == "codedeploy" else functions)
    monkeypatch.setattr(canary_traffic, "emit", emitted)
    assert canary_traffic.lambda_handler({"detail": {"deploymentId": "d"}}, None) == {
        "probes": 1, "reason": "probe_failed"}
    assert emitted.call_args.args[1] == {"DeploymentProbeFailures": 1}


def test_canary_respects_remaining_lambda_budget(monkeypatch):
    deploy, functions, context = Mock(), Mock(), Mock()
    deploy.get_deployment.return_value = {"deploymentInfo": deployment("InProgress")}
    context.get_remaining_time_in_millis.return_value = 54000
    monkeypatch.setenv("ALLOWED_FUNCTIONS", '["crawler"]')
    monkeypatch.setattr(canary_traffic.boto3, "client", lambda service, **kw:
                        deploy if service == "codedeploy" else functions)
    assert canary_traffic.lambda_handler({"detail": {"deploymentId": "d"}}, context)["probes"] == 0
    functions.invoke.assert_not_called()


def test_alias_revision_race_is_a_safe_skip(rollback_clients):
    rollback_clients[1].update_alias.side_effect = ClientError(
        {"Error": {"Code": "PreconditionFailedException", "Message": "revision changed"}}, "UpdateAlias")
    assert release_manager.rollback("CrawlerErrors", *rollback_clients)["action"] == "alias_changed_during_rollback"
    rollback_clients[0].update_item.assert_not_called()


def test_rollback_never_overwrites_concurrently_changed_history(rollback_clients):
    rollback_clients[0].update_item.side_effect = ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "new release"}}, "UpdateItem")
    assert release_manager.rollback("CrawlerErrors", *rollback_clients)["action"] == "rolled_back_history_changed"
    assert rollback_clients[0].update_item.call_args.kwargs["ConditionExpression"] == (
        "current_version = :c AND previous_version = :p")


def test_corrupt_release_state_does_not_update_alias(rollback_clients):
    rollback_clients[0].get_item.return_value = {"Item": {"current_version": "2", "previous_version": "$LATEST"}}
    assert release_manager.rollback("CrawlerErrors", *rollback_clients)["action"] == "invalid_release_state"
    rollback_clients[1].update_alias.assert_not_called()


@pytest.fixture
def release_setup(aws_tables, monkeypatch):
    monkeypatch.setenv("RELEASE_TABLE_NAME", "TestReleaseState")
    monkeypatch.setenv("ALLOWED_FUNCTIONS", '["crawler"]')
    monkeypatch.setenv("FUNCTION_GROUP_MAP", json.dumps({"crawler": {"application": "app", "group": "group"}}))
    deploy, functions = Mock(), Mock()
    functions.get_alias.return_value = {"FunctionVersion": "2"}
    monkeypatch.setattr(release_manager.boto3, "client", lambda service, **kw:
                        deploy if service == "codedeploy" else functions)
    return aws_tables["TestReleaseState"], deploy, functions


def test_release_history_distinguishes_completions_in_same_second(release_setup):
    table, deploy, _ = release_setup
    info = deployment()
    info["completeTime"] = datetime(2026, 10, 10, 0, 0, 0, 900000, tzinfo=timezone.utc)
    deploy.get_deployment.return_value = {"deploymentInfo": info}
    table.put_item(Item={"id": "crawler", "current_version": "1", "previous_version": "1",
                        "completed_at": int(info["completeTime"].timestamp()),
                        "completed_at_ms": int(info["completeTime"].timestamp() * 1000) - 100})
    event = {"source": "aws.codedeploy", "detail": {"deploymentId": "d"}}
    assert release_manager.lambda_handler(event, None)["action"] == "release_recorded"
    assert release_manager.lambda_handler(event, None)["action"] == "duplicate_or_older_release"
    assert table.get_item(Key={"id": "crawler"})["Item"]["current_version"] == "2"


def test_release_history_migrates_legacy_seconds_record(release_setup):
    table, deploy, _ = release_setup
    info = deployment()
    deploy.get_deployment.return_value = {"deploymentInfo": info}
    table.put_item(Item={"id": "crawler", "current_version": "1", "previous_version": "1",
                        "completed_at": int(info["completeTime"].timestamp()) - 1})
    assert release_manager.lambda_handler({"source": "aws.codedeploy", "detail": {"deploymentId": "d"}}, None)[
        "action"] == "release_recorded"
    assert "completed_at_ms" in table.get_item(Key={"id": "crawler"})["Item"]


def test_release_from_wrong_deployment_group_is_rejected(release_setup):
    table, deploy, _ = release_setup
    info = deployment()
    info["deploymentGroupName"] = "unrelated-group"
    deploy.get_deployment.return_value = {"deploymentInfo": info}
    with pytest.raises(ValueError, match="deployment group"):
        release_manager.lambda_handler({"source": "aws.codedeploy", "detail": {"deploymentId": "d"}}, None)
    assert table.scan()["Items"] == []


def test_weighted_alias_does_not_record_release(release_setup):
    table, deploy, functions = release_setup
    deploy.get_deployment.return_value = {"deploymentInfo": deployment()}
    functions.get_alias.return_value = {"FunctionVersion": "2", "RoutingConfig": {"AdditionalVersionWeights": {"3": .1}}}
    assert release_manager.lambda_handler({"source": "aws.codedeploy", "detail": {"deploymentId": "d"}}, None)[
        "action"] == "stale_release_event"
    assert table.scan()["Items"] == []


def test_canary_waits_for_actual_alias_routing_before_probing(monkeypatch):
    deploy, functions = Mock(), Mock()
    deploy.get_deployment.side_effect = [{"deploymentInfo": deployment("InProgress")},
        {"deploymentInfo": deployment("InProgress")}, {"deploymentInfo": deployment("Succeeded")}]
    functions.get_alias.return_value = {"FunctionVersion": "1"}
    monkeypatch.setenv("ALLOWED_FUNCTIONS", '["crawler"]')
    monkeypatch.setattr(canary_traffic.boto3, "client", lambda service, **kw:
                        deploy if service == "codedeploy" else functions)
    monkeypatch.setattr(canary_traffic.time, "sleep", lambda seconds: None)
    assert canary_traffic.lambda_handler({"detail": {"deploymentId": "d"}}, None) == {
        "probes": 0, "reason": "deployment_finished"}
    functions.invoke.assert_not_called()


def test_canary_does_not_probe_an_alias_owned_by_another_version(monkeypatch):
    deploy, functions = Mock(), Mock()
    deploy.get_deployment.return_value = {"deploymentInfo": deployment("InProgress")}
    functions.get_alias.return_value = {"FunctionVersion": "9"}
    monkeypatch.setenv("ALLOWED_FUNCTIONS", '["crawler"]')
    monkeypatch.setattr(canary_traffic.boto3, "client", lambda service, **kw:
                        deploy if service == "codedeploy" else functions)
    assert canary_traffic.lambda_handler({"detail": {"deploymentId": "d"}}, None)["reason"] == "alias_changed"
    functions.invoke.assert_not_called()


def test_canary_control_plane_error_emits_failure_instead_of_silent_worker_crash(monkeypatch):
    deploy, functions, emitted = Mock(), Mock(), Mock()
    deploy.get_deployment.return_value = {"deploymentInfo": deployment("InProgress")}
    functions.get_alias.side_effect = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "GetAlias")
    monkeypatch.setenv("ALLOWED_FUNCTIONS", '["crawler"]')
    monkeypatch.setattr(canary_traffic.boto3, "client", lambda service, **kw:
                        deploy if service == "codedeploy" else functions)
    monkeypatch.setattr(canary_traffic, "emit", emitted)
    assert canary_traffic.lambda_handler({"detail": {"deploymentId": "d"}}, None)["reason"] == "control_plane_failed"
    assert emitted.call_args.args[1]["DeploymentProbeFailures"] == 1
