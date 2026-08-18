from aws_cdk import (
    Stack,
    RemovalPolicy,
    RemovalPolicies,
    aws_cloudwatch as cloudwatch,
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

        availability_wsu = cloudwatch.Metric(
            namespace="WebHealth",
            metric_name="Availability",
            dimensions_map={"Website": "WSU"},
            period=Duration.minutes(30),
            statistic="Minimum"
        )

        latency_wsu = cloudwatch.Metric(
            namespace="WebHealth",
            metric_name="Latency",
            dimensions_map={"Website": "WSU"},
            period=Duration.minutes(30),
            statistic="Average"
        )

        availability_example = cloudwatch.Metric(
            namespace="WebHealth",
            metric_name="Availability",
            dimensions_map={"Website": "Example"},
            period=Duration.minutes(30),
            statistic="Minimum"
        )

        latency_example = cloudwatch.Metric(
            namespace="WebHealth",
            metric_name="Latency",
            dimensions_map={"Website": "Example"},
            period=Duration.minutes(30),
            statistic="Average"
        )

        dashboard = cloudwatch.Dashboard(
            self,
            "WebHealthDashboard",
            dashboard_name="WebHealth-Dashboard"
        )

        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="Website Availability",
                left=[
                    availability_wsu,
                    availability_example
                ]
            ),

            cloudwatch.GraphWidget(
                title="Website Latency",
                left=[
                    latency_wsu,
                    latency_example
                ]
            )
        )

        cloudwatch.Alarm(
            self,
            "WSUAvailabilityAlarm",
            metric=availability_wsu,
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD
        )

        cloudwatch.Alarm(
            self,
            "WSULatencyAlarm",
            metric=latency_wsu,
            threshold=3000,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD
        )

        RemovalPolicies.of(self).destroy()