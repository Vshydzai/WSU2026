"""Simulator contract and CLI boundaries; these tests make no AWS calls."""

import base64
from unittest.mock import MagicMock

import pytest
import serve_dashboard
import targets_api
from serve_dashboard import DemoStore, MissingTarget

FIELDS = {"name": "  Example  ", "url": "https://example.com", "enabled": True}


def test_simulator_uses_deployed_validation_and_preserves_server_fields():
    store = DemoStore(seed=False)
    created = store.create(FIELDS)
    assert created["name"] == "Example" and created["url"] == "https://example.com/"
    assert created["id"] and created["created_at"] == created["updated_at"]
    changed = store.update(created["id"], {**FIELDS, "enabled": False})
    assert changed["enabled"] is False
    assert changed["id"] == created["id"] and changed["created_at"] == created["created_at"]
    # Returned objects cannot mutate the store without a validated write.
    changed["name"] = "Outside mutation"
    assert store.get(created["id"])["name"] == "Example"
    store.delete(created["id"])
    for action in (store.get, store.delete, lambda key: store.update(key, FIELDS)):
        with pytest.raises(MissingTarget):
            action(created["id"])


@pytest.mark.parametrize("payload", [None, {}, {**FIELDS, "url": "http://127.0.0.1"},
                                    {**FIELDS, "url": "https://user:pass@example.com"},
                                    {**FIELDS, "enabled": "true"}, {**FIELDS, "extra": "no"}])
def test_simulator_rejects_the_same_unsafe_or_invalid_targets(payload):
    with pytest.raises(ValueError):
        DemoStore(seed=False).create(payload)


def test_simulator_paginates_without_duplicates_and_resets_on_restart():
    store = DemoStore(seed=False)
    ids = {store.create(FIELDS)["id"] for _ in range(5)}
    seen, cursor = [], None
    while True:
        query = {"limit": ["2"]}
        if cursor:
            query["cursor"] = [cursor]
        page = store.list(query)
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert set(seen) == ids and len(seen) == 5
    assert DemoStore(seed=False).list({}) == {"items": [], "next_cursor": None}
    assert len(DemoStore().list({})["items"]) == 2


@pytest.mark.parametrize("query", [{"limit": ["0"]}, {"limit": ["101"]}, {"limit": ["bad"]},
                                  {"limit": ["1", "2"]}, {"unknown": ["yes"]}, {"cursor": ["!"]},
                                  {"cursor": ["a" * 1025]}, {"cursor": [base64.b64encode(b"../x").decode()]},
                                  {"cursor": [base64.b64encode(b"\xff").decode()]}])
def test_simulator_rejects_invalid_pagination(query):
    with pytest.raises(ValueError):
        DemoStore().list(query)


@pytest.mark.parametrize("status", [200, 201, 204, 400, 404, 405, 500, 503])
def test_lambda_cors_is_present_on_every_business_response(status):
    response = targets_api.response(status, None if status == 204 else {"error": "test"})
    assert response["headers"]["Access-Control-Allow-Origin"] == "*"
    assert response["headers"]["Access-Control-Allow-Headers"] == "Content-Type"
    assert set(response["headers"]["Access-Control-Allow-Methods"].split(",")) == {
        "GET", "POST", "PUT", "DELETE", "OPTIONS"}
    assert "Access-Control-Allow-Credentials" not in response["headers"]
    if status == 204:
        assert response["body"] == ""


@pytest.mark.parametrize("args", [["--port", "0"], ["--port", "65536"],
                                 ["--demo", "--stack", "WebHealth-beta"], ["--stack", "not-a-stack"]])
def test_cli_rejects_invalid_or_ambiguous_server_modes(args):
    with pytest.raises(SystemExit):
        serve_dashboard.main(args)


@pytest.mark.parametrize("args,expected_demo", [([], False), (["--demo"], True),
                                              (["--stack", "WebHealth-beta", "--account", "111111111111"], False)])
def test_cli_binds_only_loopback_and_loads_aws_only_when_requested(monkeypatch, capsys, args, expected_demo):
    import environment
    load = MagicMock(return_value={"API_URL": "https://example.com/beta/"})
    monkeypatch.setattr(environment, "load_environment", load)
    server = MagicMock()
    server.__enter__.return_value = server
    server.server_port = 8787
    server.serve_forever.side_effect = KeyboardInterrupt
    build = MagicMock(return_value=server)
    monkeypatch.setattr(serve_dashboard, "dashboard_server", build)
    serve_dashboard.main(args)
    assert build.call_args.kwargs["demo"] is expected_demo
    if "--stack" in args:
        load.assert_called_once_with("WebHealth-beta", None, "111111111111")
        assert build.call_args.kwargs["api_url"] == "https://example.com/beta/"
    else:
        load.assert_not_called()
    output = capsys.readouterr().out
    assert "http://127.0.0.1:8787" in output and "Dashboard stopped" in output
    if expected_demo:
        assert "no AWS calls" in output
