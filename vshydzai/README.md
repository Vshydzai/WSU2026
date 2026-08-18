# WebHealth Application

## Project Overview

WebHealth is an AWS-based web monitoring application developed for the COMP2029 DevOps course project.

The application uses AWS Lambda to monitor a custom list of websites and measures:

- Website availability
- Website latency

The results are published to Amazon CloudWatch for monitoring.

## AWS Services

- AWS Lambda
- Amazon EventBridge
- Amazon CloudWatch
- AWS IAM
- AWS CDK

## Monitored Websites

The websites are stored in:

`lambda_src/sites.json`

Current websites:

- Western Sydney University
- Example.com

## How It Works

1. EventBridge runs the Lambda every 30 minutes.
2. Lambda reads the websites from `sites.json`.
3. Lambda checks each website.
4. Availability and latency are measured.
5. Boto3 publishes the metrics to CloudWatch.
6. CloudWatch Dashboard displays the metrics.
7. CloudWatch alarms monitor website health.

## Deployment

```bash
cdk synth
cdk deploy