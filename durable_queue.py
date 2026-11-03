"""Compatibility adapter: persistent SQLite Frontier with the URLQueue API.

Opt in via CrawlConfig(durable_frontier=True). No claims of exactly-once output:
leases are at-least-once and consumers must persist results idempotently.
"""
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urljoin
from typing import Iterable

from loguru import logger
from frontier_state import FrontierState
from url_policy import URLPolicy, URLPolicyError
from url_queue import QueueItem, URLFilter, URLNormalizer


class DurableURLQueue:
    def __init__(self, config, *, start_url: str, intent: str,
                 max_attempts: int = 3, lease_seconds: int = 600,
                 task_namespace: str = "local", task_id: str | None = None):
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.config = config
        self.max_attempts = max_attempts
        self._filter = URLFilter(config)
        self._normalizer = URLNormalizer()
        self.policy = URLPolicy(tuple(config.browser.allowed_domains))
        # Explicit namespace is a logical partition, NOT an authorization boundary.
        if not isinstance(task_namespace, str) or not 1 <= len(task_namespace) <= 128 or not task_namespace.strip():
            raise ValueError("task_namespace must be 1..128 non-whitespace characters")
        if task_id is not None and (not isinstance(task_id, str) or not 1 <= len(task_id) <= 128 or not task_id.strip()):
            raise ValueError("task_id must be 1..128 non-whitespace characters")
        identity = {
            "namespace": task_namespace,
            "task_id": task_id,
            "start_url": start_url,
            "intent": intent,
            "allowed_domains": sorted(self.policy.allowed_domains),
            "max_depth": config.crawl.max_depth,
        }
        fingerprint = json.dumps(identity, ensure_ascii=False, sort_keys=True)
        namespace_hash = hashlib.sha256(task_namespace.encode("utf-8")).hexdigest()[:16]
        task_hash = hashlib.sha256(
            (task_id if task_id is not None else fingerprint).encode("utf-8")
        ).hexdigest()[:24]
        path = (Path(config.storage.base_dir) / "state" /
                namespace_hash / f"frontier-{task_hash}.sqlite3")
        self.state = FrontierState(path, self.policy, lease_seconds=lease_seconds)
        try:
            self.state.assert_identity(identity)
        except BaseException:
            self.state.close()
            raise
        self.path = path
        self.task_namespace = task_namespace
        self.task_id = task_id
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

    def add_batch(self, urls: Iterable[dict | str], default_priority: int = 2,
                  default_depth: int = 0, parent_url: str = "") -> int:
        accepted = []
        for item in urls:
            data = {"url": item} if isinstance(item, str) else item
            candidate = self._normalizer.normalize(data.get("url", ""), parent_url)
            priority = data.get("priority", default_priority)
            depth = data.get("depth", default_depth)
            if not candidate or depth > self.config.crawl.max_depth:
                continue
            if not self._filter.is_allowed(candidate)[0]:
                continue
            accepted.append({"url": candidate, "priority": int(priority),
                             "depth": depth, "parent_url": parent_url,
                             "context": data.get("context") or {}})
        return self.state.enqueue_many(accepted)

    def prune_terminal(self, *, older_than_seconds: float, now: float | None = None) -> int:
        return self.state.prune_terminal(older_than_seconds=older_than_seconds, now=now)

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
