import base64
import json
import os
import urllib.error
import urllib.request
from urllib.parse import quote

from .model import json_bytes


PUBLIC_ROOT = "https://wankyo83.github.io/tokki-traffic-light"


def read_public(filename):
    request = urllib.request.Request(f"{PUBLIC_ROOT}/{filename}?t={os.urandom(4).hex()}", headers={"User-Agent": "tokki-signal-nas/1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def check_kr_egress():
    request = urllib.request.Request("https://www.cloudflare.com/cdn-cgi/trace", headers={"User-Agent": "tokki-signal-nas/1"})
    with urllib.request.urlopen(request, timeout=15) as response:
        trace = response.read(4096).decode("utf-8", "replace")
    values = dict(line.split("=", 1) for line in trace.splitlines() if "=" in line)
    return values.get("loc") == "KR", values.get("loc", "unknown")


class GitHubPublisher:
    def __init__(self):
        self.repo = os.environ["GITHUB_REPOSITORY"]
        self.branch = os.environ.get("GITHUB_BRANCH", "main")
        self.token = os.environ["GITHUB_TOKEN"]
        if not self.token:
            raise ValueError("GITHUB_TOKEN is required")

    def _api(self, method, path, payload=None):
        data = json_bytes(payload) if payload is not None else None
        request = urllib.request.Request(
            f"https://api.github.com/repos/{self.repo}{path}", data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "tokki-signal-nas/1",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            # GitHub often returns 404 for a repository the token cannot access.
            # Include the API operation, never the Authorization header.
            try:
                detail = json.loads(exc.read(2048)).get("message", "")
            except (ValueError, OSError):
                detail = ""
            raise RuntimeError(f"GitHub API {method} {path}: HTTP {exc.code} {detail}".strip()) from None

    def publish(self, domains, status):
        """Commit both public JSON files atomically; never use the stale local checkout."""
        branch = quote(self.branch, safe="")
        # GitHub's read endpoint is singular /ref, but its update endpoint is
        # plural /refs. Reusing the read path for PATCH returns HTTP 404.
        read_ref_path = f"/git/ref/heads/{branch}"
        write_ref_path = f"/git/refs/heads/{branch}"
        ref = self._api("GET", read_ref_path)
        parent_sha = ref["object"]["sha"]
        parent = self._api("GET", f"/git/commits/{parent_sha}")
        tree = self._api("POST", "/git/trees", {
            "base_tree": parent["tree"]["sha"],
            "tree": [
                {"path": "site/domains.json", "mode": "100644", "type": "blob", "content": json_bytes(domains).decode("utf-8")},
                {"path": "site/status.json", "mode": "100644", "type": "blob", "content": json_bytes(status).decode("utf-8")},
            ],
        })
        commit = self._api("POST", "/git/commits", {
            "message": "Update addresses verified by NAS Camoufox",
            "tree": tree["sha"],
            "parents": [parent_sha],
        })
        self._api("PATCH", write_ref_path, {"sha": commit["sha"], "force": False})
        return commit["sha"]
