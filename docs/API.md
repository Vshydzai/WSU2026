# Target-list API

The environment's ApiUrl CloudFormation output includes the stage prefix. Append /targets to that base URL. The API is public HTTPS and uses JSON bodies and responses.

## Routes

| Method | Path | Success |
| --- | --- | --- |
| POST | /targets | 201 with the created target |
| GET | /targets?limit=25 | 200 with items and next_cursor |
| GET | /targets/{id} | 200 with one target |
| PUT | /targets/{id} | 200 with the updated target |
| DELETE | /targets/{id} | 204 with an empty body |

## Target schema

| Field | Type | Rules |
| --- | --- | --- |
| id | string | Server-generated; immutable |
| name | string | Required; trimmed; 1–100 characters |
| url | string | Required public HTTP(S) URL; at most 2048 characters |
| enabled | boolean | Optional; defaults to true |
| created_at | string | Server UTC timestamp; preserved on updates |
| updated_at | string | Server UTC timestamp |

POST and PUT accept only name, url and enabled. PUT replaces all editable fields; omitting enabled sets it to true. URL credentials, fragments, local hostnames, private IP literals and ports other than 80/443 are rejected. International hostnames and paths are normalized to IDNA and percent encoding without changing existing escapes. The crawler also validates resolved addresses and redirect destinations at execution time.

Example body:

~~~json
{"name":"Example","url":"https://example.com/","enabled":true}
~~~

## Pagination

limit is an integer between 1 and 100. next_cursor is null on the last page. Otherwise pass the returned opaque cursor as cursor on the next request. DynamoDB scans do not promise sorted order or a snapshot across multiple requests. Repeated and unknown query parameters are rejected.

## Errors

The handler returns a JSON error field. Invalid JSON/input/cursors return 400. Missing target reads, updates and deletes return 404. Storage failures return 503. Unexpected server errors return 500. API Gateway can return 429 for throttling and gateway-generated errors before Lambda runs. The handler's unsupported-method response is 405; API Gateway rejects undefined methods itself.

Bodies larger than 16 KiB are rejected by the handler. No-store response headers prevent caching mutable target data.

## Browser access (CORS)

The public API accepts browser requests without credentials. OPTIONS on the root, /targets and /targets/{id} returns 204 through API Gateway's mock integration. Preflight permits GET, POST, PUT, DELETE and OPTIONS, with Content-Type as the allowed request header and a ten-minute maximum age.

Lambda business responses, including errors and the empty DELETE response, include Access-Control-Allow-Origin: *. API Gateway default 4XX and 5XX responses also include CORS headers so the browser can read throttling and gateway errors. Access-Control-Allow-Credentials is not enabled. CORS controls browser access; it does not authenticate callers or change the public API's throttling.

## Demonstration

Run python vshydzai/scripts/demo_crud.py --stack WebHealth-beta from the repository root. It prints each request and response, verifies the deleted target returns 404 and removes only its own target.

For the browser interface run `python vshydzai/scripts/serve_dashboard.py --stack WebHealth-beta`. The [dashboard guide](DASHBOARD.md) explains deployed use, the explicit local simulator and evidence limits.

SDK read/write durations appear in DynamoDBReadMs/DynamoDBWriteMs metrics. These timings include the client call and are measured separately from API response latency.

[OpenAPI specification](openapi.yaml)

Reference: [AWS API Gateway CORS behaviour](https://docs.aws.amazon.com/apigateway/latest/developerguide/how-to-cors.html).
