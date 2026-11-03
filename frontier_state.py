"""Transactional, resumable SQLite URL frontier.

SQLite WAL provides atomic leasing for local workers. Task completion is fenced
by a unique lease token, so expired workers cannot overwrite newer attempts.
At-least-once delivery requires idempotent result writes by the caller.
"""
import json
import sqlite3
import time
import uuid
from pathlib import Path
from urllib.parse import urldefrag
from url_policy import URLPolicy


class FrontierState:
    def __init__(self, path: str | Path, policy: URLPolicy, *, lease_seconds: int = 120):
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        self.policy = policy
        self.lease_seconds = lease_seconds
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
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
            created_at REAL NOT NULL,
            parent_url TEXT NOT NULL DEFAULT '',
            context_json TEXT NOT NULL DEFAULT '{}',
            lease_token TEXT
        )""")
        # In-place migration from the first V0.1 SQLite schema.
        columns = {row["name"] for row in self.db.execute("PRAGMA table_info(frontier)")}
        for name, spec in {
            "parent_url": "TEXT NOT NULL DEFAULT ''",
            "context_json": "TEXT NOT NULL DEFAULT '{}'",
            "lease_token": "TEXT",
        }.items():
            if name not in columns:
                self.db.execute(f"ALTER TABLE frontier ADD COLUMN {name} {spec}")
        self.db.execute("""CREATE INDEX IF NOT EXISTS frontier_schedule
                           ON frontier(state, available_at, priority, depth)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS page_results (
            url TEXT PRIMARY KEY REFERENCES frontier(url),
            result_json TEXT NOT NULL,
            updated_at REAL NOT NULL
        )""")

    def enqueue(self, url: str, priority: int = 2, depth: int = 0,
                *, parent_url: str = "", context: dict | None = None) -> bool:
        self.policy.validate(url, resolve_dns=False)
        if not isinstance(priority, int) or not 1 <= priority <= 3 or depth < 0:
            raise ValueError("Invalid priority or depth")
        url = urldefrag(url)[0]
        payload = json.dumps(context or {}, ensure_ascii=False, default=str)
        result = self.db.execute(
            """INSERT OR IGNORE INTO frontier
               (url,priority,depth,state,created_at,parent_url,context_json)
               VALUES(?, ?, ?, 'queued', ?, ?, ?)""",
            (url, priority, depth, time.time(), parent_url, payload))
        return result.rowcount == 1

    def has_entries(self) -> bool:
        return self.db.execute("SELECT 1 FROM frontier LIMIT 1").fetchone() is not None

    def has_ready(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return self.db.execute(
            """SELECT 1 FROM frontier
               WHERE (state='queued' AND available_at <= ?)
                  OR (state='leased' AND leased_until <= ?) LIMIT 1""",
            (now, now)).fetchone() is not None

    def recover_expired(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        with self.db:
            result = self.db.execute(
                """UPDATE frontier SET state='queued', leased_until=NULL,
                   lease_token=NULL, available_at=?
                   WHERE state='leased' AND leased_until <= ?""",
                (now, now))
        return result.rowcount

    def lease(self, now: float | None = None) -> dict | None:
        now = time.time() if now is None else now
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute(
                """UPDATE frontier SET state='queued', leased_until=NULL,
                   lease_token=NULL, available_at=?
                   WHERE state='leased' AND leased_until <= ?""", (now, now))
            row = self.db.execute(
                """SELECT url,priority,depth,attempts,parent_url,context_json
                   FROM frontier WHERE state='queued' AND available_at <= ?
                   ORDER BY priority,depth,created_at,url LIMIT 1""", (now,)
            ).fetchone()
            if row is None:
                self.db.execute("COMMIT")
                return None
            token = uuid.uuid4().hex
            self.db.execute(
                """UPDATE frontier SET state='leased', attempts=attempts+1,
                   leased_until=?, lease_token=?
                   WHERE url=? AND state='queued'""",
                (now + self.lease_seconds, token, row["url"]))
            self.db.execute("COMMIT")
            item = dict(row)
            item["attempts"] += 1
            item["lease_token"] = token
            item["context"] = json.loads(item.pop("context_json"))
            return item
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def finish(self, url: str, *, lease_token: str, state: str,
               error: str | None = None, retry_delay: float = 0,
               result: dict | None = None) -> None:
        """Atomically finalize the current lease and upsert its page result.

        The lease token prevents a stale worker from overwriting a newer
        attempt's result after expiry. Pending retries do not emit reports.
        """
        if state not in ("completed", "failed", "blocked", "queued"):
            raise ValueError("Unsupported final state")
        if not lease_token:
            raise ValueError("Lease token required")
        if retry_delay < 0:
            raise ValueError("retry_delay must be nonnegative")
        url = urldefrag(url)[0]
        payload = json.dumps(result, ensure_ascii=False, default=str) if result is not None else None
        self.db.execute("BEGIN IMMEDIATE")
        try:
            changed = self.db.execute(
                """UPDATE frontier SET state=?, leased_until=NULL, lease_token=NULL,
                   last_error=?, available_at=?
                   WHERE url=? AND state='leased' AND lease_token=?""",
                (state, error, time.time() + retry_delay, url, lease_token))
            if changed.rowcount != 1:
                raise ValueError("URL is not leased by this attempt")
            if payload is not None and state != "queued":
                self.db.execute(
                    """INSERT INTO page_results(url,result_json,updated_at) VALUES(?,?,?)
                       ON CONFLICT(url) DO UPDATE SET
                         result_json=excluded.result_json,
                         updated_at=excluded.updated_at""",
                    (url, payload, time.time()))
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def list_results(self) -> list[dict]:
        """Stable report order; one current result per URL over all runs."""
        rows = self.db.execute(
            """SELECT r.result_json FROM page_results r
               JOIN frontier f ON f.url=r.url
               ORDER BY f.created_at, f.url""")
        return [json.loads(row["result_json"]) for row in rows]

    def counts(self) -> dict[str, int]:
        return {row["state"]: row["n"] for row in self.db.execute(
            "SELECT state, COUNT(*) AS n FROM frontier GROUP BY state")}

    def close(self) -> None:
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
