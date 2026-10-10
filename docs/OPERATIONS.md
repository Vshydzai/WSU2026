# Operator tools and evidence boundaries

Run these commands from the repository root with the Python environment active. Set `DEPLOY_ACCOUNT` to the account you intend to operate in and `DEPLOY_REGION` to the selected region. The tools compare the active STS account with the intended account before reading project configuration or running actions. They do not copy credentials or change your AWS profile.

## Commands

| Command | AWS effect | Result meaning |
| --- | --- | --- |
| `preflight.py --identity-only` | Read STS identity | Account matches; no bootstrap/permission proof |
| `preflight.py --pipeline` | Read identity, CDKToolkit and GitHub connection | Readable prerequisites are ready; not proof of deploy permissions |
| `seed_targets.py --stack WebHealth-beta` | Create missing seed targets through the public API | Existing URLs remain; repeated seed entries are deduplicated |
| `demo_crud.py --stack WebHealth-beta` | Create/read/update/delete its own demo target | Exact CRUD statuses plus deleted-record 404 verified |
| `run_live_tests.py --stack WebHealth-beta` | Live API/storage/crawler/SNS checks | Three integration tests passed or failed in this environment |
| `collect_evidence.py --stack WebHealth-beta` | Read AWS state only | Observed snapshot; failed/unavailable states stay visible |
| `cleanup.py` | Read stack inventory only | Preview, never proof of deletion |
| `cleanup.py --execute` | Stop pipeline actions and delete allowlisted stacks | Checkpointed deletion plus owned-resource verification |

Use the `python vshydzai/scripts/` prefix for each command. The same commands work in PowerShell after setting `$env:DEPLOY_ACCOUNT` and `$env:DEPLOY_REGION`. Preflight, evidence and cleanup also accept explicit `--account` and `--region` flags.

## Before deployment

~~~bash
python vshydzai/scripts/preflight.py --identity-only
npx cdk bootstrap "aws://$DEPLOY_ACCOUNT/$DEPLOY_REGION"
python vshydzai/scripts/preflight.py --pipeline --output vshydzai/test-results/preflight.json
~~~

For a direct Beta deployment, omit `--pipeline`; no connection is required. A pipeline check requires the real `CONNECTION_ARN`. Both older `codestar-connections` and newer `codeconnections` connection ARNs are accepted. Host ARNs, another account/region, PENDING/ERROR connections and non-GitHub providers fail the check.

Exit 0 means the requested readable prerequisites passed. Exit 1 means a check failed or could not be read. Exit 2 means identity, input or a blocking SDK error prevented the check. An AVAILABLE connection does not by itself prove that WSU2026 was included in the GitHub authorization. CDK still validates bootstrap compatibility and deployment permissions during deployment.

## Collect state before destroying it

~~~bash
python vshydzai/scripts/run_live_tests.py --stack WebHealth-beta
python vshydzai/scripts/collect_evidence.py --stack WebHealth-beta --hours 2 --output vshydzai/test-results/beta-evidence.json
~~~

For a rollback exercise, use separate before/after filenames at the actual observation times. Preserve the deployment ID and source revision alongside JUnit output and screenshots. A before/after alias version change without a correlated alarm/deployment/recovered result is not a complete rollback demonstration.

The collector saves stack inventory, application aliases, release records, recent deployments/executions, state-change alarm history and selected WebHealth timing/memory metrics. It does not export the function environment, application log messages or credentials. It does not create requests, invoke functions, publish SNS messages, set alarm states or mutate AWS resources.

`complete: true` means every requested section was readable. It does **not** mean healthy or passed: an observed failed deployment or ALARM remains in the data. `interpretation: no_data` means the metric had no samples. A partial receipt returns exit 1. Missing identity/stack access returns exit 2. Direct deployment without WebHealth CodePipeline produces a partial receipt for the missing pipeline.

History is deliberately bounded: 25 state changes per alarm, 10 deployments per group, 10 pipeline executions, and a 1–24 hour metric/history window. Release records are read with a 25-item cap. This is demonstration evidence, not a complete account audit. Dashboard screenshots, email notifications and actual test runs remain separate evidence.

## Daily teardown

~~~bash
python vshydzai/scripts/cleanup.py
python vshydzai/scripts/cleanup.py --execute --output vshydzai/test-results/cleanup.json
~~~

The allowlist is WebHealth-Pipeline, WebHealth-prod, WebHealth-gamma and WebHealth-beta, in that order. Add `--include-legacy` only for the original VshydzaiStack. No wildcard account sweep is performed. Shared CDKToolkit assets and imported CodeConnections are explicitly outside scope.

All stack inventory is read before deletion. Active pipeline executions are stopped with `abandon=False`; the tool rechecks paginated execution lists and waits up to 20 minutes. A timeout or permission error stops cleanup before stack deletion. Avoid new pushes or manual executions during teardown; there is no cross-service lock that disables all incoming triggers.

Each stack is deleted by its inventoried immutable ID, then a CloudFormation waiter observes deletion. The receipt is written before deletion and after each completed stack, so an interrupted session retains progress. `deletion_requests` can contain a stack whose deletion has not finished; `deleted_stacks` contains only observed waiter completions. `verified: true` is set only after the inventoried Lambda functions, DynamoDB tables, paginated log groups and S3 buckets are no longer present. A denied bucket read never counts as deletion.

These are destructive course-teardown operations: targets, alarm logs and release history are deleted with the tables and cannot be recovered by this tool. Export required submission evidence first. Receipt verification covers the inventoried resources, not untracked orphan resources or external bootstrap assets. Review the AWS account separately for unrelated retained resources.

## AWS read/action permissions

This table describes the tool calls, not an instruction to grant broad administrator access. Use the applicable course role and restrict resource ARNs wherever the API supports it.

| Tool | Calls |
| --- | --- |
| All account-checked tools | `sts:GetCallerIdentity` |
| Preflight | `cloudformation:DescribeStacks`, `codeconnections:GetConnection` for pipeline mode |
| Live configuration | `cloudformation:DescribeStacks` |
| Evidence | `cloudformation:DescribeStacks`, `cloudformation:ListStackResources`, `lambda:GetAlias`, `lambda:GetFunctionConfiguration` for the project's release-manager mapping, `dynamodb:Scan` on ReleaseState, `cloudwatch:DescribeAlarms`, `cloudwatch:DescribeAlarmHistory`, `cloudwatch:GetMetricStatistics`, `codedeploy:ListDeployments`, `codedeploy:GetDeployment`, `codepipeline:ListPipelineExecutions` |
| Cleanup | `cloudformation:DescribeStacks`, `cloudformation:ListStackResources`, `cloudformation:DeleteStack`, execution list/get/stop in CodePipeline, `lambda:GetFunction`, `dynamodb:DescribeTable`, `logs:DescribeLogGroups`, `s3:ListBucket` for bucket existence checks; CloudFormation also needs the permissions/service role to delete stack resources |

Secrets, expired sessions and AccessDenied are stop/review conditions, not reasons to bypass account protections. No deploy, genuine alarm, rollback or teardown has been executed by the local operator tests. The [latest validation receipt](evidence/operational-readiness-validation.json) states what was actually run.
