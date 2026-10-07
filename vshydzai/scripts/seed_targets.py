import argparse
import json
from pathlib import Path

import requests
from environment import load_environment

parser = argparse.ArgumentParser()
parser.add_argument("--stack", default="WebHealth-beta")
args = parser.parse_args()
config = load_environment(args.stack)
url = config["API_URL"].rstrip("/") + "/targets"
existing, cursor = set(), None
for _ in range(100):
    reply = requests.get(url, params={"cursor": cursor} if cursor else {}, timeout=20)
    reply.raise_for_status()
    page = reply.json()
    existing.update(item["url"] for item in page["items"])
    cursor = page["next_cursor"]
    if not cursor:
        break
else:
    raise RuntimeError("Target list pagination exceeds seed limit")
sites = json.loads((Path(__file__).resolve().parents[1] / "lambda_src/sites.json").read_text())
for site in sites:
    if site["url"] not in existing:
        reply = requests.post(url, json={**site, "enabled": True}, timeout=20)
        reply.raise_for_status()
        print(json.dumps(reply.json()))
