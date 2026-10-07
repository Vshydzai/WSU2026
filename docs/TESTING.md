# Testing and requirement map

## Local checks

~~~bash
cd vshydzai
ruff check .
pytest -m "not integration" --cov=lambda_src --cov-report=term-missing --junitxml=test-results/local.xml
~~~

Local functional tests use Moto for DynamoDB and mock HTTP transport. They exercise complete handlers and persistence flows without deploying AWS or crawling real websites.

| Requirement | Implementation |
| --- | --- |
| 10 crawler unit tests | test_crawler.py covers status, failures, validation, DNS, pinned connections, redirects and measured timing |
| 8 crawler functional tests | First eight tests in test_application.py cover target selection, empty lists, failures, API changes, disabling, metrics, pagination and capacity |
| 2 additional CRUD unit tests | test_crud.py covers conditional writes, missing updates, cursor handling, timing and encoded bodies |
| 1 CRUD functional test | Complete CRUD lifecycle with missing-item behaviour |
| 2 crawler integration tests | Deployed Lambda reads the API-created target; SNS event reaches alarm history |
| 1 CRUD integration test | Public CRUD with direct DynamoDB verification and measured SDK read/write time |
| Additional infrastructure tests | Routes, permissions, cadence, runtime budget, aliases, removal policies and pipeline blockers |
| Additional release tests | Hook success/failure, completed-release state, alarm recovery, active deployment, duplicate events and safe rollback |

[Local-validation receipt](evidence/local-validation.json) lists the observed results.

## Live checks

~~~bash
python vshydzai/scripts/run_live_tests.py --stack WebHealth-beta
~~~

The script reads actual URLs/resource names from CloudFormation. Use the Gamma/Prod stack name to test those environments. The pipeline automatically provides these outputs to its stage checks.

Without --run-live, integration tests are skipped. With --run-live, missing configuration causes failure. The tests do not silently pass when no deployment exists.

Live tests remove only their own target and benchmark records. SNS test records are labelled test events and removed afterwards. SDK read/write times are recorded as JUnit properties. A performance budget can be supplied through DYNAMODB_LATENCY_BUDGET_MS.

## Test blockers

A nonzero PyTest exit status fails the CodeBuild action. Verify a deliberately failing check in a controlled branch and capture the stopped pipeline. Fix it and capture a successful run of the same stage sequence.

GitHub's validate job supplies the pull-request check. Configure it as required on main through repository branch settings or a ruleset. Writing the workflow alone does not enforce merge protection.

Canary and operational rollback checks need real AWS observations. Unit tests establish the decision logic; the Beta exercise in the runbook verifies the deployed alarm/alias workflow.
