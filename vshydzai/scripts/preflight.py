"""Read-only AWS prerequisites; not a substitute for deployment permission checks."""

import argparse
import os
import re
import sys
from datetime import datetime, timezone

from aws_session import checked_session, client, error_record, write_report
from botocore.exceptions import BotoCoreError, ClientError


def connection_location(arn):
    match = re.fullmatch(r"arn:(aws(?:-[a-z]+)*):(codeconnections|codestar-connections):"
                         r"([a-z0-9-]+):([0-9]{12}):connection/([a-zA-Z0-9-]+)", arn or "")
    if not match:
        raise ValueError("Set CONNECTION_ARN to a CodeConnections connection ARN, not a host ARN")
    return match[3], match[4]


def readiness(session, account, region, connection=None, identity_only=False):
    checks = []
    if not identity_only:
        try:
            stack = client(session, "cloudformation").describe_stacks(StackName="CDKToolkit")["Stacks"][0]
            passed = stack["StackStatus"] in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}
            checks.append({"name": "cdk_bootstrap", "status": "passed" if passed else "failed",
                           "stack_status": stack["StackStatus"]})
        except (BotoCoreError, ClientError) as exc:
            checks.append({"name": "cdk_bootstrap", **error_record(exc),
                           "next_step": "Review read permissions or bootstrap the intended account/region"})
    if connection:
        arn_region, arn_account = connection_location(connection)
        if (arn_region, arn_account) != (region, account):
            raise ValueError("Connection must belong to the selected account and region")
        try:
            info = client(session, "codeconnections").get_connection(ConnectionArn=connection)["Connection"]
            passed = info.get("ConnectionStatus") == "AVAILABLE" and info.get("ProviderType") == "GitHub"
            checks.append({"name": "github_connection", "status": "passed" if passed else "failed",
                           "connection_status": info.get("ConnectionStatus"), "provider": info.get("ProviderType"),
                           "next_step": "Complete repository authorization in AWS if not AVAILABLE"})
        except (BotoCoreError, ClientError) as exc:
            checks.append({"name": "github_connection", **error_record(exc)})
    return {"operation": "preflight", "collected_at": datetime.now(timezone.utc),
            "account": account, "region": region, "identity": "matched",
            "ok": all(check["status"] == "passed" for check in checks), "checks": checks,
            "limitations": ["Read-only prerequisites do not prove deployment or iam:PassRole permissions",
                            "AVAILABLE does not prove this repository is included in the GitHub authorization",
                            "CDK bootstrap version/roles are finally validated by the CDK deployment"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", default=os.environ.get("DEPLOY_ACCOUNT"))
    parser.add_argument("--region", default=os.environ.get("DEPLOY_REGION", "us-east-2"))
    parser.add_argument("--pipeline", action="store_true", help="Require a GitHub CodeConnections connection")
    parser.add_argument("--connection", default=os.environ.get("CONNECTION_ARN"))
    parser.add_argument("--identity-only", action="store_true", help="Check credentials before bootstrapping")
    parser.add_argument("--output", help="Save a credential-free JSON receipt")
    args = parser.parse_args(argv)
    if args.pipeline and not args.connection:
        parser.error("--pipeline requires CONNECTION_ARN or --connection")
    try:
        if args.connection:
            location = connection_location(args.connection)
            if location != (args.region, args.account):
                raise ValueError("Connection must belong to the selected account and region")
        session = checked_session(args.account, args.region)
        report = readiness(session, args.account, args.region, args.connection, args.identity_only)
        print(write_report(report, args.output), end="")
        return 0 if report["ok"] else 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (BotoCoreError, ClientError) as exc:
        print(write_report({"operation": "preflight", "ok": False, **error_record(exc)}, args.output), end="")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
