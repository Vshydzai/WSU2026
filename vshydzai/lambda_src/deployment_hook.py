"""CodeDeploy pre-traffic check of the candidate Lambda version."""

import json
import os
import re

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

PROBE_CONFIG = Config(connect_timeout=2, read_timeout=15, retries={"total_max_attempts": 1})


def deployment_target(info):
    content = info["revision"]["appSpecContent"]["content"]
    spec = json.loads(content)
    targets = []
    for resource in spec.get("Resources", []):
        for value in resource.values():
            if value["Type"] == "AWS::Lambda::Function":
                targets.append(value["Properties"])
    if len(targets) != 1:
        raise ValueError("AppSpec must contain exactly one Lambda target")
    target = targets[0]
    if not isinstance(target.get("Name"), str) or not target["Name"] or target.get("Alias") != "live":
        raise ValueError("Unexpected function or alias in AppSpec")
    for key in ("CurrentVersion", "TargetVersion"):
        if not re.fullmatch(r"[1-9][0-9]*", str(target.get(key, ""))):
            raise ValueError("AppSpec must reference published numeric versions")
    return target


def probe(functions, function, qualifier, healthcheck):
    """Fail closed on transport errors or malformed responses; never log payloads."""
    stream = None
    try:
        reply = functions.invoke(FunctionName=function, Qualifier=str(qualifier),
                                 Payload=json.dumps({"healthcheck": healthcheck}).encode())
        stream = reply.get("Payload")
        if stream is None:
            return False
        payload = json.loads(stream.read(65537))
        return not reply.get("FunctionError") and isinstance(payload, dict) and payload.get("ok") is True
    except (BotoCoreError, ClientError, ValueError, UnicodeError):
        return False
    finally:
        if stream is not None:
            stream.close()


def lambda_handler(event, context):
    deploy = boto3.client("codedeploy")
    status = "Failed"
    try:
        info = deploy.get_deployment(deploymentId=event["DeploymentId"])["deploymentInfo"]
        target = deployment_target(info)
        allowed = json.loads(os.environ["ALLOWED_FUNCTIONS"])
        if target["Name"] not in allowed:
            raise ValueError("Unexpected deployment target")
        functions = boto3.client("lambda", config=PROBE_CONFIG)
        if not probe(functions, target["Name"], target["TargetVersion"], True):
            raise ValueError("Candidate health check failed")
        status = "Succeeded"
    except Exception as exc:
        print(json.dumps({"hook_failure": type(exc).__name__}))
    deploy.put_lifecycle_event_hook_execution_status(
        deploymentId=event["DeploymentId"],
        lifecycleEventHookExecutionId=event["LifecycleEventHookExecutionId"], status=status)
    return {"status": status}
