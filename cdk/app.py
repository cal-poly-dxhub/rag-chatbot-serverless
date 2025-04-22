#!/usr/bin/env python3
import os
import aws_cdk as cdk
from cdk.cdk_stack import CdkStack
from backend import RagBackendStack

app = cdk.App()

rag_api_stack = RagBackendStack(app, "RagBackendStack")

app.synth()
