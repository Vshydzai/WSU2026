"""Run a visible CRUD demonstration and remove only the created target."""

import argparse
import json

import requests
from environment import load_environment

parser = argparse.ArgumentParser()
parser.add_argument("--stack", default="WebHealth-beta")
args = parser.parse_args()
base = load_environment(args.stack)["API_URL"].rstrip("/") + "/targets"


def call(method, url, payload=None):
    reply = requests.request(method, url, json=payload, timeout=20)
    print(f"{method} {url} -> {reply.status_code}")
    if reply.content:
        print(json.dumps(reply.json(), indent=2))
    reply.raise_for_status()
    return reply


item = call("POST", base, {"name": "Presentation demo", "url": "https://example.com/", "enabled": False}).json()
path = base + "/" + item["id"]
try:
    call("GET", base)
    call("GET", path)
    call("PUT", path, {"name": "Updated demo", "url": "https://example.com/", "enabled": True})
finally:
    call("DELETE", path)
reply = requests.get(path, timeout=20)
assert reply.status_code == 404, reply.text
print("Deleted target correctly returns 404.")
