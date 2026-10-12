#!/usr/bin/env python3
"""Synthesize an isolated environment or the full three-stage pipeline."""

import os

import aws_cdk as cdk

from vshydzai.pipeline_stack import WebHealthPipeline
from vshydzai.vshydzai_stack import VshydzaiStack

app = cdk.App()
account = os.environ.get("DEPLOY_ACCOUNT") or os.environ.get("CDK_DEFAULT_ACCOUNT")
region = os.environ.get("DEPLOY_REGION", "us-east-2")
env = cdk.Environment(account=account, region=region)
mode = app.node.try_get_context("mode") or "application"
email = os.environ.get("NOTIFICATION_EMAIL", "")
deployment_method = (app.node.try_get_context("deployment_method")
                     or os.environ.get("DEPLOYMENT_METHOD", "codedeploy"))
if mode == "pipeline":
    connection = os.environ.get("CONNECTION_ARN")
    if not connection or not account:
        raise ValueError("Pipeline mode requires DEPLOY_ACCOUNT and CONNECTION_ARN")
    WebHealthPipeline(app, "WebHealth-Pipeline", stack_name="WebHealth-Pipeline", env=env,
                      connection_arn=connection, notification_email=email,
                      branch=os.environ.get("SOURCE_BRANCH", "main"), deployment_method=deployment_method)
elif mode == "application":
    stage = app.node.try_get_context("environment") or "beta"
    fault = str(app.node.try_get_context("fault_injection") or "false").lower() == "true"
    VshydzaiStack(app, f"WebHealth-{stage}", stack_name=f"WebHealth-{stage}",
                 environment=stage, notification_email=email, fault_injection=fault,
                 deployment_method=deployment_method, env=env)
else:
    raise ValueError("mode must be application or pipeline")
app.synth()
