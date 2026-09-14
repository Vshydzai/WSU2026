# WebHealth Application

## Project Overview

WebHealth is a serverless AWS monitoring application developed for COMP2029 DevOps. The purpose of this project is to automatically monitor the health of configured web resources by measuring website availability, response latency, and HTTP status codes.

The application uses AWS Lambda to perform website health checks, Amazon EventBridge to schedule automated executions, and Amazon CloudWatch to collect, visualise, and monitor custom metrics. CloudWatch alarms are configured to detect abnormal website conditions. When an alarm threshold is breached, Amazon SNS is used to notify subscribers and trigger an Alarm Logger Lambda function, which stores alarm information in Amazon DynamoDB for historical tracking.

The overall monitoring workflow is:


Website Resources
|
↓
WebHealth Lambda
|
↓
CloudWatch Metrics
|
↓
CloudWatch Dashboard
|
↓
CloudWatch Alarms
|
↓
SNS Notification Service
|
↓
Alarm Logger Lambda
|
↓
DynamoDB AlarmLogs Table


---

# System Architecture

The application contains two main workflows.

## Website Monitoring Workflow

Amazon EventBridge triggers the WebHealth Lambda function every 30 minutes. The Lambda function reads the configured websites from a JSON file, sends HTTP requests to each website, calculates availability and latency metrics, and publishes the results to Amazon CloudWatch.


EventBridge
|
↓
WebHealth Lambda
|
↓
Website Health Check
|
↓
CloudWatch Metrics


## Alarm Notification and Logging Workflow

CloudWatch alarms monitor the published metrics. When a threshold is breached, CloudWatch sends an alarm notification to Amazon SNS. SNS distributes the notification to email subscribers and invokes the Alarm Logger Lambda function. The Alarm Logger Lambda stores the alarm event in DynamoDB.


CloudWatch Alarm
|
↓
SNS Topic
/
/
Email Alarm Logger Lambda
|
↓
DynamoDB


---

# AWS Services Used

## AWS Lambda

Two Lambda functions are used in this project.

### WebHealthFunction

The WebHealthFunction is responsible for monitoring website health.

Responsibilities:

- Read monitored websites from `sites.json`
- Send HTTP requests to websites
- Calculate website availability
- Measure response latency
- Publish custom metrics to CloudWatch

### AlarmLoggerFunction

The AlarmLoggerFunction stores alarm events.

Responsibilities:

- Receive alarm notifications from SNS
- Extract alarm information
- Store alarm records in DynamoDB using the PutItem operation

---

## Amazon EventBridge

Amazon EventBridge is used to schedule the WebHealth Lambda execution.

The application uses a rate-based schedule:


rate(30 minutes)


This allows automated website monitoring without requiring a continuously running server.

---

## Amazon CloudWatch

Amazon CloudWatch is used for metric collection, dashboard visualisation, and alarm monitoring.

The application publishes custom metrics under the namespace:


WebHealth


The monitored metrics are:

| Metric | Description |
|---|---|
| Availability | Indicates whether the website responded successfully |
| Latency | Measures website response time in milliseconds |
| StatusCode | Records HTTP response status codes |

### Availability Metric

Values:

| Value | Meaning |
|---|---|
| 1 | Website available |
| 0 | Website unavailable |

### Latency Metric

Latency measures the response time required for the website to respond.

The metric uses milliseconds as the measurement unit.

### StatusCode Metric

The HTTP response status code is recorded to identify website response conditions.

Examples:

- 200: Successful response
- 404: Resource not found
- 500: Server error

---

# CloudWatch Dashboard

A CloudWatch Dashboard is created to provide visual monitoring of website health.

Dashboard:


WebHealth-Dashboard


The dashboard displays:

- Website availability
- Website latency
- Website HTTP status codes

This allows users to observe website performance trends over time.

---

# CloudWatch Alarms

CloudWatch alarms are configured to monitor website conditions.

## Availability Alarm

Condition:


Availability < 1


This indicates that a monitored website is unavailable.

## Latency Alarm

Condition:


Latency > 3000 milliseconds


This indicates that the website response time exceeds the acceptable threshold.

When an alarm enters the ALARM state, CloudWatch sends an event to SNS.

---

# Amazon SNS Notification Service

Amazon SNS is used as the notification layer between CloudWatch alarms and subscribers.

SNS Topic:


WebHealthAlarmTopic


Subscribers:

- Email notification
- Alarm Logger Lambda

The notification workflow:


CloudWatch Alarm
|
↓
SNS Topic
|
├── Email Notification
|
└── Alarm Logger Lambda


SNS allows the system to support multiple notification destinations without changing the CloudWatch alarm configuration.

---

# Amazon DynamoDB Alarm Logging

Amazon DynamoDB is used to store historical alarm notifications.

Table:


AlarmLogs


Primary Key:


id


Stored information includes:

- Alarm ID
- Alarm name
- Alarm state
- Alarm reason
- Timestamp

The Alarm Logger Lambda receives SNS messages and writes alarm records into DynamoDB.

---

# Monitored Websites

The monitored website list is stored in:


lambda_src/sites.json


Current monitored resources:

- Western Sydney University
- Example.com

The JSON file allows additional websites to be added without modifying the Lambda function code.

Example:

```json
[
    {
        "name": "WSU",
        "url": "https://www.westernsydney.edu.au"
    }
]
Repository Structure
WebHealth
│
├── app.py
├── vshydzai_stack.py
├── cdk.json
├── requirements.txt
│
└── lambda_src
    │
    ├── webhealth.py
    ├── alarm_logger.py
    └── sites.json

File descriptions:

File	Purpose
app.py	CDK application entry point
vshydzai_stack.py	Defines AWS infrastructure resources
webhealth.py	Website monitoring Lambda function
alarm_logger.py	Alarm notification logging Lambda function
sites.json	Stores monitored website information
Deployment Instructions

Install required dependencies:

pip install -r requirements.txt

Configure AWS credentials:

aws configure

Generate the CloudFormation template:

cdk synth

Deploy the AWS infrastructure:

cdk deploy
Testing and Verification

The application can be verified through the following steps:

Infrastructure Validation

Run:

cdk synth

This confirms that the CDK application can successfully generate the required AWS CloudFormation resources.

AWS Resource Verification

Confirm that the following resources exist:

WebHealth Lambda
AlarmLogger Lambda
EventBridge schedule
CloudWatch Dashboard
CloudWatch Alarms
SNS Topic
DynamoDB AlarmLogs table
Alarm Logging Test

A test SNS event can be sent to the Alarm Logger Lambda.

Expected result:

A new record should appear in the DynamoDB AlarmLogs table.

Cleanup

To remove all AWS resources created by this project:

cdk destroy
References and Documentation

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
