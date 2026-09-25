import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from signal_nas.model import automatic_regression, host_candidates, numeric_candidates, validate_page, validate_url
from signal_nas.browser import telegram_candidates
from signal_nas.publish import GitHubPublisher
from signal_nas.service import CheckerService


class ModelTests(unittest.TestCase):
    def test_strict_family_and_https(self):
        self.assertEqual(validate_url("toki", "https://toki32.com/novel"), "https://toki32.com")
        for url in ("http://toki32.com", "https://toki32.com.evil.test", "https://user@toki32.com", "https://toki32.com:8080"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_url("toki", url)

    def test_numbers_are_limited_to_next_ten(self):
        self.assertEqual(numeric_candidates("toki", "https://toki32.com"), [f"https://toki{n}.com" for n in range(33, 43)])
        self.assertEqual(numeric_candidates("jjaptoon", "https://www.jjaptoon031.com"), [f"https://www.jjaptoon{n:03d}.com" for n in range(32, 42)])
        self.assertFalse(automatic_regression("jjaptoon", "https://jjaptoon31.com", "https://jjaptoon007.com"))
        self.assertTrue(automatic_regression("toki", "https://toki32.com", "https://toki31.com"))

    def test_guide_extraction(self):
        self.assertEqual(host_candidates("tvroom", "old https://tvroom35.org/ new https://tvroom36.org/ and https://tvroom.com"), ["https://tvroom35.org", "https://tvroom36.org"])

    def test_challenge_not_valid(self):
        result, _ = validate_page("toki", "https://toki33.com", "Just a moment", "뉴토끼 웹툰", 10, "<html></html>")
        self.assertIsNone(result)
        result, _ = validate_page("toki", "https://toki33.com", "뉴토끼", "웹툰 최신", 10, "<html></html>")
        self.assertEqual(result, "https://toki33.com")

    def test_tvwiki_uses_latest_realtime_label_not_bypass_address(self):
        site = {"key": "tvwiki", "source": {"preferredLabel": "티비위키 실시간 접속주소", "strictPreferredLabel": True}}
        messages = [
            "티비위키 실시간 접속주소\nhttps://tvwiki50.net",
            "티비위키 우회 주소\nhttps://tvwiki.store\n티비위키 실시간 접속주소\nhttps://tvwiki51.net\n우회 접속 방법",
        ]
        self.assertEqual(telegram_candidates(site, messages), ["https://tvwiki51.net"])
        self.assertEqual(telegram_candidates(site, ["티비위키 우회 주소\nhttps://tvwiki.store"]), [])


class FakeBrowser:
    def __init__(self, results, guide=None):
        self.results = results
        self.guide = guide or []
        self.tried = []
        self.discoveries = 0

    async def discover(self, site):
        self.discoveries += 1
        return self.guide, "guide failed" if not self.guide else "guide read"

    async def verify(self, key, url, **_):
        self.tried.append(url)
        result = self.results.get(url)
        return result, "verified" if result else "unavailable"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.before = os.environ.get("DATA_DIR")
        os.environ["DATA_DIR"] = self.temp.name
        self.service = CheckerService()

    def tearDown(self):
        if self.before is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = self.before
        self.temp.cleanup()

    def test_source_down_preserves_current(self):
        browser = FakeBrowser({})
        result = asyncio.run(self.service._check_site(browser, {"key": "toki", "source": {"type": "guide"}}, "https://toki32.com"))
        self.assertIsNone(result[0])
        self.assertEqual(browser.tried, ["https://toki32.com"] + [f"https://toki{n}.com" for n in range(33, 43)])
        self.assertEqual(result[4]["source"]["state"], "failed")
        self.assertEqual(result[4]["numeric"]["state"], "failed")
        self.assertEqual(result[4]["numeric"]["checked"], 10)
        second = FakeBrowser({})
        asyncio.run(self.service._check_site(second, {"key": "toki", "source": {"type": "guide"}}, "https://toki32.com"))
        self.assertEqual(second.tried, browser.tried)

    def test_redirect_to_next_verified(self):
        browser = FakeBrowser({"https://toki32.com": "https://toki33.com"})
        result = asyncio.run(self.service._check_site(browser, {"key": "toki", "source": {"type": "guide"}}, "https://toki32.com"))
        self.assertEqual(result[0], "https://toki33.com")
        self.assertEqual(browser.discoveries, 0)

    def test_working_current_skips_number_scan(self):
        browser = FakeBrowser({"https://toki32.com": "https://toki32.com", "https://toki33.com": "https://toki33.com"})
        result = asyncio.run(self.service._check_site(browser, {"key": "toki", "source": {"type": "guide"}}, "https://toki32.com"))
        self.assertEqual(result[0], "https://toki32.com")
        self.assertNotIn("https://toki33.com", browser.tried)
        self.assertEqual(browser.discoveries, 0)

    def test_working_current_kept_if_numbered_candidates_fail(self):
        browser = FakeBrowser({"https://toki32.com": "https://toki32.com"})
        result = asyncio.run(self.service._check_site(browser, {"key": "toki", "source": {"type": "guide"}}, "https://toki32.com"))
        self.assertEqual(result[0], "https://toki32.com")

    def test_old_guide_rejected(self):
        browser = FakeBrowser({"https://toki31.com": "https://toki31.com", "https://toki32.com": "https://toki32.com"}, ["https://toki31.com"])
        result = asyncio.run(self.service._check_site(browser, {"key": "toki", "source": {"type": "guide"}}, "https://toki32.com"))
        self.assertEqual(result[0], "https://toki32.com")
        self.assertNotIn("https://toki31.com", browser.tried)

    def test_source_candidate_then_numeric_success(self):
        browser = FakeBrowser({"https://toki35.com": "https://toki35.com"}, ["https://toki34.com"])
        result = asyncio.run(self.service._check_site(browser, {"key": "toki", "source": {"type": "guide"}}, "https://toki32.com"))
        self.assertEqual(result[0], "https://toki35.com")
        self.assertEqual(result[4]["source"]["state"], "failed")
        self.assertEqual(result[4]["numeric"]["state"], "healthy")

    def test_source_success_stops_numeric_scan(self):
        browser = FakeBrowser({"https://toki34.com": "https://toki34.com"}, ["https://toki34.com"])
        result = asyncio.run(self.service._check_site(browser, {"key": "toki", "source": {"type": "guide"}}, "https://toki32.com"))
        self.assertEqual(browser.tried, ["https://toki32.com", "https://toki34.com"])
        self.assertEqual(result[4]["source"]["state"], "healthy")
        self.assertEqual(result[4]["numeric"]["state"], "skipped")

    def test_all_fail_preserves_every_published_address(self):
        from signal_nas.model import SITES
        examples = {
            "newtoki": "https://newtoki1.org", "toki": "https://toki32.com", "sbxh": "https://sbxh9.com",
            "wfwf": "https://wfwf505.com", "blacktoon": "https://blacktoon423.com", "jjaptoon": "https://www.jjaptoon007.com",
            "11toon": "https://11toon.com", "naver": "https://comic.naver.com", "goodtoon": "https://goodtoon005.com",
            "newxtoon": "https://newxtoon1.com", "linkkf": "https://linkkf.tv", "ani24": "https://ohli24.net",
            "tvroom": "https://tvroom35.org", "tvwiki": "https://tvwiki51.net", "anilife": "https://anilife01.tv",
        }
        document = {"schemaVersion": 1, "domains": {key: {"baseUrl": url, "status": "healthy"} for key, url in examples.items()}}
        old_status = {"schemaVersion": 3, "groups": []}
        with patch("signal_nas.service.BrowserVerifier", return_value=FakeBrowser({})):
            updated, status = asyncio.run(self.service._run_async(document, old_status))
        self.assertEqual({key: item["baseUrl"] for key, item in updated["domains"].items()}, examples)
        self.assertEqual(len(status["groups"]), len(SITES))
        self.assertEqual(status["policy"]["numericSearchMaxOffset"], 10)
        self.assertEqual(status["groups"][1]["checks"]["numeric"]["state"], "failed")
        self.assertEqual(self.service.snapshot()["completedSites"], len(SITES))


class PublisherTests(unittest.TestCase):
    def test_ref_is_read_from_singular_endpoint_and_updated_at_plural_endpoint(self):
        with patch.dict(os.environ, {
            "GITHUB_REPOSITORY": "example/repo", "GITHUB_BRANCH": "main",
            "GITHUB_TOKEN": "test-token-not-a-secret",
        }):
            publisher = GitHubPublisher()
        calls = []

        def fake_api(method, path, payload=None):
            calls.append((method, path, payload))
            if method == "GET" and path.startswith("/git/ref/"):
                return {"object": {"sha": "old"}}
            if method == "GET" and path.startswith("/git/commits/"):
                return {"tree": {"sha": "old-tree"}}
            return {"sha": "new"}

        publisher._api = fake_api
        self.assertEqual(publisher.publish({"domains": {}}, {"groups": []}), "new")
        self.assertEqual(calls[0][:2], ("GET", "/git/ref/heads/main"))
        self.assertEqual(calls[-1][:2], ("PATCH", "/git/refs/heads/main"))
        self.assertFalse(calls[-1][2]["force"])


if __name__ == "__main__":
    unittest.main()
