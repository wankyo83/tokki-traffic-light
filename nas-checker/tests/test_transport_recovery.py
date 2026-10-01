import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from signal_nas.browser import BrowserVerifier, CloudflareProtectedError


def listing(url="https://sbxh9.com/", links=None, status=200):
    return dict(url=url, status=status, title="웹툰", body="작품 목록", html="<html>작품 목록</html>",
                links=links if links is not None else [{"href": "https://sbxh9.com/ing"}])


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirmed_protection_on_published_host_keeps_existing_policy(self):
        browser = BrowserVerifier()
        page = AsyncMock()
        page.goto.return_value.status = 403
        with patch.object(browser, "_wait_for_initial_state", AsyncMock(return_value={"confirmedChallenge": True})), \
             patch.object(browser, "_wait_for_challenge_exit", AsyncMock(return_value={"confirmedChallenge": True})):
            with self.assertRaises(CloudflareProtectedError):
                await browser._load(page, None, "https://sbxh9.com", 60_000, "", protected_current=True)

    async def test_candidate_cannot_use_published_protection_fallback(self):
        browser = BrowserVerifier()
        with patch.object(browser, "_page", AsyncMock(side_effect=CloudflareProtectedError("confirmed"))) as page:
            result, _ = await browser.verify("sbxh", "https://sbxh10.com", candidate=True, allow_protected=True)
            self.assertIsNone(result)
            self.assertFalse(page.await_args.kwargs["protected_current"])

    async def test_reset_restarts_and_retries_current(self):
        browser = BrowserVerifier()
        with patch.object(browser, "_page", AsyncMock(side_effect=[RuntimeError("Page.goto: NS_ERROR_NET_RESET"), listing()])) as page, \
             patch.object(browser, "_restart_browser", AsyncMock()) as restart:
            result, reason = await browser.verify("sbxh", "https://sbxh9.com")
            self.assertEqual(result, "https://sbxh9.com")
            self.assertIn("recovered", reason)
            restart.assert_awaited_once()
            self.assertEqual(page.await_count, 2)

    async def test_two_home_resets_still_checks_real_category(self):
        browser = BrowserVerifier()
        error = RuntimeError("NS_ERROR_NET_RESET")
        with patch.object(browser, "_page", AsyncMock(side_effect=[error, error, listing("https://sbxh9.com/ing")])) as page, \
             patch.object(browser, "_restart_browser", AsyncMock()):
            result, reason = await browser.verify("sbxh", "https://sbxh9.com")
            self.assertEqual(result, "https://sbxh9.com")
            self.assertIn("category route verified", reason)
            self.assertEqual(page.await_args_list[-1].args[0], "https://sbxh9.com/ing")

    async def test_unknown_host_does_not_restart_or_turn_healthy(self):
        browser = BrowserVerifier()
        with patch.object(browser, "_page", AsyncMock(side_effect=RuntimeError("NS_ERROR_UNKNOWN_HOST"))), \
             patch.object(browser, "_restart_browser", AsyncMock()) as restart:
            result, reason = await browser.verify("sbxh", "https://sbxh9.com")
            self.assertIsNone(result)
            self.assertIn("UNKNOWN_HOST", reason)
            restart.assert_not_awaited()

    async def test_candidate_remains_strict_after_reset(self):
        browser = BrowserVerifier()
        with patch.object(browser, "_page", AsyncMock(side_effect=[RuntimeError("NS_ERROR_NET_RESET"), listing("https://newtoki10.org/webtoon", [])])), \
             patch.object(browser, "_restart_browser", AsyncMock()) as restart:
            result, _ = await browser.verify("newtoki", "https://newtoki10.org", candidate=True)
            self.assertIsNone(result)
            restart.assert_not_awaited()

    async def test_total_budget_includes_all_attempts(self):
        browser = BrowserVerifier()

        async def slow(*_, **__):
            await asyncio.sleep(1)

        with patch.object(browser, "_page", slow), patch.object(browser, "_restart_browser", AsyncMock()):
            result, reason = await browser.verify("sbxh", "https://sbxh9.com", timeout_ms=25)
            self.assertIsNone(result)
            self.assertIn("TimeoutError", reason)

    async def test_404_home_can_recover_from_category(self):
        browser = BrowserVerifier()
        with patch.object(browser, "_page", AsyncMock(side_effect=[listing(status=404), listing("https://sbxh9.com/ing")])):
            result, _ = await browser.verify("sbxh", "https://sbxh9.com")
            self.assertEqual(result, "https://sbxh9.com")


if __name__ == "__main__":
    unittest.main()
