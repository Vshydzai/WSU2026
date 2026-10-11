"""Real loopback HTTP checks. The simulator is not deployed-AWS integration evidence."""

import json
import threading
from contextlib import closing
from http.client import HTTPConnection

import pytest
import targets_api
from botocore.exceptions import ClientError
from serve_dashboard import dashboard_server

pytestmark = pytest.mark.functional


@pytest.fixture
def local_server():
    with dashboard_server(0, demo=True) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        yield server
        server.shutdown()
        worker.join(timeout=2)


def call(server, method, path, payload=None, raw=None, headers=None):
    with closing(HTTPConnection("127.0.0.1", server.server_port, timeout=3)) as connection:
        body = raw if raw is not None else json.dumps(payload) if payload is not None else None
        connection.request(method, path, body=body, headers=headers or {"Content-Type": "application/json"})
        response = connection.getresponse()
        content = response.read()
        return response.status, dict(response.getheaders()), content


def test_browser_assets_and_configuration_are_served_without_exposing_repository(local_server):
    assert local_server.server_address[0] == "127.0.0.1"
    status, headers, content = call(local_server, "GET", "/")
    assert status == 200 and b'Target manager' in content
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert headers["Cache-Control"] == "no-store"
    for path in ("/app.mjs", "/api-client.mjs", "/view-model.mjs"):
        status, headers, _ = call(local_server, "GET", path)
        assert status == 200 and headers["Content-Type"] == "text/javascript"
    assert call(local_server, "GET", "/styles.css")[0] == 200
    config = json.loads(call(local_server, "GET", "/config.json")[2])
    assert config == {"demo": True, "api_url": "/api", "environment": ""}
    assert call(local_server, "HEAD", "/")[2] == b""
    for path in ("/.env", "/../README.md", "/%2e%2e/README.md", "/tests/", "/vshydzai/scripts/environment.py"):
        assert call(local_server, "GET", path)[0] == 404


def test_real_http_complete_simulated_crud_lifecycle(local_server):
    fields = {"name": "HTTP target", "url": "https://example.com", "enabled": True}
    status, _, content = call(local_server, "POST", "/api/targets", fields)
    assert status == 201
    item = json.loads(content)
    path = "/api/targets/" + item["id"]
    assert json.loads(call(local_server, "GET", path)[2]) == item
    page = json.loads(call(local_server, "GET", "/api/targets?limit=1")[2])
    assert len(page["items"]) == 1 and page["next_cursor"]
    changed = json.loads(call(local_server, "PUT", path, {**fields, "enabled": False})[2])
    assert changed["enabled"] is False and changed["created_at"] == item["created_at"]
    # Delete once and verify all future reads/writes return 404.
    deleted_status, _, deleted_body = call(local_server, "DELETE", path)
    assert deleted_status == 204 and deleted_body == b""
    assert call(local_server, "GET", path)[0] == 404
    assert call(local_server, "PUT", path, fields)[0] == 404
    assert call(local_server, "DELETE", path)[0] == 404


@pytest.mark.parametrize("method,path,raw", [
    ("POST", "/api/targets", "bad json"), ("POST", "/api/targets", '{"name": NaN}'),
    ("POST", "/api/targets", '"' + "a" * 16385 + '"'),
    ("POST", "/api/targets", '{"name":"local","url":"http://127.0.0.1"}'),
    ("POST", "/api/targets", ""), ("GET", "/api/targets?limit=0", None),
    ("GET", "/api/targets?limit=1&limit=2", None), ("GET", "/api/targets?unknown=1", None),
    ("GET", "/api/targets?cursor=bad", None),
], ids=["bad-json", "non-finite", "oversize", "private-address", "empty", "invalid-limit",
        "repeated-limit", "unknown-query", "invalid-cursor"])
def test_real_http_invalid_inputs_return_clear_400(local_server, method, path, raw):
    status, _, body = call(local_server, method, path, raw=raw)
    assert status == 400 and json.loads(body)["error"]


def test_simulator_rejects_unsupported_routes_and_methods(local_server):
    assert call(local_server, "POST", "/api/targets/some-id", {})[0] == 405
    assert call(local_server, "PUT", "/api/targets", {})[0] == 405
    assert call(local_server, "DELETE", "/api/targets")[0] == 405


def test_default_mode_has_no_simulator_or_aws_proxy():
    with dashboard_server(0) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            assert json.loads(call(server, "GET", "/config.json")[2]) == {
                "demo": False, "api_url": "", "environment": ""}
            assert call(server, "GET", "/api/targets")[0] == 404
            for method in ("POST", "PUT", "DELETE"):
                assert call(server, method, "/api/targets", {})[0] == 404
        finally:
            server.shutdown()
            worker.join(timeout=2)


def test_browser_receives_cors_on_actual_lambda_storage_failure(monkeypatch):
    def unavailable():
        raise ClientError({"Error": {"Code": "ServiceUnavailable", "Message": "test"}}, "Scan")
    monkeypatch.setattr(targets_api, "repository", unavailable)
    response = targets_api.lambda_handler({"httpMethod": "GET", "resource": "/targets"}, None)
    assert response["statusCode"] == 503
    assert response["headers"]["Access-Control-Allow-Origin"] == "*"
    assert json.loads(response["body"]) == {"error": "Storage temporarily unavailable"}
