# Ten-minute demonstration

## Before presenting

Deploy and verify the environment before the session. Seed its targets and confirm the SNS subscription. Start `python vshydzai/scripts/serve_dashboard.py --stack WebHealth-beta` and confirm that the page shows the deployed endpoint. Open the repository, README, Project board, relevant source files, AWS dashboard, pipeline and saved rollback evidence in advance. Keep the three-slide architecture overview brief. Rehearse beforehand with `--demo`; its simulator results are not AWS assessment evidence.

## Timing

| Time | Activity |
| --- | --- |
| 0:00–1:00 | Project purpose, architecture and release design |
| 1:00–2:00 | GitHub folders, README, API contract and Project board |
| 2:00–5:00 | Create, edit, disable and delete through the browser; show corresponding DynamoDB changes |
| 5:00–6:00 | Invoke the live crawler and explain enabled-target selection |
| 6:00–8:00 | Show tests, stage blockers and pipeline progression |
| 8:00–9:00 | Show monitoring and recorded rollback recovery |
| 9:00–10:00 | Explain your code contribution and cleanup |

Deployments and canary rollouts can take longer than the presentation. Show their previously captured outcomes and deployment IDs while demonstrating the API live.

Follow [the browser demonstration sequence](DASHBOARD.md#demonstration-sequence). Keep `demo_crud.py` available as a CLI fallback against the same deployed API. Show that browser round-trip latency and Lambda DynamoDB SDK timing are separate measurements. The browser reports enabled state, while CloudWatch reports actual crawler availability.

## Code walkthrough

1. app.py selects account, region, environment or pipeline mode.
2. vshydzai_stack.py declares the API, tables, functions, schedule, telemetry and deployment groups.
3. targets_api.py maps HTTP requests to validation and repository operations.
4. target_repository.py implements conditional writes, pagination and precise SDK timing.
5. webhealth.py reads enabled targets, validates network destinations, checks sites concurrently and emits metrics.
6. deployment_hook.py checks the candidate version before traffic.
7. canary_traffic.py checks the live alias during the release.
8. release_manager.py records successful versions and handles operational rollback.
9. tests show success paths, failures and infrastructure constraints.
10. web/api-client.mjs enforces the API response contract; web/app.mjs renders target data safely and prevents overlapping writes. serve_dashboard.py serves assets or an explicit in-memory rehearsal.

## Questions to prepare

**Why DynamoDB?** The application needs small target records and simple ID lookups. Pay-per-request billing avoids provisioned capacity for this course workload.

**Why separate target and alarm tables?** Targets describe the work to perform. Alarm records document past monitoring events and have a different lifecycle.

**How does an API update affect the crawler?** The next run scans the same environment's table and selects enabled records. No function code deployment is needed.

**Why use aliases?** API Gateway and EventBridge invoke live. A release changes which published version receives that traffic, so rollback can restore the previous code/configuration.

**What blocks an unsafe release?** Local build tests, the candidate hook, operational canary alarms, stage integration checks and production approval.

**What is the memory metric?** Python peak RSS is measured in the function. The dashboard also queries Lambda REPORT logs for full runtime Max Memory Used.

**What does the performance test measure?** SDK read/write elapsed time includes networking and retries. The integration report records actual observations rather than assuming a fixed service SLA.

**Why 30 minutes?** The schedule meets the course reminder and limits routine executions. Canary checks are bounded release-triggered tests.

**What happens when a website is down?** That target records unavailable status and raises the monitoring alert. Software release alarms use function/operation health.

**How does cleanup handle stages?** It deletes the separate application stacks as well as the pipeline, then verifies owned functions, tables, logs and the artifact bucket disappear.

## After presenting

Archive the evidence, then execute cleanup.py. Keep the source code and report in GitHub for marking.
