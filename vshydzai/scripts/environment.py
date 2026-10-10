"""Read live configuration from the selected CloudFormation stack."""

import os

from aws_session import checked_session, client

OUTPUT_ENV = {"ApiUrl": "API_URL", "TargetsTable": "TARGETS_TABLE_NAME",
              "CrawlerFunction": "CRAWLER_FUNCTION_NAME", "AlarmTopicArn": "ALARM_TOPIC_ARN",
              "AlarmTable": "ALARM_TABLE_NAME", "ReleaseTable": "RELEASE_TABLE_NAME"}


def load_environment(stack="WebHealth-beta", region=None, account=None):
    if stack not in {"WebHealth-beta", "WebHealth-gamma", "WebHealth-prod"}:
        raise ValueError("Select a WebHealth environment stack")
    region = region or os.environ.get("DEPLOY_REGION", "us-east-2")
    session = checked_session(account or os.environ.get("DEPLOY_ACCOUNT"), region)
    record = client(session, "cloudformation").describe_stacks(StackName=stack)["Stacks"][0]
    outputs = {item["OutputKey"]: item["OutputValue"] for item in record.get("Outputs", [])}
    missing = sorted(set(OUTPUT_ENV) - outputs.keys())
    if missing:
        raise ValueError("Stack is missing required live outputs: " + ", ".join(missing))
    return {name: outputs[key] for key, name in OUTPUT_ENV.items()} | {"AWS_DEFAULT_REGION": region, "AWS_REGION": region}
