# WebHealth runbook

## AWS session and region

Use an AWS session that can bootstrap CDK, create project resources and run CodePipeline, CodeBuild and CodeDeploy. Check the account and region before deployment.

~~~bash
aws sts get-caller-identity
export DEPLOY_ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
export DEPLOY_REGION=us-east-2
export AWS_DEFAULT_REGION=us-east-2
~~~

PowerShell:

~~~powershell
aws sts get-caller-identity
$env:DEPLOY_ACCOUNT = aws sts get-caller-identity --query Account --output text
$env:DEPLOY_REGION = "us-east-2"
$env:AWS_DEFAULT_REGION = "us-east-2"
~~~

Optional NOTIFICATION_EMAIL adds SNS email subscriptions. Confirm each subscription through the email SNS sends.

Run `python vshydzai/scripts/preflight.py --identity-only` after setting the account and region. It checks the active session against your intended account without creating AWS resources. Account checks also apply to the seed, demonstration, live-test runner, evidence and cleanup commands. Never set `DEPLOY_ACCOUNT` to an account you do not intend to operate in.

## First direct Beta deployment

From the repository root, with the Python virtual environment active:

~~~bash
npm ci
python -m pip install -r vshydzai/requirements-dev.txt
npx cdk bootstrap "aws://$DEPLOY_ACCOUNT/$DEPLOY_REGION"
python vshydzai/scripts/preflight.py --output vshydzai/test-results/preflight.json
npm run synth
npm run deploy:beta
python vshydzai/scripts/seed_targets.py --stack WebHealth-beta
python vshydzai/scripts/run_live_tests.py --stack WebHealth-beta
~~~

For the browser CRUD demonstration, run `python vshydzai/scripts/serve_dashboard.py --stack WebHealth-beta` and open http://127.0.0.1:8787. The server reads the selected stack's API output with the intended-account guard, then the browser calls that public API directly. Ctrl+C stops the local server. See [the dashboard guide](docs/DASHBOARD.md) for the no-AWS `--demo` rehearsal, browser checks and CORS troubleshooting. Stopping this server does not tear down deployed AWS resources.

The original VshydzaiStack is a separate legacy stack. Its hardcoded AlarmLogs table does not replace the new target table. Use the legacy cleanup flag when that stack belongs to this project.

## Pipeline setup

1. In AWS Developer Tools, create a GitHub CodeConnections connection in us-east-2. Authorize this repository and complete the connection so its status is AVAILABLE.
2. Set CONNECTION_ARN to its actual ARN.
3. Bootstrap the account/region if needed.
4. Remove the direct Beta deployment before starting the full pipeline to avoid competing ownership of shared API Gateway logging configuration.
5. Deploy the pipeline.

~~~bash
export CONNECTION_ARN="your-available-connection-arn"
export SOURCE_BRANCH=main
python vshydzai/scripts/preflight.py --pipeline --output vshydzai/test-results/pipeline-preflight.json
npm run synth:pipeline
npm run deploy:pipeline
~~~

PR #51 is merged, so `main` is the normal source branch. Use a controlled feature branch only when deliberately testing a candidate revision. The synth step preserves the selected source branch and notification address during self-mutation. A preflight pass confirms readable prerequisites, not all IAM permissions or repository authorization.

PowerShell pipeline setup uses `$env:CONNECTION_ARN = "your-available-connection-arn"` and `$env:SOURCE_BRANCH = "main"`. The Python and npm commands are the same. For bootstrap, use `npx cdk bootstrap "aws://$($env:DEPLOY_ACCOUNT)/$($env:DEPLOY_REGION)"`.

The first pipeline deployment establishes the pipeline, shared API Gateway logging role and artifact bucket. Subsequent pipeline runs deploy WebHealth-beta, WebHealth-gamma and WebHealth-prod. Beta and Gamma have post-deployment integration blockers. Production includes an approval action and its own tests.

Do not shorten the 30-minute EventBridge schedule for demonstrations. Invoke the crawler manually or use the bounded deployment canary checks.

## API and crawler verification

~~~bash
python vshydzai/scripts/demo_crud.py --stack WebHealth-beta
python vshydzai/scripts/run_live_tests.py --stack WebHealth-beta
~~~

To invoke the crawler manually:

~~~bash
aws lambda invoke --function-name WebHealth-beta-Crawler --qualifier live --payload '{}' --cli-binary-format raw-in-base64-out crawler-result.json
~~~

The result should show target IDs that exist in DynamoDB. Enabled targets participate; disabled targets do not. The live test creates its own enabled target and removes it afterwards.

The crawler integration check now requires a successful HTTP response from its `https://example.com/` target. A failed network request is no longer accepted as a successful crawl. External DNS/network/site failures will block promotion and need investigation. The runner writes separate `live-WebHealth-beta.xml`, `live-WebHealth-gamma.xml` and `live-WebHealth-prod.xml` reports so later stages do not overwrite earlier evidence. SDK timing properties use the compatible JUnit family.

## Operational dashboard

Open WebHealth-beta-Dashboard in CloudWatch, or the equivalent Gamma/Prod dashboard. Set the time range to include actual executions.

Review target metrics, Lambda invocations/errors/throttles, crawler run duration, DynamoDB timing, process RSS and the REPORT memory query. Website availability and latency have a 30-minute period. TargetsUnavailable alerts on at least one unavailable target; TargetsSlow alerts when the maximum measured target latency reaches 3,000 ms. These website alerts do not trigger code rollback. Deployment health alarms have a one-minute period and treat missing data as non-breaching.

DynamoDBReadMs and DynamoDBWriteMs measure client SDK call elapsed time, including networking and retries. They are distinct from DynamoDB server-side service latency. The integration report separately records SDK read/write timings. Set DYNAMODB_LATENCY_BUDGET_MS only after deciding and documenting a measured performance budget.

## Alarm history

SNS publishes notifications to the AlarmLogger Lambda. Check the environment's AlarmLogs table. Records contain id, alarm_name, new_state, reason, timestamp and expires_at.

The SNS integration test explicitly labels its message as a test event. It verifies delivery and persistence. Actual CloudWatch alarm transitions and rollback evidence must come from a real failing invocation or release.

## Rollback exercise in Beta

Establish a healthy deployment and save its live alias version. The deliberate fault configuration is restricted to Beta.

~~~bash
aws lambda get-alias --function-name WebHealth-beta-Crawler --name live
npm run deploy:beta -- -c fault_injection=true
~~~

The pre-traffic hook performs a read-only candidate check. The release worker waits until the alias routes to this candidate, then invokes both the candidate version and the live alias with synthetic canary checks. The injected candidate raises a genuine Lambda error even if the live request hits the healthy old version. `DeploymentProbeFailures` records that failure. CodeDeploy health alarms can stop the release and return traffic to the old version. The deployment command is expected to report a failed release.

Collect the CodeDeploy deployment ID/status, alarm history, alias versions before/after and a recovered crawler result. Reset the fault setting through the next deployment:

~~~bash
npm run deploy:beta
~~~

Rollback after a completed release uses ReleaseState and ReleaseManager. On an operational ALARM event, the handler rechecks the current alarm, refuses to compete with an active deployment, and verifies the alias/current-version match. It restores the previous version with a RevisionId guard. An alias revision race produces a safe skip. A conditional history update does not overwrite a newer version pair. Repeated events do not move an already restored alias again. These read-and-update checks are not an atomic lock across CodeDeploy, Lambda and DynamoDB; avoid concurrent manual releases during the exercise.

Retained code versions remain available while the parent function exists. The process preserves code/configuration versions and target data. After operational rollback, fix the release and redeploy through the normal pipeline to reconcile the CloudFormation alias configuration.

## Save observed AWS evidence

From the repository root, before/after the rollback exercise and before teardown:

~~~bash
python vshydzai/scripts/collect_evidence.py --stack WebHealth-beta --output vshydzai/test-results/beta-before.json
python vshydzai/scripts/collect_evidence.py --stack WebHealth-beta --output vshydzai/test-results/beta-after.json
~~~

Run the commands at the corresponding times; two immediate snapshots do not prove recovery. Repeat for Gamma and Prod after their stage tests. Use `--hours 6` when the exercise spans more than the default two hours.

The collector is read-only: it does not invoke Lambda, set alarm states, change aliases or start deployments. It saves stack inventory, live aliases, release history, recent CodeDeploy/pipeline state, alarm transitions and SDK timing/memory metrics. `observed` means the read succeeded, not that the resource is healthy. `no_data` means no metric samples. Missing permissions produce a partial receipt and exit code 1; a blocking account/stack error exits 2. A direct Beta deployment without a pipeline normally has an unavailable pipeline section. Preserve that limitation rather than describing a partial snapshot as a full pipeline result.

Receipts and JUnit files are ignored by git under `test-results`. Review them before attaching to submission evidence; they can include AWS account/resource identifiers. Never commit AWS credentials or the raw function environment. See [operator tools](docs/OPERATIONS.md) for exact scope and permissions.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Connection unavailable | Complete the AWS-to-GitHub authorization in the connection settings |
| AccessDenied | Identify the exact service action in the failed event and review the applicable AWS role |
| 400 response | Read the validation message; check JSON fields, URL, boolean type and pagination cursor |
| 404 target | Confirm the ID and environment; deletes do not recreate missing records |
| No target metrics | Seed the table, enable targets and invoke the live crawler alias |
| Crawler capacity error | Reduce enabled targets to 25 or fewer; remove excessive disabled records if scan-page cap is exceeded |
| API 503 | Check DynamoDB permissions and function logs |
| No SNS email | Confirm the subscription and check the topic's delivery destinations |
| ReleaseState absent | A completed CodeDeploy release is needed to record the previous/current version pair |
| No rollback | Confirm the operational alarm, retained version, group state and alias; website-only alerts do not request code rollback |
| Stale cdk.out lock | Check for a running synth process; use a separate --output directory for independent synthesis |

## Teardown at the end of work

~~~bash
python vshydzai/scripts/cleanup.py
python vshydzai/scripts/cleanup.py --execute
~~~

Use --include-legacy when the original VshydzaiStack also needs removal. The script targets named project stacks rather than arbitrary account resources.

Preview does not delete anything and has `verified: false`. `--execute` checks your account, inventories all allowlisted stacks before deletion, waits for pipeline actions to stop, and checkpoints `vshydzai/test-results/cleanup.json` after each deleted stack. Deletion uses the inventoried stack ID. A permissions error, an unfinished action or a failed stack-delete waiter stops the process. A 403 response is not treated as proof that a bucket disappeared. Review `deletion_requests` and `deleted_stacks` if the session is interrupted; do not describe an incomplete receipt as successful teardown.

The pipeline stack has an artifact bucket with automatic object deletion. Application log groups and tables use explicit destruction policies. Function versions use explicit retention between releases and disappear when their parent function is deleted. Confirm the cleanup command's verification result in addition to CloudFormation deletion status.

Review the shared CDKToolkit bucket/ECR assets and imported CodeConnections separately when this account is dedicated to the project. Those prerequisites are outside the project stacks. Archive useful screenshots and test output before destroying a working deployment.
