"""bin/log_raw.py의 https 전용 전송을 검사해요. 실제 네트워크는 mock/로컬로 막아요."""

import http.server
import os
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

DEV_URL = "https://usage-dashboard-dev.velar-agent.duckdns.org/api/ingest"
PROD_URL = "https://usage-dashboard.velar-agent.duckdns.org/api/ingest"


def _load_log_raw_namespace():
    """log_raw.py를 메인 루프 없이 불러와요. `done = set(` 앞부분만 exec해요."""
    src = Path(__file__).resolve().parent.parent / "bin" / "log_raw.py"
    prefix = src.read_text(encoding="utf-8").split("done = set(", 1)[0]
    ns = {"__name__": "log_raw_under_test", "__file__": str(src)}
    with mock.patch.dict(os.environ, {}, clear=True):
        exec(compile(prefix, str(src), "exec"), ns)
    return ns


class CheckIngestUrlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = _load_log_raw_namespace()
        cls.check = staticmethod(cls.ns["check_ingest_url"])

    def test_http_and_non_https_urls_are_refused(self):
        for url in ("http://127.0.0.1:8787/api/ingest",
                    "http://127.0.0.1:8788/api/ingest",
                    "http://usage-dashboard-dev.velar-agent.duckdns.org/api/ingest",
                    "ftp://usage-dashboard.velar-agent.duckdns.org/api/ingest",
                    "usage-dashboard.velar-agent.duckdns.org/api/ingest"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    self.check(url)

    def test_workers_dev_is_refused(self):
        with self.assertRaises(ValueError):
            self.check("https://usage-dashboard.velar-agent.workers.dev/api/ingest")

    def test_https_defaults(self):
        self.assertEqual(self.ns["INGEST_URL"], DEV_URL)
        self.assertEqual(self.ns["INGEST_PROD_URL"], PROD_URL)
        self.check(DEV_URL)
        self.check(PROD_URL)


class PostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = _load_log_raw_namespace()

    def setUp(self):
        self.key = "test-ingest-key"
        self.key_file = _make_temp_file(self.key + "\n")
        self.addCleanup(lambda: os.unlink(self.key_file))

    def test_https_accepted_up_to_the_network_call(self):
        seen = []
        ns = self.ns

        class FakeResponse:
            def read(self):
                return b'{"ok":true}'

        class FakeOpener:
            def open(self, request, timeout=None):
                seen.append(request)
                return FakeResponse()

        with mock.patch.dict(ns, {"_NO_REDIRECT_OPENER": FakeOpener()}):
            ns["_post_to"](DEV_URL, self.key_file,
                           [{"service": "claude", "metric": "session_used_pct", "value": 1}])
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].full_url, DEV_URL)
        self.assertEqual(seen[0].get_header("Authorization") or seen[0].unredirected_hdrs.get("Authorization"),
                         "Bearer " + self.key)

    def test_http_refused_before_the_network_call(self):
        seen = []
        ns = self.ns

        class FakeOpener:
            def open(self, request, timeout=None):
                seen.append(request)
                raise AssertionError("network must not be called")

        with mock.patch.dict(ns, {"_NO_REDIRECT_OPENER": FakeOpener()}):
            with self.assertRaises(ValueError):
                ns["_post_to"]("http://127.0.0.1:8787/api/ingest", self.key_file, [{"service": "s"}])
        self.assertEqual(seen, [])


class RedirectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = _load_log_raw_namespace()

    def test_redirect_request_raises(self):
        handler = self.ns["_NoRedirect"]()
        request = urllib.request.Request(DEV_URL, data=b"[]", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            handler.redirect_request(request, None, 302, "Found", {}, "http://127.0.0.1:8787/api/ingest")
        self.assertEqual(ctx.exception.code, 302)

    def test_opener_has_no_redirect_handler_and_keeps_https(self):
        opener = self.ns["_NO_REDIRECT_OPENER"]
        self.assertTrue(any(isinstance(h, self.ns["_NoRedirect"]) for h in opener.handlers))
        self.assertTrue(any(type(h) is urllib.request.HTTPRedirectHandler for h in opener.handlers) is False)

    def test_opener_does_not_follow_redirect(self):
        seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                seen.append(self.path)
                if len(seen) == 1:
                    self.send_response(302)
                    self.send_header("Location", "http://127.0.0.1:%d/api/ingest" % self.server.server_port)
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"followed")

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        request = urllib.request.Request("http://127.0.0.1:%d/api/ingest" % server.server_port,
                                         data=b"[]", method="POST")
        request.add_unredirected_header("Authorization", "Bearer secret")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.ns["_NO_REDIRECT_OPENER"].open(request, timeout=5)
        self.assertEqual(ctx.exception.code, 302)
        ctx.exception.close()
        self.assertEqual(len(seen), 1)


def _make_temp_file(content):
    import tempfile
    fd, name = tempfile.mkstemp(prefix="log_raw_test_key_", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    return name
