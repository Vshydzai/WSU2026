# WebHealth Runbook

## Check Website Health

1. Open AWS CloudWatch.
2. Open `WebHealth-Dashboard`.
3. Check the Availability and Latency graphs.
4. Check CloudWatch alarms for any problems.

## Availability

* `1` = website is available
* `0` = website is unavailable

## Latency

Latency is measured in milliseconds.

Higher latency means the website is responding more slowly.

## If a Website Has a Problem

1. Check the CloudWatch alarm.
2. Check the Lambda execution.
3. Check CloudWatch logs.
4. Test the website manually.

## Cleanup

After finishing project work for the day, destroy the AWS infrastructure:

```bash
cdk destroy
```
