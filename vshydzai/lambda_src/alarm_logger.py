import json
import boto3
from datetime import datetime


dynamodb = boto3.resource("dynamodb")

table = dynamodb.Table("AlarmLogs")


def lambda_handler(event, context):

    for record in event["Records"]:

        sns_message = record["Sns"]["Message"]

        alarm_data = json.loads(sns_message)

        item = {
            "id": str(datetime.now().timestamp()),
            "alarm_name": alarm_data.get(
                "AlarmName",
                "Unknown"
            ),
            "new_state": alarm_data.get(
                "NewStateValue",
                "Unknown"
            ),
            "reason": alarm_data.get(
                "NewStateReason",
                "Unknown"
            ),
            "timestamp": datetime.now().isoformat()
        }

        table.put_item(
            Item=item
        )

    return {
        "statusCode": 200,
        "body": "Alarm logged successfully"
    }