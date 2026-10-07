"""API Gateway REST proxy handler for the crawler target list."""

import base64
import json
import logging
from decimal import Decimal

from botocore.exceptions import ClientError
from target_repository import NotFound, repository
from telemetry import emit, memory_snapshot
from validation import validate_target

LOGGER = logging.getLogger(__name__)


def response(status, body=None):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
        "body": "" if body is None else json.dumps(body, default=lambda value:
                  float(value) if isinstance(value, Decimal) else str(value)),
    }


def body(event):
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        try:
            raw = base64.b64decode(raw, validate=True).decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise ValueError("Invalid encoded JSON body") from exc
    if len(raw.encode("utf-8")) > 16384:
        raise ValueError("Request body exceeds 16 KiB")
    try:
        return json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError("Non-finite numbers are not supported")))
    except (ValueError, TypeError) as exc:
        raise ValueError("Body must contain valid JSON") from exc


def lambda_handler(event, context):
    if event.get("healthcheck"):
        repository().list(limit=1)
        memory_snapshot("api")
        return {"ok": True, "component": "api"}
    try:
        method, resource = event.get("httpMethod", ""), event.get("resource", "")
        target_id = (event.get("pathParameters") or {}).get("id")
        repo = repository()
        if resource == "/targets" and method == "POST":
            result = response(201, repo.create(validate_target(body(event))))
        elif resource == "/targets" and method == "GET":
            query = event.get("queryStringParameters") or {}
            multi = event.get("multiValueQueryStringParameters") or {}
            if any(len(values) != 1 for values in multi.values()) or set(query) - {"limit", "cursor"}:
                raise ValueError("Unsupported or repeated query parameters")
            result = response(200, repo.list(int(query.get("limit", "25")), query.get("cursor")))
        elif resource == "/targets/{id}" and target_id and method == "GET":
            result = response(200, repo.get(target_id))
        elif resource == "/targets/{id}" and target_id and method == "PUT":
            result = response(200, repo.update(target_id, validate_target(body(event))))
        elif resource == "/targets/{id}" and target_id and method == "DELETE":
            repo.delete(target_id)
            result = response(204)
        else:
            result = response(405, {"error": "Method not supported"})
    except NotFound as exc:
        result = response(404, {"error": str(exc)})
    except (ValueError, TypeError) as exc:
        result = response(400, {"error": str(exc)})
    except ClientError:
        LOGGER.exception("DynamoDB request failed")
        emit("api", {"ApiServerErrors": 1})
        result = response(503, {"error": "Storage temporarily unavailable"})
    except Exception:
        LOGGER.exception("API request failed")
        emit("api", {"ApiServerErrors": 1})
        result = response(500, {"error": "Internal server error"})
    memory_snapshot("api")
    emit("api", {"ApiRequests": 1})
    return result
