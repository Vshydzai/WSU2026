"""Real API Gateway, DynamoDB, Lambda and SNS checks used by each pipeline stage."""

import json
import os
import time
import uuid
from contextlib import contextmanager

import boto3
import pytest
import requests
from botocore.config import Config

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def live():
    names = ("API_URL", "TARGETS_TABLE_NAME", "CRAWLER_FUNCTION_NAME", "ALARM_TOPIC_ARN", "ALARM_TABLE_NAME")
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        pytest.fail("Missing live configuration: " + ", ".join(missing))
    return {name: os.environ[name] for name in names}


def api(live, method, path="", body=None, *, preflight_method="POST"):
    headers = {"Origin": "http://127.0.0.1:8787"}
    if method == "OPTIONS":
        headers.update({"Access-Control-Request-Method": preflight_method,
                        "Access-Control-Request-Headers": "content-type"})
    response = requests.request(method, live["API_URL"].rstrip("/") + "/targets" + path,
                                json=body, headers=headers, timeout=20)
    assert response.headers.get("Access-Control-Allow-Origin") == "*", response.headers
    assert response.headers.get("Access-Control-Allow-Credentials", "").lower() != "true"
    return response


def preflight(live, path="", method="POST"):
    response = api(live, "OPTIONS", path, preflight_method=method)
    assert response.status_code == 204, response.text
    allowed = {value.strip() for value in response.headers.get("Access-Control-Allow-Methods", "").split(",")}
    assert {"GET", "POST", "PUT", "DELETE", "OPTIONS"} <= allowed
    assert "content-type" in response.headers.get("Access-Control-Allow-Headers", "").lower()


@contextmanager
def target(live, enabled=False):
    created = api(live, "POST", body={"name": "Integration-" + uuid.uuid4().hex[:8],
                                    "url": "https://example.com/", "enabled": enabled})
    assert created.status_code == 201, created.text
    item = created.json()
    try:
        yield item
    finally:
        removed = api(live, "DELETE", "/" + item["id"])
        assert removed.status_code in {204, 404}, removed.text


def test_live_crud_with_dynamodb_read_write_timings(live, record_property):
    table = boto3.resource("dynamodb").Table(live["TARGETS_TABLE_NAME"])
    preflight(live)
    with target(live) as item:
        path = "/" + item["id"]
        preflight(live, path, "PUT")
        assert api(live, "GET", path).json()["id"] == item["id"]
        assert api(live, "GET").status_code == 200
        changed = api(live, "PUT", path, {"name": "Updated", "url": "https://example.com/", "enabled": False})
        assert changed.status_code == 200
        started = time.perf_counter()
        stored = table.get_item(Key={"id": item["id"]}, ConsistentRead=True)["Item"]
        read_ms = (time.perf_counter() - started) * 1000
        assert stored["name"] == "Updated"
        assert api(live, "DELETE", path).status_code == 204
        assert api(live, "GET", path).status_code == 404
        record_property("browser_cors_verified", "collection/item preflight and CRUD/error responses")
    benchmark = {"id": "timing_" + uuid.uuid4().hex, "name": "Timing", "url": "https://example.com/",
                 "enabled": False}
    try:
        started = time.perf_counter()
        table.put_item(Item=benchmark, ConditionExpression="attribute_not_exists(id)")
        write_ms = (time.perf_counter() - started) * 1000
        assert read_ms > 0 and write_ms > 0
        record_property("dynamodb_read_ms", round(read_ms, 3))
        record_property("dynamodb_write_ms", round(write_ms, 3))
        budget = os.environ.get("DYNAMODB_LATENCY_BUDGET_MS")
        if budget:
            assert max(read_ms, write_ms) < float(budget)
    finally:
        table.delete_item(Key={"id": benchmark["id"]})


def test_live_crawler_reads_api_target(live):
    with target(live, enabled=True) as item:
        client = boto3.client("lambda", config=Config(read_timeout=100, retries={"max_attempts": 0}))
        response = client.invoke(FunctionName=live["CRAWLER_FUNCTION_NAME"], Qualifier="live",
                                 Payload=b"{}")
        payload = json.loads(response["Payload"].read())
        assert not response.get("FunctionError"), payload
        result = next(x for x in payload["results"] if x["id"] == item["id"])
        assert 200 <= result["http_status"] < 400, result
        assert result["availability"] == 1 and result["latency_ms"] > 0, result


def test_live_sns_alarm_is_persisted(live):
    topic, table = boto3.client("sns"), boto3.resource("dynamodb").Table(live["ALARM_TABLE_NAME"])
    name = "Integration-" + uuid.uuid4().hex
    reply = topic.publish(TopicArn=live["ALARM_TOPIC_ARN"], Message=json.dumps({
        "AlarmName": name, "NewStateValue": "ALARM",
        "NewStateReason": "Integration test event; verifies SNS-to-DynamoDB delivery"}))
    message_id = reply["MessageId"]
    try:
        deadline, item = time.monotonic() + 60, None
        while time.monotonic() < deadline:
            item = table.get_item(Key={"id": message_id}, ConsistentRead=True).get("Item")
            if item:
                break
            time.sleep(2)
        assert item and item["alarm_name"] == name
        assert item["new_state"] == "ALARM" and "expires_at" in item
    finally:
        table.delete_item(Key={"id": message_id})
