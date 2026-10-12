# WebHealth

WebHealth is the COMP2029 DevOps applied project. A browser target manager calls a public REST API to manage websites in DynamoDB. A Python Lambda checks enabled websites every 30 minutes and records availability, latency and HTTP status. AWS CDK defines the infrastructure and a pipeline promotes one revision through Beta, Gamma and Prod.

## Verification status

Local Python validation passes 186 tests: 152 unit/infrastructure tests and 34 functional tests, with 92.22% statement coverage of `lambda_src` and `scripts`. Twenty Node client tests pass with 100% line coverage of `web/api-client.mjs` and `web/view-model.mjs`. Twenty-six desktop/mobile browser checks pass separately. The [validation receipt](docs/evidence/browser-dashboard-validation.json) records observed checks and their scopes. Three additional integration tests require a deployed AWS environment. GitHub Actions and the pipeline build enforce at least 85% Python statement coverage and 95% line coverage of the two tested client modules. Live API, pipeline, alarm, rollback and teardown evidence must come from AWS. [The evidence checklist](docs/EVIDENCE.md) tracks that work.

## Architecture

~~~mermaid
flowchart TD
    Client["Browser or CLI client"] --> API["API Gateway"]
    API --> CRUD["CRUD Lambda: live alias"]
    CRUD <--> Targets[("DynamoDB Targets")]
    Schedule["EventBridge: 30 minutes"] --> Crawler["Crawler Lambda: live alias"]
    Targets --> Crawler
    Crawler --> CW["CloudWatch metrics and alarms"]
    CW --> SNS["SNS"]
    SNS --> Logger["Alarm logger"]
    Logger --> History[("DynamoDB AlarmLogs")]
~~~

Each environment has its own API, tables, functions, dashboard and metric dimensions. The default deployment region is us-east-2. The API Gateway account logging role is shared within that account and region.

## API

| Method | Route | Result |
| --- | --- | --- |
| POST | /targets | Create a target, return 201 |
| GET | /targets | List a page of targets |
| GET | /targets/{id} | Read a target |
| PUT | /targets/{id} | Replace editable fields |
| DELETE | /targets/{id} | Delete a target, return 204 |

Use name, url and an optional enabled boolean. The server generates IDs and timestamps. [API documentation](docs/API.md) and [OpenAPI](docs/openapi.yaml) contain the complete contract.

## Local setup

Install Python 3.12 and Node.js 22. From the repository root:

~~~bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r vshydzai/requirements-dev.txt
npm ci
cd vshydzai
ruff check .
pytest -m "not integration"
cd ..
npm run test:dashboard
~~~

In PowerShell, create the environment with py -3.12 -m venv .venv and activate .\.venv\Scripts\Activate.ps1. The remaining Python and npm commands are the same.

## Browser demonstration

Rehearse immediately without AWS credentials or deployment:

~~~bash
python3 vshydzai/scripts/serve_dashboard.py --demo
~~~

Open **http://127.0.0.1:8787**. The **Local simulator** label explains that records are temporary and no AWS calls are made. For assessment, run `python vshydzai/scripts/serve_dashboard.py --stack WebHealth-beta` against a deployed stack and show the corresponding DynamoDB changes. The browser supports CRUD, filtering of the current page, cursor pagination and actionable errors. [The dashboard guide](docs/DASHBOARD.md) covers the full sequence and browser tests.

## Deploy and test

Use your own AWS session. Configure DEPLOY_ACCOUNT, DEPLOY_REGION and optionally NOTIFICATION_EMAIL. Set DEPLOY_ACCOUNT from aws sts get-caller-identity. No credentials belong in this repository.

~~~bash
export DEPLOY_ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
export DEPLOY_REGION=us-east-2
python vshydzai/scripts/preflight.py --identity-only
npx cdk bootstrap "aws://$DEPLOY_ACCOUNT/$DEPLOY_REGION"
python vshydzai/scripts/preflight.py
npm run synth
npm run deploy:beta
python vshydzai/scripts/seed_targets.py --stack WebHealth-beta
python vshydzai/scripts/run_live_tests.py --stack WebHealth-beta
python vshydzai/scripts/demo_crud.py --stack WebHealth-beta
~~~

See [the runbook](RUNBOOK.md) for PowerShell commands, pipeline setup and recovery. The seed script uses sites.json only to populate DynamoDB. The crawler's runtime source is DynamoDB.

## CI/CD and recovery

GitHub Actions runs lint, Python/Node tests, desktop/mobile browser checks and synthesis on pushes and pull requests. The repository owner must configure the validate status check as required on main.

AWS CodePipeline reads GitHub through a CodeConnections connection. CodeBuild runs the build tests. Beta and Gamma must pass live service tests before progression. Production requires approval, then its own live checks. A failed test command fails its action and stops progression.

CodeDeploy shifts 10% of alias traffic for five minutes before completing a release. A pre-traffic hook invokes the candidate version. A bounded release-triggered worker waits for actual alias routing, then checks both the candidate version directly and the live alias. Direct checks prevent a broken candidate from being missed because a small sample reached only the old version. That worker has no recurring schedule. Operational alarms can stop and roll back the deployment.

After successful deployments, the release manager records the current and previous versions with millisecond completion ordering. Operational alarm events can restore the previous version after the release completes. It checks that the alarm is still active, that CodeDeploy has no active release, and that the alias still points to the recorded version. A revision guard rejects stale alias updates, and conditional storage updates preserve newer release history. These checks reduce races; they are not a distributed lock. Website unavailability and target latency of at least 3,000 ms produce alerts independently of software rollback.

## Monitoring and quality

CloudWatch displays website availability, latency and HTTP status, plus function invocations, errors, throttles, crawler run duration and DynamoDB SDK read/write times. Embedded Metric Format records these timings without a synchronous PutMetricData call.

Memory alarms use the Python process peak RSS divided by allocated memory. This measures the process, including imported modules, but does not represent the entire Lambda runtime. A Logs Insights widget reads the full Max Memory Used field from Lambda REPORT records.

The public demonstration API has throttling of five requests per second and a burst limit of ten. It has no per-user authorization. Target validation rejects malformed URLs and private IP literals. The crawler validates DNS results on every connection and redirect and pins the checked address while preserving HTTPS certificate verification. It checks at most 25 enabled targets using five workers. Requests have a three-second timeout; the crawler has a 90-second Lambda budget. Excess capacity fails visibly instead of silently dropping targets.

SNS alarm records use MessageId for retry deduplication and expire after 30 days. The course teardown removes the table sooner when a working session ends.

## Repository

| Path | Purpose |
| --- | --- |
| vshydzai/app.py | Select a direct environment or pipeline |
| vshydzai/vshydzai/ | CDK application, stages, pipeline and removal policies |
| vshydzai/lambda_src/ | API, repository, crawler, telemetry and release handlers |
| vshydzai/tests/unit/ | Behaviour and infrastructure assertions |
| vshydzai/tests/functional/ | Full application flows with mocked boundaries |
| vshydzai/tests/integration/ | Deployed AWS checks |
| vshydzai/scripts/ | Account checks, preflight, seed, demo, live tests, evidence and cleanup |
| web/ | Browser dashboard, public API client, Node tests and browser checks |
| .github/workflows/ci.yml | Pull-request validation |
| docs/ | API contract, report, demonstration and evidence |

## Daily teardown

Destroy project infrastructure after work. The application stacks created by the pipeline are separate CloudFormation stacks, so removing only the pipeline does not remove them.

~~~bash
python vshydzai/scripts/collect_evidence.py --stack WebHealth-beta --output vshydzai/test-results/beta-before-cleanup.json
python vshydzai/scripts/cleanup.py
python vshydzai/scripts/cleanup.py --execute
~~~

Set `DEPLOY_ACCOUNT` to the intended account; the scripts reject credentials for another account. Add --include-legacy only when removing the earlier VshydzaiStack as well. Cleanup previews by default, stops active pipeline executions without abandoning actions, deletes inventoried stack IDs and verifies the functions, tables, logs and artifact buckets disappear. It checkpoints a JSON receipt after each stack. Old Lambda versions have an explicit retention policy for rollback between releases; deleting their parent function removes those versions. [Operator tools](docs/OPERATIONS.md) explains the receipt fields and permission requirements.

The imported CodeConnections connection and shared CDKToolkit bootstrap are external deployment prerequisites. Review those separately when the account is dedicated to this project.

## Assessment materials

- [Project report](docs/PROJECT_REPORT.md)
- [Testing map](docs/TESTING.md)
- [Demonstration and Q&A](docs/DEMONSTRATION.md)
- [GitHub Project setup](docs/GITHUB_PROJECT.md)
- [Evidence checklist](docs/EVIDENCE.md)
- [Operator tools and evidence limits](docs/OPERATIONS.md)
- [Browser dashboard and local rehearsal](docs/DASHBOARD.md)
- [Architecture slides](docs/WebHealth_Architecture.pptx)

## References

- [API Gateway, Lambda and DynamoDB](https://docs.aws.amazon.com/lambda/latest/dg/services-apigateway-tutorial.html)
- [CDK Pipelines](https://docs.aws.amazon.com/cdk/v2/guide/cdk-pipeline.html)
- [CodeDeploy Lambda deployments](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_codedeploy/LambdaDeploymentGroup.html)
- [Lambda metrics](https://docs.aws.amazon.com/lambda/latest/dg/monitoring-metrics-types.html)
- [Removal policies](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk/RemovalPolicy.html)

## Deployment without CodeDeploy

An explicit `alias` alternative retains CodePipeline, all three stages and live test gates. CDK/CloudFormation uses native Lambda alias traffic splitting (10% for five minutes), with candidate checks and automatic CloudWatch/EventBridge rollback. Select `npm run deploy:beta:alias` or `npm run deploy:pipeline:alias`; the existing CodeDeploy option is still available. See [setup, recovery and evidence steps](RUNBOOK.md#alternative-codepipeline-with-native-lambda-alias-releases). This implementation is locally tested; actual account service access and live release evidence must be verified.
