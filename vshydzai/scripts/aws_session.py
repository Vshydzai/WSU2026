"""Shared, account-checked AWS sessions and credential-free operation reports."""

import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

READ_CONFIG = Config(connect_timeout=3, read_timeout=10, retries={"total_max_attempts": 2})
ENVIRONMENT_STACKS = ("WebHealth-beta", "WebHealth-gamma", "WebHealth-prod")


def checked_session(account, region):
    if not account or not re.fullmatch(r"[0-9]{12}", account):
        raise ValueError("Set DEPLOY_ACCOUNT or --account to your intended 12-digit AWS account")
    if not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-[0-9]+", region):
        raise ValueError("Choose an explicit AWS region")
    session = boto3.Session(region_name=region)
    identity = client(session, "sts").get_caller_identity()
    if identity["Account"] != account:
        raise ValueError("AWS session account does not match the intended DEPLOY_ACCOUNT; no operation performed")
    return session


def client(session, service):
    return session.client(service, config=READ_CONFIG)


def error_record(exc):
    # AWS service messages can contain caller-supplied values: retain the code, not raw messages.
    code = exc.response["Error"]["Code"] if isinstance(exc, ClientError) else type(exc).__name__
    return {"status": "unavailable", "error": code}


def json_default(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"Unsupported report value: {type(value).__name__}")


def write_report(report, output=None):
    text = json.dumps(report, default=json_default, allow_nan=False, indent=2) + "\n"
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return text
