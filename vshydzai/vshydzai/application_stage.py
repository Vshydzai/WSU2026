from aws_cdk import Stage
from constructs import Construct

from .vshydzai_stack import VshydzaiStack


class WebHealthStage(Stage):
    def __init__(self, scope: Construct, identifier: str, *, environment, notification_email="", **kwargs):
        super().__init__(scope, identifier, **kwargs)
        self.application = VshydzaiStack(
            self, "Application", stack_name=f"WebHealth-{environment}",
            environment=environment, notification_email=notification_email, manage_api_logging_role=False)
