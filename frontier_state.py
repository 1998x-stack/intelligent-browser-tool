"""Transactional SQLite URL frontier for resumable, at-least-once crawl jobs."""
import sqlite3
import time
from pathlib import Path
from urllib.parse import urldefrag

from url_policy import URLPolicy, URLPolicyError


class FrontierState:
    def __init__(self, path: str | Path, policy: URLPolicy, *, lease_seconds: int = 120):
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        self.policy = policy
        self.lease_seconds = lease_seconds
        self.db = sqlite3.connect(str(path), timeout=15, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=15000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS frontier (
            url TEXT PRIMARY KEY,
            priority INTEGER NOT NULL,
            depth INTEGER NOT NULL,
            state TEXT NOT NULL CHECK(state IN
                ('queued','leased','completed','failed','blocked')),
            attempts INTEGER NOT NULL DEFAULT 0,
            leased_until REAL,
            available_at REAL NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at REAL NOT NULL
        )""")
        self.db.execute("CREATE INDEX IF NOT EXISTS frontier_schedule ON frontier(state, available_at, priority, depth)")

    def enqueue(self, url: str, priority: int = 2, depth: int = 0) -> bool:
        self.policy.validate(url, resolve_dns=False)
        if not 1 <= priority <= 3 or depth < 0:
            raise ValueError("Invalid priority or depth")
        url = urldefrag(url)[0]
        cursor = self.db.execute(
            """INSERT OR IGNORE INTO frontier(url,priority,depth,state,created_at)
               VALUES(?, ?, ?, 'queued', ?)""",
            (url, priority, depth, time.time()))
        return cursor.rowcount == 1

    def recover_expired(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        with self.db:
            result = self.db.execute(
                """UPDATE frontier SET state='queued', leased_until=NULL,
                   available_at=? WHERE state='leased' AND leased_until <= ?""",
                (now, now))
        return result.rowcount

    def lease(self, now: float | None = None) -> dict | None:
        now = time.time() if now is None else now
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute(
                """UPDATE frontier SET state='queued', leased_until=NULL, available_at=?
                   WHERE state='leased' AND leased_until <= ?""",
                (now, now))
            row = self.db.execute(
                """SELECT url,priority,depth,attempts FROM frontier
                   WHERE state='queued' AND available_at <= ?
                   ORDER BY priority,depth,created_at LIMIT 1""", (now,)
            ).fetchone()
            if row is not None:
                self.db.execute(
                    """UPDATE frontier SET state='leased', attempts=attempts+1,
                       leased_until=? WHERE url=? AND state='queued'""",
                    (now + self.lease_seconds, row["url"]))
            self.db.execute("COMMIT")
            return dict(row) if row else None
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def finish(self, url: str, *, state: str, error: str | None = None,
               retry_delay: float = 0) -> None:
        if state not in ("completed", "failed", "blocked", "queued"):
            raise ValueError("Unsupported final state")
        if retry_delay < 0:
            raise ValueError("retry_delay must be nonnegative")
        result = self.db.execute(
            """UPDATE frontier SET state=?, leased_until=NULL, last_error=?,
               available_at=? WHERE url=? AND state='leased'""",
            (state, error, time.time() + retry_delay, urldefrag(url)[0]))
        if result.rowcount != 1:
            raise ValueError("URL is not leased")

    def counts(self) -> dict[str, int]:
        return {row["state"]: row["n"] for row in self.db.execute(
            "SELECT state, COUNT(*) AS n FROM frontier GROUP BY state")}

    def close(self) -> None:
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
