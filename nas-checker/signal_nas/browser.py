import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager, suppress
from urllib.parse import urlsplit

from .model import (
    CHALLENGE_MARKERS, RULES, candidate_url_allowed, host_candidates,
    validate_page, validate_url,
)


CHALLENGE_DOM_MARKERS = (
    "challenges.cloudflare.com",
    "/cdn-cgi/challenge-platform/",
    "cf-chl-widget",
    "cf-turnstile",
)

LOG = logging.getLogger(__name__)


def transient_navigation_error(exc):
    # DNS failures, invalid URLs, HTTP errors and failed content validation
    # must not be promoted to healthy or waste time in network recovery.
    return isinstance(exc, (TimeoutError, asyncio.TimeoutError)) or any(
        marker in str(exc).upper() for marker in (
            "NS_ERROR_NET_RESET", "ERR_CONNECTION_RESET", "NS_ERROR_NET_TIMEOUT",
            "ERR_TIMED_OUT", "PAGE.GOTO: TIMEOUT",
        )
    )


class CloudflareProtectedError(RuntimeError):
    """A confirmed Cloudflare screen stayed active after the solve window."""


def _seconds(name, default):
    try:
        return max(1.0, float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return float(default)


def challenge_signals(status, title, html, frame_urls=()):
    """Return (challenge, widget_ready) without relying on one CF DOM shape."""
    sample = f"{title} {html[:120_000]}".lower()
    frame_sample = " ".join(frame_urls).lower()
    challenge = status == 403 or any(marker in sample for marker in CHALLENGE_MARKERS)
    widget_ready = any(marker in sample or marker in frame_sample for marker in CHALLENGE_DOM_MARKERS)
    return challenge or widget_ready, widget_ready


def telegram_candidates(site, messages):
    """Telegram's DOM is oldest-first; use the newest matching address post."""
    source = site["source"]
    preferred = source.get("preferredLabel", "")
    for message in reversed(messages):
        if preferred:
            position = message.lower().find(preferred.lower())
            if position < 0:
                continue
            candidates = host_candidates(site["key"], message[position + len(preferred):position + len(preferred) + 240])
            if candidates:
                return candidates[:1]
            continue
        candidates = host_candidates(site["key"], message)
        if candidates:
            return candidates[:1]
    return []


class BrowserVerifier:
    def __init__(self):
        self._manager = None
        self.browser = None
        self.context = None
        self.guide_cache = {}

    async def __aenter__(self):
        from camoufox import AsyncCamoufox
        from playwright_captcha.utils.camoufox_add_init_script.add_init_script import get_addon_path

        self._manager = AsyncCamoufox(
            headless=True, humanize=True, geoip=False, locale="ko-KR",
            main_world_eval=True, addons=[get_addon_path()],
            i_know_what_im_doing=True, config={"forceScopeAccess": True},
            disable_coop=True,
        )
        self.browser = await self._manager.__aenter__()
        # Reuse one sequential context for the complete cycle so a Cloudflare
        # clearance cookie survives home/category/source probes. Individual
        # pages are still closed after every probe to keep memory bounded.
        self.context = await self.browser.new_context()
        return self

    async def __aexit__(self, kind, value, traceback):
        if self.context is not None:
            with suppress(Exception):
                await self.context.close()
            self.context = None
        if self._manager is not None:
            with suppress(Exception):
                await self._manager.__aexit__(kind, value, traceback)
            self._manager = None
        self.browser = None

    async def _inspect(self, page, status=0):
        try:
            title = await page.title()
        except Exception:
            title = ""
        try:
            html = await page.content()
        except Exception:
            html = ""
        try:
            frame_urls = [frame.url for frame in page.frames if frame.url]
        except Exception:
            frame_urls = []
        challenge, widget_ready = challenge_signals(status, title, html, frame_urls)
        sample = f"{title} {html[:120_000]}".lower()
        frame_sample = " ".join(frame_urls).lower()
        confirmed_challenge = widget_ready or any(
            marker in sample for marker in CHALLENGE_MARKERS + CHALLENGE_DOM_MARKERS
        ) or any(marker in frame_sample for marker in CHALLENGE_DOM_MARKERS)
        try:
            body_attached = await page.locator("body").count() > 0
            link_count = await page.locator("a[href]").count()
        except Exception:
            body_attached, link_count = False, 0
        return {
            "challenge": challenge,
            "confirmedChallenge": confirmed_challenge,
            "widgetReady": widget_ready,
            "bodyAttached": body_attached,
            "linkCount": link_count,
            "title": title,
            "html": html,
        }

    async def _wait_for_initial_state(self, page, status, source_type, timeout_seconds):
        deadline = time.monotonic() + timeout_seconds
        last = None
        while time.monotonic() < deadline:
            last = await self._inspect(page, status)
            if last["challenge"] or last["widgetReady"]:
                return last
            if source_type == "telegram":
                try:
                    if await page.locator(".tgme_widget_message_text").count():
                        return last
                except Exception:
                    pass
            elif last["bodyAttached"] and last["linkCount"]:
                return last
            await asyncio.sleep(0.5)
        return last or await self._inspect(page, status)

    async def _wait_for_widget(self, page, status, timeout_seconds):
        deadline = time.monotonic() + timeout_seconds
        last = None
        while time.monotonic() < deadline:
            last = await self._inspect(page, status)
            if not last["challenge"] or last["widgetReady"]:
                return last
            await asyncio.sleep(0.5)
        return last or await self._inspect(page, status)

    async def _wait_for_challenge_exit(self, page, timeout_seconds):
        deadline = time.monotonic() + timeout_seconds
        last = None
        while time.monotonic() < deadline:
            last = await self._inspect(page)
            if not last["challenge"] and last["bodyAttached"] and last["linkCount"]:
                return last
            await asyncio.sleep(0.5)
        return last or await self._inspect(page)

    @asynccontextmanager
    async def _solver(self, page, enabled):
        if not enabled:
            yield None
            return
        from playwright_captcha import ClickSolver, FrameworkType

        # Prepare before page.goto(). The solver's shadow-root unlock script
        # must exist when Cloudflare creates its closed widget tree.
        async with ClickSolver(
            framework=FrameworkType.CAMOUFOX,
            page=page,
            max_attempts=8,
            attempt_delay=2,
        ) as solver:
            yield solver

    async def _load(self, page, solver, url, timeout_ms, source_type, protected_current=False):
        deadline = time.monotonic() + timeout_ms / 1000

        def remaining_seconds():
            return max(1.0, deadline - time.monotonic())

        commit_timeout = min(timeout_ms, int(_seconds("NAVIGATION_COMMIT_TIMEOUT_SECONDS", 45) * 1000))
        response = await page.goto(url, wait_until="commit", timeout=commit_timeout)
        status = response.status if response else 0
        detect_seconds = min(_seconds("CF_DETECT_TIMEOUT_SECONDS", 20), remaining_seconds())
        state = await self._wait_for_initial_state(page, status, source_type, detect_seconds)
        solved_challenge = False

        # The existing policy permits only the published host to preserve its
        # address after a confirmed CF response. Keep that proof before a
        # solver timeout can erase it. Plain HTTP 403/reset is NOT sufficient.
        if protected_current and state.get("confirmedChallenge"):
            state = await self._wait_for_challenge_exit(page, min(10, remaining_seconds()))
            if state.get("confirmedChallenge"):
                raise CloudflareProtectedError("confirmed protection on published host; content not verified")

        if solver is not None and state["challenge"]:
            widget_seconds = min(_seconds("CF_WIDGET_TIMEOUT_SECONDS", 30), remaining_seconds())
            state = await self._wait_for_widget(page, status, widget_seconds)
            if state["challenge"]:
                from playwright_captcha import CaptchaType

                solve_seconds = min(_seconds("CF_SOLVE_TIMEOUT_SECONDS", 90), remaining_seconds())
                solve_error = None
                try:
                    await asyncio.wait_for(
                        solver.solve_captcha(
                            captcha_container=page,
                            captcha_type=CaptchaType.CLOUDFLARE_INTERSTITIAL,
                            solve_click_delay=10,
                            wait_checkbox_attempts=20,
                            wait_checkbox_delay=1,
                            checkbox_click_attempts=5,
                        ),
                        timeout=solve_seconds,
                    )
                    solved_challenge = True
                except Exception as exc:
                    # The helper can report a failed heuristic immediately after
                    # a successful click. Keep the page alive and judge the real
                    # DOM transition before treating the probe as failed.
                    solve_error = exc
                exit_seconds = min(_seconds("CF_POST_SOLVE_TIMEOUT_SECONDS", 60), remaining_seconds())
                state = await self._wait_for_challenge_exit(page, exit_seconds)
                if state["challenge"]:
                    detail = f": {type(solve_error).__name__}: {str(solve_error)[:120]}" if solve_error else ""
                    if state.get("confirmedChallenge"):
                        raise CloudflareProtectedError(f"Cloudflare challenge remained after solver{detail}")
                    raise TimeoutError(f"HTTP 403 remained after solver{detail}")
                solved_challenge = True

        try:
            await page.wait_for_function("document.querySelectorAll('a[href]').length > 0", timeout=5_000)
        except Exception:
            pass
        title = await page.title()
        html = (await page.content())[:2_000_000]
        try:
            body = (await page.locator("body").inner_text(timeout=5_000))[:120_000]
        except Exception:
            body = ""
        links = await page.locator("a[href]").evaluate_all(
            "nodes => nodes.slice(0, 1000).map(a => ({href: a.href, text: a.innerText, parent: a.parentElement?.innerText?.slice(0, 500) || ''}))"
        )
        messages = await page.locator(".tgme_widget_message_text").evaluate_all("nodes => nodes.map(n => n.innerText)")
        if solved_challenge and status == 403:
            status = 200
        return {
            "url": page.url, "title": title, "html": html, "body": body,
            "links": links, "messages": messages, "status": status,
        }

    async def _page(self, url, *, solve=True, timeout_ms=210_000, source_type="", protected_current=False):
        if self.context is None:
            raise RuntimeError("BrowserVerifier is not started")
        page = await self.context.new_page()
        try:
            async with self._solver(page, solve) as solver:
                return await self._load(page, solver, url, timeout_ms, source_type, protected_current)
        finally:
            with suppress(Exception):
                await page.close()

    async def discover(self, site):
        source = site["source"]
        if source["type"] in ("none", "fixed"):
            return [], "no reference source configured"
        url = source["url"]
        if url not in self.guide_cache:
            try:
                self.guide_cache[url] = await asyncio.wait_for(
                    self._page(url, solve=False, timeout_ms=30_000, source_type=source["type"]),
                    timeout=35,
                )
            except Exception as exc:
                self.guide_cache[url] = exc
        page = self.guide_cache[url]
        if isinstance(page, Exception):
            return [], f"guide unavailable: {type(page).__name__}: {str(page)[:120]}"
        if page["status"] >= 400:
            return [], f"guide unavailable: HTTP {page['status']}"
        if any(marker in (page["title"] + page["body"][:300]).lower() for marker in CHALLENGE_MARKERS):
            return [], "guide challenged"
        if source["type"] == "telegram":
            selected = telegram_candidates(site, page.get("messages", []))
            if selected:
                return selected, "latest labeled Telegram address"
            if source.get("strictPreferredLabel"):
                return [], "Telegram address label missing or invalid"
        scored = {}
        preferred = source.get("preferredLabel", "").lower()
        strict_preferred = source.get("strictPreferredLabel", False)
        stop_labels = [x.lower() for x in source.get("stopLabels", [])]
        for index, link in enumerate(page["links"]):
            context = (link["text"] + " " + link["parent"][:250]).lower()
            if any(label in context for label in stop_labels):
                continue
            if strict_preferred and preferred not in link["text"].lower():
                continue
            for candidate in host_candidates(site["key"], link["href"] + " " + link["text"]):
                score = 10 + (20 if preferred and preferred in context else 0) - index / 1000
                scored[candidate] = max(scored.get(candidate, -999), score)
        if not strict_preferred:
            for index, candidate in enumerate(host_candidates(site["key"], page["body"][:80_000])):
                scored[candidate] = max(scored.get(candidate, -999), 1 - index / 1000)
        return sorted(scored, key=lambda item: scored[item], reverse=True)[:5], "guide read"

    async def verify(self, key, url, *, timeout_ms=210_000, allow_protected=False, candidate=False):
        # One budget covers homepage, restart, retry and category probes. The
        # old implementation could spend the full timeout on every route.
        try:
            return await asyncio.wait_for(
                self._verify(key, url, timeout_ms, allow_protected, candidate),
                timeout=timeout_ms / 1000,
            )
        except Exception as exc:
            return None, f"{type(exc).__name__}: {str(exc)[:160]}"

    async def _restart_browser(self):
        # A new tab/context alone shares Firefox's broken connection pool.
        # This verifier is isolated per site, so no other site's work is lost.
        await self.__aexit__(None, None, None)
        await self.__aenter__()

    async def _verify(self, key, url, timeout_ms, allow_protected, candidate):
        target = None
        deadline = time.monotonic() + timeout_ms / 1000

        async def probe(route, cap_ms):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("site verification budget exhausted")
            budget = min(cap_ms, int(remaining * 1000))
            return await asyncio.wait_for(
                self._page(route, timeout_ms=budget, protected_current=allow_protected and not candidate),
                timeout=budget / 1000,
            )

        try:
            target = validate_url(key, url)
            if candidate and not candidate_url_allowed(key, target):
                return None, "candidate host is explicitly blocked after a confirmed false positive"
            reason = "homepage unavailable"
            for attempt in range(1 if candidate else 2):
                try:
                    page = await probe(target, 60_000)
                    result, reason = validate_page(
                        key, page["url"], page["title"], page["body"], page["links"], page["html"], page["status"],
                        require_candidate_content=candidate,
                    )
                    if result and not candidate:
                        return result, reason + ("; recovered after browser restart" if attempt else "")
                    if not result and reason not in ("category navigation not found", "HTTP 404"):
                        return None, reason
                    break
                except CloudflareProtectedError:
                    raise
                except Exception as exc:
                    if not transient_navigation_error(exc):
                        raise
                    reason = f"homepage transport failed: {type(exc).__name__}: {str(exc)[:100]}"
                    LOG.warning("%s homepage attempt %s: %s", key, attempt + 1, reason)
                    if candidate or attempt:
                        break
                    await asyncio.wait_for(
                        self._restart_browser(), timeout=min(30, max(0.01, deadline - time.monotonic())),
                    )
            # A reset at '/' does not prove '/ing' or '/novel/updates' is down.
            # Only actual same-family category content can recover the check.
            for category in RULES[key]["categoryPaths"]:
                if urlsplit(category).fragment:
                    continue
                try:
                    category_page = await probe(target + category, 45_000)
                    result, probe_reason = validate_page(
                        key, category_page["url"], category_page["title"], category_page["body"], category_page["links"],
                        category_page["html"], category_page["status"], category,
                        require_candidate_content=candidate,
                    )
                    if result:
                        return result, probe_reason
                    reason = probe_reason
                except CloudflareProtectedError:
                    raise
                except Exception as exc:
                    reason = f"category route unavailable: {type(exc).__name__}: {str(exc)[:100]}"
            return None, reason
        except CloudflareProtectedError as exc:
            # Only an already-published address may use this reachability
            # fallback. Discovered/numbered candidates must still expose one of
            # the configured category routes before replacing an address.
            if allow_protected and not candidate and target:
                return target, "Cloudflare protection responded; verified address preserved"
            return None, f"CloudflareProtectedError: {str(exc)[:160]}"
        except Exception as exc:
            return None, f"{type(exc).__name__}: {str(exc)[:160]}"
