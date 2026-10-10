import json

import alarm_logger
import pytest
import targets_api
import webhealth
from target_repository import TargetRepository

pytestmark = pytest.mark.functional


def request(method, target_id=None, payload=None, query=None):
    return targets_api.lambda_handler({
        "httpMethod": method, "resource": "/targets/{id}" if target_id else "/targets",
        "pathParameters": {"id": target_id} if target_id else None,
        "body": json.dumps(payload) if payload is not None else None,
        "queryStringParameters": query}, None)


def test_crawler_reads_only_enabled_targets(seed, monkeypatch):
    seed("active")
    seed("disabled", enabled=False)
    monkeypatch.setattr(webhealth, "fetch_status", lambda *a: 200)
    result = webhealth.lambda_handler({}, None)
    assert [item["id"] for item in result["results"]] == ["active"]


def test_empty_target_list_succeeds(aws_tables):
    assert webhealth.lambda_handler({}, None) == {"checked": 0, "results": []}


def test_one_unavailable_site_does_not_abort_other_checks(seed, monkeypatch):
    seed("good", url="https://good.example.com/")
    seed("bad", url="https://bad.example.com/")
    monkeypatch.setattr(webhealth, "fetch_status", lambda url, timeout: 503 if "bad" in url else 200)
    results = webhealth.lambda_handler({}, None)["results"]
    assert len(results) == 2
    assert sum(item["availability"] for item in results) == 1


def test_new_api_target_is_used_by_next_run(aws_tables, monkeypatch):
    created = json.loads(request("POST", payload={"name": "new", "url": "https://example.com"})["body"])
    monkeypatch.setattr(webhealth, "fetch_status", lambda *a: 200)
    assert webhealth.lambda_handler({}, None)["results"][0]["id"] == created["id"]


def test_update_disabled_target_stops_future_checks(seed, monkeypatch):
    seed()
    request("PUT", "t1", {"name": "t1", "url": "https://example.com/", "enabled": False})
    monkeypatch.setattr(webhealth, "fetch_status", lambda *a: pytest.fail("Disabled target was requested"))
    assert webhealth.lambda_handler({}, None)["checked"] == 0


def test_crawler_publishes_environment_and_target_metrics(seed, monkeypatch, capsys):
    seed()
    monkeypatch.setattr(webhealth, "fetch_status", lambda *a: 200)
    webhealth.lambda_handler({}, None)
    documents = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    target = next(item for item in documents if "Availability" in item)
    assert target["Environment"] == "test" and target["TargetId"] == "t1"
    assert target["Latency"] >= 0
    run = next(item for item in documents if "RunDurationMs" in item)
    assert run["MaxTargetLatencyMs"] == target["Latency"]


def test_crawler_follows_paginated_target_scan(monkeypatch):
    from unittest.mock import Mock
    table = Mock()
    table.scan.side_effect = [
        {"Items": [], "LastEvaluatedKey": {"id": "disabled"}},
        {"Items": [{"id": "active", "enabled": True}]}]
    assert TargetRepository(table, "crawler").enabled_targets() == [{"id": "active", "enabled": True}]
    assert table.scan.call_count == 2


def test_crawler_capacity_error_is_observable(seed, capsys):
    for n in range(26):
        seed(f"t{n}")
    with pytest.raises(ValueError, match="capacity"):
        webhealth.lambda_handler({}, None)
    assert '"CrawlerFailures": 1.0' in capsys.readouterr().out


def test_complete_crud_lifecycle_and_missing_responses(aws_tables):
    fields = {"name": "Example", "url": "https://example.com", "enabled": True}
    created_response = request("POST", payload=fields)
    assert created_response["statusCode"] == 201
    item = json.loads(created_response["body"])
    target_id = item["id"]
    assert request("GET", target_id)["statusCode"] == 200
    assert target_id in [x["id"] for x in json.loads(request("GET")["body"])["items"]]
    changed = request("PUT", target_id, {**fields, "name": "Updated", "enabled": False})
    assert json.loads(changed["body"])["created_at"] == item["created_at"]
    assert json.loads(changed["body"])["enabled"] is False
    assert request("DELETE", target_id)["statusCode"] == 204
    assert request("GET", target_id)["statusCode"] == 404
    assert request("PUT", target_id, fields)["statusCode"] == 404
    assert request("DELETE", target_id)["statusCode"] == 404


def test_invalid_api_inputs_rejected(aws_tables):
    assert request("POST", payload={"name": "", "url": "http://127.0.0.1"})["statusCode"] == 400
    assert request("GET", query={"limit": "0"})["statusCode"] == 400
    assert request("GET", query={"cursor": "bad"})["statusCode"] == 400
    event = {"httpMethod": "POST", "resource": "/targets", "body": "{invalid"}
    assert targets_api.lambda_handler(event, None)["statusCode"] == 400


def test_repeated_query_parameters_rejected(aws_tables):
    event = {"httpMethod": "GET", "resource": "/targets", "multiValueQueryStringParameters": {"limit": ["1", "2"]}}
    assert targets_api.lambda_handler(event, None)["statusCode"] == 400


def test_alarm_logger_handles_retry_without_duplicate(aws_tables):
    event = {"Records": [{"Sns": {"MessageId": "message-1",
             "Message": json.dumps({"AlarmName": "Example", "NewStateValue": "ALARM"})}}]}
    assert alarm_logger.lambda_handler(event, None)["logged"] == 1
    assert alarm_logger.lambda_handler(event, None)["logged"] == 0
    items = aws_tables["TestAlarmLogs"].scan()["Items"]
    assert len(items) == 1 and "expires_at" in items[0]


def test_beta_fault_injection_raises_real_function_error(aws_tables, monkeypatch):
    monkeypatch.setenv("FAULT_INJECTION", "true")
    assert webhealth.lambda_handler({"healthcheck": True}, None)["ok"]
    with pytest.raises(RuntimeError, match="rollback"):
        webhealth.lambda_handler({"healthcheck": "canary"}, None)


def test_database_failure_returns_safe_api_response(aws_tables, monkeypatch):
    from unittest.mock import Mock

    from botocore.exceptions import ClientError
    repo = Mock()
    repo.list.side_effect = ClientError({"Error": {"Code": "ProvisionedThroughputExceededException"}}, "Scan")
    monkeypatch.setattr(targets_api, "repository", lambda: repo)
    reply = request("GET")
    assert reply["statusCode"] == 503
    assert "Provisioned" not in reply["body"]
