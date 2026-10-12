"""Read observed AWS state without invoking functions, injecting alarms or writing AWS data."""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

from aws_session import ENVIRONMENT_STACKS, checked_session, client, error_record, write_report
from botocore.exceptions import BotoCoreError, ClientError


def observe(call):
    try:
        return {"status": "observed", "data": call()}
    except (BotoCoreError, ClientError) as exc:
        return error_record(exc)


def resources(cfn, stack):
    return [{key: item[key] for key in ("LogicalResourceId", "PhysicalResourceId", "ResourceType", "ResourceStatus")
             if key in item}
            for page in cfn.get_paginator("list_stack_resources").paginate(StackName=stack)
            for item in page["StackResourceSummaries"]]


def metric(session, environment, component, name, start, end):
    response = client(session, "cloudwatch").get_metric_statistics(
        Namespace="WebHealth", MetricName=name,
        Dimensions=[{"Name": "Environment", "Value": environment}, {"Name": "Component", "Value": component}],
        StartTime=start, EndTime=end, Period=60, Statistics=["Average", "Maximum", "SampleCount"])
    points = sorted(response.get("Datapoints", []), key=lambda point: point["Timestamp"])
    return {"namespace": "WebHealth", "metric": name, "component": component,
            "datapoints": points, "interpretation": "observed" if points else "no_data"}


def collect(session, account, region, stack, hours=2, now=None):
    if stack not in ENVIRONMENT_STACKS or not 1 <= hours <= 24:
        raise ValueError("Select a known environment and a 1–24 hour evidence window")
    now = now or datetime.now(timezone.utc)
    cfn = client(session, "cloudformation")
    record = cfn.describe_stacks(StackName=stack)["Stacks"][0]
    inventory = resources(cfn, stack)
    outputs = {item["OutputKey"]: item["OutputValue"] for item in record.get("Outputs", [])}
    sections = {"stack": {"status": "observed", "data": {
        "name": stack, "stack_status": record["StackStatus"], "outputs": outputs, "resources": inventory}}}
    functions = client(session, "lambda")
    cloudwatch = client(session, "cloudwatch")
    start = now - timedelta(hours=hours)
    for resource in inventory:
        name, kind = resource.get("PhysicalResourceId"), resource["ResourceType"]
        if not name:
            continue
        if kind == "AWS::Lambda::Function" and name in {outputs.get("CrawlerFunction"), outputs.get("ApiFunction")}:
            sections["alias:" + name] = observe(lambda name=name: {
                key: value for key, value in functions.get_alias(FunctionName=name, Name="live").items()
                if key in {"Name", "FunctionVersion", "RevisionId", "RoutingConfig"}})
        elif kind == "AWS::CloudWatch::Alarm":
            sections["alarm:" + name] = observe(lambda name=name: [
                {key: item[key] for key in ("AlarmName", "StateValue", "StateUpdatedTimestamp", "MetricName",
                                            "Namespace", "Threshold") if key in item}
                for item in cloudwatch.describe_alarms(AlarmNames=[name]).get("MetricAlarms", [])])
            sections["alarm_history:" + name] = observe(lambda name=name: [
                {key: item[key] for key in ("Timestamp", "HistoryItemType", "HistorySummary") if key in item}
                for item in cloudwatch.describe_alarm_history(AlarmName=name, HistoryItemType="StateUpdate",
                    StartDate=start, EndDate=now, MaxRecords=25).get("AlarmHistoryItems", [])])
        elif kind == "AWS::CodeDeploy::DeploymentGroup":
            # PhysicalResourceId alone does not identify its generated application; use function config below.
            continue
    if outputs.get("ReleaseTable"):
        from aws_session import READ_CONFIG
        sections["release_history"] = observe(lambda: session.resource("dynamodb", config=READ_CONFIG).Table(
            outputs["ReleaseTable"]).scan(Limit=25, ConsistentRead=True).get("Items", []))
    # Only select the non-secret deployment mapping; do not export the function environment.
    managers = [item["PhysicalResourceId"] for item in inventory
                if item["ResourceType"] == "AWS::Lambda::Function" and "ReleaseManager" in item["LogicalResourceId"]]
    for manager in managers:
        def deployments(manager=manager):
            import json
            config = functions.get_function_configuration(FunctionName=manager)
            if config.get("Environment", {}).get("Variables", {}).get("DEPLOYMENT_METHOD") == "alias":
                return {"method": "alias", "note": "Canary and rollback versions are in release_history"}
            mapping = json.loads(config.get("Environment", {}).get("Variables", {}).get("FUNCTION_GROUP_MAP", "{}"))
            deploy = client(session, "codedeploy")
            result = []
            for group in mapping.values():
                ids = deploy.list_deployments(applicationName=group["application"],
                    deploymentGroupName=group["group"], createTimeRange={"start": start, "end": now}).get("deployments", [])[:10]
                for deployment_id in ids:
                    info = deploy.get_deployment(deploymentId=deployment_id)["deploymentInfo"]
                    result.append({key: info[key] for key in ("deploymentId", "applicationName", "deploymentGroupName",
                                                             "status", "createTime", "completeTime", "rollbackInfo") if key in info})
            return result
        sections["deployments"] = observe(deployments)
    pipeline = client(session, "codepipeline")
    sections["pipeline"] = observe(lambda: [
        {key: item[key] for key in ("pipelineExecutionId", "status", "startTime", "lastUpdateTime", "sourceRevisions")
         if key in item}
        for item in pipeline.list_pipeline_executions(pipelineName="WebHealth", maxResults=10).get("pipelineExecutionSummaries", [])])
    for component in ("crawler", "api"):
        for name in ("DynamoDBReadMs", "DynamoDBWriteMs", "MemoryUtilizationPercent"):
            sections[f"metric:{component}:{name}"] = observe(
                lambda component=component, name=name: metric(session, stack.removeprefix("WebHealth-"),
                                                             component, name, start, now))
    sections["metric:crawler:RunDurationMs"] = observe(lambda: metric(
        session, stack.removeprefix("WebHealth-"), "crawler", "RunDurationMs", start, now))
    return {"operation": "collect_evidence", "collected_at": now, "window_start": start,
            "account": account, "region": region, "stack": stack,
            "complete": all(section["status"] == "observed" for section in sections.values()),
            "sections": sections, "limitations": [
                "A snapshot is not proof of a successful rollback; compare before/after receipts and test output",
                "Empty metric datapoints mean no_data, never a passing performance check",
                "Alarm history is limited to 25 entries per alarm; deployments to 10 per group; pipeline to 10 runs",
                "This command does not run live integration tests or collect notification emails/screenshots",
                "An observed section may show a failed deployment or an ALARM state; observed does not mean healthy"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", default=os.environ.get("DEPLOY_ACCOUNT"))
    parser.add_argument("--region", default=os.environ.get("DEPLOY_REGION", "us-east-2"))
    parser.add_argument("--stack", choices=ENVIRONMENT_STACKS, default="WebHealth-beta")
    parser.add_argument("--hours", type=int, choices=range(1, 25), default=2)
    parser.add_argument("--output", default="vshydzai/test-results/aws-evidence.json")
    args = parser.parse_args(argv)
    try:
        session = checked_session(args.account, args.region)
        report = collect(session, args.account, args.region, args.stack, args.hours)
        write_report(report, args.output)
        print(f"Saved observed AWS state to {args.output}; complete={report['complete']}")
        return 0 if report["complete"] else 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (BotoCoreError, ClientError) as exc:
        write_report({"operation": "collect_evidence", "complete": False, **error_record(exc)}, args.output)
        print(f"Evidence collection blocked: {error_record(exc)['error']}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
