"""V0.1.4 hardening regression tests: tenancy, batching, retention, crash recovery."""
import os
import sqlite3
import time

import pytest

from config import Config
from durable_queue import DurableURLQueue
from frontier_state import FrontierState
from url_policy import URLPolicy


def config_for(tmp):
    cfg = Config()
    cfg.storage.base_dir = tmp
    cfg.browser.allowed_domains = ["example.com"]
    cfg.crawl.max_depth = 4
    return cfg


def test_namespace_and_task_id_partition(tmp_path):
    cfg = config_for(tmp_path)
    a = DurableURLQueue(cfg, start_url="https://example.com/",
                        intent="research", task_namespace="alice", task_id="session1")
    assert a.add("https://example.com/private-a")
    path_a = a.path
    a.close()
    b = DurableURLQueue(cfg, start_url="https://example.com/",
                        intent="research", task_namespace="bob", task_id="session1")
    assert b.path != path_a
    assert not b.has_entries()
    b.close()
    restored = DurableURLQueue(cfg, start_url="https://example.com/",
                               intent="research", task_namespace="alice", task_id="session1")
    assert restored.path == path_a
    assert restored.has_entries()
    restored.close()


def test_identity_mismatch_refuses_existing_db(tmp_path):
    cfg = config_for(tmp_path)
    q = DurableURLQueue(cfg, start_url="https://example.com/a", intent="task",
                        task_namespace="alice", task_id="fixed")
    q.add("https://example.com/a")
    q.close()
    with pytest.raises(ValueError, match="identity|policy"):
        DurableURLQueue(cfg, start_url="https://example.com/b", intent="task",
                        task_namespace="alice", task_id="fixed")
    cfg.browser.allowed_domains = ["example.org"]
    with pytest.raises(ValueError, match="identity|policy"):
        DurableURLQueue(cfg, start_url="https://example.com/a", intent="task",
                        task_namespace="alice", task_id="fixed")


def test_no_silent_adoption_of_legacy_database(tmp_path):
    path = tmp_path / "legacy.db"
    with FrontierState(path, URLPolicy(("example.com",))) as q:
        q.enqueue("https://example.com/secret")
    with FrontierState(path, URLPolicy(("example.com",))) as q:
        with pytest.raises(ValueError, match="Legacy Frontier"):
            q.assert_identity({"namespace":"bob"})


def test_bulk_order_is_same_as_legacy(tmp_path):
    cfg = config_for(tmp_path)
    data = [{"url":f"https://example.com/entry-{i:03d}",
             "priority": i % 3+1, "depth":i%4, "context":{"n": i}}
            for i in range(100)]
    q = DurableURLQueue(cfg, start_url="https://example.com/", intent="batch")
    assert q.add_batch(data) == 100
    assert q.add_batch(data[:20]) == 0
    seen = []
    while q.has_next():
        item = q.get_next()
        seen.append((item.url, item.priority, item.depth))
        q.mark_processed(item.url)
    assert len(seen) == 100
    assert seen == sorted(seen, key=lambda item:
                          (item[1], item[2], int(item[0].rsplit("-", 1)[-1])))
    assert q.counts()["completed"] == 100
    q.close()


def test_atomic_bulk_validation_rollback(tmp_path):
    with FrontierState(tmp_path / "batch.db", URLPolicy(("example.com",))) as q:
        with pytest.raises(ValueError):
            q.enqueue_many([
                {"url":"https://example.com/good"},
                {"url":"https://example.com/bad", "priority":99}
            ])
        assert q.counts() == {}


def test_prune_only_old_terminal_rows_and_results(tmp_path):
    with FrontierState(tmp_path / "prune.db", URLPolicy(("example.com",))) as q:
        for name in ("finished","queued","leased"):
            q.enqueue(f"https://example.com/{name}")
        first=q.lease()
        assert first["url"] == "https://example.com/finished"
        q.finish(first["url"], lease_token=first["lease_token"],
                 state="completed", result={"url":first["url"], "summary":"old"})
        second=q.lease()
        assert second["url"] == "https://example.com/queued"
        q.finish(second["url"], lease_token=second["lease_token"],
                 state="queued", retry_delay=600)
        leased=q.lease()
        assert leased["url"] == "https://example.com/leased"
        assert q.prune_terminal(older_than_seconds=1, now=time.time()+10) == 1
        assert q.list_results() == []
        assert q.counts()["queued"] == 1
        assert q.counts()["leased"] == 1
        with pytest.raises(ValueError):
            q.prune_terminal(older_than_seconds=0)


def test_crash_restart_lease_fencing_after_recovery(tmp_path):
    path=tmp_path / "recover.db"
    policy=URLPolicy(("example.com",))
    with FrontierState(path, policy, lease_seconds=5) as q:
        q.enqueue("https://example.com/a")
        stale=q.lease(now=100)
    with FrontierState(path, policy, lease_seconds=5) as q:
        assert q.recover_expired(now=106) == 1
        current=q.lease(now=106)
        assert stale["lease_token"] != current["lease_token"]
        with pytest.raises(ValueError):
            q.finish(stale["url"], lease_token=stale["lease_token"],
                     state="completed", result={"summary":"wrong"})
        q.finish(current["url"], lease_token=current["lease_token"],
                 state="completed", result={"summary":"right"})
        assert q.list_results() == [{"summary":"right"}]


def test_scope_input_validation(tmp_path):
    cfg=config_for(tmp_path)
    with pytest.raises(ValueError):
        DurableURLQueue(cfg, start_url="https://example.com/", intent="x",
                        task_namespace="")
    with pytest.raises(ValueError):
        DurableURLQueue(cfg, start_url="https://example.com/", intent="x",
                        task_id=" ")
