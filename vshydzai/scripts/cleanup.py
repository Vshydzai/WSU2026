"""Destroy known project stacks and verify owned billable resources disappear."""

import argparse
import os
import time

import boto3
from botocore.exceptions import ClientError


def exists(client, action, **kwargs):
    try:
        getattr(client, action)(**kwargs)
        return True
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in {"ResourceNotFoundException", "ResourceNotFound", "NotFoundException"}:
            return False
        if code == "ValidationError" and "does not exist" in exc.response["Error"]["Message"]:
            return False
        raise


def stop_pipeline(pipeline):
    executions = pipeline.get_paginator("list_pipeline_executions").paginate(pipelineName="WebHealth")
    active = [execution["pipelineExecutionId"] for page in executions
              for execution in page["pipelineExecutionSummaries"]
              if execution["status"] in {"InProgress", "Stopping"}]
    for execution_id in active:
        status = pipeline.get_pipeline_execution(pipelineName="WebHealth",
            pipelineExecutionId=execution_id)["pipelineExecution"]["status"]
        if status == "InProgress":
            pipeline.stop_pipeline_execution(pipelineName="WebHealth",
                pipelineExecutionId=execution_id, abandon=False)
    deadline = time.monotonic() + 1200
    while active:
        active = [execution_id for execution_id in active
                  if pipeline.get_pipeline_execution(pipelineName="WebHealth",
                    pipelineExecutionId=execution_id)["pipelineExecution"]["status"]
                  in {"InProgress", "Stopping"}]
        if not active:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("Pipeline actions are still stopping; retry cleanup after they finish")
        print("Waiting for running pipeline actions before deleting stacks...")
        time.sleep(5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", default=os.environ.get("DEPLOY_REGION", "us-east-2"))
    parser.add_argument("--execute", action="store_true", help="Delete the listed project stacks")
    parser.add_argument("--include-legacy", action="store_true", help="Also destroy the original VshydzaiStack")
    args = parser.parse_args()
    cfn = boto3.client("cloudformation", region_name=args.region)
    names = ["WebHealth-Pipeline", "WebHealth-prod", "WebHealth-gamma", "WebHealth-beta"]
    if args.include_legacy:
        names.append("VshydzaiStack")
    inventory = []
    for name in names:
        if not exists(cfn, "describe_stacks", StackName=name):
            continue
        inventory.extend(item for page in cfn.get_paginator("list_stack_resources").paginate(StackName=name)
                         for item in page["StackResourceSummaries"])
        print(name)
        if args.execute:
            if name == "WebHealth-Pipeline":
                pipeline = boto3.client("codepipeline", region_name=args.region)
                stop_pipeline(pipeline)
            cfn.delete_stack(StackName=name)
            cfn.get_waiter("stack_delete_complete").wait(StackName=name)
    if not args.execute:
        print("Preview complete. Add --execute to destroy these stacks.")
        return
    services = {name: boto3.client(name, region_name=args.region) for name in ("lambda", "dynamodb", "logs", "s3")}
    remaining = []
    for resource in inventory:
        physical, kind = resource.get("PhysicalResourceId"), resource["ResourceType"]
        if not physical:
            continue
        if kind == "AWS::Lambda::Function":
            present = exists(services["lambda"], "get_function", FunctionName=physical)
        elif kind == "AWS::DynamoDB::Table":
            present = exists(services["dynamodb"], "describe_table", TableName=physical)
        elif kind == "AWS::Logs::LogGroup":
            present = any(item["logGroupName"] == physical for item in services["logs"].describe_log_groups(
                logGroupNamePrefix=physical).get("logGroups", []))
        elif kind == "AWS::S3::Bucket":
            try:
                services["s3"].head_bucket(Bucket=physical)
                present = True
            except ClientError as exc:
                if exc.response["ResponseMetadata"]["HTTPStatusCode"] == 404:
                    present = False
                else:
                    raise
        else:
            continue
        if present:
            remaining.append(physical)
    if remaining:
        raise RuntimeError("Resources remain: " + ", ".join(remaining))
    print("Project functions, tables, log groups and artifact buckets are removed.")
    print("Imported CodeConnections and shared CDKToolkit bootstrap resources are outside these stacks.")


if __name__ == "__main__":
    main()
