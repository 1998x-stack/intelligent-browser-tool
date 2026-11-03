"""Compatibility adapter: persistent SQLite Frontier with the URLQueue API.

Opt in via CrawlConfig(durable_frontier=True). No claims of exactly-once output:
leases are at-least-once and consumers must persist results idempotently.
"""
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urljoin

from loguru import logger
from frontier_state import FrontierState
from url_policy import URLPolicy, URLPolicyError
from url_queue import QueueItem, URLFilter, URLNormalizer


class DurableURLQueue:
    def __init__(self, config, *, start_url: str, intent: str,
                 max_attempts: int = 3, lease_seconds: int = 600):
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.config = config
        self.max_attempts = max_attempts
        self._filter = URLFilter(config)
        self._normalizer = URLNormalizer()
        self.policy = URLPolicy(tuple(config.browser.allowed_domains))
        # Avoid mixing unrelated goals in one saved Frontier DB.
        identity = json.dumps([start_url, intent], ensure_ascii=False)
        task_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        path = Path(config.storage.base_dir) / "state" / f"frontier-{task_hash}.sqlite3"
        self.state = FrontierState(path, self.policy, lease_seconds=lease_seconds)
        self.path = path
        self._active = {}
        self._attempts = {}

    def add(self, url: str, priority: int = 2, depth: int = 0,
            parent_url: str = "", context: dict | None = None) -> bool:
        candidate = self._normalizer.normalize(url, parent_url)
        if depth > self.config.crawl.max_depth or not candidate:
            return False
        allowed, reason = self._filter.is_allowed(candidate)
        if not allowed:
            logger.debug("Frontier skipped %s: %s", candidate, reason)
            return False
        try:
            return self.state.enqueue(candidate, priority=int(priority), depth=depth,
                                      parent_url=parent_url, context=context)
        except (ValueError, URLPolicyError):
            return False

    def has_entries(self) -> bool:
        return self.state.has_entries()

    def has_next(self) -> bool:
        return self.state.has_ready()

    def get_next(self) -> QueueItem | None:
        record = self.state.lease()
        if record is None:
            return None
        self._active[record["url"]] = record["lease_token"]
        self._attempts[record["url"]] = record["attempts"]
        return QueueItem(priority=record["priority"], depth=record["depth"],
                         timestamp=time.time(), url=record["url"],
                         parent_url=record["parent_url"], context=record["context"])

    def mark_processed(self, url: str, success: bool = True,
                       error: str | None = None, result: dict | None = None) -> None:
        token = self._active.pop(url)
        attempts = self._attempts.pop(url)
        if success:
            state, delay = "completed", 0
        elif attempts < self.max_attempts:
            state, delay = "queued", min(60.0, 2.0 ** (attempts - 1))
        else:
            state, delay = "failed", 0
        self.state.finish(url, lease_token=token, state=state,
                          error=error, retry_delay=delay, result=result)

    def close(self):
        self.state.close()

    def counts(self) -> dict[str, int]:
        return self.state.counts()

    def list_results(self) -> list[dict]:
        return self.state.list_results()
