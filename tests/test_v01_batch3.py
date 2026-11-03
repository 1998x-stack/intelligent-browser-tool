"""Local-only regression: HTTP routes, navigation policy, resume and benchmark."""
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from config import BrowserConfig
from frontier_state import FrontierState
from network_policy import BrowserNetworkPolicy, NetworkBoundaryError
from url_policy import URLPolicy, URLPolicyError


class FixtureHandler(BaseHTTPRequestHandler):
    hits = {}

    def log_message(self, *_):
        pass

    def do_GET(self):
        cls = type(self)
        cls.hits[self.path] = cls.hits.get(self.path, 0) + 1
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
        elif self.path == "/bad-redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.2/internal")
            self.end_headers()
        elif self.path == "/flaky" and cls.hits[self.path] == 1:
            self.send_response(503)
            self.end_headers()
        elif self.path == "/slow":
            time.sleep(0.2)
            try:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"slow")
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>fixture page content</body></html>")


@pytest.fixture
def local_http(monkeypatch):
    """Only tests relax loopback; no production bypass switches are exposed."""
    FixtureHandler.hits = {}
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def fixture_only_validate(self, url, *, resolve_dns=True):
        if url == base or url.startswith(base + "/"):
            return url
        raise URLPolicyError("Not on fixture server")

    monkeypatch.setattr(URLPolicy, "validate", fixture_only_validate)
    yield base
    server.shutdown()
    server.server_close()
    thread.join(timeout=1)


def test_local_http_redirect_and_retry(local_http):
    from browser_engine import RequestsEngine
    cfg = BrowserConfig(allowed_domains=["127.0.0.1"], max_retries=2,
                        retry_delay=0, request_delay=0, page_load_timeout=2)
    engine = RequestsEngine(cfg)
    result = engine.fetch_page(local_http + "/redirect")
    assert result.success and result.final_url == local_http + "/ok"
    assert FixtureHandler.hits["/redirect"] == 1
    assert FixtureHandler.hits["/ok"] == 1
    result = engine.fetch_page(local_http + "/flaky")
    assert result.success
    assert FixtureHandler.hits["/flaky"] >= 2
    engine.close()


def test_local_http_redirect_does_not_contact_disallowed_target(local_http):
    from browser_engine import RequestsEngine
    cfg = BrowserConfig(allowed_domains=["127.0.0.1"], max_retries=1,
                        request_delay=0, page_load_timeout=1)
    engine = RequestsEngine(cfg)
    result = engine.fetch_page(local_http + "/bad-redirect")
    assert not result.success
    assert FixtureHandler.hits["/bad-redirect"] == 1
    engine.close()


def test_local_http_timeout(local_http):
    from browser_engine import RequestsEngine
    cfg = BrowserConfig(allowed_domains=["127.0.0.1"], max_retries=1,
                        request_delay=0, retry_delay=0, page_load_timeout=0.04)
    engine = RequestsEngine(cfg)
    result = engine.fetch_page(local_http + "/slow")
    assert not result.success
    engine.close()


def test_browser_strict_mode_requires_proxy_and_allowlist():
    with pytest.raises(NetworkBoundaryError):
        BrowserNetworkPolicy(("example.com",), strict=True)
    with pytest.raises(NetworkBoundaryError):
        BrowserNetworkPolicy((), strict=True, proxy_url="http://proxy:3128")
    with pytest.raises(NetworkBoundaryError):
        BrowserNetworkPolicy(("example.com",), strict=True, proxy_url="socks5://proxy:1080")
    class Options:
        def __init__(self):
            self.args = []
        def add_argument(self, value):
            self.args.append(value)
    options = Options()
    policy = BrowserNetworkPolicy(("example.com",), strict=True,
                                  proxy_url="http://proxy:3128")
    policy.install_chrome_proxy(options)
    assert "--proxy-server=http://proxy:3128" in options.args
    with pytest.raises(NetworkBoundaryError):
        policy.check_chrome_arguments(["--proxy-server=http://another:8888"])


def test_resume_results_survive_restart_without_duplicates(tmp_path):
    path = tmp_path / "frontier.db"
    policy = URLPolicy(("example.com",))
    url = "https://example.com/page"
    with FrontierState(path, policy) as store:
        assert store.enqueue(url)
        item = store.lease()
        store.finish(url, lease_token=item["lease_token"], state="completed",
                     result={"url": url, "success": True, "summary": "first"})
        assert store.list_results() == [{"url": url, "success": True, "summary": "first"}]
    with FrontierState(path, policy) as restored:
        assert restored.counts()["completed"] == 1
        assert len(restored.list_results()) == 1
        assert restored.list_results()[0]["summary"] == "first"
        assert not restored.enqueue(url)


def test_stale_worker_cannot_update_results(tmp_path):
    with FrontierState(tmp_path / "frontier.db", URLPolicy(("example.com",)),
                       lease_seconds=5) as store:
        url = "https://example.com/page"
        store.enqueue(url)
        first = store.lease(now=100)
        second = store.lease(now=106)
        with pytest.raises(ValueError):
            store.finish(url, lease_token=first["lease_token"], state="completed",
                         result={"url": url, "summary": "stale"})
        store.finish(url, lease_token=second["lease_token"], state="completed",
                     result={"url": url, "summary": "accepted"})
        assert store.list_results() == [{"url": url, "summary": "accepted"}]


def test_crawler_report_hydrates_prior_pages(tmp_path):
    import crawler
    from durable_queue import DurableURLQueue
    cfg = crawler.Config()
    cfg.storage.base_dir = tmp_path
    cfg.browser.allowed_domains = ["example.com"]
    q = DurableURLQueue(cfg, start_url="https://example.com/", intent="test")
    first_url = "https://example.com/first"
    q.add(first_url)
    claim = q.get_next()
    q.mark_processed(first_url, result={"url":first_url,"summary":"saved"},
                     success=True)
    c = crawler.WebCrawler.__new__(crawler.WebCrawler)
    c.url_queue = q
    c.results = []
    c._load_durable_results()
    assert len(c.results) == 1
    assert c.results[0].summary == "saved"
    q.close()


def test_frontier_benchmark_agrees_for_small_fixture():
    from benchmarks.frontier_compare import run_comparison
    output = run_comparison(20)
    assert output["order_equal"]
    assert output["legacy"]["completed"] == 20
    assert output["durable"]["completed"] == 20
    assert output["legacy"]["duplicates_rejected"] == 10
    assert output["durable"]["duplicates_rejected"] == 10
