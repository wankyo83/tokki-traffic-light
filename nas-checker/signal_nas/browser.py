import asyncio
from urllib.parse import urlsplit

from .model import CHALLENGE_MARKERS, RULES, host_candidates, validate_page, validate_url


def telegram_candidates(site, messages):
    """Telegram's DOM is oldest-first; use the newest matching address post."""
    source = site["source"]
    preferred = source.get("preferredLabel", "")
    for message in reversed(messages):
        if preferred:
            position = message.lower().find(preferred.lower())
            if position < 0:
                continue
            # The first URL after the label is the corresponding address, not
            # a preceding 'bypass' or permanent gateway link in the same post.
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
        return self

    async def __aexit__(self, kind, value, traceback):
        await self._manager.__aexit__(kind, value, traceback)

    async def _page(self, url, *, solve=True, timeout_ms=12_000, source_type=""):
        context = await self.browser.new_context()
        page = await context.new_page()
        try:
            response = await page.goto(url, wait_until="commit", timeout=timeout_ms)
            solved_challenge = False
            try:
                selector = ".tgme_widget_message_text" if source_type == "telegram" else "body"
                await page.locator(selector).first.wait_for(state="attached", timeout=4_000)
            except Exception:
                pass
            title = await page.title()
            if solve and ((response and response.status == 403) or any(marker in title.lower() for marker in CHALLENGE_MARKERS)):
                from playwright_captcha import CaptchaType, ClickSolver, FrameworkType
                async with ClickSolver(framework=FrameworkType.CAMOUFOX, page=page, max_attempts=3, attempt_delay=1) as solver:
                    await asyncio.wait_for(solver.solve_captcha(
                        captcha_container=page,
                        captcha_type=CaptchaType.CLOUDFLARE_INTERSTITIAL,
                        wait_checkbox_attempts=1,
                        wait_checkbox_delay=0.5,
                    ), timeout=12)
                solved_challenge = True
                try:
                    await page.locator("body").first.wait_for(state="attached", timeout=4_000)
                except Exception:
                    pass
            try:
                await page.wait_for_function("document.querySelectorAll('a[href]').length > 0", timeout=3_000)
            except Exception:
                pass
            title = await page.title()
            html = (await page.content())[:2_000_000]
            try:
                body = (await page.locator("body").inner_text(timeout=3_000))[:120_000]
            except Exception:
                body = ""
            links = await page.locator("a[href]").evaluate_all("nodes => nodes.slice(0, 1000).map(a => ({href: a.href, text: a.innerText, parent: a.parentElement?.innerText?.slice(0, 500) || ''}))")
            messages = await page.locator(".tgme_widget_message_text").evaluate_all("nodes => nodes.map(n => n.innerText)")
            status = response.status if response else 0
            if solved_challenge and status == 403:
                status = 200  # Challenge was solved; the final DOM is checked below.
            return {"url": page.url, "title": title, "html": html, "body": body, "links": links, "messages": messages, "status": status}
        finally:
            await context.close()

    async def discover(self, site):
        source = site["source"]
        if source["type"] in ("none", "fixed"):
            return [], "no reference source configured"
        url = source["url"]
        if url not in self.guide_cache:
            try:
                self.guide_cache[url] = await asyncio.wait_for(self._page(url, solve=False, source_type=source["type"]), timeout=20)
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

    async def verify(self, key, url, *, timeout_ms=35_000):
        try:
            target = validate_url(key, url)
            page = await asyncio.wait_for(self._page(target, timeout_ms=min(timeout_ms, 10_000)), timeout=28)
            result, reason = validate_page(key, page["url"], page["title"], page["body"], page["links"], page["html"], page["status"])
            if result:
                return result, reason
            if reason != "category navigation not found":
                return None, reason
            for category in RULES[key]["categoryPaths"]:
                if urlsplit(category).fragment:
                    continue
                try:
                    probe = await asyncio.wait_for(self._page(target + category, solve=False, timeout_ms=min(timeout_ms, 5_000)), timeout=9)
                    result, probe_reason = validate_page(key, probe["url"], probe["title"], probe["body"], probe["links"], probe["html"], probe["status"], category)
                    if result:
                        return result, probe_reason
                    reason = probe_reason
                except Exception as exc:
                    reason = f"category route unavailable: {type(exc).__name__}: {str(exc)[:100]}"
            return None, reason
        except Exception as exc:
            return None, f"{type(exc).__name__}: {str(exc)[:160]}"
