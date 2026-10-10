"""Track completed releases and roll back operational alarms after deployment."""

import json
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError
from deployment_hook import deployment_target


def rollback(alarm_name, table, functions, deploy, cloudwatch):
    mapping = json.loads(os.environ["ALARM_FUNCTION_MAP"])
    function = mapping.get(alarm_name)
    if not function:
        return {"action": "ignored"}
    alarms = cloudwatch.describe_alarms(AlarmNames=[alarm_name]).get("MetricAlarms", [])
    if not alarms or alarms[0]["StateValue"] != "ALARM":
        return {"action": "alarm_recovered"}
    group = json.loads(os.environ["FUNCTION_GROUP_MAP"])[function]
    active = deploy.list_deployments(applicationName=group["application"],
                                    deploymentGroupName=group["group"],
                                    includeOnlyStatuses=["Created", "Queued", "InProgress",
                                                         "Ready", "Baking"])
    if active.get("deployments"):
        return {"action": "codedeploy_owns_active_release"}
    item = table.get_item(Key={"id": function}, ConsistentRead=True).get("Item")
    if not item or item["previous_version"] == item["current_version"]:
        return {"action": "no_previous_version"}
    alias = functions.get_alias(FunctionName=function, Name="live")
    if alias["FunctionVersion"] != item["current_version"] or alias.get(
            "RoutingConfig", {}).get("AdditionalVersionWeights"):
        return {"action": "alias_already_changed"}
    functions.update_alias(FunctionName=function, Name="live", RevisionId=alias["RevisionId"],
                           FunctionVersion=item["previous_version"],
                           RoutingConfig={"AdditionalVersionWeights": {}})
    table.update_item(Key={"id": function},
                      UpdateExpression="SET rollback_alarm = :a, rolled_back_at = :t",
                      ExpressionAttributeValues={":a": alarm_name,
                                                 ":t": datetime.now(timezone.utc).isoformat()})
    return {"action": "rolled_back", "function": function, "version": item["previous_version"]}


def lambda_handler(event, context):
    table = boto3.resource("dynamodb").Table(os.environ["RELEASE_TABLE_NAME"])
    functions, deploy = boto3.client("lambda"), boto3.client("codedeploy")
    if event.get("source") == "aws.cloudwatch":
        result = rollback(event["detail"]["alarmName"], table, functions, deploy,
                          boto3.client("cloudwatch"))
        print(json.dumps(result))
        return result
    info = deploy.get_deployment(deploymentId=event["detail"]["deploymentId"])["deploymentInfo"]
    if info["status"] != "Succeeded" or info.get("rollbackInfo", {}).get("rollbackTriggeringDeploymentId"):
        return {"action": "ignored"}
    target = deployment_target(info)
    if target["Name"] not in json.loads(os.environ["ALLOWED_FUNCTIONS"]):
        raise ValueError("Unexpected deployment target")
    alias = functions.get_alias(FunctionName=target["Name"], Name="live")
    if alias["FunctionVersion"] != str(target["TargetVersion"]):
        return {"action": "stale_release_event"}
    item = {"id": target["Name"], "current_version": str(target["TargetVersion"]),
            "previous_version": str(target["CurrentVersion"]), "deployment_id": info["deploymentId"],
            "completed_at": int(info["completeTime"].timestamp())}
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(id) OR completed_at < :t",
                       ExpressionAttributeValues={":t": item["completed_at"]})
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
    return {"action": "release_recorded"}
