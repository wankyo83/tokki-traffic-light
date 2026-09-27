import asyncio
import os
import time
from contextlib import asynccontextmanager, suppress
from urllib.parse import urlsplit

from .model import CHALLENGE_MARKERS, RULES, host_candidates, validate_page, validate_url


CHALLENGE_DOM_MARKERS = (
    "challenges.cloudflare.com",
    "/cdn-cgi/challenge-platform/",
    "cf-chl-widget",
    "cf-turnstile",
)


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
            await self.context.close()
            self.context = None
        if self._manager is not None:
            await self._manager.__aexit__(kind, value, traceback)

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
        try:
            body_attached = await page.locator("body").count() > 0
            link_count = await page.locator("a[href]").count()
        except Exception:
            body_attached, link_count = False, 0
        return {
            "challenge": challenge,
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

    async def _load(self, page, solver, url, timeout_ms, source_type):
        deadline = time.monotonic() + timeout_ms / 1000

        def remaining_seconds():
            return max(1.0, deadline - time.monotonic())

        response = await page.goto(url, wait_until="commit", timeout=min(timeout_ms, 20_000))
        status = response.status if response else 0
        detect_seconds = min(_seconds("CF_DETECT_TIMEOUT_SECONDS", 20), remaining_seconds())
        state = await self._wait_for_initial_state(page, status, source_type, detect_seconds)
        solved_challenge = False

        if solver is not None and state["challenge"]:
            widget_seconds = min(_seconds("CF_WIDGET_TIMEOUT_SECONDS", 30), remaining_seconds())
            state = await self._wait_for_widget(page, status, widget_seconds)
            if state["challenge"]:
                from playwright_captcha import CaptchaType

                solve_seconds = min(_seconds("CF_SOLVE_TIMEOUT_SECONDS", 90), remaining_seconds())
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
                exit_seconds = min(_seconds("CF_POST_SOLVE_TIMEOUT_SECONDS", 60), remaining_seconds())
                state = await self._wait_for_challenge_exit(page, exit_seconds)
                if state["challenge"]:
                    raise TimeoutError("Cloudflare challenge remained after solver")

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

    async def _page(self, url, *, solve=True, timeout_ms=210_000, source_type=""):
        if self.context is None:
            raise RuntimeError("BrowserVerifier is not started")
        page = await self.context.new_page()
        try:
            async with self._solver(page, solve) as solver:
                return await self._load(page, solver, url, timeout_ms, source_type)
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

    async def verify(self, key, url, *, timeout_ms=210_000):
        try:
            target = validate_url(key, url)
            page = await asyncio.wait_for(
                self._page(target, timeout_ms=timeout_ms),
                timeout=timeout_ms / 1000 + 10,
            )
            result, reason = validate_page(
                key, page["url"], page["title"], page["body"], page["links"], page["html"], page["status"]
            )
            if result:
                return result, reason
            if reason != "category navigation not found":
                return None, reason
            for category in RULES[key]["categoryPaths"]:
                if urlsplit(category).fragment:
                    continue
                try:
                    route_timeout = min(timeout_ms, 180_000)
                    probe = await asyncio.wait_for(
                        self._page(target + category, solve=True, timeout_ms=route_timeout),
                        timeout=route_timeout / 1000 + 10,
                    )
                    result, probe_reason = validate_page(
                        key, probe["url"], probe["title"], probe["body"], probe["links"],
                        probe["html"], probe["status"], category,
                    )
                    if result:
                        return result, probe_reason
                    reason = probe_reason
                except Exception as exc:
                    reason = f"category route unavailable: {type(exc).__name__}: {str(exc)[:100]}"
            return None, reason
        except Exception as exc:
            return None, f"{type(exc).__name__}: {str(exc)[:160]}"
