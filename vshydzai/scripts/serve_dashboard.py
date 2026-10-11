"""Serve the browser dashboard on loopback; AWS writes go directly from the browser to the API.

--demo is an explicit in-memory simulator. It makes no AWS calls and creates no AWS evidence.
"""

import argparse
import base64
import importlib.util
import json
import mimetypes
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
ASSETS = {"/": "index.html", "/index.html": "index.html", "/styles.css": "styles.css",
          "/app.mjs": "app.mjs", "/api-client.mjs": "api-client.mjs", "/view-model.mjs": "view-model.mjs"}
# Load the deployed validator by its trusted repository path, even when run as a script.
_spec = importlib.util.spec_from_file_location("dashboard_validation", ROOT / "vshydzai/lambda_src/validation.py")
_validation = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_validation)


class MissingTarget(Exception):
    pass


class DemoStore:
    """Thread-safe simulator with the same CRUD shapes and input rules as the public API."""

    def __init__(self, seed=True):
        self.items = {}
        self.lock = threading.RLock()
        if seed:
            self.create({"name": "Example website", "url": "https://example.com", "enabled": True})
            self.create({"name": "Western Sydney University", "url": "https://www.westernsydney.edu.au",
                         "enabled": False})

    def create(self, payload):
        values = _validation.validate_target(payload)
        stamp = datetime.now(UTC).isoformat()
        item = {**values, "id": str(uuid4()), "created_at": stamp, "updated_at": stamp}
        with self.lock:
            self.items[item["id"]] = item
        return dict(item)

    def get(self, target_id):
        _validation.validate_id(target_id)
        with self.lock:
            if target_id not in self.items:
                raise MissingTarget("Target not found")
            return dict(self.items[target_id])

    def update(self, target_id, payload):
        values = _validation.validate_target(payload)
        with self.lock:
            item = self.get(target_id)
            item.update(values, updated_at=datetime.now(UTC).isoformat())
            self.items[target_id] = item
            return dict(item)

    def delete(self, target_id):
        with self.lock:
            self.get(target_id)
            del self.items[target_id]

    def list(self, query):
        if set(query) - {"limit", "cursor"} or any(len(values) != 1 for values in query.values()):
            raise ValueError("Unsupported or repeated query parameters")
        limit = int(query.get("limit", ["25"])[0])
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        after = ""
        if "cursor" in query:
            try:
                raw = query["cursor"][0]
                if len(raw) > 1024:
                    raise ValueError("Cursor too long")
                after = base64.b64decode(raw, altchars=b"-_", validate=True).decode("utf-8")
                _validation.validate_id(after)
            except (ValueError, UnicodeError) as exc:
                raise ValueError("Invalid pagination cursor") from exc
        with self.lock:
            keys = sorted(key for key in self.items if key > after)
            selected = keys[:limit]
            cursor = base64.urlsafe_b64encode(selected[-1].encode()).decode() if len(keys) > limit else None
            return {"items": [dict(self.items[key]) for key in selected], "next_cursor": cursor}


def dashboard_server(port=8787, *, demo=False, api_url="", environment=""):
    store = DemoStore() if demo else None

    class Handler(BaseHTTPRequestHandler):
        def send(self, status, body=b"", content_type="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; "
                             "connect-src 'self' https: http://127.0.0.1:* http://localhost:* http://[::1]:*; "
                             "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def json_response(self, status, payload=None):
            self.send(status, b"" if payload is None else json.dumps(payload).encode())

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/config.json":
                self.json_response(200, {"demo": demo, "api_url": "/api" if demo else api_url,
                                         "environment": environment})
            elif path in ASSETS:
                asset = ROOT / "web" / ASSETS[path]
                content_type = "text/javascript" if asset.suffix == ".mjs" else mimetypes.guess_type(asset)[0]
                self.send(200, asset.read_bytes(), content_type or "application/octet-stream")
            elif path.startswith("/api/") and store is not None:
                self.handle_api()
            else:
                self.json_response(404, {"error": "Not found"})

        def handle_api(self):
            parsed = urlsplit(self.path)
            parts = parsed.path.split("/")
            collection = parts == ["", "api", "targets"]
            target_id = parts[3] if len(parts) == 4 and parts[:3] == ["", "api", "targets"] else None
            try:
                if self.command == "GET" and collection:
                    self.json_response(200, store.list(parse_qs(parsed.query, keep_blank_values=True)))
                elif self.command == "GET" and target_id:
                    self.json_response(200, store.get(target_id))
                elif self.command in {"POST", "PUT"} and (collection or target_id):
                    if (self.command == "POST") != collection:
                        self.json_response(405, {"error": "Method not supported"})
                        return
                    size = int(self.headers.get("Content-Length", "0"))
                    if size < 1 or size > 16384:
                        raise ValueError("Request body must contain JSON and be at most 16 KiB")
                    payload = json.loads(self.rfile.read(size), parse_constant=lambda value: (_ for _ in ()).throw(
                        ValueError("Non-finite numbers are not supported")))
                    item = store.create(payload) if collection else store.update(target_id, payload)
                    self.json_response(201 if collection else 200, item)
                elif self.command == "DELETE" and target_id:
                    store.delete(target_id)
                    self.json_response(204)
                else:
                    self.json_response(405, {"error": "Method not supported"})
            except MissingTarget as exc:
                self.json_response(404, {"error": str(exc)})
            except (ValueError, TypeError, UnicodeError) as exc:
                self.json_response(400, {"error": str(exc)})

        def do_POST(self):
            if store is not None and urlsplit(self.path).path.startswith("/api/"):
                self.handle_api()
            else:
                self.json_response(404, {"error": "Not found"})

        do_PUT = do_POST
        do_DELETE = do_POST

        def log_message(self, format, *args):
            # No target URLs, request bodies or AWS credentials in server logs.
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--demo", action="store_true", help="Rehearse with local memory only; no AWS evidence")
    source.add_argument("--stack", choices=["WebHealth-beta", "WebHealth-gamma", "WebHealth-prod"])
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--account", help="Expected AWS account; required for --stack (or DEPLOY_ACCOUNT)")
    parser.add_argument("--region", help="AWS region for --stack")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    api_url = ""
    if args.stack:
        from environment import load_environment
        api_url = load_environment(args.stack, args.region, args.account)["API_URL"]
    with dashboard_server(args.port, demo=args.demo, api_url=api_url, environment=args.stack or "") as server:
        print(f"Dashboard: http://127.0.0.1:{server.server_port}", flush=True)
        print("Local simulator: no AWS calls; data resets on stop." if args.demo else
              "Browser connects directly to the chosen public API; no credentials are sent.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Dashboard stopped.", flush=True)


if __name__ == "__main__":
    main()
