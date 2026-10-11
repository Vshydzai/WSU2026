# Browser target manager

The browser dashboard creates, lists, reads, updates and deletes targets through the existing REST API. It adds no AWS hosting resources. A small Python server serves only the dashboard assets on 127.0.0.1; API requests go directly from the browser to the selected API Gateway stage.

## Rehearse without AWS

From the repository root, with Python 3.12 installed:

~~~bash
python3 vshydzai/scripts/serve_dashboard.py --demo
~~~

Open **http://127.0.0.1:8787**. On Windows use `py -3.12` instead of `python3`. The simulator uses only Python's standard library, so no AWS credentials, Python dependencies or deployment are needed for this mode.

The page displays **Local simulator** and explains that data lives in memory and resets when the server stops. Two example targets are seeded. The simulator shares the deployed API's target validation and HTTP response shapes. It does not run a crawler, write DynamoDB, emit CloudWatch metrics, create alarms or demonstrate release recovery. Local rehearsal and browser test results are not deployed-AWS evidence.

Stop the server with Ctrl+C. This discards the simulated targets. There is no local persistence or automatic AWS deployment.

## Connect a deployed environment

Deploy the updated stack so browser CORS support is present. With the project's Python dependencies installed and your intended AWS account selected:

~~~bash
export DEPLOY_ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
export DEPLOY_REGION=us-east-2
python vshydzai/scripts/serve_dashboard.py --stack WebHealth-beta
~~~

Use WebHealth-gamma or WebHealth-prod to select another deployed environment. `--stack` reads the actual ApiUrl through the same account-checked CloudFormation configuration helper as the operator tools. AWS credentials stay in the Python/AWS SDK process; they are never supplied to the page or used to proxy CRUD requests.

Alternatively, start `python vshydzai/scripts/serve_dashboard.py` and paste the ApiUrl output into **API connection**. Include the stage root, for example `https://API_ID.execute-api.us-east-2.amazonaws.com/beta/`. Do not append `/targets`. The last successful public endpoint is saved in browser storage; manual mode waits for Connect before sending requests. A remembered endpoint is a convenience, not proof that its deployment still exists.

The page labels standard execute-api hostnames **AWS API**, other HTTPS endpoints **Public API**, and loopback endpoints **Local API**. A hostname label does not verify account ownership, stage health or AWS deployment history. Switching away from the configured simulator removes its simulator label.

Only HTTPS endpoints are accepted, with HTTP allowed on exact loopback hosts. URLs containing embedded credentials, query parameters or fragments are rejected. The browser sends no cookies or AWS credentials and refuses redirects. The public course API remains unauthenticated and throttled; CORS does not provide authorization.

## Demonstration sequence

1. Show the mode label and selected stage URL. For assessment use the deployed Beta API.
2. Create a target with a public website URL. Show the returned server-generated ID in the card and the matching DynamoDB row.
3. Open Edit. The page first reads the individual target, then saves all editable fields with PUT.
4. Disable the target and show its `enabled` field in DynamoDB. Enable it again if it should be included in the next crawler run.
5. Show **Filter this page** and enabled/disabled filters. Navigate Next/Previous when the API returns a pagination cursor.
6. Open Delete, demonstrate cancellation, then confirm deletion and verify the DynamoDB row is gone.
7. Continue to the crawler and CloudWatch portion of the demonstration using the existing operator commands.

The page requests 25 targets at a time. Counts and filters refer to the currently loaded page. DynamoDB scans have no guaranteed sort order or cross-page snapshot. A mutation resets pagination and filters and reloads page 1. If a refresh fails, previously loaded targets remain labelled as last loaded data.

**Last API round trip** is measured in the browser and includes the entire request/response. It is separate from the Lambda's measured DynamoDBReadMs/DynamoDBWriteMs SDK timings. An enabled target is queued for the crawler; its availability is determined by a crawler run and shown in CloudWatch. The browser has no run-now button. The recurring crawler remains on its 30-minute schedule.

## Errors and recovery

The client reports API validation, missing targets, throttling, storage failures and invalid response shapes. It times requests out after 20 seconds and never retries a write automatically. After a timeout or network error, a write may have completed: refresh and inspect the target list before submitting again. Refreshing the current page is not a complete search of a multi-page table; use the API/DynamoDB view when resolving an uncertain create outcome.

The server exposes only an explicit dashboard asset allowlist and `/config.json`; it cannot browse repository files or serve credentials. It binds only to 127.0.0.1. It is a local demonstration tool, not a public production web host.

If an old deployment fails browser requests, redeploy the CORS change. JSON writes require OPTIONS preflight. Lambda responses and API Gateway default 4XX/5XX responses include Access-Control-Allow-Origin. See [API documentation](API.md).

## Automated checks

~~~bash
npm ci
npm run test:dashboard
npx playwright install --with-deps chromium
DASHBOARD_PYTHON=python npm run test:browser
~~~

Activate the project's Python environment first. On PowerShell set `$env:DASHBOARD_PYTHON="python"`, then run `npm run test:browser`. The browser suite starts and stops its own loopback simulator on port 8787; stop any manually running server on that port first.

The native Node tests enforce at least 95% line coverage for `web/api-client.mjs` and `web/view-model.mjs`. This scope excludes DOM orchestration and CSS, which are checked separately by Playwright on desktop and mobile viewport configurations. Browser checks cover HTTP CRUD, validation errors, pagination, cancellation, text-safe rendering, duplicate-write prevention, stale data and mode changes. GitHub Actions runs all three test layers; CodePipeline also blocks on the Node client tests alongside Python tests. Real AWS stage checks remain separate.

The existing live CRUD integration test now sends a browser Origin, verifies wildcard CORS without credentials, checks collection/item OPTIONS preflight and records `browser_cors_verified` in JUnit. That check runs against each deployed stage. Its assertions have not been exercised against AWS by local rehearsal; collect the passing stage reports after deployment.

For an environment with an existing compatible Chromium binary, `DASHBOARD_CHROMIUM_PATH` selects it explicitly. The default uses the Chromium version downloaded for the pinned Playwright dependency. Generated screenshots, traces and JUnit reports are saved under `test-results/` and excluded from source control.

After an AWS demonstration, archive genuine evidence and run [daily teardown](../RUNBOOK.md#teardown-at-the-end-of-work). Stopping the local dashboard does not destroy AWS infrastructure.
