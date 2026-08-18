# WebHealth Application

## Project Overview

WebHealth is an AWS monitoring application developed for COMP2029 DevOps.

The application:
- Uses AWS Lambda to monitor websites
- Reads websites from a custom JSON list
- Measures website availability and latency
- Runs every 30 minutes using EventBridge
- Publishes metrics to Amazon CloudWatch using Boto3
- Uses a CloudWatch Dashboard and alarms for monitoring

## Monitored Websites

The website list is stored in:

`lambda_src/sites.json`

Current websites:
- Western Sydney University
- Example.com

## AWS Services Used

- AWS Lambda
- Amazon EventBridge
- Amazon CloudWatch
- AWS IAM
- AWS CDK

## Cleanup

After completing project work for the day, destroy the infrastructure:

```bash
cdk destroy