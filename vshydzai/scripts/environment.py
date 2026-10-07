"""Read live configuration from the selected CloudFormation stack."""

import os

import boto3

OUTPUT_ENV = {"ApiUrl": "API_URL", "TargetsTable": "TARGETS_TABLE_NAME",
              "CrawlerFunction": "CRAWLER_FUNCTION_NAME", "AlarmTopicArn": "ALARM_TOPIC_ARN",
              "AlarmTable": "ALARM_TABLE_NAME", "ReleaseTable": "RELEASE_TABLE_NAME"}


def load_environment(stack="WebHealth-beta"):
    if stack not in {"WebHealth-beta", "WebHealth-gamma", "WebHealth-prod"}:
        raise ValueError("Select a WebHealth environment stack")
    region = os.environ.get("DEPLOY_REGION", "us-east-2")
    record = boto3.client("cloudformation", region_name=region).describe_stacks(StackName=stack)["Stacks"][0]
    outputs = {item["OutputKey"]: item["OutputValue"] for item in record.get("Outputs", [])}
    return {name: outputs[key] for key, name in OUTPUT_ENV.items()} | {"AWS_DEFAULT_REGION": region}
