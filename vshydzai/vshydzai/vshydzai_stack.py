from aws_cdk import (
    Stack,
    RemovalPolicy,
    RemovalPolicies,
    Duration,
    aws_lambda as _lambda,
    aws_iam as iam,
    aws_events as events,
    aws_events_targets as targets,
)

from constructs import Construct


class VshydzaiStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        webhealth_function = _lambda.Function(
            self,
            "WebHealthFunction",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="webhealth.lambda_handler",
            code=_lambda.Code.from_asset("lambda_src"),
        )

        webhealth_function.apply_removal_policy(RemovalPolicy.DESTROY)

        webhealth_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["cloudwatch:PutMetricData"],
                resources=["*"]
            )
        )

        schedule = events.Rule(
            self,
            "WebHealthSchedule",
            schedule=events.Schedule.rate(
                Duration.minutes(30)
            )
        )

        schedule.add_target(
            targets.LambdaFunction(webhealth_function)
        )

        RemovalPolicies.of(self).destroy()