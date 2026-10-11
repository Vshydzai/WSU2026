"""Complete operator-command flows with all AWS boundaries mocked."""

import json
from unittest.mock import Mock

import cleanup
import collect_evidence
import preflight
import pytest
from botocore.exceptions import ClientError

pytestmark = pytest.mark.functional
ACCOUNT, REGION = "111111111111", "us-east-2"


def test_preflight_command_writes_passed_read_only_receipt(monkeypatch, tmp_path):
    cfn, connections, session = Mock(), Mock(), Mock()
    cfn.describe_stacks.return_value = {"Stacks": [{"StackStatus": "CREATE_COMPLETE"}]}
    connections.get_connection.return_value = {"Connection": {"ConnectionStatus": "AVAILABLE", "ProviderType": "GitHub"}}
    session.client.side_effect = lambda service, **kwargs: {"cloudformation": cfn, "codeconnections": connections}[service]
    monkeypatch.setattr(preflight, "checked_session", lambda account, region: session)
    output = tmp_path / "preflight.json"
    assert preflight.main(["--account", ACCOUNT, "--pipeline", "--connection",
                          f"arn:aws:codeconnections:{REGION}:{ACCOUNT}:connection/test", "--output", str(output)]) == 0
    report = json.loads(output.read_text())
    assert report["ok"] and len(report["checks"]) == 2
    cfn.create_stack.assert_not_called()


def test_evidence_command_saves_partial_permission_failures_without_fake_passes(monkeypatch, tmp_path):
    cfn, services, session = Mock(), Mock(), Mock()
    cfn.describe_stacks.return_value = {"Stacks": [{"StackStatus": "CREATE_COMPLETE", "Outputs": []}]}
    cfn.get_paginator.return_value.paginate.return_value = [{"StackResourceSummaries": []}]
    services.get_metric_statistics.return_value = {"Datapoints": []}
    services.list_pipeline_executions.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "sensitive session detail"}}, "ListPipelineExecutions")
    session.client.side_effect = lambda service, **kwargs: cfn if service == "cloudformation" else services
    monkeypatch.setattr(collect_evidence, "checked_session", lambda account, region: session)
    output = tmp_path / "evidence.json"
    assert collect_evidence.main(["--account", ACCOUNT, "--output", str(output)]) == 1
    report = json.loads(output.read_text())
    assert report["complete"] is False
    assert report["sections"]["pipeline"]["status"] == "unavailable"
    assert report["sections"]["metric:api:DynamoDBReadMs"]["data"]["interpretation"] == "no_data"
    assert "sensitive" not in output.read_text()
    services.invoke.assert_not_called()
    services.put_metric_data.assert_not_called()
    services.set_alarm_state.assert_not_called()


def test_cleanup_command_waits_for_delete_and_writes_observed_receipt(monkeypatch, tmp_path):
    cfn, session, log = Mock(), Mock(), Mock()

    def describe(StackName):
        if StackName != "WebHealth-beta":
            raise ClientError({"Error": {"Code": "ValidationError", "Message": "does not exist"}}, "DescribeStacks")
        return {"Stacks": [{"StackId": "immutable-beta-id", "StackStatus": "CREATE_COMPLETE"}]}

    cfn.describe_stacks.side_effect = describe
    cfn.get_paginator.return_value.paginate.return_value = [{"StackResourceSummaries": [
        {"ResourceType": "AWS::Lambda::Function", "PhysicalResourceId": "WebHealth-beta-Crawler"}]}]
    missing = Mock()
    missing.get_function.side_effect = ClientError({"Error": {"Code": "ResourceNotFoundException", "Message": "gone"}},
                                                  "GetFunction")
    session.client.side_effect = lambda service, **kwargs: cfn if service == "cloudformation" else missing
    log.attach_mock(cfn.delete_stack, "delete")
    log.attach_mock(cfn.get_waiter.return_value.wait, "wait")
    log.attach_mock(missing.get_function, "verify")
    monkeypatch.setattr(cleanup, "checked_session", lambda account, region: session)
    output = tmp_path / "cleanup.json"
    assert cleanup.main(["--account", ACCOUNT, "--execute", "--output", str(output)]) == 0
    report = json.loads(output.read_text())
    assert report["verified"] is True and report["deleted_stacks"] == ["WebHealth-beta"]
    assert [call[0] for call in log.mock_calls] == ["delete", "wait", "verify"]
    cfn.delete_stack.assert_called_once_with(StackName="immutable-beta-id")


def test_cleanup_failed_identity_creates_failure_receipt_and_never_deletes(monkeypatch, tmp_path):
    session = Mock()
    monkeypatch.setattr(cleanup, "client", session.client)
    monkeypatch.setattr(cleanup, "checked_session", Mock(side_effect=ValueError("AWS session account does not match")))
    output = tmp_path / "cleanup.json"
    assert cleanup.main(["--account", ACCOUNT, "--execute", "--output", str(output)]) == 1
    assert json.loads(output.read_text())["verified"] is False
    session.client.assert_not_called()


def test_cleanup_pipeline_stop_failure_blocks_every_stack_deletion(monkeypatch):
    cfn, session = Mock(), Mock()
    cfn.describe_stacks.return_value = {"Stacks": [{"StackId": "immutable-id", "StackStatus": "CREATE_COMPLETE"}]}
    cfn.get_paginator.return_value.paginate.return_value = [{"StackResourceSummaries": []}]
    session.client.return_value = cfn
    monkeypatch.setattr(cleanup, "stop_pipeline", Mock(side_effect=RuntimeError("still stopping")))
    with pytest.raises(RuntimeError, match="still stopping"):
        cleanup.cleanup(session, ACCOUNT, REGION, execute=True)
    cfn.delete_stack.assert_not_called()


def test_evidence_snapshot_collects_aliases_alarms_releases_and_deployments_without_secrets(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    cfn, functions, cw, deploy, pipeline, session = (Mock() for _ in range(6))
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    outputs = {"CrawlerFunction": "crawler", "ApiFunction": "api", "ReleaseTable": "releases"}
    cfn.describe_stacks.return_value = {"Stacks": [{"StackStatus": "CREATE_COMPLETE", "Outputs": [
        {"OutputKey": key, "OutputValue": value} for key, value in outputs.items()]}]}
    cfn.get_paginator.return_value.paginate.return_value = [{"StackResourceSummaries": [
        {"LogicalResourceId": name, "PhysicalResourceId": name.lower(), "ResourceType": "AWS::Lambda::Function"}
        for name in ("Crawler", "Api", "ReleaseManager")] + [
        {"LogicalResourceId": "Errors", "PhysicalResourceId": "errors", "ResourceType": "AWS::CloudWatch::Alarm"},
        {"LogicalResourceId": "Group", "PhysicalResourceId": "group", "ResourceType": "AWS::CodeDeploy::DeploymentGroup"}]}]
    functions.get_alias.return_value = {"Name": "live", "FunctionVersion": "2", "RevisionId": "revision"}
    functions.get_function_configuration.return_value = {"Environment": {"Variables": {
        "FUNCTION_GROUP_MAP": json.dumps({"crawler": {"application": "app", "group": "group"}}),
        "DO_NOT_EXPORT": "not-exported"}}}
    cw.describe_alarms.return_value = {"MetricAlarms": [{"AlarmName": "errors", "StateValue": "ALARM"}]}
    cw.describe_alarm_history.return_value = {"AlarmHistoryItems": [{"Timestamp": now, "HistoryItemType": "StateUpdate"}]}
    cw.get_metric_statistics.return_value = {"Datapoints": [{"Timestamp": now, "Average": 1.0}]}
    deploy.list_deployments.return_value = {"deployments": ["d-1"]}
    deploy.get_deployment.return_value = {"deploymentInfo": {"deploymentId": "d-1", "status": "Failed",
        "createTime": now, "rollbackInfo": {"rollbackDeploymentId": "d-2"}}}
    pipeline.list_pipeline_executions.return_value = {"pipelineExecutionSummaries": [{"pipelineExecutionId": "p-1", "status": "Failed"}]}
    session.resource.return_value.Table.return_value.scan.return_value = {"Items": [{"id": "crawler", "previous_version": "1"}]}
    session.client.side_effect = lambda service, **kwargs: {
        "cloudformation": cfn, "lambda": functions, "cloudwatch": cw, "codedeploy": deploy, "codepipeline": pipeline}[service]
    monkeypatch.setattr(collect_evidence, "checked_session", lambda account, region: session)
    output = tmp_path / "observations.json"
    assert collect_evidence.main(["--account", ACCOUNT, "--output", str(output)]) == 0
    report = json.loads(output.read_text())
    assert report["complete"] is True  # Completeness, not health: actual failed states are retained.
    assert report["sections"]["alarm:errors"]["data"][0]["StateValue"] == "ALARM"
    assert report["sections"]["deployments"]["data"][0]["status"] == "Failed"
    assert report["sections"]["alias:api"]["data"]["FunctionVersion"] == "2"
    assert "not-exported" not in output.read_text()
    functions.invoke.assert_not_called()
    deploy.stop_deployment.assert_not_called()
    pipeline.start_pipeline_execution.assert_not_called()
