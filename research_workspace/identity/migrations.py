"""SQLite v3 identity schema and conservative, backed-up legacy migration.

Create a consistent, permission-restricted backup BEFORE changing an existing
v0/v1/v2 database. One BEGIN IMMEDIATE transaction contains all new schema,
project backfill and version bump. No login or public multi-user support.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from contextlib import closing
import sqlite3
import time
import uuid

SCHEMA_VERSION = 3


def stable_local_ids(alias: str) -> tuple[str, str]:
    """Stable unverified identity per existing local-owner alias."""
    # Historical V0.2-B owner values had no database-level length or blank
    # constraints. Backfill MUST support every persisted TEXT alias, including
    # empty/long values; new local owner inputs are validated separately.
    if not isinstance(alias, str):
        raise ValueError("Invalid legacy local owner alias")
    key = hashlib.sha256(alias.encode("utf-8")).hexdigest()
    return "legacy_usr_" + key, "legacy_ws_" + key


def _check_database(db: sqlite3.Connection) -> None:
    ok = db.execute("PRAGMA quick_check").fetchone()
    if not ok or ok[0] != "ok":
        raise RuntimeError("Database integrity check failed; do not migrate")


def _contains_projects(db: sqlite3.Connection) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='projects'").fetchone() is not None


def snapshot_before_v3(path: str | Path) -> Path | None:
    """Return new consistent v0–v2 pre-migration snapshot; fail closed on errors.

    Uses the SQLite backup API so WAL transactions are included. The source DB
    is never replaced. The backup is an immutable 0600 local file; no secrets
    or source text are copied to a network service.
    """
    p = Path(path)
    if not p.is_file() or p.stat().st_size == 0:
        return None
    if p.is_symlink():
        raise ValueError("Database symlinks are not supported for automatic migration")
    with closing(sqlite3.connect(str(p), timeout=20)) as source:
        version = source.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError("Unknown future research database schema")
        if version == SCHEMA_VERSION or not _contains_projects(source):
            return None
        _check_database(source)
        destination = p.with_name(p.name + ".pre-v3-" + str(time.time_ns()) + "-" + uuid.uuid4().hex[:8] + ".sqlite3")
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        try:
            with closing(sqlite3.connect(str(destination), timeout=20)) as target:
                source.backup(target)
                _check_database(target)
                # Guarantee we actually captured the pre-migration version.
                if target.execute("PRAGMA user_version").fetchone()[0] != version:
                    raise RuntimeError("Backup schema did not match source")
            os.chmod(destination, 0o600)
            return destination
        except BaseException:
            destination.unlink(missing_ok=True)
            raise


# All SQLite DDL and backfill happen inside the same explicit transaction.
_DDL = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL CHECK(length(display_name) BETWEEN 1 AND 200),
    kind TEXT NOT NULL CHECK(kind IN ('legacy_placeholder','unverified')),
    created_at TEXT NOT NULL,
    disabled_at TEXT
);
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 200),
    kind TEXT NOT NULL CHECK(kind IN ('personal','team')),
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    deleted_at TEXT
);
CREATE TABLE IF NOT EXISTS workspace_memberships (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    role TEXT NOT NULL CHECK(role IN ('owner','admin','editor','viewer')),
    state TEXT NOT NULL CHECK(state IN ('ACTIVE','SUSPENDED')),
    joined_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(workspace_id,user_id)
);
CREATE INDEX IF NOT EXISTS memberships_by_user ON workspace_memberships(user_id,state);
CREATE TABLE IF NOT EXISTS legacy_owner_bindings (
    owner_alias TEXT PRIMARY KEY,
    user_id TEXT NOT NULL UNIQUE REFERENCES users(id),
    workspace_id TEXT NOT NULL UNIQUE REFERENCES workspaces(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS membership_audit (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    actor_user_id TEXT REFERENCES users(id),
    subject_user_id TEXT NOT NULL REFERENCES users(id),
    action TEXT NOT NULL CHECK(action IN ('CREATED','GRANTED','ROLE_CHANGED','SUSPENDED','REACTIVATED','REMOVED')),
    old_role TEXT, new_role TEXT,
    occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS membership_audit_by_workspace ON membership_audit(workspace_id,occurred_at);

CREATE TRIGGER IF NOT EXISTS v3_audit_immutable_update BEFORE UPDATE ON membership_audit
BEGIN SELECT RAISE(ABORT, 'Membership audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS v3_audit_immutable_delete BEFORE DELETE ON membership_audit
BEGIN SELECT RAISE(ABORT, 'Membership audit is append-only'); END;

CREATE TRIGGER IF NOT EXISTS v3_keep_last_owner_delete
BEFORE DELETE ON workspace_memberships
WHEN OLD.role='owner' AND OLD.state='ACTIVE' AND
     (SELECT count(*) FROM workspace_memberships WHERE workspace_id=OLD.workspace_id
        AND role='owner' AND state='ACTIVE')<=1
BEGIN SELECT RAISE(ABORT, 'Workspace must have an active owner'); END;

CREATE TRIGGER IF NOT EXISTS v3_keep_last_owner_update
BEFORE UPDATE OF role,state ON workspace_memberships
WHEN OLD.role='owner' AND OLD.state='ACTIVE' AND
     (NEW.role!='owner' OR NEW.state!='ACTIVE') AND
     (SELECT count(*) FROM workspace_memberships WHERE workspace_id=OLD.workspace_id
        AND role='owner' AND state='ACTIVE')<=1
BEGIN SELECT RAISE(ABORT, 'Workspace must have an active owner'); END;

CREATE TRIGGER IF NOT EXISTS v3_project_scoped_insert
BEFORE INSERT ON projects
WHEN NEW.workspace_id IS NULL OR NEW.created_by IS NULL OR
     NOT EXISTS (SELECT 1 FROM workspace_memberships m
       WHERE m.workspace_id=NEW.workspace_id AND m.user_id=NEW.created_by AND m.state='ACTIVE')
BEGIN SELECT RAISE(ABORT, 'Project creator must be active in workspace'); END;

CREATE TRIGGER IF NOT EXISTS v3_project_scoped_update
BEFORE UPDATE OF workspace_id,created_by ON projects
WHEN NEW.workspace_id IS NULL OR NEW.created_by IS NULL OR
     NOT EXISTS (SELECT 1 FROM workspace_memberships m
       WHERE m.workspace_id=NEW.workspace_id AND m.user_id=NEW.created_by AND m.state='ACTIVE')
BEGIN SELECT RAISE(ABORT, 'Project creator must be active in workspace'); END;
"""


def ensure_legacy_binding(db: sqlite3.Connection, alias: str) -> tuple[str, str]:
    """Internal-only local bootstrap. Must be called inside an existing write tx."""
    from ..store import now
    user_id, workspace_id = stable_local_ids(alias)
    stamp = now()
    db.execute("INSERT OR IGNORE INTO users(id,display_name,kind,created_at) VALUES(?,?,?,?)",
               (user_id, "Imported local operator", "legacy_placeholder", stamp))
    db.execute("INSERT OR IGNORE INTO workspaces(id,name,kind,created_by,created_at) VALUES(?,?,?,?,?)",
               (workspace_id, "Personal workspace (imported)", "personal", user_id, stamp))
    db.execute("""INSERT OR IGNORE INTO workspace_memberships
        (workspace_id,user_id,role,state,joined_at,updated_at) VALUES(?,?,?,?,?,?)""",
               (workspace_id, user_id, "owner", "ACTIVE", stamp, stamp))
    db.execute("""INSERT OR IGNORE INTO legacy_owner_bindings
        (owner_alias,user_id,workspace_id,created_at) VALUES(?,?,?,?)""",
               (alias, user_id, workspace_id, stamp))
    row = db.execute("SELECT user_id,workspace_id FROM legacy_owner_bindings WHERE owner_alias=?", (alias,)).fetchone()
    if not row or row[0] != user_id or row[1] != workspace_id:
        raise RuntimeError("Legacy binding conflict")
    return user_id, workspace_id


def migrate_v3(db: sqlite3.Connection) -> int:
    """Atomic, idempotent v3 schema creation and all-owner project backfill."""
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError("Unknown future research database schema")
    if version == SCHEMA_VERSION:
        return 0
    try:
        db.execute("BEGIN IMMEDIATE")
        # Re-check after acquiring the SQLite write lock; another process could
        # have finished the migration between open and BEGIN.
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version == SCHEMA_VERSION:
            db.execute("COMMIT")
            return 0
        if version > SCHEMA_VERSION:
            raise RuntimeError("Unknown future research database schema")
        # Important: add the columns BEFORE creating triggers that reference them.
        # All migrations are additive; never modify or drop run/snapshot evidence.
        columns = {row[1] for row in db.execute("PRAGMA table_info(projects)")}
        if "workspace_id" not in columns:
            db.execute("ALTER TABLE projects ADD COLUMN workspace_id TEXT REFERENCES workspaces(id)")
        if "created_by" not in columns:
            db.execute("ALTER TABLE projects ADD COLUMN created_by TEXT REFERENCES users(id)")
        # sqlite3.executescript commits implicitly; execute DDL one statement at
        # a time while the write transaction is active. Trigger definitions have
        # internal semicolons, so sqlite3.complete_statement is used.
        statement = ""
        for line in _DDL.splitlines(keepends=True):
            statement += line
            if sqlite3.complete_statement(statement):
                if statement.strip():
                    db.execute(statement)
                statement = ""
        if statement.strip():
            raise RuntimeError("Incomplete identity migration DDL")
        owners = [row[0] for row in db.execute("SELECT DISTINCT owner FROM projects ORDER BY owner")]
        for alias in owners:
            user_id, workspace_id = ensure_legacy_binding(db, alias)
            db.execute("UPDATE projects SET workspace_id=?,created_by=? WHERE owner=?",
                       (workspace_id,user_id,alias))
        remaining = db.execute("SELECT count(*) FROM projects WHERE workspace_id IS NULL OR created_by IS NULL").fetchone()[0]
        if remaining:
            raise RuntimeError("Project migration left unassigned rows")
        db.execute("PRAGMA user_version=3")
        db.execute("COMMIT")
        return len(owners)
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
