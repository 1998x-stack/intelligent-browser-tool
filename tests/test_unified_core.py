"""Unified release gates: atomic graph persistence and recovery under failures."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import time

import pytest
from config import Config
from durable_queue import DurableURLQueue
from frontier_state import FrontierState
from url_policy import URLPolicy


def configured(tmp_path):
    config = Config()
    config.browser.allowed_domains = ["example.com"]
    config.storage.base_dir = tmp_path
    config.crawl.max_depth = 3
    return config


def test_result_and_children_survive_restart_together(tmp_path):
    conf = configured(tmp_path)
    parent = "https://example.com/parent"
    child = "https://example.com/child"
    queue = DurableURLQueue(conf, start_url=parent, intent="atomic",
                            task_namespace="release", task_id="test1")
    assert queue.add(parent)
    leased = queue.get_next()
    queue.mark_processed(parent, success=True,
        result={"url":parent,"summary":"committed"},
        discovered=[{"url":child,"priority":1,"depth":1,
                     "parent_url":parent,"context":{"reason":"linked"}}])
    queue.close()
    resumed = DurableURLQueue(conf, start_url=parent, intent="atomic",
                               task_namespace="release", task_id="test1")
    assert resumed.list_results() == [{"url":parent,"summary":"committed"}]
    leased = resumed.get_next()
    assert leased.url == child
    assert leased.parent_url == parent
    assert leased.context == {"reason":"linked"}
    resumed.mark_processed(child, result={"url":child}, success=True)
    assert resumed.counts()["completed"] == 2
    resumed.close()


def test_fault_injection_rolls_back_state_results_and_children(tmp_path):
    conf = configured(tmp_path)
    parent, child = "https://example.com/p", "https://example.com/c"
    queue = DurableURLQueue(conf, start_url=parent, intent="transaction", task_id="rollback")
    assert queue.add(parent)
    leased = queue.get_next()
    # Inject a database exception after updating the lease but before
    # writing page_results and discovered links.
    queue.state.db.execute("""
        CREATE TRIGGER reject_page_result BEFORE INSERT ON page_results
        BEGIN SELECT RAISE(ABORT, 'injected_failure'); END
    """)
    with pytest.raises(sqlite3.IntegrityError, match="injected_failure"):
        queue.mark_processed(parent, success=True, result={"url":parent},
            discovered=[{"url":child,"priority":1,"depth":1,"parent_url":parent}])
    assert queue.state.counts()["leased"] == 1
    assert queue.state.list_results() == []
    assert parent in queue._active
    assert not queue.state.db.execute(
        "SELECT 1 FROM frontier WHERE url=?", (child,)).fetchone()
    queue.state.db.execute("DROP TRIGGER reject_page_result")
    queue.mark_processed(parent, success=True, result={"url":parent},
        discovered=[{"url":child,"priority":1,"depth":1,"parent_url":parent}])
    assert queue.state.counts()["completed"] == 1
    assert queue.state.counts()["queued"] == 1
    queue.close()


def test_invalid_child_aborts_commit_without_state_change(tmp_path):
    with FrontierState(tmp_path/"fail.db",URLPolicy(("example.com",))) as state:
        parent = "https://example.com/p"
        state.enqueue(parent)
        claim = state.lease()
        with pytest.raises(ValueError, match="priority"):
            state.finish(parent,lease_token=claim["lease_token"],state="completed",
                         result={"url":parent},discovered=[
                             {"url":"https://example.com/c","priority":True,"depth":1}])
        assert state.counts()["leased"] == 1
        assert state.list_results() == []
        state.finish(parent,lease_token=claim["lease_token"],state="completed",
                     result={"url":parent})
        assert state.counts()["completed"] == 1


def test_parallel_sqlite_workers_never_lease_same_url(tmp_path):
    path = tmp_path/"parallel.db"
    policy = URLPolicy(("example.com",))
    with FrontierState(path,policy,lease_seconds=30) as seed:
        assert seed.enqueue_many([
            {"url":f"https://example.com/{i:03d}"} for i in range(60)]) == 60

    def worker(_):
        visited = []
        with FrontierState(path,policy,lease_seconds=30) as connection:
            for _ in range(15):
                claim=connection.lease()
                assert claim is not None
                visited.append(claim["url"])
                connection.finish(claim["url"],lease_token=claim["lease_token"],
                                  state="completed",result={"url":claim["url"]})
        return visited

    with ThreadPoolExecutor(max_workers=4) as pool:
        groups = list(pool.map(worker,range(4)))
    combined = [item for group in groups for item in group]
    assert len(combined) == len(set(combined)) == 60
    with FrontierState(path,policy) as verify:
        assert verify.counts()["completed"] == 60
        assert len(verify.list_results()) == 60


def test_durable_adapter_rejects_malformed_batch_priority(tmp_path):
    q=DurableURLQueue(configured(tmp_path),start_url="https://example.com/",
                      intent="type-regression",task_id="priority")
    with pytest.raises(ValueError):
        q.add_batch([{"url":"https://example.com/b","priority":True}])
    assert q.counts() == {}
    q.close()
