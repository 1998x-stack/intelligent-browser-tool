from pathlib import Path

import pytest

from config import Config
from url_queue import URLQueue


@pytest.fixture
def frontier(tmp_path: Path) -> URLQueue:
    config = Config()
    config.browser.allowed_domains = ["example.com"]
    config.crawl.max_depth = 2
    return URLQueue(config)


def test_enqueue_rejects_domain_confusion(frontier):
    assert frontier.add("https://example.com/page")
    assert frontier.add("https://sub.example.com/other")
    assert not frontier.add("https://example.com.attacker.test/page")
    assert not frontier.add("http://127.0.0.1/private")


def test_leased_success_updates_processed(frontier):
    assert frontier.add("https://example.com/page")
    item = frontier.get_next()
    assert item is not None
    assert not frontier.is_processed(item.url)
    frontier.mark_processed(item.url, success=True)
    assert frontier.is_processed(item.url)
    assert frontier.get_stats().total_processed == 1
    assert frontier.get_stats().total_failed == 0


def test_leased_failure_is_accounted(frontier):
    frontier.add("https://example.com/page")
    item = frontier.get_next()
    frontier.mark_processed(item.url, success=False)
    assert frontier.get_stats().total_processed == 1
    assert frontier.get_stats().total_failed == 1
    assert frontier.get_failed_urls() == [(item.url, 1)]


def test_double_ack_does_not_corrupt_stats(frontier):
    frontier.add("https://example.com/page")
    item = frontier.get_next()
    frontier.mark_processed(item.url)
    with pytest.raises(ValueError, match="not leased"):
        frontier.mark_processed(item.url)
    assert frontier.get_stats().total_processed == 1


def test_inflight_item_requeues_after_restore(frontier):
    frontier.add("https://example.com/page")
    item = frontier.get_next()
    snapshot = frontier.snapshot()
    recovered = URLQueue(frontier.config)
    recovered.restore(snapshot)
    assert recovered.size() == 1
    assert recovered.get_next().url == item.url


def test_restored_snapshot_checks_policy(frontier):
    snapshot = frontier.snapshot()
    snapshot["heap"] = [{
        "url": "https://example.com.evil.test/path",
        "priority": 1, "depth": 0, "timestamp": 0,
        "parent_url": "", "context": {}
    }]
    recovered = URLQueue(frontier.config)
    with pytest.raises(ValueError, match="Rejected checkpoint URL"):
        recovered.restore(snapshot)


def test_persistent_state_is_roundtrippable(frontier, tmp_path):
    frontier.add("https://example.com/page")
    path = tmp_path / "state" / "frontier.json"
    assert frontier.save_state(path)
    assert path.is_file()
    recovered = URLQueue(frontier.config)
    assert recovered.load_state(path)
    assert recovered.get_next().url == "https://example.com/page"
