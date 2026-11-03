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
            lease_token TEXT,
            finished_at REAL
        )""")
        # In-place migration from the first V0.1 SQLite schema.
        columns = {row["name"] for row in self.db.execute("PRAGMA table_info(frontier)")}
        for name, spec in {
            "parent_url": "TEXT NOT NULL DEFAULT ''",
            "context_json": "TEXT NOT NULL DEFAULT '{}'",
            "lease_token": "TEXT",
            "finished_at": "REAL",
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
        self.db.execute("""CREATE TABLE IF NOT EXISTS frontier_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )""")

    def assert_identity(self, identity: dict) -> None:
        """Bind a DB to one logical task and access policy; fail on mismatches."""
        serialized = json.dumps(identity, sort_keys=True, ensure_ascii=False)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT value FROM frontier_meta WHERE key='identity'").fetchone()
            if row is None:
                # Old schema without a recorded identity: do not silently adopt it.
                if self.db.execute("SELECT 1 FROM frontier LIMIT 1").fetchone():
                    raise ValueError("Legacy Frontier data has no verified task identity")
                self.db.execute(
                    "INSERT INTO frontier_meta(key,value) VALUES('identity',?)",
                    (serialized,))
            elif row["value"] != serialized:
                raise ValueError("Frontier task identity or access policy changed")
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def enqueue_many(self, items: list[dict]) -> int:
        """Atomic batch admission with validation before any write."""
        rows = []
        for entry in items:
            url = entry["url"]
            self.policy.validate(url, resolve_dns=False)
            priority = entry.get("priority", 2)
            depth = entry.get("depth", 0)
            if isinstance(priority, bool) or not isinstance(priority, int) or not 1 <= priority <= 3:
                raise ValueError("Invalid priority")
            if isinstance(depth, bool) or not isinstance(depth, int) or depth < 0:
                raise ValueError("Invalid depth")
            rows.append((urldefrag(url)[0], priority, depth, time.time(),
                         entry.get("parent_url", ""),
                         json.dumps(entry.get("context") or {}, ensure_ascii=False, default=str)))
        if not rows:
            return 0
        self.db.execute("BEGIN IMMEDIATE")
        try:
            before = self.db.total_changes
            self.db.executemany(
                """INSERT OR IGNORE INTO frontier
                   (url,priority,depth,state,created_at,parent_url,context_json)
                   VALUES(?,?,?,'queued',?,?,?)""", rows)
            added = self.db.total_changes - before
            self.db.execute("COMMIT")
            return added
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def prune_terminal(self, *, older_than_seconds: float, now: float | None = None) -> int:
        """Explicit retention policy; active/queued jobs are never removed."""
        if older_than_seconds <= 0:
            raise ValueError("Retention period must be positive")
        cutoff = (time.time() if now is None else now) - older_than_seconds
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute(
                """DELETE FROM page_results WHERE url IN
                   (SELECT url FROM frontier WHERE state IN ('completed','failed','blocked')
                    AND finished_at IS NOT NULL AND finished_at <= ?)""", (cutoff,))
            removed = self.db.execute(
                """DELETE FROM frontier WHERE state IN ('completed','failed','blocked')
                   AND finished_at IS NOT NULL AND finished_at <= ?""", (cutoff,)).rowcount
            self.db.execute("COMMIT")
            return removed
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

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
                   ORDER BY priority,depth,created_at,rowid LIMIT 1""", (now,)
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
                   last_error=?, available_at=?, finished_at=?
                   WHERE url=? AND state='leased' AND lease_token=?""",
                (state, error, time.time() + retry_delay,
                 None if state == 'queued' else time.time(), url, lease_token))
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
