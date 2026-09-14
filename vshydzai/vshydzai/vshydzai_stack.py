from aws_cdk import (
    Stack,
    RemovalPolicy,
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cloudwatch_actions,
    aws_lambda as _lambda,
    aws_iam as iam,
    aws_events as events,
    aws_events_targets as targets,
    aws_sns as sns,
    aws_sns_subscriptions as subscriptions,
    aws_dynamodb as dynamodb,
)

from constructs import Construct


class VshydzaiStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)


        # -------------------------
        # Lambda Function
        # -------------------------

        webhealth_function = _lambda.Function(
            self,
            "WebHealthFunction",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="webhealth.lambda_handler",
            code=_lambda.Code.from_asset("lambda_src"),
        )

        webhealth_function.apply_removal_policy(
            RemovalPolicy.DESTROY
        )


        # Permission to publish CloudWatch metrics

        webhealth_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "cloudwatch:PutMetricData"
                ],
                resources=[
                    "*"
                ]
            )
        )


        # -------------------------
        # EventBridge Schedule
        # -------------------------

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


        # -------------------------
        # CloudWatch Metrics
        # -------------------------

        availability_wsu = cloudwatch.Metric(
            namespace="WebHealth",
            metric_name="Availability",
            dimensions_map={
                "Website": "WSU"
            },
            period=Duration.minutes(30),
            statistic="Minimum"
        )


        latency_wsu = cloudwatch.Metric(
            namespace="WebHealth",
            metric_name="Latency",
            dimensions_map={
                "Website": "WSU"
            },
            period=Duration.minutes(30),
            statistic="Average"
        )


        status_wsu = cloudwatch.Metric(
            namespace="WebHealth",
            metric_name="StatusCode",
            dimensions_map={
                "Website": "WSU"
            },
            period=Duration.minutes(30),
            statistic="Average"
        )


        availability_example = cloudwatch.Metric(
            namespace="WebHealth",
            metric_name="Availability",
            dimensions_map={
                "Website": "Example"
            },
            period=Duration.minutes(30),
            statistic="Minimum"
        )


        latency_example = cloudwatch.Metric(
            namespace="WebHealth",
            metric_name="Latency",
            dimensions_map={
                "Website": "Example"
            },
            period=Duration.minutes(30),
            statistic="Average"
        )


        # -------------------------
        # CloudWatch Dashboard
        # -------------------------

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
            ),

            cloudwatch.GraphWidget(
                title="Website Status Code",
                left=[
                    status_wsu
                ]
            )

        )


        # -------------------------
        # SNS Notification Topic
        # -------------------------

        alarm_topic = sns.Topic(
            self,
            "WebHealthAlarmTopic",
            display_name="Web Health Alarm Notifications"
        )


        alarm_topic.add_subscription(
            subscriptions.EmailSubscription(
                "vi16082006@gmail.com"
            )
        )

        # -------------------------
        # DynamoDB Alarm Logs
        # -------------------------

        alarm_table = dynamodb.Table(
            self,
            "AlarmLogsTable",

            table_name="AlarmLogs",

            partition_key=dynamodb.Attribute(
                name="id",
                type=dynamodb.AttributeType.STRING
            ),

            removal_policy=RemovalPolicy.DESTROY
        )

        # -------------------------
        # Alarm Logger Lambda
        # -------------------------

        alarm_logger_function = _lambda.Function(
            self,
            "AlarmLoggerFunction",

            runtime=_lambda.Runtime.PYTHON_3_12,

            handler="alarm_logger.lambda_handler",

            code=_lambda.Code.from_asset(
                "lambda_src"
            )
        )

        # Allow Alarm Logger Lambda to write to DynamoDB

        alarm_logger_function.add_to_role_policy(
            iam.PolicyStatement(

                actions=[
                    "dynamodb:PutItem"
                ],

                resources=[
                    alarm_table.table_arn
                ]
            )
        )

        alarm_topic.add_subscription(
            subscriptions.LambdaSubscription(
                alarm_logger_function
            )
        )

        # -------------------------
        # CloudWatch Alarms
        # -------------------------

        # WSU Availability Alarm

        wsu_availability_alarm = cloudwatch.Alarm(
            self,
            "WSUAvailabilityAlarm",
            metric=availability_wsu,
            threshold=1,
            evaluation_periods=1,
            comparison_operator=
            cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD
        )

        wsu_availability_alarm.add_alarm_action(
            cloudwatch_actions.SnsAction(alarm_topic)
        )


        # WSU Latency Alarm

        wsu_latency_alarm = cloudwatch.Alarm(
            self,
            "WSULatencyAlarm",
            metric=latency_wsu,
            threshold=3000,
            evaluation_periods=1,
            comparison_operator=
            cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD
        )

        wsu_latency_alarm.add_alarm_action(
            cloudwatch_actions.SnsAction(alarm_topic)
        )


        # Example Availability Alarm

        example_availability_alarm = cloudwatch.Alarm(
            self,
            "ExampleAvailabilityAlarm",
            metric=availability_example,
            threshold=1,
            evaluation_periods=1,
            comparison_operator=
            cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD
        )

        example_availability_alarm.add_alarm_action(
            cloudwatch_actions.SnsAction(alarm_topic)
        )


        # Example Latency Alarm

        example_latency_alarm = cloudwatch.Alarm(
            self,
            "ExampleLatencyAlarm",
            metric=latency_example,
            threshold=3000,
            evaluation_periods=1,
            comparison_operator=
            cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD
        )

        example_latency_alarm.add_alarm_action(
            cloudwatch_actions.SnsAction(alarm_topic)
        )