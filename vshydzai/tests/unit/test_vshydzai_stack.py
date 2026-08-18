import aws_cdk as core
import aws_cdk.assertions as assertions

from vshydzai.vshydzai_stack import VshydzaiStack

# example tests. To run these tests, uncomment this file along with the example
# resource in vshydzai/vshydzai_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = VshydzaiStack(app, "vshydzai")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
