# Testing and requirement map

## Local checks

~~~bash
cd vshydzai
ruff check .
pytest -m "not integration" --cov=lambda_src --cov=scripts --cov-fail-under=85 --cov-report=term-missing --cov-report=json:test-results/coverage.json --junitxml=test-results/local.xml
~~~

Local functional tests use Moto for DynamoDB and mock HTTP transport. They exercise complete handlers and persistence flows without deploying AWS or crawling real websites.

The dashboard HTTP tests run a real loopback server against in-memory targets. They verify its asset allowlist, lifecycle, validation failures and explicit simulator mode. They do not contact AWS.

From the repository root run `npm run test:dashboard` for the public API client, response validation, timeout/no-retry behaviour, filtering and pagination. Run `npx playwright install --with-deps chromium`, then `DASHBOARD_PYTHON=python npm run test:browser` for desktop/mobile browser flows. See [DASHBOARD.md](DASHBOARD.md#automated-checks) for Windows and alternate Chromium commands.

| Requirement | Implementation |
| --- | --- |
| 10 crawler unit tests | test_crawler.py covers status, failures, validation, DNS, pinned connections, redirects and measured timing |
| 8 crawler functional tests | First eight tests in test_application.py cover target selection, empty lists, failures, API changes, disabling, metrics, pagination and capacity |
| 2 additional CRUD unit tests | test_crud.py covers conditional writes, missing updates, cursor handling, timing and encoded bodies |
| 1 CRUD functional test | Complete CRUD lifecycle with missing-item behaviour |
| 2 crawler integration tests | Deployed Lambda reads the API-created target; SNS event reaches alarm history |
| 1 CRUD integration test | Public CRUD with direct DynamoDB verification and measured SDK read/write time |
| Browser stage gate | The existing live CRUD test verifies collection/item preflight and CORS on CRUD/404 responses; no fourth AWS integration test is introduced |
| Additional infrastructure tests | Routes, permissions, cadence, runtime budget, aliases, removal policies and pipeline blockers |
| Additional release tests | Hook success/failure, completed-release state, alarm recovery, active deployment, duplicate events and safe rollback |
| Release hardening | Published-version/AppSpec validation, deterministic candidate checks, alias routing readiness, SDK failures, budget limits, millisecond ordering and conditional history updates |
| Operator unit tests | Account guard, connection prerequisites, pagination, fail-closed cleanup, HTTP status contracts and per-environment test reports |
| Operator functional tests | Full preflight/evidence/cleanup command flows with AWS boundaries mocked; no live resources are created or deleted |
| Dashboard Python tests | Shared target validation, in-memory CRUD/pagination, loopback HTTP, static-file boundaries and explicit CLI modes |
| CORS tests | Business/error response headers, mock OPTIONS preflight, gateway errors, live-alias routing and resource removal policies |
| Dashboard Node tests | API contracts, safe URLs, malformed responses, no credentials, write timeout/uncertain outcomes and cursor history |
| Browser checks | Desktop/mobile HTTP CRUD, validation, cursor pages, cancellation, text-safe rendering, duplicate writes and stale-data recovery |

[Latest validation receipt](evidence/browser-dashboard-validation.json) lists the observed results. The [operational-readiness receipt](evidence/operational-readiness-validation.json) and earlier [receipt](evidence/local-validation.json) remain historical. Python coverage includes `lambda_src` and `scripts`. GitHub Actions and the CodePipeline build both fail below 85% combined statement coverage. Node coverage has a separate 95% line gate for `api-client.mjs` and `view-model.mjs`; it excludes `app.mjs` DOM code and CSS. GitHub Actions runs Playwright as an additional blocker. CodePipeline runs Python/Node build tests and its existing real AWS stage integration tests.

## Live checks

~~~bash
python vshydzai/scripts/run_live_tests.py --stack WebHealth-beta
~~~

The script reads actual URLs/resource names from CloudFormation. Use the Gamma/Prod stack name to test those environments. The pipeline automatically provides these outputs to its stage checks.

Without --run-live, integration tests are skipped. With --run-live, missing configuration causes failure. The tests do not silently pass when no deployment exists.

Live tests remove only their own target and benchmark records. SNS test records are labelled test events and removed afterwards. SDK read/write times are recorded as JUnit properties. A performance budget can be supplied through DYNAMODB_LATENCY_BUDGET_MS.

The crawler test requires HTTP 200–399, availability 1 and positive measured latency for the API-created Example target. Status 0 is a transport failure, not a passing integration result. Reports from the runner are named per environment and use the legacy JUnit family to retain timing properties compatibly.

## Test blockers

A nonzero PyTest exit status fails the CodeBuild action. Verify a deliberately failing check in a controlled branch and capture the stopped pipeline. Fix it and capture a successful run of the same stage sequence.

GitHub's validate job supplies the pull-request check. Configure it as required on main through repository branch settings or a ruleset. Writing the workflow alone does not enforce merge protection.

Canary and operational rollback checks need real AWS observations. Unit tests establish the decision logic; the Beta exercise in the runbook verifies the deployed alarm/alias workflow.
