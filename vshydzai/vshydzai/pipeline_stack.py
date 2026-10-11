"""GitHub source, AWS CodeBuild test gates and three CDK deployment stages."""

from aws_cdk import (
    ArnFormat,
    Aspects,
    Environment,
    RemovalPolicy,
    Stack,
    pipelines,
)
from aws_cdk import (
    aws_apigateway as apigateway,
)
from aws_cdk import (
    aws_codebuild as codebuild,
)
from aws_cdk import (
    aws_codepipeline as codepipeline,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_s3 as s3,
)
from constructs import Construct

from .application_stage import WebHealthStage
from .removal import ProjectRemovalPolicy


class WebHealthPipeline(Stack):
    def __init__(self, scope: Construct, identifier: str, *, connection_arn, repository="Vshydzai/WSU2026",
                 branch="main", notification_email="", **kwargs):
        super().__init__(scope, identifier, **kwargs)
        # REST API account logging role is shared by all stages in this account/region.
        logging_role = iam.Role(self, "ApiLoggingRole", assumed_by=iam.ServicePrincipal("apigateway.amazonaws.com"),
            managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AmazonAPIGatewayPushToCloudWatchLogs")])
        apigateway.CfnAccount(self, "ApiLoggingAccount", cloud_watch_role_arn=logging_role.role_arn)
        artifacts = s3.Bucket(self, "Artifacts", block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
                              encryption=s3.BucketEncryption.S3_MANAGED, enforce_ssl=True,
                              auto_delete_objects=True, removal_policy=RemovalPolicy.DESTROY)
        defaults = pipelines.CodeBuildOptions(
            build_environment=codebuild.BuildEnvironment(build_image=codebuild.LinuxBuildImage.STANDARD_7_0),
            partial_build_spec=codebuild.BuildSpec.from_object({
                "phases": {"install": {"runtime-versions": {"nodejs": "22", "python": "3.12"}}}}))
        source = pipelines.CodePipelineSource.connection(repository, branch, connection_arn=connection_arn)
        pipeline = pipelines.CodePipeline(
            self, "Pipeline", pipeline_name="WebHealth", pipeline_type=codepipeline.PipelineType.V2,
            artifact_bucket=artifacts, cross_account_keys=False, code_build_defaults=defaults, cli_version="2.1128.0",
            synth=pipelines.ShellStep(
                "BuildAndTest", input=source,
                install_commands=["npm ci", "python3 -m pip install -r vshydzai/requirements-dev.txt"],
                commands=["cd vshydzai", "ruff check .",
                          "pytest -m 'not integration' --cov=lambda_src --cov=scripts --cov-fail-under=85 "
                          "--junitxml=test-results/local.xml",
                          "cd ..", "npm run test:dashboard", "npm run synth:pipeline"],
                env={"CONNECTION_ARN": connection_arn,
                     "DEPLOY_ACCOUNT": self.account, "DEPLOY_REGION": self.region,
                     "SOURCE_BRANCH": branch, "NOTIFICATION_EMAIL": notification_email},
                primary_output_directory="vshydzai/cdk.out"))
        for environment in ("beta", "gamma", "prod"):
            stage = WebHealthStage(self, environment.capitalize(), environment=environment,
                                   notification_email=notification_email, env=Environment(account=self.account, region=self.region))
            app = stage.application
            api_test = pipelines.CodeBuildStep(
                f"{environment.capitalize()}Tests", input=source,
                install_commands=["python3 -m pip install -r vshydzai/requirements-dev.txt"],
                commands=["cd vshydzai", "pytest -m integration --run-live -o junit_family=legacy "
                          f"--junitxml=test-results/{environment}.xml"],
                env_from_cfn_outputs={
                    "API_URL": app.api_url_output, "TARGETS_TABLE_NAME": app.targets_output,
                    "CRAWLER_FUNCTION_NAME": app.crawler_output,
                    "ALARM_TOPIC_ARN": app.alarm_topic_output,
                    "ALARM_TABLE_NAME": app.alarm_table_output},
                role_policy_statements=[
                    iam.PolicyStatement(actions=["dynamodb:GetItem", "dynamodb:Scan", "dynamodb:PutItem", "dynamodb:DeleteItem"],
                                        resources=[self.format_arn(service="dynamodb", resource="table", resource_name=f"WebHealth-{environment}-{name}") for name in ("Targets", "AlarmLogs")]),
                    iam.PolicyStatement(actions=["lambda:InvokeFunction"],
                                        resources=[self.format_arn(service="lambda", resource="function", resource_name=f"WebHealth-{environment}-Crawler:live", arn_format=ArnFormat.COLON_RESOURCE_NAME)]),
                    iam.PolicyStatement(actions=["sns:Publish"], resources=[self.format_arn(service="sns", resource=f"WebHealth-{environment}-Alarms")]),
                ],
                partial_build_spec=codebuild.BuildSpec.from_object({
                    "reports": {"WebHealthTests": {"files": ["*.xml"],
                        "base-directory": "vshydzai/test-results", "file-format": "JUNITXML"}}}))
            pre = [pipelines.ManualApprovalStep("ApproveProduction")] if environment == "prod" else []
            pipeline.add_stage(stage, pre=pre, post=[api_test])
        pipeline.build_pipeline()
        Aspects.of(self).add(ProjectRemovalPolicy())
