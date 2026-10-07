"""Idempotent SNS alarm history with automatic expiry."""

import json
import os
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError
from telemetry import timed


def lambda_handler(event, context):
    table = boto3.resource("dynamodb").Table(os.environ["ALARM_TABLE_NAME"])
    count = 0
    for record in event["Records"]:
        message = record["Sns"]
        alarm = json.loads(message["Message"])
        item = {"id": message["MessageId"], "alarm_name": alarm.get("AlarmName", "Unknown"),
                "new_state": alarm.get("NewStateValue", "Unknown"),
                "reason": alarm.get("NewStateReason", "Unknown"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "expires_at": int(time.time()) + 30 * 86400}
        try:
            timed("alarm_logger", "Write", lambda: table.put_item(
                Item=item, ConditionExpression="attribute_not_exists(id)"))
            count += 1
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
    return {"logged": count}
