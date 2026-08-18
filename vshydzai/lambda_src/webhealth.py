import time
from urllib import request


def lambda_handler(event, context):
    url = "https://www.westernsydney.edu.au/"

    start_time = time.time()

    try:
        response = request.urlopen(url, timeout=10)

        latency = round((time.time() - start_time) * 1000, 2)

        return {
            "statusCode": 200,
            "website": url,
            "availability": 1,
            "latency_ms": latency,
            "http_status": response.status
        }

    except Exception as error:
        latency = round((time.time() - start_time) * 1000, 2)

        return {
            "statusCode": 500,
            "website": url,
            "availability": 0,
            "latency_ms": latency,
            "error": str(error)
        }