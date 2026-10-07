"""Explicit removal policies for generated resources, including pipeline resources."""

import jsii
from aws_cdk import CfnResource, IAspect, RemovalPolicy


@jsii.implements(IAspect)
class ProjectRemovalPolicy:
    def visit(self, node):
        if isinstance(node, CfnResource):
            # Keep old code versions for recovery while the parent function exists.
            # Deleting the parent Lambda deletes its versions at project teardown.
            policy = RemovalPolicy.RETAIN if node.cfn_resource_type == "AWS::Lambda::Version" else RemovalPolicy.DESTROY
            node.apply_removal_policy(policy)
