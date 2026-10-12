"""CloudFormation-owned Lambda alias canaries without CodeDeploy.

The CDK Provider sends Create/Update/Delete requests here. Never log its event:
it contains CloudFormation's signed response URL. Synthetic probes are read-only.
"""

import json
import os
import re
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError
from deployment_hook import PROBE_CONFIG, probe
from telemetry import emit


def get_alias(functions, name):
    try:
        return functions.get_alias(FunctionName=name, Name="live")
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ResourceNotFoundException":
            return None
        raise


def weights(alias):
    return alias.get("RoutingConfig", {}).get("AdditionalVersionWeights", {})


def healthy(cloudwatch, names):
    alarms = cloudwatch.describe_alarms(AlarmNames=names).get("MetricAlarms", [])
    return ({alarm["AlarmName"] for alarm in alarms} == set(names)
            and all(alarm["StateValue"] in {"OK", "INSUFFICIENT_DATA"} for alarm in alarms))


def record(table, name, candidate, previous, request, state, old_item):
    item = {"id": name, "current_version": candidate, "previous_version": previous,
            "release_id": request, "release_state": state,
            "completed_at_ms": int(time.time() * 1000), "deployment_method": "alias"}
    if old_item:
        condition = "current_version = :c AND previous_version = :p"
        values = {":c": old_item["current_version"], ":p": old_item["previous_version"]}
        if old_item.get("release_id"):
            condition += " AND release_id = :r AND release_state = :s"
            values.update({":r": old_item["release_id"], ":s": old_item["release_state"]})
        table.put_item(Item=item, ConditionExpression=condition, ExpressionAttributeValues=values)
    else:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(id)")


def owned_canary(alias, previous, candidate):
    return (alias is not None and alias["FunctionVersion"] == previous
            and weights(alias) == {candidate: 0.1})


def restore(functions, table, name, previous, candidate, request):
    """Restore only this request's still-active canary; never overwrite newer traffic."""
    item = table.get_item(Key={"id": name}, ConsistentRead=True).get("Item", {})
    if item.get("release_id") != request or item.get("release_state") != "canary":
        return
    alias = get_alias(functions, name)
    if not (owned_canary(alias, previous, candidate)
            or (alias and alias["FunctionVersion"] == candidate and not weights(alias))):
        return
    functions.update_alias(FunctionName=name, Name="live", FunctionVersion=previous,
                           RoutingConfig={"AdditionalVersionWeights": {}}, RevisionId=alias["RevisionId"])
    table.update_item(Key={"id": name},
        UpdateExpression="SET release_state = :s, rolled_back_at = :t",
        ConditionExpression="release_id = :r AND current_version = :c AND previous_version = :p",
        ExpressionAttributeValues={":s": "rolled_back", ":t": datetime.now(timezone.utc).isoformat(),
                                   ":r": request, ":c": candidate, ":p": previous})


def release(functions, table, cloudwatch, name, candidate, names, seconds, request, context=None):
    alias = get_alias(functions, name)
    item = table.get_item(Key={"id": name}, ConsistentRead=True).get("Item")
    if alias and alias["FunctionVersion"] == candidate and not weights(alias):
        # An idempotent retry or CloudFormation restoring the old properties after
        # a failed canary. Do not replace a valid previous version on a no-op.
        if not item or item["current_version"] != candidate:
            record(table, name, candidate, candidate, request, "released", item)
        return {"version": candidate, "action": "unchanged"}
    if not probe(functions, name, candidate, True):
        raise RuntimeError("Candidate pre-traffic health check failed")
    if not alias:
        if not probe(functions, name, candidate, "canary"):
            raise RuntimeError("Initial candidate probe failed; no previous version exists")
        functions.create_alias(FunctionName=name, Name="live", FunctionVersion=candidate)
        record(table, name, candidate, candidate, request, "released", item)
        return {"version": candidate, "action": "created"}

    previous = alias["FunctionVersion"]
    if weights(alias):
        raise RuntimeError("An alias canary is already running; refusing a competing release")
    if not healthy(cloudwatch, names):
        raise RuntimeError("Operational alarms are not healthy; candidate not exposed")
    record(table, name, candidate, previous, request, "canary", item)
    try:
        functions.update_alias(FunctionName=name, Name="live", FunctionVersion=previous,
                               RoutingConfig={"AdditionalVersionWeights": {candidate: 0.1}},
                               RevisionId=alias["RevisionId"])
        deadline = time.monotonic() + seconds
        while True:
            if context is not None and context.get_remaining_time_in_millis() <= 75000:
                raise RuntimeError("Canary execution budget exhausted")
            current = get_alias(functions, name)
            state = table.get_item(Key={"id": name}, ConsistentRead=True).get("Item", {})
            if (not owned_canary(current, previous, candidate) or state.get("release_id") != request
                    or state.get("release_state") != "canary"):
                raise RuntimeError("Canary was rolled back or changed; promotion blocked")
            candidate_ok = probe(functions, name, candidate, "canary")
            live_ok = probe(functions, name, "live", "canary")
            failed = not (candidate_ok and live_ok)
            emit("canary", {"DeploymentProbeFailures": int(failed)}, dimensions={"FunctionName": name})
            if failed or not healthy(cloudwatch, names):
                raise RuntimeError("Canary probe or operational alarm failed")
            if time.monotonic() >= deadline:
                break
            time.sleep(10)
        # Fresh revision/state checks ensure an alarm rollback during the last
        # probe cannot be undone by this worker's promotion.
        current = get_alias(functions, name)
        state = table.get_item(Key={"id": name}, ConsistentRead=True).get("Item", {})
        if (not owned_canary(current, previous, candidate) or state.get("release_id") != request
                or state.get("release_state") != "canary"):
            raise RuntimeError("Alias changed before promotion")
        functions.update_alias(FunctionName=name, Name="live", FunctionVersion=candidate,
                               RoutingConfig={"AdditionalVersionWeights": {}}, RevisionId=current["RevisionId"])
        table.update_item(Key={"id": name}, UpdateExpression="SET release_state = :s",
            ConditionExpression="release_id = :r AND release_state = :active",
            ExpressionAttributeValues={":s": "released", ":r": request, ":active": "canary"})
        return {"version": candidate, "previous_version": previous, "action": "promoted"}
    except Exception:
        restore(functions, table, name, previous, candidate, request)
        raise


def lambda_handler(event, context):
    props = event["ResourceProperties"]
    name, candidate = props["FunctionName"], str(props["CandidateVersion"])
    if name not in json.loads(os.environ["ALLOWED_FUNCTIONS"]) or not re.fullmatch(r"[1-9][0-9]*", candidate):
        raise ValueError("Unexpected function or unpublished candidate version")
    functions = boto3.client("lambda", config=PROBE_CONFIG)
    table = boto3.resource("dynamodb").Table(os.environ["RELEASE_TABLE_NAME"])
    physical = f"{name}:live"
    if event["RequestType"] == "Delete":
        if get_alias(functions, name):
            functions.delete_alias(FunctionName=name, Name="live")
        table.delete_item(Key={"id": name})
        return {"PhysicalResourceId": physical}
    if event["RequestType"] not in {"Create", "Update"}:
        raise ValueError("Unexpected CloudFormation request type")
    seconds = int(props["CanarySeconds"])
    if seconds != 300 or not props.get("AlarmNames"):
        raise ValueError("Require a five-minute canary and operational alarms")
    result = release(functions, table, boto3.client("cloudwatch", config=PROBE_CONFIG), name, candidate,
                     props["AlarmNames"], seconds, event["RequestId"], context)
    print(json.dumps({"function": name, **result}))
    return {"PhysicalResourceId": physical, "Data": result}
