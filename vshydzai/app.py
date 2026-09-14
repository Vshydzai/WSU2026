#!/usr/bin/env python3
import os

import aws_cdk as cdk

from vshydzai.vshydzai_stack import VshydzaiStack


app = cdk.App()

VshydzaiStack(
    app,
    "VshydzaiStack",
    env=cdk.Environment(
        account="634176594693",
        region="us-east-2"
    )
)

app.synth()
