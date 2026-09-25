import asyncio
from urllib.parse import urlsplit

from .model import CHALLENGE_MARKERS, host_candidates, validate_page, validate_url


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

    async def _page(self, url, *, solve=True, timeout_ms=35_000):
        context = await self.browser.new_context()
        page = await context.new_page()
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_timeout(1500)
            title = await page.title()
            if solve and ((response and response.status == 403) or any(marker in title.lower() for marker in CHALLENGE_MARKERS)):
                from playwright_captcha import CaptchaType, ClickSolver, FrameworkType
                async with ClickSolver(framework=FrameworkType.CAMOUFOX, page=page, max_attempts=10, attempt_delay=1) as solver:
                    await asyncio.wait_for(solver.solve_captcha(
                        captcha_container=page,
                        captcha_type=CaptchaType.CLOUDFLARE_INTERSTITIAL,
                        wait_checkbox_attempts=1,
                        wait_checkbox_delay=0.5,
                    ), timeout=60)
                await page.wait_for_load_state("domcontentloaded", timeout=20_000)
            title = await page.title()
            html = (await page.content())[:2_000_000]
            body = (await page.locator("body").inner_text(timeout=10_000))[:120_000]
            links = await page.locator("a[href]").evaluate_all("nodes => nodes.slice(0, 1000).map(a => ({href: a.href, text: a.innerText, parent: a.parentElement?.innerText?.slice(0, 500) || ''}))")
            return {"url": page.url, "title": title, "html": html, "body": body, "links": links, "status": response.status if response else 0}
        finally:
            await context.close()

    async def discover(self, site):
        source = site["source"]
        if source["type"] == "fixed":
            return [], "fixed address"
        url = source["url"]
        if url not in self.guide_cache:
            try:
                self.guide_cache[url] = await asyncio.wait_for(self._page(url, solve=False, timeout_ms=15_000), timeout=20)
            except Exception as exc:
                self.guide_cache[url] = exc
        page = self.guide_cache[url]
        if isinstance(page, Exception):
            return [], f"guide unavailable: {type(page).__name__}: {str(page)[:120]}"
        if page["status"] >= 400:
            return [], f"guide unavailable: HTTP {page['status']}"
        if any(marker in (page["title"] + page["body"][:300]).lower() for marker in CHALLENGE_MARKERS):
            return [], "guide challenged"
        scored = {}
        preferred = source.get("preferredLabel", "").lower()
        stop_labels = [x.lower() for x in source.get("stopLabels", [])]
        for index, link in enumerate(page["links"]):
            context = (link["text"] + " " + link["parent"][:250]).lower()
            if any(label in context for label in stop_labels):
                continue
            for candidate in host_candidates(site["key"], link["href"] + " " + link["text"]):
                score = 10 + (20 if preferred and preferred in context else 0) - index / 1000
                scored[candidate] = max(scored.get(candidate, -999), score)
        for index, candidate in enumerate(host_candidates(site["key"], page["body"][:80_000])):
            scored[candidate] = max(scored.get(candidate, -999), 1 - index / 1000)
        return sorted(scored, key=lambda item: scored[item], reverse=True)[:5], "guide read"

    async def verify(self, key, url, *, timeout_ms=35_000):
        try:
            target = validate_url(key, url)
            page = await asyncio.wait_for(self._page(target, timeout_ms=min(timeout_ms, 15_000)), timeout=20)
            if page["status"] >= 500:
                return None, f"upstream HTTP {page['status']}"
            host = urlsplit(page["url"]).hostname
            internal = sum(1 for link in page["links"] if urlsplit(link["href"]).hostname == host)
            result, reason = validate_page(key, page["url"], page["title"], page["body"], internal, page["html"])
            return result, reason
        except Exception as exc:
            return None, f"{type(exc).__name__}: {str(exc)[:160]}"
