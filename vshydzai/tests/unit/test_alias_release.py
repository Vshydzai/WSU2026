from unittest.mock import Mock

import alias_release
import pytest
import release_manager
from botocore.exceptions import ClientError


@pytest.fixture
def clients(aws_tables, monkeypatch):
    table = aws_tables["TestReleaseState"]
    functions, cloudwatch = Mock(), Mock()
    functions.get_alias.return_value = {"FunctionVersion": "1", "RevisionId": "initial"}
    cloudwatch.describe_alarms.return_value = {"MetricAlarms": [{"AlarmName": "Errors", "StateValue": "OK"}]}
    monkeypatch.setattr(alias_release, "probe", lambda *args: True)
    monkeypatch.setattr(alias_release.time, "sleep", lambda seconds: None)
    clock = iter([0, 301])
    monkeypatch.setattr(alias_release.time, "monotonic", lambda: next(clock))

    def update(**kw):
        functions.get_alias.return_value = {
            "FunctionVersion": kw["FunctionVersion"], "RoutingConfig": kw["RoutingConfig"], "RevisionId": "updated"}
        return functions.get_alias.return_value

    functions.update_alias.side_effect = update
    return functions, table, cloudwatch


def run(clients, **kwargs):
    return alias_release.release(*clients, "crawler", "2", ["Errors"], 300, "request", **kwargs)


def test_canary_records_old_version_before_weighting_and_promotes_after_checks(clients):
    functions, table, _ = clients
    assert run(clients)["action"] == "promoted"
    first, last = [call.kwargs for call in functions.update_alias.call_args_list]
    assert first["FunctionVersion"] == "1" and first["RoutingConfig"]["AdditionalVersionWeights"] == {"2": .1}
    assert last["FunctionVersion"] == "2" and last["RevisionId"] == "updated"
    item = table.get_item(Key={"id": "crawler"})["Item"]
    assert item["previous_version"] == "1" and item["current_version"] == "2"
    assert item["release_state"] == "released"


def test_first_release_has_no_previous_candidate(clients):
    functions, table, _ = clients
    functions.get_alias.return_value = None
    assert run(clients)["action"] == "created"
    functions.create_alias.assert_called_once_with(FunctionName="crawler", Name="live", FunctionVersion="2")
    item = table.get_item(Key={"id": "crawler"})["Item"]
    assert item["current_version"] == item["previous_version"] == "2"


def test_initial_fault_never_creates_live_alias(clients, monkeypatch):
    functions, table, _ = clients
    functions.get_alias.return_value = None
    monkeypatch.setattr(alias_release, "probe", lambda f, n, q, health: health is True)
    with pytest.raises(RuntimeError, match="Initial candidate"):
        run(clients)
    functions.create_alias.assert_not_called()
    assert table.scan()["Items"] == []


def test_pretraffic_failure_never_exposes_candidate(clients, monkeypatch):
    monkeypatch.setattr(alias_release, "probe", lambda *args: False)
    with pytest.raises(RuntimeError, match="pre-traffic"):
        run(clients)
    clients[0].update_alias.assert_not_called()
    assert clients[1].scan()["Items"] == []


def test_candidate_fault_restores_old_alias_and_blocks_deployment(clients, monkeypatch):
    monkeypatch.setattr(alias_release, "probe", lambda f, n, q, health: health is True or q == "live")
    with pytest.raises(RuntimeError, match="Canary probe"):
        run(clients)
    assert clients[0].get_alias.return_value["FunctionVersion"] == "1"
    assert clients[0].get_alias.return_value["RoutingConfig"]["AdditionalVersionWeights"] == {}
    assert clients[1].get_item(Key={"id": "crawler"})["Item"]["release_state"] == "rolled_back"


@pytest.mark.parametrize("response", [{"MetricAlarms": []}, {"MetricAlarms": [
    {"AlarmName": "Errors", "StateValue": "ALARM"}]}])
def test_missing_or_existing_alarm_blocks_exposure(clients, response):
    clients[2].describe_alarms.return_value = response
    with pytest.raises(RuntimeError, match="alarms are not healthy"):
        run(clients)
    clients[0].update_alias.assert_not_called()


def test_alarm_during_canary_restores_old_version(clients):
    clients[2].describe_alarms.side_effect = [
        {"MetricAlarms": [{"AlarmName": "Errors", "StateValue": "OK"}]},
        {"MetricAlarms": [{"AlarmName": "Errors", "StateValue": "ALARM"}]}]
    with pytest.raises(RuntimeError, match="operational alarm failed"):
        run(clients)
    assert clients[0].get_alias.return_value["FunctionVersion"] == "1"


def test_low_execution_budget_restores_old_version(clients):
    context = Mock()
    context.get_remaining_time_in_millis.return_value = 74000
    with pytest.raises(RuntimeError, match="budget"):
        run(clients, context=context)
    assert clients[0].get_alias.return_value["FunctionVersion"] == "1"


def test_control_plane_failure_during_probes_restores_old_version(clients):
    clients[2].describe_alarms.side_effect = [
        {"MetricAlarms": [{"AlarmName": "Errors", "StateValue": "OK"}]},
        ClientError({"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "DescribeAlarms")]
    with pytest.raises(ClientError):
        run(clients)
    assert clients[0].get_alias.return_value["FunctionVersion"] == "1"


def test_competing_weighted_alias_is_never_overwritten(clients):
    clients[0].get_alias.return_value["RoutingConfig"] = {"AdditionalVersionWeights": {"3": .1}}
    with pytest.raises(RuntimeError, match="already running"):
        run(clients)
    clients[0].update_alias.assert_not_called()


def test_alias_revision_conflict_does_not_overwrite_newer_release(clients):
    functions, table, _ = clients

    def conflict(**kw):
        functions.get_alias.return_value = {"FunctionVersion": "9", "RevisionId": "other"}
        raise ClientError({"Error": {"Code": "PreconditionFailedException", "Message": "changed"}}, "UpdateAlias")

    functions.update_alias.side_effect = conflict
    with pytest.raises(ClientError):
        run(clients)
    assert functions.get_alias.return_value["FunctionVersion"] == "9"
    functions.update_alias.assert_called_once()
    assert table.get_item(Key={"id": "crawler"})["Item"]["release_state"] == "canary"


def test_operational_rollback_during_final_probe_cannot_be_repromoted(clients, monkeypatch):
    functions, table, cloudwatch = clients
    monkeypatch.setenv("ALARM_FUNCTION_MAP", '{"Errors":"crawler"}')

    def probe(f, n, q, health):
        if q == "live":
            cloudwatch.describe_alarms.return_value = {"MetricAlarms": [{"AlarmName": "Errors", "StateValue": "ALARM"}]}
            assert release_manager.rollback("Errors", table, functions, None, cloudwatch)["action"] == "rolled_back"
            cloudwatch.describe_alarms.return_value = {"MetricAlarms": [{"AlarmName": "Errors", "StateValue": "OK"}]}
        return True

    monkeypatch.setattr(alias_release, "probe", probe)
    with pytest.raises(RuntimeError, match="Alias changed before promotion"):
        run(clients)
    assert functions.get_alias.return_value["FunctionVersion"] == "1"
    assert table.get_item(Key={"id": "crawler"})["Item"]["release_state"] == "rolled_back"


def test_noop_release_keeps_valid_previous_version(clients):
    clients[0].get_alias.return_value["FunctionVersion"] = "2"
    clients[1].put_item(Item={"id": "crawler", "current_version": "2", "previous_version": "1"})
    assert run(clients)["action"] == "unchanged"
    assert clients[1].get_item(Key={"id": "crawler"})["Item"]["previous_version"] == "1"
    clients[0].update_alias.assert_not_called()


def test_cloudformation_restoring_old_properties_does_not_reexpose_bad_version(clients):
    clients[1].put_item(Item={"id": "crawler", "current_version": "2", "previous_version": "1",
                             "release_id": "failed", "release_state": "rolled_back"})
    assert alias_release.release(*clients, "crawler", "1", ["Errors"], 300, "rollback")["action"] == "unchanged"
    item = clients[1].get_item(Key={"id": "crawler"})["Item"]
    assert item["current_version"] == item["previous_version"] == "1"
    clients[0].update_alias.assert_not_called()


def test_alias_mode_handler_never_instantiates_codedeploy(clients, monkeypatch):
    functions, table, cloudwatch = clients
    monkeypatch.setenv("DEPLOYMENT_METHOD", "alias")
    monkeypatch.setenv("RELEASE_TABLE_NAME", "TestReleaseState")
    monkeypatch.setenv("ALARM_FUNCTION_MAP", '{"Errors":"crawler"}')
    functions.get_alias.return_value = {"FunctionVersion": "2", "RevisionId": "current"}
    table.put_item(Item={"id": "crawler", "current_version": "2", "previous_version": "1"})
    cloudwatch.describe_alarms.return_value["MetricAlarms"][0]["StateValue"] = "ALARM"
    services = []

    def client(service):
        services.append(service)
        return {"lambda": functions, "cloudwatch": cloudwatch}[service]

    monkeypatch.setattr(release_manager.boto3, "client", client)
    result = release_manager.lambda_handler({"source": "aws.cloudwatch", "detail": {"alarmName": "Errors"}}, None)
    assert result["action"] == "rolled_back" and "codedeploy" not in services


@pytest.fixture
def handler_setup(clients, monkeypatch):
    monkeypatch.setenv("ALLOWED_FUNCTIONS", '["crawler"]')
    monkeypatch.setenv("RELEASE_TABLE_NAME", "TestReleaseState")
    monkeypatch.setattr(alias_release.boto3, "client", lambda service, **kw:
                        {"lambda": clients[0], "cloudwatch": clients[2]}[service])
    return {"RequestType": "Update", "RequestId": "request", "ResourceProperties": {
        "FunctionName": "crawler", "CandidateVersion": "2", "AlarmNames": ["Errors"], "CanarySeconds": "300"}}


def test_provider_returns_stable_physical_id_and_records_release(handler_setup):
    result = alias_release.lambda_handler(handler_setup, None)
    assert result["PhysicalResourceId"] == "crawler:live" and result["Data"]["version"] == "2"


def test_provider_delete_removes_owned_alias_and_history(handler_setup, clients):
    handler_setup["RequestType"] = "Delete"
    assert alias_release.lambda_handler(handler_setup, None)["PhysicalResourceId"] == "crawler:live"
    clients[0].delete_alias.assert_called_once_with(FunctionName="crawler", Name="live")
    assert clients[1].scan()["Items"] == []


@pytest.mark.parametrize("field,value", [("FunctionName", "other"), ("CandidateVersion", "$LATEST"),
                                         ("CanarySeconds", "10"), ("AlarmNames", [])])
def test_provider_rejects_wrong_target_or_shortened_canary(handler_setup, field, value):
    handler_setup["ResourceProperties"][field] = value
    with pytest.raises(ValueError):
        alias_release.lambda_handler(handler_setup, None)


def test_alias_get_ignores_only_missing_resource():
    functions = Mock()
    functions.get_alias.side_effect = ClientError(
        {"Error": {"Code": "ResourceNotFoundException", "Message": "missing"}}, "GetAlias")
    assert alias_release.get_alias(functions, "crawler") is None
    functions.get_alias.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "GetAlias")
    with pytest.raises(ClientError):
        alias_release.get_alias(functions, "crawler")
