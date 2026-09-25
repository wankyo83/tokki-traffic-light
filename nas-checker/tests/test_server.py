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
        self.submitted = None

    def snapshot(self):
        return {"running": False}

    def submit(self, key, url):
        self.submitted = (key, url)
        return url


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
        with self.assertRaises(HTTPError) as raised:
            urlopen(self.base + "/api/state")
        self.assertEqual(raised.exception.code, 401)

    def test_manual_request_requires_token_and_cors_exact_origin(self):
        payload = json.dumps({"key": "toki", "url": "https://toki33.com"}).encode()
        request = Request(self.base + "/api/manual-candidate", data=payload, method="POST", headers={
            "Authorization": "Bearer " + os.environ["ADMIN_TOKEN"],
            "Content-Type": "application/json",
            "Origin": "https://wankyo83.github.io",
        })
        with urlopen(request) as response:
            self.assertEqual(response.status, 202)
            self.assertEqual(response.headers["Access-Control-Allow-Origin"], "https://wankyo83.github.io")
        self.assertEqual(self.service.submitted, ("toki", "https://toki33.com"))


if __name__ == "__main__":
    unittest.main()
