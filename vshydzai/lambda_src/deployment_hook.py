"""CodeDeploy pre-traffic check of the candidate Lambda version."""

import json
import os

import boto3
from botocore.config import Config


def deployment_target(info):
    content = info["revision"]["appSpecContent"]["content"]
    spec = json.loads(content)
    for resource in spec["Resources"]:
        for value in resource.values():
            if value["Type"] == "AWS::Lambda::Function":
                return value["Properties"]
    raise ValueError("No Lambda target in AppSpec")


def lambda_handler(event, context):
    deploy = boto3.client("codedeploy")
    status = "Failed"
    try:
        info = deploy.get_deployment(deploymentId=event["DeploymentId"])["deploymentInfo"]
        target = deployment_target(info)
        allowed = json.loads(os.environ["ALLOWED_FUNCTIONS"])
        if target["Name"] not in allowed:
            raise ValueError("Unexpected deployment target")
        functions = boto3.client("lambda", config=Config(read_timeout=100, retries={"max_attempts": 0}))
        reply = functions.invoke(FunctionName=target["Name"], Qualifier=str(target["TargetVersion"]),
                                 Payload=json.dumps({"healthcheck": True}).encode())
        payload = json.loads(reply["Payload"].read())
        if reply.get("FunctionError") or payload.get("ok") is not True:
            raise ValueError("Candidate health check failed")
        status = "Succeeded"
    except Exception as exc:
        print(json.dumps({"hook_failure": type(exc).__name__}))
    deploy.put_lifecycle_event_hook_execution_status(
        deploymentId=event["DeploymentId"],
        lifecycleEventHookExecutionId=event["LifecycleEventHookExecutionId"], status=status)
    return {"status": status}
