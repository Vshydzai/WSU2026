"""Bounded test traffic during a release, with no periodic schedule."""

import json
import os
import time

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from deployment_hook import PROBE_CONFIG, deployment_target, probe
from telemetry import emit


def lambda_handler(event, context):
    deployment_id = event["detail"]["deploymentId"]
    deploy = boto3.client("codedeploy", config=PROBE_CONFIG)
    info = deploy.get_deployment(deploymentId=deployment_id)["deploymentInfo"]
    target = deployment_target(info)
    if target["Name"] not in json.loads(os.environ["ALLOWED_FUNCTIONS"]):
        raise ValueError("Unexpected deployment target")
    functions = boto3.client("lambda", config=PROBE_CONFIG)
    deadline = time.monotonic() + 240
    probes = 0
    reason = "budget_exhausted"
    # Four bounded SDK calls need at most ~68 seconds; leave time to return cleanly.
    while deadline - time.monotonic() > 75:
        if context is not None and context.get_remaining_time_in_millis() <= 75000:
            break
        try:
            info = deploy.get_deployment(deploymentId=deployment_id)["deploymentInfo"]
            if info["status"] not in {"Created", "Queued", "InProgress", "Ready", "Baking"}:
                reason = "deployment_finished"
                break
            alias = functions.get_alias(FunctionName=target["Name"], Name="live")
        except (BotoCoreError, ClientError):
            emit("canary", {"DeploymentProbeFailures": 1}, dimensions={"FunctionName": target["Name"]})
            reason = "control_plane_failed"
            break
        weights = alias.get("RoutingConfig", {}).get("AdditionalVersionWeights", {})
        if alias["FunctionVersion"] not in {str(target["CurrentVersion"]), str(target["TargetVersion"])} or (
                weights and str(target["TargetVersion"]) not in weights):
            reason = "alias_changed"
            break
        if alias["FunctionVersion"] != str(target["TargetVersion"]) and not weights:
            # START can arrive before the pre-traffic hook completes. Do not claim canary traffic yet.
            time.sleep(3)
            continue
        # Direct candidate checks are deterministic, even if live traffic hits only the old version.
        candidate_ok = probe(functions, target["Name"], target["TargetVersion"], "canary")
        live_ok = probe(functions, target["Name"], "live", "canary")
        failed = not (candidate_ok and live_ok)
        emit("canary", {"DeploymentProbeFailures": int(failed)},
             dimensions={"FunctionName": target["Name"]})
        probes += 1
        if failed:
            reason = "probe_failed"
            break
        time.sleep(3)
    return {"probes": probes, "reason": reason}
