import json
import boto3
import time
from pathlib import Path
from urllib import request


def load_sites():
    file_path = Path(__file__).with_name("sites.json")

    with open(file_path, "r") as file:
        return json.load(file)


def check_website(url):
    start_time = time.time()

    try:
        response = request.urlopen(url, timeout=10)

        latency = round(
            (time.time() - start_time) * 1000,
            2
        )

        return {
            "availability": 1,
            "latency_ms": latency,
            "http_status": response.status
        }

    except Exception as error:
        latency = round(
            (time.time() - start_time) * 1000,
            2
        )

        return {
            "availability": 0,
            "latency_ms": latency,
            "error": str(error)
        }


def lambda_handler(event, context):

    sites = load_sites()

    cloudwatch = boto3.client("cloudwatch")

    results = []

    for site in sites:

        result = check_website(site["url"])

        cloudwatch.put_metric_data(
            Namespace="WebHealth",
            MetricData=[
                {
                    "MetricName": "Availability",
                    "Dimensions": [
                        {
                            "Name": "Website",
                            "Value": site["name"]
                        }
                    ],
                    "Value": result["availability"]
                },
                {
                    "MetricName": "Latency",
                    "Dimensions": [
                        {
                            "Name": "Website",
                            "Value": site["name"]
                        }
                    ],
                    "Value": result["latency_ms"],
                    "Unit": "Milliseconds"
                }
            ]
        )

        results.append({
            "name": site["name"],
            "url": site["url"],
            **result
        })

    return {
        "checked": len(results),
        "results": results
    }