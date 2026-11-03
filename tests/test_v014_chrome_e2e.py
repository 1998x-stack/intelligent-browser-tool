"""Real Chrome/Selenium E2E through a local enforcing HTTP proxy.

Runs only in the browser E2E GitHub Actions job (Chrome is mandatory).
This proves the configured proxy sees and blocks browser subresources; it does
NOT prove that a runner's network namespace prohibits all direct egress.
"""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest
from config import BrowserConfig
from url_policy import URLPolicy, URLPolicyError


class ProxyFixture(BaseHTTPRequestHandler):
    seen = []
    lock = threading.Lock()

    def log_message(self, *_):
        pass

    def reply(self, status, content=b"", headers=()):
        self.send_response(status)
        for key, value in headers:
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Connection", "close")
        self.end_headers()
        if content:
            self.wfile.write(content)

    def do_CONNECT(self):
        with self.lock:
            type(self).seen.append(("CONNECT", self.path))
        self.reply(403, b"TLS CONNECT rejected in HTTP-only fixture")

    def do_GET(self):
        parsed = urlsplit(self.path)
        host = (parsed.hostname or self.headers.get("Host") or "").lower()
        path = parsed.path or "/"
        with self.lock:
            type(self).seen.append((host, path))
        if host == "allowed.test" and path == "/redirect":
            self.reply(302, headers=(("Location", "http://allowed.test/start"),))
        elif host == "allowed.test" and path == "/offsite":
            self.reply(302, headers=(("Location", "http://blocked.test/offsite"),))
        elif host == "allowed.test" and path == "/start":
            html = b"""<!doctype html><html><head><title>Controlled Browser Fixture</title></head>
<body><h1>Allowed Fixture</h1><p>Testing proxy navigation and blocked subresources.</p>
<img src="http://blocked.test/forbidden-image.png" width="1" height="1">
<iframe src="http://blocked.test/forbidden-frame" width="1" height="1"></iframe>
<script>fetch('http://blocked.test/forbidden-fetch').catch(()=>{});</script>
<p>End of controlled test fixture.</p>
</body></html>"""
            self.reply(200, html, (("Content-Type", "text/html"),))
        elif host == "allowed.test":
            self.reply(200, b"<html><body>ok</body></html>")
        else:
            self.reply(403, b"Denied by local E2E proxy policy")


@pytest.fixture
def egress_proxy(monkeypatch):
    ProxyFixture.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), ProxyFixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # Local test has deliberately fake DNS hosts; production URL policy is
    # not weakened and this stub exists for the duration of this fixture only.
    original = URLPolicy.validate
    def fixture_admission(self, url, *, resolve_dns=True):
        parsed = urlsplit(url)
        if parsed.scheme == "http" and parsed.hostname == "allowed.test":
            return url
        raise URLPolicyError("Non-allowlisted E2E host")
    monkeypatch.setattr(URLPolicy, "validate", fixture_admission)
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def test_real_chrome_redirects_subresources_and_denial(egress_proxy, monkeypatch):
    import browser_engine
    # The GitHub runner's local ChromeDriver or Selenium Manager must work;
    # this test is not marked optional and should fail CI if Chrome is missing.
    monkeypatch.setattr(browser_engine, "WEBDRIVER_MANAGER_AVAILABLE", False)
    config = BrowserConfig(
        allowed_domains=["allowed.test"], headless=True, max_retries=1,
        page_load_timeout=15, implicit_wait=1, request_delay=0,
        strict_browser_network=True, egress_proxy_url=egress_proxy)
    browser = browser_engine.SeleniumEngine(
        config, use_undetected=False, lazy_init=True)
    try:
        result = browser.fetch_page("http://allowed.test/redirect")
        assert result.success, result.error
        assert result.final_url == "http://allowed.test/start"
        assert "Allowed Fixture" in result.html
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            with ProxyFixture.lock:
                hits = list(ProxyFixture.seen)
            if any(h[0] == "blocked.test" for h in hits):
                break
            time.sleep(0.1)
        assert ("allowed.test", "/redirect") in hits, hits
        assert ("allowed.test", "/start") in hits, hits
        assert any(host == "blocked.test" for host, path in hits), hits
        prior = len(hits)
        result = browser.fetch_page("http://blocked.test/")
        assert not result.success
        with ProxyFixture.lock:
            assert len(ProxyFixture.seen) >= prior
        # A cross-domain redirect is denied by the local proxy and then
        # rejected by the Python post-navigation check; never treat it as
        # proof of network-namespace isolation.
        blocked = browser.fetch_page("http://allowed.test/offsite")
        assert not blocked.success
    finally:
        browser.close()
