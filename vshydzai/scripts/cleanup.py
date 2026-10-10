"""Preview or destroy only known project stacks in the explicitly checked account."""

import argparse
import os
import sys
import time
from datetime import datetime, timezone

from aws_session import checked_session, client, error_record, write_report
from botocore.exceptions import BotoCoreError, ClientError, WaiterError

STACKS = ("WebHealth-Pipeline", "WebHealth-prod", "WebHealth-gamma", "WebHealth-beta")
ACTIVE = {"InProgress", "Stopping"}


def exists(client, action, **kwargs):
    try:
        getattr(client, action)(**kwargs)
        return True
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in {"ResourceNotFoundException", "ResourceNotFound", "NotFoundException"}:
            return False
        if code == "ValidationError" and "does not exist" in exc.response["Error"].get("Message", ""):
            return False
        raise


def active_executions(pipeline):
    try:
        return [item["pipelineExecutionId"]
                for page in pipeline.get_paginator("list_pipeline_executions").paginate(pipelineName="WebHealth")
                for item in page["pipelineExecutionSummaries"] if item["status"] in ACTIVE]
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "PipelineNotFoundException":
            return []
        raise


def stop_pipeline(pipeline, timeout=1200):
    deadline, stopped = time.monotonic() + timeout, set()
    while True:
        active = active_executions(pipeline)
        if not active:
            return sorted(stopped)
        for execution_id in active:
            status = pipeline.get_pipeline_execution(pipelineName="WebHealth",
                pipelineExecutionId=execution_id)["pipelineExecution"]["status"]
            if status == "InProgress":
                try:
                    pipeline.stop_pipeline_execution(pipelineName="WebHealth",
                        pipelineExecutionId=execution_id, abandon=False)
                except ClientError as exc:
                    if exc.response["Error"]["Code"] != "PipelineExecutionNotStoppableException":
                        raise
                    current = pipeline.get_pipeline_execution(pipelineName="WebHealth",
                        pipelineExecutionId=execution_id)["pipelineExecution"]["status"]
                    if current == "InProgress":
                        raise
            stopped.add(execution_id)
        if time.monotonic() >= deadline:
            raise RuntimeError("Pipeline actions are still stopping; no stack deleted. Retry after they finish")
        print("Waiting for running pipeline actions before deleting stacks...")
        time.sleep(5)


def inventory_stacks(cfn, include_legacy=False):
    result = []
    for name in STACKS + (("VshydzaiStack",) if include_legacy else ()):
        try:
            record = cfn.describe_stacks(StackName=name)["Stacks"][0]
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ValidationError" and "does not exist" in exc.response["Error"].get("Message", ""):
                continue
            raise
        resources = [item for page in cfn.get_paginator("list_stack_resources").paginate(StackName=record["StackId"])
                     for item in page["StackResourceSummaries"]]
        result.append({"name": name, "id": record["StackId"], "status": record["StackStatus"], "resources": resources})
    return result


def verify_removed(session, inventory):
    services = {name: client(session, name) for name in ("lambda", "dynamodb", "logs", "s3")}
    checked, remaining = [], []
    for resource in inventory:
        physical, kind = resource.get("PhysicalResourceId"), resource["ResourceType"]
        if not physical:
            continue
        if kind == "AWS::Lambda::Function":
            present = exists(services["lambda"], "get_function", FunctionName=physical)
        elif kind == "AWS::DynamoDB::Table":
            present = exists(services["dynamodb"], "describe_table", TableName=physical)
        elif kind == "AWS::Logs::LogGroup":
            present = any(item["logGroupName"] == physical
                          for page in services["logs"].get_paginator("describe_log_groups").paginate(logGroupNamePrefix=physical)
                          for item in page.get("logGroups", []))
        elif kind == "AWS::S3::Bucket":
            try:
                services["s3"].head_bucket(Bucket=physical)
                present = True
            except ClientError as exc:
                if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                    present = False
                else:
                    raise
        else:
            continue
        checked.append({"resource": physical, "type": kind, "removed": not present})
        if present:
            remaining.append(physical)
    if remaining:
        raise RuntimeError("Resources remain: " + ", ".join(remaining))
    return checked


def cleanup(session, account, region, execute=False, include_legacy=False, receipt=None, checkpoint=None):
    report = receipt if receipt is not None else {}
    report.update({"operation": "cleanup", "started_at": datetime.now(timezone.utc),
                   "account": account, "region": region, "mode": "execute" if execute else "preview",
                   "verified": False, "deleted_stacks": [], "deletion_requests": [],
                   "outside_scope": ["CDKToolkit", "imported CodeConnections"]})
    cfn = client(session, "cloudformation")
    stacks = inventory_stacks(cfn, include_legacy)
    report["stacks"] = stacks
    for stack in stacks:
        print(f"{stack['name']} ({stack['status']})")
    if checkpoint:
        checkpoint(report)  # Prove the receipt path is writable before any AWS mutation.
    if not execute:
        return report
    if any(stack["name"] == "WebHealth-Pipeline" for stack in stacks):
        report["stopped_executions"] = stop_pipeline(client(session, "codepipeline"))
    for stack in stacks:
        report["deletion_requests"].append(stack["name"])
        if checkpoint:
            checkpoint(report)
        cfn.delete_stack(StackName=stack["id"])
        cfn.get_waiter("stack_delete_complete").wait(StackName=stack["id"],
                                                    WaiterConfig={"Delay": 5, "MaxAttempts": 240})
        report["deleted_stacks"].append(stack["name"])
        if checkpoint:
            checkpoint(report)
    report["resource_checks"] = verify_removed(session, [resource for stack in stacks for resource in stack["resources"]])
    report["verified"] = True
    report["completed_at"] = datetime.now(timezone.utc)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", default=os.environ.get("DEPLOY_ACCOUNT"))
    parser.add_argument("--region", default=os.environ.get("DEPLOY_REGION", "us-east-2"))
    parser.add_argument("--execute", action="store_true", help="Delete the listed project stacks")
    parser.add_argument("--include-legacy", action="store_true", help="Also destroy the original VshydzaiStack")
    parser.add_argument("--output", default="vshydzai/test-results/cleanup.json")
    args = parser.parse_args(argv)
    report = {"operation": "cleanup", "verified": False, "deleted_stacks": []}
    try:
        session = checked_session(args.account, args.region)
        cleanup(session, args.account, args.region, args.execute, args.include_legacy, report,
                checkpoint=lambda snapshot: write_report(snapshot, args.output))
        write_report(report, args.output)
        print("Known project stacks and inventoried functions/tables/logs/buckets are removed." if args.execute
              else "Preview only; nothing deleted. Add --execute to destroy these project stacks.")
        print("Imported CodeConnections and shared CDKToolkit resources are outside this cleanup.")
        return 0
    except (ValueError, RuntimeError, BotoCoreError, ClientError, WaiterError) as exc:
        report.update(error_record(exc))
        if isinstance(exc, (ValueError, RuntimeError)):
            report["reason"] = str(exc)
        write_report(report, args.output)
        print(str(exc) if isinstance(exc, (ValueError, RuntimeError)) else error_record(exc)["error"], file=sys.stderr)
        print(f"Cleanup incomplete; see {args.output} and review remaining stacks before retrying.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
