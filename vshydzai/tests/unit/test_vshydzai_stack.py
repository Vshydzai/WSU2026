import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from vshydzai.pipeline_stack import WebHealthPipeline
from vshydzai.vshydzai_stack import VshydzaiStack


@pytest.fixture(scope="module")
def template():
    app = cdk.App()
    stack = VshydzaiStack(app, "Test", environment="beta",
                         env=cdk.Environment(account="111111111111", region="us-east-2"))
    return Template.from_stack(stack)


def test_schedule_is_exactly_thirty_minutes(template):
    template.has_resource_properties("AWS::Events::Rule", {"ScheduleExpression": "rate(30 minutes)"})


def test_crawler_has_sufficient_runtime_budget(template):
    template.has_resource_properties("AWS::Lambda::Function", {
        "Handler": "webhealth.lambda_handler", "Timeout": 90, "MemorySize": 256})


def test_target_table_and_alarm_history_are_separate(template):
    template.resource_count_is("AWS::DynamoDB::Table", 3)
    template.has_resource_properties("AWS::DynamoDB::Table", {
        "TableName": "WebHealth-beta-Targets", "BillingMode": "PAY_PER_REQUEST"})


def test_api_exposes_all_crud_methods(template):
    methods = template.find_resources("AWS::ApiGateway::Method")
    assert {item["Properties"]["HttpMethod"] for item in methods.values()} == {"GET", "POST", "PUT", "DELETE"}
    assert len(methods) == 5


def test_gateway_has_throttling(template):
    template.has_resource_properties("AWS::ApiGateway::Stage", {
        "MethodSettings": Match.array_with([Match.object_like({"ThrottlingRateLimit": 5, "ThrottlingBurstLimit": 10})])})


def test_canary_and_alarm_rollback_enabled(template):
    for resource in template.find_resources("AWS::CodeDeploy::DeploymentGroup").values():
        props = resource["Properties"]
        assert props["DeploymentConfigName"] == "CodeDeployDefault.LambdaCanary10Percent5Minutes"
        assert props["AlarmConfiguration"]["Enabled"] is True
        assert "DEPLOYMENT_STOP_ON_ALARM" in props["AutoRollbackConfiguration"]["Events"]
        assert "TargetsSlow" not in str(props["AlarmConfiguration"])
        assert "TargetsUnavailable" not in str(props["AlarmConfiguration"])
    template.has_resource_properties("AWS::CloudWatch::Alarm", {
        "MetricName": "MaxTargetLatencyMs", "Threshold": 3000, "Period": 1800})


def test_schedule_and_api_invoke_live_aliases(template):
    schedule = next(resource for resource in template.find_resources("AWS::Events::Rule").values()
                    if "ScheduleExpression" in resource["Properties"])
    assert "CrawlerLive" in str(schedule["Properties"]["Targets"])
    for method in template.find_resources("AWS::ApiGateway::Method").values():
        assert "ApiLive" in str(method["Properties"]["Integration"]["Uri"])


def test_explicit_removal_policy_on_every_owned_resource(template):
    for resource in template.to_json()["Resources"].values():
        policy = "Retain" if resource["Type"] == "AWS::Lambda::Version" else "Delete"
        assert resource["DeletionPolicy"] == policy
        assert resource["UpdateReplacePolicy"] == policy


def test_crawler_has_read_only_target_permissions(template):
    policy = next(value for value in template.find_resources("AWS::IAM::Policy").values()
                  if "Crawler" in str(value["Properties"].get("Roles")))
    actions = [action for statement in policy["Properties"]["PolicyDocument"]["Statement"]
               for action in (statement["Action"] if isinstance(statement["Action"], list)
                              else [statement["Action"]])]
    assert "dynamodb:Scan" in actions
    assert "dynamodb:PutItem" not in actions


def test_all_operational_resources_have_environment_names(template):
    for resource in template.find_resources("AWS::Lambda::Function").values():
        assert resource["Properties"]["FunctionName"].startswith("WebHealth-beta-")


def test_canary_worker_invokes_only_versions_of_its_environment_functions(template):
    policy = next(value for value in template.find_resources("AWS::IAM::Policy").values()
                  if "CanaryTraffic" in str(value["Properties"].get("Roles")))
    statements = [item for item in policy["Properties"]["PolicyDocument"]["Statement"]
                  if item["Action"] == "lambda:InvokeFunction"]
    assert len(statements) == 2
    assert all(item["Resource"] != "*" and ":*" in str(item["Resource"]) for item in statements)


def test_evidence_collector_can_discover_both_application_functions(template):
    assert "ApiFunction" in template.to_json()["Outputs"]
    assert "CrawlerFunction" in template.to_json()["Outputs"]


def test_prod_rejects_deliberate_fault_injection():
    with pytest.raises(ValueError, match="beta"):
        VshydzaiStack(cdk.App(), "BadProd", environment="prod", fault_injection=True)


def test_pipeline_has_three_stages_and_blocking_live_tests():
    app = cdk.App()
    stack = WebHealthPipeline(app, "Pipeline", connection_arn=(
        "arn:aws:codestar-connections:us-east-2:111111111111:connection/"
        "00000000-0000-0000-0000-000000000000"),
        env=cdk.Environment(account="111111111111", region="us-east-2"))
    assembly = app.synth()
    tpl = Template.from_stack(stack)
    tpl.has_resource_properties("AWS::CodePipeline::Pipeline", {
        "Stages": Match.array_with([
            Match.object_like({"Name": "Beta"}),
            Match.object_like({"Name": "Gamma"}),
            Match.object_like({"Name": "Prod"})])})
    projects = tpl.find_resources("AWS::CodeBuild::Project")
    live_projects = [x for x in projects.values() if "--run-live" in str(x)]
    assert len(live_projects) == 3
    assert len(assembly.stacks) == 1
    for resource in tpl.to_json()["Resources"].values():
        assert "DeletionPolicy" in resource
