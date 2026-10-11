# WebHealth applied project report

## Project purpose

WebHealth manages a list of websites and checks their operational health on AWS. The original implementation read a packaged JSON list. The extended design stores editable targets in DynamoDB and exposes a public API so a client can create, list, inspect, update and delete them. Enabled records become the input to scheduled checks.

This report describes the implemented design and local verification. The evidence checklist identifies the AWS observations still needed before final submission. It makes no claim that an unobserved deployment, pipeline run or rollback succeeded.

The browser target manager provides the demonstration interface. It calls the public API directly for CRUD, reads an individual target before editing, supports current-page filters and cursor navigation, and displays actionable errors. Its page counts and browser round-trip timing are labelled separately from global target counts and DynamoDB SDK measurements. CloudWatch remains the source of crawler health and availability.

## Requirements and scope

The project combines CRUD target management, Python business logic, AWS CDK infrastructure, staged CI/CD and operational telemetry. The recurring crawler cadence is 30 minutes. Every owned CloudFormation resource has an explicit removal policy. Project infrastructure must be destroyed when each working session ends.

The crawler performs website health checks. It measures availability, response latency and HTTP status rather than recursively extracting page content. The supplied brief defines target management and monitoring requirements; no content-extraction contract is assumed.

## Architecture and data

API Gateway passes REST proxy events to the CRUD Lambda's live alias. Validation accepts only editable target fields. The repository layer handles DynamoDB operations. Target IDs and UTC timestamps come from the server, and conditional update/delete operations prevent missing records from being silently created.

The crawler reads enabled records from the same environment's Targets table. It handles paginated scans, caps enabled targets at 25 and uses five workers. Each HTTP operation has a three-second timeout. The Lambda timeout is 90 seconds, replacing the original default timeout that was shorter than an individual HTTP request.

Targets, AlarmLogs and ReleaseState have different responsibilities. Targets defines work. AlarmLogs stores deduplicated SNS notifications with expiry. ReleaseState records successful current/previous Lambda versions for operational recovery. Beta, Gamma and Prod have independent records, names and metric dimensions in one region.

## API behaviour

POST creates a target. GET supports individual reads and cursor-based list pagination. PUT replaces editable fields while preserving creation time. DELETE removes an existing target. The API returns 201, 200 and 204 on success, 400 for invalid input, 404 for missing targets, and safe server-error responses for storage or internal failures.

The demonstration endpoint is public as required. API Gateway rate/burst throttling bounds incoming requests. There is no per-user access-control model in this course implementation.

## Network and permission controls

The crawler validates each URL, DNS result and redirect destination. It rejects private/internal addresses and connects to the validated address while preserving the original hostname for HTTP and TLS verification. This prevents a target record from directing the function at an internal service through a redirect or a second DNS lookup.

The crawler role has read-only target access. The API role can perform target CRUD. The alarm logger writes alarm history. Release helpers have access to their own functions, aliases and release-state table. Some control-plane list/describe actions require a wildcard resource, while data operations use the relevant resource ARNs.

## Automated delivery

GitHub Actions validates pull requests with lint, local tests and infrastructure synthesis. Enforcing merge protection requires the repository's main branch to require the actual validate check.

The browser chunk adds native Node client tests and desktop/mobile Playwright checks to GitHub validation. CodePipeline also runs the client tests with a 95% line gate for the API client and view model, alongside its existing 85% Python statement gate. CodeBuild explicitly selects Node 22 and Python 3.12 to match the local setup.

AWS CodePipeline reads the source repository through a CodeConnections connection. CodeBuild runs the local tests and synthesizes the cloud assembly. CDK deployment stages promote the selected revision through Beta, Gamma and Prod. Each stage includes live integration checks. Production also includes an approval action.

This separates source validation from deployed-service verification. The pipeline stops if a test process exits unsuccessfully. Stage checks use actual CloudFormation outputs, so generated endpoint names do not need to be copied into source code.

## Monitoring and recovery

CloudWatch receives website metrics and operational measurements through Embedded Metric Format. SDK read/write elapsed time includes client-side networking and retries. Function invocation/error/throttle metrics supplement crawler run duration and target counts. Aggregate website unavailability and maximum target latency alarms preserve alerts when the editable list changes.

The function measures Python process peak RSS and memory utilization. The dashboard's REPORT query exposes Lambda's full runtime Max Memory Used. These measurements have different boundaries and are labelled accordingly.

CodeDeploy uses a five-minute, ten-percent canary shift. A pre-traffic hook checks the candidate version. A bounded event-driven worker waits for candidate alias routing, then checks the candidate directly and the live alias. Candidate detection therefore does not depend on a small sample reaching the ten-percent route. SDK/response failures emit probe failure metrics, and remaining-time checks bound the worker without changing the 30-minute crawler schedule.

Deployment alarms can stop and roll back an active release. After success, ReleaseManager stores the version pair with millisecond completion ordering and rejects older/duplicate events. A later operational alarm can restore the prior version if the alarm remains active, no CodeDeploy deployment is running and the alias still matches the recorded current version. RevisionId guards reject stale alias updates; conditional writes preserve concurrently changed history. These controls reduce races but are not a distributed lock between services. Successful CodeDeploy rollback events do not record the failed version as a future recovery target.

## Testing

Unit tests cover validation, HTTP behaviour, DNS checks, transport pinning, conditional storage operations, timing and release decisions. Functional tests exercise complete API/crawler flows using mocked AWS and HTTP boundaries. Infrastructure tests verify the routes, cadence, permissions, aliases, removal policies and stage blockers.

Three integration tests target deployed AWS: public CRUD with direct storage verification and timing, crawler consumption of an API-created target, and SNS delivery to alarm history. The tests remove their own records. Missing live configuration causes a failure when live execution is requested.

The local validation receipt records observed results. AWS stage reports and screenshots remain separate evidence. Performance thresholds should be based on a documented workload and measured results, rather than an invented service guarantee.

Dashboard functional tests exercise actual loopback HTTP against an explicit in-memory simulator. The simulator shares deployed target validation, binds only to 127.0.0.1 and serves an asset allowlist. Its local records disappear when the server stops. These tests and the browser rehearsal do not establish DynamoDB, crawler, alarm or deployment behaviour on AWS.

## Operations and teardown

The runbook supplies deployment, seed, demonstration, troubleshooting and rollback procedures. Daily teardown deletes the pipeline and separate application stacks. The artifact bucket deletes objects automatically. Tables and logs use destruction policies. Lambda versions retain their code between releases; deleting the parent function removes its versions during teardown.

The cleanup script verifies project functions, tables, log groups and artifact buckets disappear. Shared CDK bootstrap resources and the imported connection are external prerequisites and require separate account-level review.

The operational follow-up adds a strict intended-account check, read-only bootstrap/connection preflight, read-only evidence snapshots and checkpointed teardown receipts. Cleanup uses inventoried stack IDs, paginates execution/log checks, waits without abandoning active actions, and stops on permission or verification failures. Preview receipts and incomplete deletion receipts are not reported as successful teardown. Operator tests mock AWS boundaries; they are not evidence of actual account deletion or deployment permission.

## Demonstration and technical contribution

The presentation begins with a brief architecture overview and then shows the GitHub repository, README, Project board and live API operations. The walkthrough explains how a request reaches DynamoDB, how the next crawler run consumes changed targets, how tests block promotion and how a previous version receives traffic after recovery.

For the API portion, the browser connects to the actual Beta stage while the presenter shows matching DynamoDB changes. It uses wildcard CORS without credentials because the course API is public. OPTIONS preflight is handled by API Gateway; Lambda and gateway error responses expose the CORS headers required for browser diagnostics. Target names are rendered as text, target links are restricted to HTTP(S), writes cannot overlap, and uncertain write outcomes require inspection before retrying. The dashboard adds no cloud hosting resources and does not change the 30-minute crawler schedule.

The implementation replaces the static runtime target list, adds CRUD and validation, introduces stage isolation and release automation, and makes behaviour testable. Commits, linked issues and the code walkthrough provide evidence of those technical changes. The final presenter should explain the design decisions and reproduce the observed outcomes.

## Evaluation and remaining verification

The local implementation satisfies the source-level checks recorded in the validation receipt. Final evaluation still requires the deployed CRUD responses, all stage integration runs, successful/blocked pipeline executions, genuine alarm transitions, rollback recovery, merge-protection settings, Project board properties and teardown verification.

Those observations should be attached to the evidence checklist before submission. They determine whether the implemented design behaves correctly in the selected AWS account and permissions.

## References

Amazon Web Services. API Gateway, Lambda and DynamoDB tutorial. https://docs.aws.amazon.com/lambda/latest/dg/services-apigateway-tutorial.html

Amazon Web Services. Continuous integration and delivery using CDK Pipelines. https://docs.aws.amazon.com/cdk/v2/guide/cdk-pipeline.html

Amazon Web Services. LambdaDeploymentGroup API reference. https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_codedeploy/LambdaDeploymentGroup.html

Amazon Web Services. Lambda function metrics. https://docs.aws.amazon.com/lambda/latest/dg/monitoring-metrics-types.html

Amazon Web Services. Configure Lambda function timeout. https://docs.aws.amazon.com/lambda/latest/dg/configuration-timeout.html

Amazon Web Services. CDK removal policies. https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk/RemovalPolicy.html

GitHub. About protected branches. https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
