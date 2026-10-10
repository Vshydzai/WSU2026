import io
import json
from datetime import datetime, timezone
from unittest.mock import Mock

import canary_traffic
import deployment_hook
import pytest
import release_manager


def deployment(status="Succeeded"):
    return {"status": status, "deploymentId": "d-test", "completeTime": datetime.now(timezone.utc),
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
    functions.invoke.return_value = {"Payload": io.BytesIO(b'{"ok":true}')}
    monkeypatch.setenv("ALLOWED_FUNCTIONS", '["crawler"]')
    monkeypatch.setattr(canary_traffic.boto3, "client", lambda service, **kw:
                        deploy if service == "codedeploy" else functions)
    monkeypatch.setattr(canary_traffic.time, "sleep", lambda seconds: None)
    result = canary_traffic.lambda_handler({"detail": {"deploymentId": "d"}}, None)
    assert result["probes"] == 1
    assert functions.invoke.call_args.kwargs["Qualifier"] == "live"


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
