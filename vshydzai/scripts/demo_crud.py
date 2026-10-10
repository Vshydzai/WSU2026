"""Run a visible CRUD demonstration and remove only the created target."""

import argparse
import json

import requests
from environment import load_environment


def call(method, url, payload=None, expected=200):
    reply = requests.request(method, url, json=payload, timeout=20)
    print(f"{method} {url} -> {reply.status_code}")
    if reply.content:
        print(json.dumps(reply.json(), indent=2))
    reply.raise_for_status()
    if reply.status_code != expected:
        raise RuntimeError(f"Expected {expected}, received {reply.status_code}")
    return reply


def demonstrate(base):
    item = call("POST", base, {"name": "Presentation demo", "url": "https://example.com/", "enabled": False}, 201).json()
    path = base + "/" + item["id"]
    try:
        call("GET", base)
        call("GET", path)
        call("PUT", path, {"name": "Updated demo", "url": "https://example.com/", "enabled": True})
    except Exception as primary:
        try:
            call("DELETE", path, expected=204)
        except Exception as removal:
            raise ExceptionGroup("Demonstration failed and its record could not be removed", [primary, removal]) from None
        raise
    else:
        call("DELETE", path, expected=204)
    reply = requests.get(path, timeout=20)
    if reply.status_code != 404:
        raise RuntimeError("Deleted target did not return 404")
    print("Deleted target correctly returns 404.")
    return item["id"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", default="WebHealth-beta")
    args = parser.parse_args(argv)
    demonstrate(load_environment(args.stack)["API_URL"].rstrip("/") + "/targets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
