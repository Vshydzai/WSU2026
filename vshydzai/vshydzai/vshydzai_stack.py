"""One isolated WebHealth environment."""

import json
from pathlib import Path

from aws_cdk import (
    Aspects,
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import (
    aws_apigateway as apigateway,
)
from aws_cdk import (
    aws_cloudwatch as cw,
)
from aws_cdk import (
    aws_cloudwatch_actions as cw_actions,
)
from aws_cdk import (
    aws_codedeploy as codedeploy,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_events as events,
)
from aws_cdk import (
    aws_events_targets as event_targets,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_lambda as lambdas,
)
from aws_cdk import (
    aws_logs as logs,
)
from aws_cdk import (
    aws_sns as sns,
)
from aws_cdk import (
    aws_sns_subscriptions as subscriptions,
)
from constructs import Construct

from .removal import ProjectRemovalPolicy

ASSETS = str(Path(__file__).resolve().parents[1] / "lambda_src")


class VshydzaiStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, environment="beta",
                 notification_email="", fault_injection=False, manage_api_logging_role=True, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        if environment not in {"beta", "gamma", "prod"}:
            raise ValueError("Use beta, gamma or prod")
        if fault_injection and environment != "beta":
            raise ValueError("Fault injection is supported only in beta")
        prefix = f"WebHealth-{environment}"

        def table(identifier, ttl=None):
            return dynamodb.Table(self, identifier, table_name=f"{prefix}-{identifier}",
                                  partition_key=dynamodb.Attribute(name="id", type=dynamodb.AttributeType.STRING),
                                  billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
                                  time_to_live_attribute=ttl, removal_policy=RemovalPolicy.DESTROY)

        self.targets_table = table("Targets")
        self.alarm_table = table("AlarmLogs", "expires_at")
        release_table = table("ReleaseState")
        common = {"ENVIRONMENT": environment, "TARGETS_TABLE_NAME": self.targets_table.table_name}

        def function(identifier, handler, timeout=15, memory=256, extra=None):
            name = f"{prefix}-{identifier}"
            log_group = logs.LogGroup(self, f"{identifier}Logs", log_group_name=f"/aws/lambda/{name}",
                                      retention=logs.RetentionDays.ONE_WEEK, removal_policy=RemovalPolicy.DESTROY)
            return lambdas.Function(
                self, identifier, function_name=name, runtime=lambdas.Runtime.PYTHON_3_12,
                code=lambdas.Code.from_asset(ASSETS, exclude=["__pycache__", "*.pyc"]),
                handler=handler, timeout=Duration.seconds(timeout), memory_size=memory,
                log_group=log_group, environment={**common, **(extra or {})},
                current_version_options=lambdas.VersionOptions(removal_policy=RemovalPolicy.RETAIN),
                retry_attempts=0)

        self.crawler = function("Crawler", "webhealth.lambda_handler", timeout=90,
                                extra={"HTTP_TIMEOUT_SECONDS": "3", "MAX_TARGETS": "25",
                                       "FAULT_INJECTION": str(fault_injection).lower()})
        self.api_function = function("Api", "targets_api.lambda_handler")
        self.targets_table.grant_read_data(self.crawler)
        self.targets_table.grant_read_write_data(self.api_function)
        self.crawler_alias = lambdas.Alias(self, "CrawlerLive", alias_name="live",
                                          version=self.crawler.current_version)
        self.api_alias = lambdas.Alias(self, "ApiLive", alias_name="live",
                                      version=self.api_function.current_version)
        events.Rule(self, "Schedule", schedule=events.Schedule.rate(Duration.minutes(30)),
                    targets=[event_targets.LambdaFunction(self.crawler_alias)])

        access_logs = logs.LogGroup(self, "ApiAccessLogs", log_group_name=f"/webhealth/{environment}/api",
                                    retention=logs.RetentionDays.ONE_WEEK, removal_policy=RemovalPolicy.DESTROY)
        self.api = apigateway.RestApi(
            self, "TargetsApi", rest_api_name=f"{prefix}-TargetsApi", cloud_watch_role=manage_api_logging_role,
            default_cors_preflight_options=apigateway.CorsOptions(
                allow_origins=apigateway.Cors.ALL_ORIGINS,
                allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                allow_headers=["Content-Type"], max_age=Duration.minutes(10)),
            deploy_options=apigateway.StageOptions(
                stage_name=environment, throttling_rate_limit=5, throttling_burst_limit=10,
                metrics_enabled=True, logging_level=apigateway.MethodLoggingLevel.ERROR,
                access_log_destination=apigateway.LogGroupLogDestination(access_logs),
                access_log_format=apigateway.AccessLogFormat.json_with_standard_fields(
                    caller=False, user=False, ip=False, http_method=True, protocol=True,
                    request_time=True, resource_path=True, response_length=True, status=True)))
        integration = apigateway.LambdaIntegration(self.api_alias)
        collection = self.api.root.add_resource("targets")
        for method in ("GET", "POST"):
            collection.add_method(method, integration)
        item = collection.add_resource("{id}")
        for method in ("GET", "PUT", "DELETE"):
            item.add_method(method, integration)
        # Gateway-generated failures (including throttling) never reach Lambda.
        for name, kind in (("ClientError", apigateway.ResponseType.DEFAULT_4_XX),
                           ("ServerError", apigateway.ResponseType.DEFAULT_5_XX)):
            self.api.add_gateway_response(name, type=kind, response_headers={
                "Access-Control-Allow-Origin": "'*'",
                "Access-Control-Allow-Headers": "'Content-Type'",
                "Access-Control-Allow-Methods": "'GET,POST,PUT,DELETE,OPTIONS'"})

        topic = sns.Topic(self, "AlarmTopic", topic_name=f"{prefix}-Alarms")
        if notification_email:
            topic.add_subscription(subscriptions.EmailSubscription(notification_email))
        logger = function("AlarmLogger", "alarm_logger.lambda_handler",
                          extra={"ALARM_TABLE_NAME": self.alarm_table.table_name})
        self.alarm_table.grant_write_data(logger)
        topic.add_subscription(subscriptions.LambdaSubscription(logger))

        allowed = json.dumps([self.crawler.function_name, self.api_function.function_name])
        hook = function("DeploymentHook", "deployment_hook.lambda_handler", timeout=120,
                        extra={"ALLOWED_FUNCTIONS": allowed})
        traffic = function("CanaryTraffic", "canary_traffic.lambda_handler", timeout=290,
                           extra={"ALLOWED_FUNCTIONS": allowed})
        for worker in (hook, traffic):
            worker.add_to_role_policy(iam.PolicyStatement(actions=["codedeploy:GetDeployment"], resources=["*"]))
        for target in (self.crawler, self.api_function):
            for worker in (hook, traffic):
                worker.add_to_role_policy(iam.PolicyStatement(actions=["lambda:InvokeFunction"],
                                                              resources=[target.function_arn + ":*"]))
            traffic.add_to_role_policy(iam.PolicyStatement(actions=["lambda:GetAlias"],
                resources=[target.function_arn, target.function_arn + ":live"]))

        alarms, alarm_map, group_map = [], {}, {}
        dimensions = {"Environment": environment}

        def metric(name, component, unit=None):
            return cw.Metric(namespace="WebHealth", metric_name=name,
                             dimensions_map={**dimensions, "Component": component},
                             period=Duration.minutes(1), statistic="Average" if unit == cw.Unit.MILLISECONDS else "Sum", unit=unit)

        def alarm(identifier, metric_value, threshold, period_count=1):
            result = cw.Alarm(self, identifier, alarm_name=f"{prefix}-{identifier}", metric=metric_value,
                              threshold=threshold, evaluation_periods=period_count,
                              comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                              treat_missing_data=cw.TreatMissingData.NOT_BREACHING)
            result.add_alarm_action(cw_actions.SnsAction(topic))
            alarms.append(result)
            return result

        for label, target, alias, component in (
                ("Crawler", self.crawler, self.crawler_alias, "crawler"),
                ("Api", self.api_function, self.api_alias, "api")):
            operational = [
                alarm(f"{label}Errors", alias.metric_errors(period=Duration.minutes(1), statistic="Sum"), 1),
                alarm(f"{label}Duration", alias.metric_duration(period=Duration.minutes(1), statistic="Maximum"),
                      80000 if component == "crawler" else 12000),
                alarm(f"{label}Memory", cw.Metric(
                    namespace="WebHealth", metric_name="MemoryUtilizationPercent",
                    dimensions_map={**dimensions, "Component": component},
                    period=Duration.minutes(1), statistic="Maximum"), 85),
                alarm(f"{label}ProbeFailures", cw.Metric(
                    namespace="WebHealth", metric_name="DeploymentProbeFailures",
                    dimensions_map={**dimensions, "Component": "canary", "FunctionName": target.function_name},
                    period=Duration.minutes(1), statistic="Sum"), 1),
            ]
            if component == "api":
                operational.append(alarm("ApiServerErrors", metric("ApiServerErrors", "api"), 1))
            for health_alarm in operational:
                alarm_map[health_alarm.alarm_name] = target.function_name
            group = codedeploy.LambdaDeploymentGroup(
                self, f"{label}Deployment", alias=alias,
                deployment_group_name=f"{prefix}-{label}",
                deployment_config=codedeploy.LambdaDeploymentConfig.CANARY_10_PERCENT_5_MINUTES,
                alarms=operational, pre_hook=hook,
                auto_rollback=codedeploy.AutoRollbackConfig(
                    failed_deployment=True, stopped_deployment=True, deployment_in_alarm=True))
            group_map[target.function_name] = {
                "application": group.application.application_name, "group": group.deployment_group_name}
            events.Rule(self, f"{label}CanaryStart",
                        event_pattern=events.EventPattern(
                            source=["aws.codedeploy"], detail_type=["CodeDeploy Deployment State-change Notification"],
                            detail={"application": [group.application.application_name],
                                    "deploymentGroup": [group.deployment_group_name], "state": ["START"]}),
                        targets=[event_targets.LambdaFunction(traffic)])
            self.node.add_metadata(f"{label}DeploymentGroup", group.deployment_group_name)

        manager = function("ReleaseManager", "release_manager.lambda_handler", timeout=30, extra={
            "RELEASE_TABLE_NAME": release_table.table_name, "ALLOWED_FUNCTIONS": allowed,
            "ALARM_FUNCTION_MAP": json.dumps(alarm_map), "FUNCTION_GROUP_MAP": json.dumps(group_map)})
        release_table.grant_read_write_data(manager)
        manager.add_to_role_policy(iam.PolicyStatement(
            actions=["codedeploy:GetDeployment", "codedeploy:ListDeployments", "cloudwatch:DescribeAlarms"],
            resources=["*"]))
        for target in (self.crawler, self.api_function):
            manager.add_to_role_policy(iam.PolicyStatement(actions=["lambda:GetAlias", "lambda:UpdateAlias"],
                                                           resources=[target.function_arn, target.function_arn + ":live"]))
        events.Rule(self, "CompletedRelease", event_pattern=events.EventPattern(
            source=["aws.codedeploy"], detail_type=["CodeDeploy Deployment State-change Notification"],
            detail={"application": [value["application"] for value in group_map.values()], "state": ["SUCCESS"]}),
            targets=[event_targets.LambdaFunction(manager)])
        events.Rule(self, "OperationalRollback", event_pattern=events.EventPattern(
            source=["aws.cloudwatch"], detail_type=["CloudWatch Alarm State Change"],
            detail={"alarmName": list(alarm_map), "state": {"value": ["ALARM"]}}),
            targets=[event_targets.LambdaFunction(manager)])

        # Website failures trigger monitoring alerts, independently of release-health alarms.
        alarm("TargetsUnavailable", cw.Metric(
            namespace="WebHealth", metric_name="TargetsUnavailable",
            dimensions_map={**dimensions, "Component": "crawler"},
            period=Duration.minutes(30), statistic="Maximum"), 1)
        alarm("TargetsSlow", cw.Metric(
            namespace="WebHealth", metric_name="MaxTargetLatencyMs",
            dimensions_map={**dimensions, "Component": "crawler"},
            period=Duration.minutes(30), statistic="Maximum"), 3000)

        dashboard = cw.Dashboard(self, "Dashboard", dashboard_name=f"{prefix}-Dashboard")
        website_metrics = []
        for name in ("Availability", "Latency", "StatusCode"):
            expression = cw.MathExpression(expression=(
                f"SEARCH('{{WebHealth,Environment,Component,TargetId}} "
                f"Environment=\"{environment}\" Component=\"crawler\" MetricName=\"{name}\"', 'Average', 1800)"),
                label=name, period=Duration.minutes(30))
            website_metrics.append(cw.GraphWidget(title=f"Target {name}", left=[expression]))
        dashboard.add_widgets(*website_metrics)
        dashboard.add_widgets(
            cw.GraphWidget(title="Lambda invocations", left=[self.crawler.metric_invocations(), self.api_function.metric_invocations()]),
            cw.GraphWidget(title="Lambda errors and throttles", left=[
                self.crawler.metric_errors(), self.api_function.metric_errors(),
                self.crawler.metric_throttles(), self.api_function.metric_throttles()]),
            cw.GraphWidget(title="Crawler run duration (ms)", left=[metric("RunDurationMs", "crawler", cw.Unit.MILLISECONDS)]),
            cw.GraphWidget(title="DynamoDB read/write elapsed time (ms)", left=[
                metric(name, component, cw.Unit.MILLISECONDS) for component in ("api", "crawler")
                for name in ("DynamoDBReadMs", "DynamoDBWriteMs")]),
            cw.GraphWidget(title="Python peak RSS / allocated memory (%)", left=[
                cw.Metric(namespace="WebHealth", metric_name="MemoryUtilizationPercent",
                          dimensions_map={**dimensions, "Component": component}, statistic="Maximum")
                for component in ("api", "crawler")]),
            cw.LogQueryWidget(title="Full Lambda runtime memory from REPORT", log_group_names=[
                f"/aws/lambda/{self.crawler.function_name}", f"/aws/lambda/{self.api_function.function_name}"],
                query_lines=["filter @type = 'REPORT'", "stats max(@maxMemoryUsed / 1024 / 1024) as MaxMemoryMB by bin(5m)"]),
            cw.AlarmStatusWidget(title="Operational and website alarms", alarms=alarms),
        )
        self.api_url_output = CfnOutput(self, "ApiUrl", value=self.api.url)
        self.targets_output = CfnOutput(self, "TargetsTable", value=self.targets_table.table_name)
        self.crawler_output = CfnOutput(self, "CrawlerFunction", value=self.crawler.function_name)
        CfnOutput(self, "ApiFunction", value=self.api_function.function_name)
        self.alarm_topic_output = CfnOutput(self, "AlarmTopicArn", value=topic.topic_arn)
        self.alarm_table_output = CfnOutput(self, "AlarmTable", value=self.alarm_table.table_name)
        CfnOutput(self, "ReleaseTable", value=release_table.table_name)
        CfnOutput(self, "DashboardName", value=dashboard.dashboard_name)
        Aspects.of(self).add(ProjectRemovalPolicy())
