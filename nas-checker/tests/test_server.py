import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from signal_nas.server import make_handler


class FakeService:
    def __init__(self):
        self.wake = threading.Event()

    def snapshot(self):
        return {
            "running": True, "phase": "verifying sites", "currentSite": "티비위키",
            "completedSites": 13, "totalSites": 15, "lastError": "private detail",
            "groups": [{"key": "tvwiki", "name": "티비위키", "category": "media",
                        "activeBaseUrl": "https://tvwiki51.net", "state": "manual",
                        "sourceName": "티비위키 공식 텔레그램", "sourceUrl": "https://t.me/s/tvwiki_url",
                        "reason": "", "checkedAt": "2026-09-25T00:00:00Z", "privateField": "hidden"}],
        }


class ServerTests(unittest.TestCase):
    def setUp(self):
        os.environ["ADMIN_TOKEN"] = "test-only-token-longer-than-24-characters"
        os.environ["ADMIN_ALLOWED_ORIGIN"] = "https://wankyo83.github.io"
        self.service = FakeService()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.service))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_health_public_but_state_private(self):
        with urlopen(self.base + "/health") as response:
            self.assertTrue(json.load(response)["ok"])
        with urlopen(self.base + "/api/overview") as response:
            overview = json.load(response)
        self.assertEqual(overview["currentSite"], "티비위키")
        self.assertTrue(overview["hasError"])
        self.assertNotIn("lastError", overview)
        self.assertNotIn("privateField", overview["groups"][0])
        with self.assertRaises(HTTPError) as raised:
            urlopen(self.base + "/api/state")
        self.assertEqual(raised.exception.code, 401)

    def test_dashboard_is_readable_without_token(self):
        with urlopen(self.base + "/") as response:
            html = response.read().decode("utf-8")
        self.assertIn("만화·웹툰 신호등", html)
        self.assertIn("미디어 주소", html)
        self.assertIn("/api/overview", html)

    def test_manual_request_is_removed_but_run_requires_token(self):
        payload = json.dumps({"key": "toki", "url": "https://toki33.com"}).encode()
        request = Request(self.base + "/api/manual-candidate", data=payload, method="POST", headers={
            "Authorization": "Bearer " + os.environ["ADMIN_TOKEN"],
            "Content-Type": "application/json",
            "Origin": "https://wankyo83.github.io",
        })
        with self.assertRaises(HTTPError) as raised:
            urlopen(request)
        self.assertEqual(raised.exception.code, 404)
        request = Request(self.base + "/api/run", data=b"{}", method="POST", headers={
            "Authorization": "Bearer " + os.environ["ADMIN_TOKEN"],
            "Content-Type": "application/json",
            "Origin": "https://wankyo83.github.io",
        })
        with urlopen(request) as response:
            self.assertEqual(response.status, 202)
            self.assertEqual(response.headers["Access-Control-Allow-Origin"], "https://wankyo83.github.io")
        self.assertTrue(self.service.wake.is_set())


if __name__ == "__main__":
    unittest.main()
