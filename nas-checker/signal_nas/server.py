import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .model import json_bytes


ADMIN_HTML = Path(__file__).with_name("admin.html").read_text(encoding="utf-8")


def public_overview(state):
    """Only publish read-only metadata already visible in the public signal."""
    fields = ("key", "name", "category", "activeBaseUrl", "state", "sourceName", "sourceUrl", "reason", "checkedAt")
    return {
        "running": state["running"],
        "phase": state.get("phase", "idle"),
        "currentSite": state.get("currentSite"),
        "completedSites": state.get("completedSites", 0),
        "totalSites": state.get("totalSites", 0),
        "startedAt": state.get("startedAt"),
        "lastRun": state.get("lastRun"),
        "lastCommit": state.get("lastCommit"),
        "hasError": bool(state.get("lastError")),
        "publishedCheckedAt": state.get("publishedCheckedAt"),
        "groups": [{key: group.get(key) for key in fields} for group in state.get("groups", [])],
    }


def make_handler(service):
    secret = os.environ.get("ADMIN_TOKEN", "")
    origin = os.environ.get("ADMIN_ALLOWED_ORIGIN", "https://wankyo83.github.io")
    if len(secret) < 24:
        raise ValueError("ADMIN_TOKEN must contain at least 24 characters")

    class Handler(BaseHTTPRequestHandler):
        def _cors(self):
            if self.headers.get("Origin") == origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Vary", "Origin")

        def _send(self, status, data, content_type="application/json; charset=utf-8"):
            payload = json_bytes(data) if not isinstance(data, bytes) else data
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self._cors()
            self.end_headers()
            self.wfile.write(payload)

        def _authorized(self):
            header = self.headers.get("Authorization", "")
            return hmac.compare_digest(header, "Bearer " + secret)

        def do_OPTIONS(self):
            if self.path.startswith("/api/") and self.headers.get("Origin") == origin:
                self.send_response(204)
                self._cors()
                self.end_headers()
            else:
                self._send(403, {"error": "origin not allowed"})

        def do_GET(self):
            if self.path == "/health":
                state = service.snapshot()
                self._send(200, {
                    "ok": True,
                    "running": state["running"],
                    "phase": state.get("phase", "idle"),
                    "currentSite": state.get("currentSite"),
                    "completedSites": state.get("completedSites", 0),
                    "totalSites": state.get("totalSites", 0),
                    "startedAt": state.get("startedAt"),
                    "lastRun": state.get("lastRun"),
                    "lastCommit": state.get("lastCommit"),
                    "hasError": bool(state.get("lastError")),
                })
                return
            if self.path == "/api/overview":
                self._send(200, public_overview(service.snapshot()))
                return
            if self.path == "/":
                from .model import SITES
                html = ADMIN_HTML.replace("%KEYS%", json.dumps([[s["key"], s["name"]] for s in SITES], ensure_ascii=False))
                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
                return
            if not self._authorized():
                self._send(401, {"error": "관리 토큰이 필요합니다."})
                return
            if self.path == "/api/state":
                self._send(200, service.snapshot())
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._authorized():
                self._send(401, {"error": "관리 토큰이 필요합니다."})
                return
            if self.path not in ("/api/manual-candidate", "/api/run"):
                self._send(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 2048 or length < 0:
                    raise ValueError("request too large")
                value = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/run":
                    service.wake.set()
                    self._send(202, {"queued": True})
                else:
                    url = service.submit(value.get("key"), value.get("url"))
                    self._send(202, {"queued": True, "url": url})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._send(400, {"error": str(exc)[:200]})

        def log_message(self, format_string, *args):
            # Do not log bearer token or user-submitted values.
            return

    return Handler


def serve(service):
    port = int(os.environ.get("PORT", "8792"))
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(service))
    server.serve_forever()
