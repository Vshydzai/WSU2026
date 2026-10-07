
import boto3
import pytest
from moto import mock_aws


def pytest_addoption(parser):
    parser.addoption("--run-live", action="store_true", help="Run integration tests against deployed AWS")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-live"):
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(pytest.mark.skip(reason="Requires deployed AWS resources and --run-live"))


@pytest.fixture
def aws_tables(monkeypatch):
    # Only local tests use these credentials. Live integration tests never request this fixture.
    for key, value in {"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
                       "AWS_DEFAULT_REGION": "us-east-2", "AWS_EC2_METADATA_DISABLED": "true",
                       "TARGETS_TABLE_NAME": "TestTargets", "ALARM_TABLE_NAME": "TestAlarmLogs",
                       "ENVIRONMENT": "test", "FAULT_INJECTION": "false"}.items():
        monkeypatch.setenv(key, value)
    with mock_aws():
        database = boto3.resource("dynamodb", region_name="us-east-2")
        tables = {}
        for name in ("TestTargets", "TestAlarmLogs", "TestReleaseState"):
            tables[name] = database.create_table(
                TableName=name, KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST")
        yield tables


@pytest.fixture
def seed(aws_tables):
    table = aws_tables["TestTargets"]

    def insert(target_id="t1", *, enabled=True, url="https://example.com/"):
        item = {"id": target_id, "name": target_id, "url": url, "enabled": enabled,
                "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00"}
        table.put_item(Item=item)
        return item

    return insert
