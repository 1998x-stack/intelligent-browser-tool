"""Offline regression for the second V0.1 batch (no external HTTP)."""
import socket
import sqlite3
import time

import pytest
from config import Config, BrowserConfig
from durable_queue import DurableURLQueue
from frontier_state import FrontierState
from url_policy import URLPolicy, URLPolicyError


def config_for(tmp_path):
    cfg = Config()
    cfg.storage.base_dir = tmp_path
    cfg.browser.allowed_domains = ["example.com"]
    cfg.crawl.max_depth = 2
    return cfg


def test_durable_adapter_restart_and_context(tmp_path):
    cfg = config_for(tmp_path)
    q = DurableURLQueue(cfg, start_url="https://example.com/", intent="study")
    assert q.add("https://example.com/a", priority=1,
                 context={"reason": "test"}, parent_url="https://example.com/")
    assert not q.add("https://example.com/a#top")
    assert not q.add("https://example.com.evil.test/")
    assert not q.add("https://example.com/deep", depth=3)
    item = q.get_next()
    assert item.context["reason"] == "test"
    assert item.parent_url == "https://example.com/"
    q.mark_processed(item.url, success=True)
    assert q.counts()["completed"] == 1
    db_path = q.path
    q.close()
    resumed = DurableURLQueue(cfg, start_url="https://example.com/", intent="study")
    assert resumed.path == db_path
    assert resumed.has_entries()
    assert not resumed.has_next()
    assert not resumed.add("https://example.com/a")
    resumed.close()


def test_lease_fencing_prevents_stale_commit(tmp_path):
    with FrontierState(tmp_path / "f.db", URLPolicy(("example.com",)),
                       lease_seconds=5) as q:
        q.enqueue("https://example.com/a")
        first = q.lease(now=100)
        assert q.recover_expired(now=106) == 1
        second = q.lease(now=106)
        assert first["lease_token"] != second["lease_token"]
        with pytest.raises(ValueError):
            q.finish(first["url"], lease_token=first["lease_token"], state="completed")
        q.finish(second["url"], lease_token=second["lease_token"], state="completed")
        assert q.counts()["completed"] == 1


def test_migrate_old_v01_frontier_schema(tmp_path):
    path = tmp_path / "v01.db"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE frontier (
            url TEXT PRIMARY KEY, priority INTEGER NOT NULL, depth INTEGER NOT NULL,
            state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            leased_until REAL, available_at REAL NOT NULL DEFAULT 0,
            last_error TEXT, created_at REAL NOT NULL)""")
        db.execute("INSERT INTO frontier VALUES(?,1,0,'queued',0,NULL,0,NULL,1)",
                   ("https://example.com/a",))
    with FrontierState(path, URLPolicy(("example.com",))) as q:
        record = q.lease()
        assert record["url"] == "https://example.com/a"
        assert record["context"] == {}
        q.finish(record["url"], lease_token=record["lease_token"], state="completed")


def test_redirect_rechecks_target_before_following(monkeypatch):
    from browser_engine import RequestsEngine
    engine = RequestsEngine(BrowserConfig(allowed_domains=["example.com"]))
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 443))])
    calls = []
    class FakeResponse:
        status_code = 302
        headers = {"Location": "http://127.0.0.1/admin"}
        def close(self):
            pass
    def fake_get(url, **kwargs):
        calls.append(url)
        assert kwargs["allow_redirects"] is False
        return FakeResponse()
    monkeypatch.setattr(engine.session, "get", fake_get)
    with pytest.raises(URLPolicyError):
        engine._get_checked("https://example.com", timeout=2)
    assert calls == ["https://example.com"]
    engine.close()


def test_crawler_loop_uses_durable_queue(tmp_path, monkeypatch):
    import crawler
    cfg = config_for(tmp_path)
    c = crawler.WebCrawler.__new__(crawler.WebCrawler)
    c.crawl_config = crawler.CrawlConfig(
        start_url="https://example.com/", intent="offline",
        output_dir=str(tmp_path), max_pages=3, durable_frontier=True,
        use_selenium=False, use_search_seeds=False)
    c.url_queue = DurableURLQueue(cfg, start_url=c.crawl_config.start_url,
                                  intent=c.crawl_config.intent)
    c.url_queue.add("https://example.com/", priority=1)
    class Progress:
        def update(self, *args):
            pass
    c.progress = Progress()
    c.results = []
    def process(item):
        if item.depth == 0:
            return crawler.PageResult(url=item.url, depth=item.depth,
                priority_urls=[{"url":"https://example.com/child","priority":2}])
        return crawler.PageResult(url=item.url, depth=item.depth)
    c._process_page = process
    monkeypatch.setattr(crawler.time, "sleep", lambda _: None)
    c._crawl_loop()
    assert c.url_queue.counts() == {"completed": 2}
    c.url_queue.close()
