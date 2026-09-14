# WebHealth Application

## Project Overview

WebHealth is an AWS-based web monitoring application developed for the COMP2029 DevOps course project.

The application uses AWS serverless services to monitor a custom list of websites and measure:

- Website availability
- Website latency
- HTTP response status codes

The collected metrics are published to Amazon CloudWatch for monitoring, visualisation, and alarm management.

When monitoring thresholds are breached, CloudWatch alarms send notifications through Amazon SNS. Alarm events are also logged into Amazon DynamoDB using a dedicated Alarm Logger Lambda function for historical tracking.

---

## AWS Services

The application uses the following AWS services:

- AWS Lambda
- Amazon EventBridge
- Amazon CloudWatch
- Amazon SNS
- Amazon DynamoDB
- AWS IAM
- AWS CDK

---

## Monitored Websites

The monitored websites are stored in:


lambda_src/sites.json


Current websites:

- Western Sydney University
- Example.com

The website list can be updated by modifying the JSON configuration file without changing the Lambda source code.

---

## How It Works

1. Amazon EventBridge triggers the WebHealth Lambda every 30 minutes.

2. The Lambda function reads website information from `sites.json`.

3. Lambda sends HTTP requests to each monitored website.

4. The application calculates:
   - Website availability
   - Website latency
   - HTTP status code

5. Boto3 publishes the collected metrics to Amazon CloudWatch.

6. CloudWatch Dashboard displays website monitoring metrics.

7. CloudWatch alarms monitor metric thresholds.

8. When an alarm threshold is breached, CloudWatch sends an event to Amazon SNS.

9. SNS sends notifications to subscribers and triggers the Alarm Logger Lambda.

10. The Alarm Logger Lambda stores alarm information in the DynamoDB `AlarmLogs` table.

---

## Monitoring Metrics

The application publishes custom CloudWatch metrics under the namespace:


WebHealth


Metrics collected:

| Metric | Description |
|---|---|
| Availability | Shows whether the website is reachable (1 = available, 0 = unavailable) |
| Latency | Measures website response time in milliseconds |
| StatusCode | Records HTTP response status codes |

---

## CloudWatch Dashboard

The application includes a CloudWatch Dashboard to visualise:

- Website availability
- Website latency
- Website status codes

The dashboard allows users to monitor website health trends over time.

---

## CloudWatch Alarms

CloudWatch alarms are configured to detect abnormal website conditions.

Examples:

### Availability Alarm

Triggers when:


Availability < 1


Meaning:

The website is unavailable.

### Latency Alarm

Triggers when:


Latency > 3000 milliseconds


Meaning:

The website response time is higher than the defined threshold.

---

## SNS Notification System

Amazon SNS is used to distribute CloudWatch alarm notifications.

The notification flow is:


CloudWatch Alarm
|
↓
SNS Topic
|
├── Email Notification
|
└── Alarm Logger Lambda


SNS allows multiple subscribers to receive alarm notifications.

---

## DynamoDB Alarm Logging

Alarm notifications are stored in Amazon DynamoDB.

Table name:


AlarmLogs


Primary key:


id


Stored information includes:

- Alarm name
- Alarm state
- Alarm reason
- Timestamp

The Alarm Logger Lambda receives SNS messages and writes alarm records into DynamoDB.

---

## Repository Structure


WebHealth
│
├── app.py
├── vshydzai_stack.py
├── cdk.json
├── requirements.txt
│
└── lambda_src
├── webhealth.py
├── alarm_logger.py
└── sites.json


---

## Deployment

Install dependencies:

```bash
pip install -r requirements.txt

Generate CloudFormation template:

cdk synth

Deploy AWS resources:

cdk deploy
Cleanup

Remove deployed AWS resources:

cdk destroy
References

AWS CDK Python API Reference:

https://docs.aws.amazon.com/cdk/api/v2/python/

AWS Lambda Documentation:

https://docs.aws.amazon.com/lambda/

Amazon CloudWatch Documentation:

https://docs.aws.amazon.com/cloudwatch/

Amazon SNS Documentation:

https://docs.aws.amazon.com/sns/

Amazon DynamoDB Documentation:

https://docs.aws.amazon.com/dynamodb/