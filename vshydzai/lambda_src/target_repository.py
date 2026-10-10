"""Conditional target writes and measured DynamoDB access."""

import base64
import json
import os
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError
from telemetry import timed
from validation import validate_id


class NotFound(Exception):
    pass


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class TargetRepository:
    def __init__(self, table, component="api"):
        self.table, self.component = table, component

    def _run(self, operation, action):
        return timed(self.component, operation, action)

    def create(self, fields):
        now = timestamp()
        item = {**fields, "id": uuid.uuid4().hex, "created_at": now, "updated_at": now}
        self._run("Write", lambda: self.table.put_item(
            Item=item, ConditionExpression="attribute_not_exists(id)"))
        return item

    def get(self, target_id):
        result = self._run("Read", lambda: self.table.get_item(
            Key={"id": validate_id(target_id)}, ConsistentRead=True))
        if "Item" not in result:
            raise NotFound("Target does not exist")
        return result["Item"]

    def update(self, target_id, fields):
        try:
            result = self._run("Write", lambda: self.table.update_item(
                Key={"id": validate_id(target_id)}, ConditionExpression="attribute_exists(id)",
                UpdateExpression="SET #n = :n, #u = :u, #e = :e, updated_at = :t",
                ExpressionAttributeNames={"#n": "name", "#u": "url", "#e": "enabled"},
                ExpressionAttributeValues={":n": fields["name"], ":u": fields["url"],
                                           ":e": fields["enabled"], ":t": timestamp()},
                ReturnValues="ALL_NEW"))
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise NotFound("Target does not exist") from exc
            raise
        return result["Attributes"]

    def delete(self, target_id):
        try:
            self._run("Write", lambda: self.table.delete_item(
                Key={"id": validate_id(target_id)}, ConditionExpression="attribute_exists(id)"))
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise NotFound("Target does not exist") from exc
            raise

    def list(self, limit=25, cursor=None):
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        kwargs = {"Limit": limit, "ConsistentRead": True}
        if cursor:
            try:
                key = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
                if not isinstance(key, dict) or set(key) != {"id"}:
                    raise ValueError()
                validate_id(key["id"])
            except (ValueError, TypeError, UnicodeError) as exc:
                raise ValueError("Invalid cursor") from exc
            kwargs["ExclusiveStartKey"] = key
        result = self._run("Read", lambda: self.table.scan(**kwargs))
        next_cursor = None
        if result.get("LastEvaluatedKey"):
            next_cursor = base64.urlsafe_b64encode(
                json.dumps(result["LastEvaluatedKey"]).encode()).decode()
        return {"items": result.get("Items", []), "next_cursor": next_cursor}

    def enabled_targets(self, maximum=25):
        kwargs = {"FilterExpression": Attr("enabled").eq(True), "Limit": 100, "ConsistentRead": True}
        targets, pages = [], 0
        while True:
            page = self._run("Read", lambda: self.table.scan(**kwargs))
            targets.extend(page.get("Items", []))
            pages += 1
            if len(targets) > maximum or pages > 10:
                raise ValueError("Crawler capacity exceeded: reduce the enabled target list")
            if not page.get("LastEvaluatedKey"):
                return targets
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def repository(component="api"):
    return TargetRepository(boto3.resource("dynamodb").Table(os.environ["TARGETS_TABLE_NAME"]), component)
