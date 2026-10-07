"""Bounded website health checks against the enabled DynamoDB targets."""

import http.client
import ipaddress
import logging
import os
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlsplit

from target_repository import repository
from telemetry import emit, memory_snapshot
from validation import validate_url

LOGGER = logging.getLogger(__name__)


def resolve_public(host, port):
    addresses = list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(
        host, port, type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("Target resolves to a private/internal address")
    return addresses[0]


class PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port, address, timeout):
        super().__init__(host, port=port, timeout=timeout)
        self.address = address

    def connect(self):
        self.sock = socket.create_connection((self.address, self.port), self.timeout)


class PinnedHTTPSConnection(PinnedHTTPConnection):
    def connect(self):
        super().connect()
        self.sock = ssl.create_default_context().wrap_socket(self.sock, server_hostname=self.host)


def fetch_status(url, timeout):
    """Pin the validated IP while preserving TLS verification and the HTTP Host header."""
    for _ in range(4):
        url = validate_url(url)
        parts = urlsplit(url)
        port = parts.port or (443 if parts.scheme == "https" else 80)
        address = resolve_public(parts.hostname, port)
        cls = PinnedHTTPSConnection if parts.scheme == "https" else PinnedHTTPConnection
        connection = cls(parts.hostname, port, address, timeout)
        try:
            path = parts.path or "/"
            if parts.query:
                path += "?" + parts.query
            connection.request("GET", path, headers={"User-Agent": "WebHealth-CourseProject/1.0"})
            reply = connection.getresponse()
            status, location = reply.status, reply.getheader("Location")
            reply.close()
        finally:
            connection.close()
        if status in {301, 302, 303, 307, 308} and location:
            url = urljoin(url, location)
        else:
            return status
    raise ValueError("Too many redirects")


def check_website(url):
    start = time.perf_counter()
    try:
        status = fetch_status(url, float(os.environ.get("HTTP_TIMEOUT_SECONDS", "3")))
        result = {"availability": int(200 <= status < 400), "http_status": status}
    except Exception as exc:
        result = {"availability": 0, "http_status": 0, "error": type(exc).__name__}
    result["latency_ms"] = round((time.perf_counter() - start) * 1000, 3)
    return result


def load_sites():
    return repository("crawler").enabled_targets(int(os.environ.get("MAX_TARGETS", "25")))


def lambda_handler(event, context):
    start = time.perf_counter()
    try:
        sites = load_sites()
        if event.get("healthcheck") is True:
            memory_snapshot("crawler")
            return {"ok": True, "component": "crawler", "target_count": len(sites)}
        # Beta-only deliberate fault injection is configured through CDK context.
        if os.environ.get("FAULT_INJECTION", "false") == "true":
            raise RuntimeError("Deliberate beta rollback exercise")

        if event.get("healthcheck") == "canary":
            memory_snapshot("crawler")
            return {"ok": True, "component": "crawler"}

        def check(site):
            return {"id": site["id"], "name": site["name"], **check_website(site["url"])}

        with ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(check, sites))
        for result in results:
            emit("crawler", {"Availability": result["availability"], "Latency": result["latency_ms"],
                             "StatusCode": result["http_status"]}, dimensions={"TargetId": result["id"]},
                 units={"Latency": "Milliseconds", "StatusCode": "None"})
        emit("crawler", {"TargetsChecked": len(results),
                         "TargetsUnavailable": sum(not item["availability"] for item in results),
                         "MaxTargetLatencyMs": max((item["latency_ms"] for item in results), default=0),
                         "RunDurationMs": (time.perf_counter() - start) * 1000},
             units={"RunDurationMs": "Milliseconds", "MaxTargetLatencyMs": "Milliseconds"})
        memory_snapshot("crawler")
        return {"checked": len(results), "results": results}
    except Exception:
        LOGGER.exception("Crawler run failed")
        emit("crawler", {"CrawlerFailures": 1})
        raise
