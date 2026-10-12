import json

import aws_cdk as cdk
import pytest
import yaml
from aws_cdk.assertions import Template

from vshydzai.pipeline_stack import WebHealthPipeline
from vshydzai.vshydzai_stack import VshydzaiStack


@pytest.fixture(scope="module")
def alias_template():
    stack = VshydzaiStack(cdk.App(), "AliasBeta", environment="beta", deployment_method="alias",
                         env=cdk.Environment(account="111111111111", region="ap-southeast-2"))
    return Template.from_stack(stack)


def test_alias_mode_has_no_codedeploy_resources_permissions_or_events(alias_template):
    template = alias_template.to_json()
    assert not any(value["Type"].startswith("AWS::CodeDeploy") for value in template["Resources"].values())
    assert "codedeploy:" not in json.dumps(template)
    assert "aws.codedeploy" not in json.dumps(template)
    alias_template.resource_count_is("AWS::Lambda::Alias", 0)
    alias_template.resource_count_is("AWS::StepFunctions::StateMachine", 0)


def test_custom_resource_owns_each_live_alias_with_five_minute_canary(alias_template):
    resources = alias_template.find_resources("Custom::WebHealthAliasRelease")
    assert len(resources) == 2
    for value in resources.values():
        props = value["Properties"]
        assert props["CanarySeconds"] == 300
        assert len(props["AlarmNames"]) >= 4
        assert "CurrentVersion" in str(props["CandidateVersion"])
        assert "OperationalRollback" in str(value["DependsOn"])
        assert "ReleaseManager" in str(value["DependsOn"])


def test_api_and_schedule_have_explicit_scoped_alias_invoke_permissions(alias_template):
    permissions = [item["Properties"] for item in alias_template.find_resources("AWS::Lambda::Permission").values()]
    api = [item for item in permissions if item["Principal"] == "apigateway.amazonaws.com"]
    schedule = [item for item in permissions if item["Principal"] == "events.amazonaws.com"
                and ":live" in str(item["FunctionName"])]
    assert len(api) == len(schedule) == 1
    assert ":live" in str(api[0]["FunctionName"]) and "SourceArn" in api[0]
    assert "Schedule" in str(schedule[0]["SourceArn"])


def test_schedule_cannot_run_until_custom_alias_resources_exist(alias_template):
    schedule = next(item for item in alias_template.find_resources("AWS::Events::Rule").values()
                    if "ScheduleExpression" in item["Properties"])
    assert "CrawlerAliasRelease" in str(schedule["DependsOn"])
    assert "ApiAliasRelease" in str(schedule["DependsOn"])


def test_operational_rollback_and_release_table_remain_in_alias_mode(alias_template):
    alias_template.has_resource_properties("AWS::Lambda::Function", {
        "Handler": "release_manager.lambda_handler", "Environment": {"Variables": {
            "DEPLOYMENT_METHOD": "alias"}}})
    alias_template.has_resource_properties("AWS::Events::Rule", {
        "EventPattern": {"source": ["aws.cloudwatch"], "detail": {"state": {"value": ["ALARM"]}}}})
    assert alias_template.to_json()["Outputs"]["DeploymentMethod"]["Value"] == "alias"


def test_unsupported_deployment_method_is_rejected():
    with pytest.raises(ValueError, match="deployment_method"):
        VshydzaiStack(cdk.App(), "Invalid", deployment_method="typo")


def test_pipeline_passes_alias_method_to_all_stages_and_self_mutation():
    app = cdk.App()
    stack = WebHealthPipeline(app, "AliasPipeline", deployment_method="alias", connection_arn=(
        "arn:aws:codeconnections:ap-southeast-2:111111111111:connection/"
        "00000000-0000-0000-0000-000000000000"),
        env=cdk.Environment(account="111111111111", region="ap-southeast-2"))
    app.synth()
    template = Template.from_stack(stack)
    projects = template.find_resources("AWS::CodeBuild::Project")
    synth = next(item for item in projects.values() if "npm run synth:pipeline" in str(item))
    env = synth["Properties"]["Environment"]["EnvironmentVariables"]
    assert {item["Name"]: item["Value"] for item in env}["DEPLOYMENT_METHOD"] == "alias"
    assert len([item for item in projects.values() if "--run-live" in str(item)]) == 3
    spec = yaml.safe_load(synth["Properties"]["Source"]["BuildSpec"])
    assert "ruff check ." in spec["phases"]["build"]["commands"]
    for name in ("Beta", "Gamma", "Prod"):
        stage = stack.node.find_child(name)
        child = Template.from_stack(stage.application)
        assert len(child.find_resources("Custom::WebHealthAliasRelease")) == 2
        assert "AWS::CodeDeploy" not in json.dumps(child.to_json())
