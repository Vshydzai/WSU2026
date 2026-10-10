import argparse
import json
from pathlib import Path

import requests
from environment import load_environment


def seed(url, sites):
    existing, cursor, created = set(), None, []
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
    for site in sites:
        if site["url"] not in existing:
            reply = requests.post(url, json={**site, "enabled": True}, timeout=20)
            reply.raise_for_status()
            if reply.status_code != 201:
                raise RuntimeError("Seed create did not return 201")
            created.append(reply.json())
            existing.add(site["url"])
    return created


def main(argv=None):
    parser = argparse.ArgumentParser(description="Seed missing URLs without replacing the existing target list")
    parser.add_argument("--stack", default="WebHealth-beta")
    args = parser.parse_args(argv)
    url = load_environment(args.stack)["API_URL"].rstrip("/") + "/targets"
    sites = json.loads((Path(__file__).resolve().parents[1] / "lambda_src/sites.json").read_text(encoding="utf-8"))
    for item in seed(url, sites):
        print(json.dumps(item))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
