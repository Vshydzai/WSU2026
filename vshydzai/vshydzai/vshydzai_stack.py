from aws_cdk import (
    Stack,
    RemovalPolicy,
    aws_lambda as _lambda,
)
from constructs import Construct


class VshydzaiStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        hello_function = _lambda.Function(
            self,
            "HelloWorldFunction",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="hello.lambda_handler",
            code=_lambda.Code.from_asset("lambda_src"),
        )

        hello_function.apply_removal_policy(RemovalPolicy.DESTROY)