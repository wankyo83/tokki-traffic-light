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
        self.phase = "idle"
        self.current_site = None
        self.completed_sites = 0
        self.started_at = None
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

    def snapshot(self):
        with self.lock:
            return {
                "running": self.running,
                "lastRun": self.last_run,
                "lastError": self.last_error,
                "lastCommit": self.last_commit,
                "phase": self.phase,
                "currentSite": self.current_site,
                "completedSites": self.completed_sites,
                "totalSites": len(SITES),
                "startedAt": self.started_at,
                "domains": copy.deepcopy(self.latest.get("domains", {})),
                "groups": copy.deepcopy(self.latest_status.get("groups", [])),
                "publishedCheckedAt": self.latest_status.get("checkedAt"),
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

    async def _check_site(self, browser, site, current):
        key = site["key"]
        checks = {
            "current": {"state": "skipped", "detail": "no published address"},
            "source": {"state": "skipped", "detail": "current address not checked yet"},
            "numeric": {"state": "skipped", "checked": 0, "detail": "current address not checked yet"},
        }
        if current:
            result, reason = await browser.verify(key, current)
            if result and not automatic_regression(key, current, result):
                checks["current"] = {"state": "healthy", "detail": reason}
                checks["source"] = {"state": "skipped", "detail": "published address verified"}
                checks["numeric"] = {"state": "skipped", "checked": 0, "detail": "published address verified"}
                return result, "healthy", "", reason, checks
            checks["current"] = {"state": "failed", "detail": reason}
        source_urls, source_result = await browser.discover(site)
        source_failures = []
        tried = {current} if current else set()
        for candidate in self._unique(source_urls)[:5]:
            if automatic_regression(key, current, candidate):
                source_failures.append(f"{candidate}: older than the published address")
                continue
            if candidate in tried:
                source_failures.append(f"{candidate}: published address already failed")
                continue
            tried.add(candidate)
            result, reason = await browser.verify(key, candidate)
            if result and not automatic_regression(key, current, result):
                checks["source"] = {"state": "healthy", "detail": f"{candidate}: {reason}"}
                checks["numeric"] = {"state": "skipped", "checked": 0, "detail": "source address verified"}
                return result, "healthy", source_result, reason, checks
            source_failures.append(f"{candidate}: {reason}")
        checks["source"] = {"state": "failed", "detail": "; ".join([source_result] + source_failures)[:400]}
        numbered = numeric_candidates(key, current, count=10, start_offset=1)
        numeric_failures = []
        for candidate in numbered:
            if candidate in tried:
                numeric_failures.append(f"{candidate}: already failed")
                continue
            result, reason = await browser.verify(key, candidate, timeout_ms=15_000)
            if result and result != current and not automatic_regression(key, current, result):
                checks["numeric"] = {"state": "healthy", "checked": numbered.index(candidate) + 1, "detail": f"{candidate}: {reason}"}
                return result, "healthy", source_result, reason, checks
            numeric_failures.append(f"{candidate}: {reason}")
        checks["numeric"] = {
            "state": "failed" if numbered else "unavailable",
            "checked": len(numbered),
            "detail": ("; ".join(numeric_failures)[-400:] if numbered else "no numbered successor for this site"),
        }
        return None, "stale", source_result, checks["current"]["detail"], checks

    async def _run_async(self, domains, old_status):
        start = time.monotonic()
        old_groups = {group["key"]: group for group in old_status["groups"] if "key" in group}
        async with BrowserVerifier() as browser:
            async def check_one(site):
                key = site["key"]
                with self.lock:
                    self.current_site = site["name"]
                prior = domains["domains"].get(key, {})
                current = prior.get("baseUrl")
                try:
                    result, state, source_result, reason, checks = await asyncio.wait_for(
                        self._check_site(browser, site, current), timeout=540)
                except Exception as exc:
                    result, state, source_result, reason = None, "stale", "check failed", f"{type(exc).__name__}: {str(exc)[:160]}"
                    checks = {"current": {"state": "failed", "detail": reason}, "source": {"state": "skipped", "detail": "site check interrupted"}, "numeric": {"state": "skipped", "checked": 0, "detail": "site check interrupted"}}
                checked = now_iso()
                if result:
                    domains["domains"][key] = {**prior, "baseUrl": result, "status": "healthy", "lastConfirmedAt": checked}
                old = old_groups.get(key, {})
                source = site["source"]
                group = {
                    "key": key, "name": site["name"], "category": site["category"],
                    "activeBaseUrl": domains["domains"].get(key, {}).get("baseUrl"),
                    "state": state if result else "stale",
                    "checkedAt": checked,
                    "lastSuccessfulAt": checked if result else old.get("lastSuccessfulAt", prior.get("lastConfirmedAt")),
                    "candidateBaseUrl": None,
                    "candidateConfirmations": 0,
                    "candidateConfirmationsRequired": 1,
                    "sourceName": source["name"], "sourceUrl": source["url"], "sourceType": source["type"],
                    "errorCode": "" if result else "VERIFICATION_FAILED",
                    "reason": (source_result + "; " + reason)[:600],
                    "checks": checks,
                }
                LOG.info("%s: %s %s", key, state, result or current or "none")
                return group
            groups = []
            for site in SITES:
                groups.append(await check_one(site))
                with self.lock:
                    self.completed_sites = len(groups)
        domains["updatedAt"] = now_iso()
        status = {
            "schemaVersion": 3,
            "checkedAt": domains["updatedAt"],
            "durationMs": round((time.monotonic() - start) * 1000),
            "policy": {"intervalMinutes": 60, "preservesLastKnownGood": True, "browser": "Camoufox", "directNasEgress": True, "numericSearchWindow": 10, "numericSearchMaxOffset": 10, "maxConcurrentSites": 1, "candidateTimeoutSeconds": 20},
            "groups": groups,
        }
        return domains, status

    def run_once(self):
        with self.lock:
            self.running = True
            self.last_error = ""
            self.phase = "reading published snapshot"
            self.current_site = None
            self.completed_sites = 0
            self.started_at = now_iso()
        try:
            domains, old_status = self._bootstrap()
            with self.lock:
                self.latest = copy.deepcopy(domains)
                self.latest_status = copy.deepcopy(old_status)
            if os.environ.get("REQUIRE_KR_EGRESS", "true").lower() == "true":
                with self.lock:
                    self.phase = "checking KR egress"
                is_kr, location = check_kr_egress()
                if not is_kr:
                    raise RuntimeError(f"direct NAS exit not verified as KR (loc={location}); publication stopped")
            with self.lock:
                self.phase = "verifying sites"
            domains, status = asyncio.run(self._run_async(domains, old_status))
            # GitHub commit precedes local state update: public snapshot remains the authority.
            with self.lock:
                self.phase = "publishing GitHub snapshot"
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
                self.last_error = f"{self.phase}: {type(exc).__name__}: {str(exc)[:250]}"
        finally:
            with self.lock:
                self.running = False
                self.phase = "idle"
                self.current_site = None
                self.last_run = now_iso()

    def loop(self):
        interval = max(900, int(os.environ.get("CHECK_INTERVAL_SECONDS", "3600")))
        while True:
            started = time.monotonic()
            self.run_once()
            self.wake.wait(max(0, interval - (time.monotonic() - started)))
            self.wake.clear()
