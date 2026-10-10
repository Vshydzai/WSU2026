"""Bounded test traffic during a release, with no periodic schedule."""

import json
import os
import time

import boto3
from botocore.config import Config
from deployment_hook import deployment_target
from telemetry import emit


def lambda_handler(event, context):
    deployment_id = event["detail"]["deploymentId"]
    deploy = boto3.client("codedeploy")
    info = deploy.get_deployment(deploymentId=deployment_id)["deploymentInfo"]
    target = deployment_target(info)
    if target["Name"] not in json.loads(os.environ["ALLOWED_FUNCTIONS"]):
        raise ValueError("Unexpected deployment target")
    functions = boto3.client("lambda", config=Config(read_timeout=100, retries={"max_attempts": 0}))
    deadline = time.monotonic() + 240
    probes = 0
    while time.monotonic() < deadline:
        info = deploy.get_deployment(deploymentId=deployment_id)["deploymentInfo"]
        if info["status"] not in {"Created", "Queued", "InProgress", "Ready", "Baking"}:
            break
        reply = functions.invoke(FunctionName=target["Name"], Qualifier="live",
                                 Payload=json.dumps({"healthcheck": "canary"}).encode())
        payload = json.loads(reply["Payload"].read())
        failed = bool(reply.get("FunctionError")) or payload.get("ok") is not True
        emit("canary", {"DeploymentProbeFailures": int(failed)},
             dimensions={"FunctionName": target["Name"]})
        probes += 1
        time.sleep(3)
    return {"probes": probes}
