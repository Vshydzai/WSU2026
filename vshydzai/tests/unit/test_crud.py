import base64
from unittest.mock import Mock

import pytest
import target_repository
import targets_api
from botocore.exceptions import ClientError
from target_repository import NotFound, TargetRepository


def test_create_assigns_server_id_and_conditional_write():
    table = Mock()
    item = TargetRepository(table).create({"name": "x", "url": "https://example.com/", "enabled": True})
    assert len(item["id"]) == 32
    assert item["created_at"] == item["updated_at"]
    assert table.put_item.call_args.kwargs["ConditionExpression"] == "attribute_not_exists(id)"


def test_update_missing_target_does_not_create_record():
    table = Mock()
    table.update_item.side_effect = ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem")
    with pytest.raises(NotFound):
        TargetRepository(table).update("missing", {"name": "x", "url": "https://example.com", "enabled": True})


def test_corrupt_cursor_returns_validation_error():
    with pytest.raises(ValueError, match="cursor"):
        TargetRepository(Mock()).list(cursor="invalid")
    with pytest.raises(ValueError, match="cursor"):
        TargetRepository(Mock()).list(cursor=base64.urlsafe_b64encode(b'["wrong"]').decode())


def test_pagination_passes_only_validated_key():
    table = Mock()
    table.scan.return_value = {"Items": [], "LastEvaluatedKey": {"id": "target"}}
    repo = TargetRepository(table)
    page = repo.list(limit=1)
    repo.list(limit=1, cursor=page["next_cursor"])
    assert table.scan.call_args.kwargs["ExclusiveStartKey"] == {"id": "target"}


def test_write_time_emitted_even_when_write_fails(monkeypatch):
    ticks = iter((2, 2.01))
    recorded = Mock()
    monkeypatch.setattr(target_repository, "timed", lambda component, operation, action:
                        target_repository.__dict__["test_timed"](component, operation, action))
    import telemetry
    monkeypatch.setitem(target_repository.__dict__, "test_timed", telemetry.timed)
    monkeypatch.setattr(telemetry.time, "perf_counter", lambda: next(ticks))
    monkeypatch.setattr(telemetry, "emit", recorded)
    table = Mock()
    table.put_item.side_effect = RuntimeError("failed")
    with pytest.raises(RuntimeError):
        TargetRepository(table).create({"name": "x"})
    assert recorded.call_args.args[1]["DynamoDBWriteMs"] == pytest.approx(10)


def test_encoded_json_body_and_body_size_limit():
    assert targets_api.body({"body": base64.b64encode(b'{"name":"x"}').decode(),
                             "isBase64Encoded": True}) == {"name": "x"}
    with pytest.raises(ValueError):
        targets_api.body({"body": "x" * 16385})
    with pytest.raises(ValueError):
        targets_api.body({"body": '{"x":NaN}'})
