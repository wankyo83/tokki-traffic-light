import asyncio
import copy
import json
import logging
import os
import threading
import time
from pathlib import Path

from .browser import BrowserVerifier
from .model import BY_KEY, SITES, automatic_regression, json_bytes, now_iso, numeric_candidates, validate_url
from .publish import GitHubPublisher, check_kr_egress, read_public


LOG = logging.getLogger(__name__)


class CheckerService:
    def __init__(self):
        self.data_dir = Path(os.environ.get("DATA_DIR", "/app/data"))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.running = False
        self.last_run = None
        self.last_error = ""
        self.last_commit = None
        self.queue_path = self.data_dir / "manual-candidates.json"
        self.pending = self._read_file(self.queue_path, {})
        self.cursor_path = self.data_dir / "scan-cursors.json"
        self.scan_cursor = self._read_file(self.cursor_path, {})
        self.latest = {}
        self.latest_status = {}

    @staticmethod
    def _read_file(path, fallback):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return fallback

    @staticmethod
    def _write_file(path, value):
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(json_bytes(value))
        temporary.replace(path)

    def submit(self, key, url):
        normalized = validate_url(key, url)
        with self.lock:
            self.pending[key] = {"url": normalized, "submittedAt": now_iso()}
            self._write_file(self.queue_path, self.pending)
            self.wake.set()
        return normalized

    def snapshot(self):
        with self.lock:
            return {
                "running": self.running,
                "lastRun": self.last_run,
                "lastError": self.last_error,
                "lastCommit": self.last_commit,
                "pending": copy.deepcopy(self.pending),
                "domains": copy.deepcopy(self.latest.get("domains", {})),
                "groups": copy.deepcopy(self.latest_status.get("groups", [])),
            }

    def _bootstrap(self):
        # The published Pages snapshot is canonical. Local repo files may be stale.
        domains = read_public("domains.json")
        status = read_public("status.json")
        if domains.get("schemaVersion") != 1 or not isinstance(domains.get("domains"), dict):
            raise ValueError("published domains.json schema invalid")
        if status.get("schemaVersion") != 3 or not isinstance(status.get("groups"), list):
            raise ValueError("published status.json schema invalid")
        for key in BY_KEY:
            value = domains["domains"].get(key, {})
            if value.get("baseUrl"):
                validate_url(key, value["baseUrl"])
        return domains, status

    @staticmethod
    def _unique(urls):
        return list(dict.fromkeys(url for url in urls if url))

    async def _check_site(self, browser, site, current, manual):
        key = site["key"]
        if manual:
            result, reason = await browser.verify(key, manual)
            if result:
                self._reset_cursor(key)
                return result, "manual", "manual candidate", reason, True
        source_urls, source_result = await browser.discover(site)
        candidates = self._unique(source_urls + ([current] if current else []))
        # Search numbered successors only when neither guide nor current address works.
        tried = set()
        failures = []
        for candidate in candidates[:7]:
            if automatic_regression(key, current, candidate):
                failures.append(f"{candidate}: older than the published address")
                continue
            tried.add(candidate)
            result, reason = await browser.verify(key, candidate)
            if result and not automatic_regression(key, current, result):
                if result != current:
                    self._reset_cursor(key)
                    return result, "healthy", source_result, reason, False
                self._reset_cursor(key)
                return result, "healthy", source_result, reason, False
            failures.append(f"{candidate}: {reason}")
        offset = self._cursor_offset(key, current)
        numbered = numeric_candidates(key, current, start_offset=offset)
        for candidate in numbered:
            if candidate in tried:
                continue
            result, reason = await browser.verify(key, candidate, timeout_ms=15_000)
            if result and result != current and not automatic_regression(key, current, result):
                self._reset_cursor(key)
                return result, "healthy", source_result, "numeric candidate verified: " + reason, False
            failures.append(f"{candidate}: {reason}")
        if numbered:
            # Progress across hourly cycles instead of repeatedly checking only +1..+10.
            next_offset = 1 if offset >= 191 else offset + 10
            self.scan_cursor[key] = {"baseUrl": current, "nextOffset": next_offset}
            self._write_file(self.cursor_path, self.scan_cursor)
        return None, "stale", source_result, "; ".join(failures)[:500], False

    def _cursor_offset(self, key, current):
        saved = self.scan_cursor.get(key, {})
        if saved.get("baseUrl") != current:
            return 1
        return max(1, min(191, int(saved.get("nextOffset", 1))))

    def _reset_cursor(self, key):
        if key in self.scan_cursor:
            del self.scan_cursor[key]
            self._write_file(self.cursor_path, self.scan_cursor)

    async def _run_async(self, domains, old_status):
        start = time.monotonic()
        old_groups = {group["key"]: group for group in old_status["groups"] if "key" in group}
        async with BrowserVerifier() as browser:
            async def check_one(site):
                key = site["key"]
                prior = domains["domains"].get(key, {})
                current = prior.get("baseUrl")
                with self.lock:
                    pending = self.pending.get(key, {}).get("url")
                try:
                    result, state, source_result, reason, accepted_manual = await asyncio.wait_for(
                        self._check_site(browser, site, current, pending), timeout=540)
                except Exception as exc:
                    result, state, source_result, reason, accepted_manual = None, "stale", "check failed", f"{type(exc).__name__}: {str(exc)[:160]}", False
                checked = now_iso()
                if result:
                    domains["domains"][key] = {**prior, "baseUrl": result, "status": "healthy", "lastConfirmedAt": checked}
                if accepted_manual:
                    with self.lock:
                        if self.pending.get(key, {}).get("url") == pending:
                            del self.pending[key]
                            self._write_file(self.queue_path, self.pending)
                old = old_groups.get(key, {})
                source = site["source"]
                group = {
                    "key": key, "name": site["name"], "category": site["category"],
                    "activeBaseUrl": domains["domains"].get(key, {}).get("baseUrl"),
                    "state": state if result else "stale",
                    "checkedAt": checked,
                    "lastSuccessfulAt": checked if result else old.get("lastSuccessfulAt", prior.get("lastConfirmedAt")),
                    "candidateBaseUrl": pending if pending and not accepted_manual else None,
                    "candidateConfirmations": 0,
                    "candidateConfirmationsRequired": 1,
                    "sourceName": source["name"], "sourceUrl": source["url"], "sourceType": source["type"],
                    "errorCode": "" if result else "VERIFICATION_FAILED",
                    "reason": (source_result + "; " + reason)[:600],
                }
                LOG.info("%s: %s %s", key, state, result or current or "none")
                return group
            groups = []
            for site in SITES:
                groups.append(await check_one(site))
        domains["updatedAt"] = now_iso()
        status = {
            "schemaVersion": 3,
            "checkedAt": domains["updatedAt"],
            "durationMs": round((time.monotonic() - start) * 1000),
            "policy": {"intervalMinutes": 60, "preservesLastKnownGood": True, "browser": "Camoufox", "directNasEgress": True, "numericSearchWindow": 10, "numericSearchMaxOffset": 200, "maxConcurrentSites": 1, "candidateTimeoutSeconds": 20},
            "groups": groups,
        }
        return domains, status

    def run_once(self):
        with self.lock:
            self.running = True
            self.last_error = ""
        try:
            domains, old_status = self._bootstrap()
            with self.lock:
                self.latest = copy.deepcopy(domains)
                self.latest_status = copy.deepcopy(old_status)
            if os.environ.get("REQUIRE_KR_EGRESS", "true").lower() == "true":
                is_kr, location = check_kr_egress()
                if not is_kr:
                    raise RuntimeError(f"direct NAS exit not verified as KR (loc={location}); publication stopped")
            domains, status = asyncio.run(self._run_async(domains, old_status))
            # GitHub commit precedes local state update: public snapshot remains the authority.
            sha = GitHubPublisher().publish(domains, status)
            self._write_file(self.data_dir / "last-domains.json", domains)
            self._write_file(self.data_dir / "last-status.json", status)
            with self.lock:
                self.latest = domains
                self.latest_status = status
                self.last_commit = sha
            LOG.info("Published verified snapshot %s", sha)
        except Exception as exc:
            LOG.exception("Cycle failed; published addresses were not changed")
            with self.lock:
                self.last_error = f"{type(exc).__name__}: {str(exc)[:250]}"
        finally:
            with self.lock:
                self.running = False
                self.last_run = now_iso()

    def loop(self):
        interval = max(900, int(os.environ.get("CHECK_INTERVAL_SECONDS", "3600")))
        while True:
            started = time.monotonic()
            self.run_once()
            self.wake.wait(max(0, interval - (time.monotonic() - started)))
            self.wake.clear()
