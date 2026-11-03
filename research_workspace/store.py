"""SQLite with run-level durable checkpoints and project/owner-aware queries."""
from __future__ import annotations
import sqlite3
import json
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone
import uuid
import time


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return uuid.uuid4().hex


def pack(item):
    return json.dumps(item, ensure_ascii=False, sort_keys=True)


def unpack(item):
    return json.loads(item)


class ResearchStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        # Back up all legacy data, including committed WAL pages, before any
        # schema-changing statement. Fail closed if backup cannot complete.
        from .identity.migrations import snapshot_before_v3
        self.migration_backup = snapshot_before_v3(self.path)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects(
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, question TEXT NOT NULL,
                    sources_json TEXT NOT NULL, fields_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS projects_by_owner ON projects(owner,created_at);
                CREATE TABLE IF NOT EXISTS runs(
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                    status TEXT NOT NULL, pages_limit INTEGER NOT NULL, bytes_limit INTEGER NOT NULL,
                    pages_used INTEGER NOT NULL DEFAULT 0, bytes_used INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    worker_token TEXT, leased_until REAL
                );
                CREATE TABLE IF NOT EXISTS run_sources(
                    run_id TEXT NOT NULL REFERENCES runs(id), url TEXT NOT NULL,
                    ordinal INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'PENDING',
                    attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, snapshot_id TEXT,
                    PRIMARY KEY(run_id,url)
                );
                CREATE TABLE IF NOT EXISTS snapshots(
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    url TEXT NOT NULL, final_url TEXT NOT NULL, captured_at TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL, content_type TEXT NOT NULL,
                    text TEXT NOT NULL, byte_count INTEGER NOT NULL,
                    UNIQUE(run_id,url)
                );
                CREATE TABLE IF NOT EXISTS claims(
                    id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
                    field_key TEXT NOT NULL, status TEXT NOT NULL, value_json TEXT NOT NULL,
                    anchors_json TEXT NOT NULL, reason TEXT NOT NULL,
                    UNIQUE(snapshot_id,field_key)
                );
                CREATE TABLE IF NOT EXISTS run_events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                    kind TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)
            columns={row["name"] for row in db.execute("PRAGMA table_info(runs)")}
            if "worker_token" not in columns:
                db.execute("ALTER TABLE runs ADD COLUMN worker_token TEXT")
            if "leased_until" not in columns:
                db.execute("ALTER TABLE runs ADD COLUMN leased_until REAL")
            version=db.execute("PRAGMA user_version").fetchone()[0]
            if version>3:
                raise RuntimeError("Unknown newer research database schema")
            # Preserve existing V0.3 events and runs, then atomically backfill
            # identity and workspace columns without discarding any evidence.
            from .monitoring import ensure_schema
            from .identity.migrations import migrate_v3
            ensure_schema(db)
            migrate_v3(db)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=20, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=20000")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def tx(self):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise

    def create_project(self, owner: str, question: str, sources: list[dict], fields: list[dict]) -> str:
        if not isinstance(owner, str) or not owner.strip() or len(owner) > 200:
            raise ValueError("Invalid legacy local owner alias")
        pid = uid()
        from .identity.migrations import ensure_legacy_binding
        with self.tx() as db:
            created_by, workspace_id = ensure_legacy_binding(db, owner)
            db.execute("""INSERT INTO projects
                (id,owner,question,sources_json,fields_json,created_at,workspace_id,created_by)
                VALUES(?,?,?,?,?,?,?,?)""",
                (pid,owner,question,pack(sources),pack(fields),now(),workspace_id,created_by))
        return pid

    def project(self, owner: str, pid: str) -> dict | None:
        with self.db() as db:
            row = db.execute("SELECT * FROM projects WHERE id=? AND owner=?",(pid,owner)).fetchone()
            if not row: return None
            obj = dict(row)
            obj["sources"] = unpack(obj.pop("sources_json"))
            obj["fields"] = unpack(obj.pop("fields_json"))
            return obj

    def projects(self, owner: str) -> list[dict]:
        with self.db() as db:
            rows = db.execute("SELECT id,question,created_at FROM projects WHERE owner=? ORDER BY created_at DESC",(owner,)).fetchall()
            return [dict(r) for r in rows]

    def create_run(self, owner: str, project: dict, *, pages_limit: int, bytes_limit: int) -> str:
        rid=uid()
        with self.tx() as db:
            db.execute("INSERT INTO runs(id,project_id,status,pages_limit,bytes_limit,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                       (rid,project["id"],"CREATED",pages_limit,bytes_limit,now(),now()))
            db.executemany("INSERT INTO run_sources(run_id,url,ordinal) VALUES(?,?,?)",
                           [(rid,s["url"],i) for i,s in enumerate(project["sources"])])
            db.execute("INSERT INTO run_events(run_id,kind,detail,created_at) VALUES(?,?,?,?)",
                       (rid,"CREATED","Run initialized with bounded source set",now()))
        return rid

    def runs(self, owner: str, pid: str) -> list[dict]:
        with self.db() as db:
            return [dict(row) for row in db.execute(
                """SELECT r.id,r.status,r.created_at,r.updated_at,r.pages_used,r.bytes_used
                   FROM runs r JOIN projects p ON p.id=r.project_id
                   WHERE p.id=? AND p.owner=? ORDER BY r.created_at DESC""",
                (pid,owner))]

    def get_run(self, owner: str, rid: str) -> dict | None:
        with self.db() as db:
            row = db.execute("""SELECT r.* FROM runs r JOIN projects p ON p.id=r.project_id
                                 WHERE r.id=? AND p.owner=?""",(rid,owner)).fetchone()
            if not row: return None
            o=dict(row)
            o.pop("worker_token",None)  # no internal worker token in user-facing API
            sources=db.execute("SELECT * FROM run_sources WHERE run_id=? ORDER BY ordinal",(rid,)).fetchall()
            o["sources"]=[dict(s) for s in sources]
            o["events"]=[dict(e) for e in db.execute("SELECT kind,detail,created_at FROM run_events WHERE run_id=? ORDER BY seq",(rid,))]
            return o

    def claim_run(self,rid:str)->str:
        """Fence cross-process workers. Crashed attempts reclaim only after expiry."""
        with self.tx() as db:
            row=db.execute("SELECT status,leased_until FROM runs WHERE id=?",(rid,)).fetchone()
            if not row:raise ValueError("Unknown run")
            if row["status"]=="COMPLETED":raise ValueError("Run already complete")
            if row["status"]=="RUNNING" and row["leased_until"] and row["leased_until"]>time.time():
                raise ValueError("Run is already leased by a worker")
            token=uid()
            db.execute("UPDATE runs SET status='RUNNING',worker_token=?,leased_until=?,updated_at=? WHERE id=?",
                       (token,time.time()+300,now(),rid))
            db.execute("INSERT INTO run_events(run_id,kind,detail,created_at) VALUES(?,?,?,?)",
                       (rid,"RUNNING","Worker claimed or recovered expired run",now()))
            return token

    @staticmethod
    def _check_token(db,rid:str,token:str):
        row=db.execute("SELECT worker_token,leased_until FROM runs WHERE id=?",(rid,)).fetchone()
        if not row or not token or row["worker_token"]!=token or row["leased_until"] is None or row["leased_until"]<time.time():
            raise ValueError("Stale or missing worker lease")

    def finish_run(self,rid:str,token:str,status:str,*,detail:str=""):
        if status not in ("COMPLETED","FAILED","PARTIAL","BUDGET_EXHAUSTED"):
            raise ValueError("Invalid run terminal state")
        with self.tx() as db:
            self._check_token(db,rid,token)
            db.execute("UPDATE runs SET status=?,worker_token=NULL,leased_until=NULL,updated_at=?,last_error=? WHERE id=?",
                       (status,now(),detail if status!="COMPLETED" else None,rid))
            db.execute("INSERT INTO run_events(run_id,kind,detail,created_at) VALUES(?,?,?,?)",
                       (rid,status,detail,now()))

    def release_on_error(self,rid:str,token:str):
        """Best-effort release after a controlled Python exception (not hard kill)."""
        with self.tx() as db:
            row=db.execute("SELECT worker_token FROM runs WHERE id=?",(rid,)).fetchone()
            if not row or row["worker_token"]!=token:return
            db.execute("UPDATE runs SET status='PARTIAL',worker_token=NULL,leased_until=NULL,updated_at=?,last_error=? WHERE id=?",
                       (now(),"Worker interrupted before source commit",rid))
            db.execute("INSERT INTO run_events(run_id,kind,detail,created_at) VALUES(?,?,?,?)",
                       (rid,"PARTIAL","Worker interrupted; uncommitted source can be retried",now()))

    def save_source(self, rid: str, url: str, fetched, claims: list[dict], *, lease_token: str):
        """Snapshot, claims and source completion commit as one transaction."""
        from .extraction import digest, validate_anchors
        snapid=claims[0]["snapshot_id"] if claims else uid()
        if any(claim["snapshot_id"] != snapid for claim in claims):
            raise ValueError("Claim snapshot mismatch")
        for c in claims: validate_anchors(fetched.text,c["anchors"])
        with self.tx() as db:
            self._check_token(db,rid,lease_token)
            db.execute("INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?,?)",
                       (snapid,rid,url,fetched.final_url,now(),digest(fetched.text),
                        fetched.content_type,fetched.text,fetched.bytes_read))
            db.executemany("INSERT INTO claims VALUES(?,?,?,?,?,?,?)",
                           [(uid(),snapid,c["field"],c["status"],pack(c["value"]),pack(c["anchors"]),c["reason"]) for c in claims])
            changed=db.execute("""UPDATE run_sources SET state='SUCCESS',attempts=attempts+1,
                                last_error=NULL,snapshot_id=? WHERE run_id=? AND url=? AND state!='SUCCESS'""",
                                (snapid,rid,url))
            if changed.rowcount!=1:raise ValueError("Source already committed or unknown")
            db.execute("UPDATE runs SET pages_used=pages_used+1,bytes_used=bytes_used+?,updated_at=? WHERE id=?",
                       (fetched.bytes_read,now(),rid))
            db.execute("INSERT INTO run_events(run_id,kind,detail,created_at) VALUES(?,?,?,?)",
                       (rid,"SOURCE_SUCCEEDED",url,now()))

    def fail_source(self,rid:str,url:str,error:str,*,lease_token:str):
        with self.tx() as db:
            self._check_token(db,rid,lease_token)
            changed=db.execute("""UPDATE run_sources SET state='FAILED',attempts=attempts+1,last_error=?
                                WHERE run_id=? AND url=? AND state!='SUCCESS'""",(error,rid,url))
            if changed.rowcount!=1:raise ValueError("Source already succeeded or unknown")
            db.execute("UPDATE runs SET pages_used=pages_used+1,updated_at=? WHERE id=?",(now(),rid))
            db.execute("INSERT INTO run_events(run_id,kind,detail,created_at) VALUES(?,?,?,?)",
                       (rid,"SOURCE_FAILED",f"{url}: {error}",now()))

    def delete_project(self,owner:str,pid:str)->None:
        """Explicit owner-authorized deletion of source text, claims, runs and project."""
        with self.tx() as db:
            row=db.execute("SELECT owner FROM projects WHERE id=?",(pid,)).fetchone()
            if not row or row["owner"]!=owner:raise ValueError("Project missing or not owned")
            running=db.execute("SELECT 1 FROM runs WHERE project_id=? AND status='RUNNING' LIMIT 1",(pid,)).fetchone()
            if running:raise ValueError("Cannot delete while a run is executing")
            # New monitoring records refer to runs and projects, so remove
            # them first in the same transaction as the source data.
            db.execute("DELETE FROM research_changes WHERE project_id=?",(pid,))
            db.execute("DELETE FROM research_reconciliations WHERE run_id IN (SELECT id FROM runs WHERE project_id=?)",(pid,))
            db.execute("DELETE FROM research_schedules WHERE project_id=?",(pid,))
            db.execute("DELETE FROM claims WHERE snapshot_id IN (SELECT s.id FROM snapshots s JOIN runs r ON s.run_id=r.id WHERE r.project_id=?)",(pid,))
            db.execute("DELETE FROM snapshots WHERE run_id IN (SELECT id FROM runs WHERE project_id=?)",(pid,))
            db.execute("DELETE FROM run_sources WHERE run_id IN (SELECT id FROM runs WHERE project_id=?)",(pid,))
            db.execute("DELETE FROM run_events WHERE run_id IN (SELECT id FROM runs WHERE project_id=?)",(pid,))
            db.execute("DELETE FROM runs WHERE project_id=?",(pid,))
            db.execute("DELETE FROM projects WHERE id=? AND owner=?",(pid,owner))

    def dossier(self, owner: str, pid: str, rid: str) -> dict | None:
        p=self.project(owner,pid)
        if not p: return None
        run=self.get_run(owner,rid)
        if not run or run["project_id"]!=pid:return None
        with self.db() as db:
            snaps=[dict(x) for x in db.execute("SELECT * FROM snapshots WHERE run_id=? ORDER BY captured_at,url",(rid,))]
            claims=[dict(x) for x in db.execute("""SELECT c.* FROM claims c
                      JOIN snapshots s ON s.id=c.snapshot_id WHERE s.run_id=? ORDER BY s.url,c.field_key""",(rid,))]
        bysnap={s["id"]:s for s in snaps}
        entries=[]
        for claim in claims:
            anchors=unpack(claim["anchors_json"])
            snap=bysnap[claim["snapshot_id"]]
            entries.append({"field":claim["field_key"],"status":claim["status"],
                            "value":unpack(claim["value_json"]),"reason":claim["reason"],
                            "source_url":snap["url"],"captured_at":snap["captured_at"],
                            "snapshot_id":snap["id"],"content_sha256":snap["content_sha256"],
                            "evidence":[{**a,"valid":snap["text"][a["start"]:a["end"]]==a["quote"]} for a in anchors]})
        # Keep full source text within the authenticated dossier only. No public share URL.
        sources=[{k:s[k] for k in ("id","url","final_url","captured_at","content_sha256","content_type","text","byte_count")} for s in snaps]
        return {"schema_version":"0.2b.1","mode":"local_live","notice":"Live, bounded public-source extraction. SUPPORTED means literal evidence present, not independent confirmation of website truth.",
                "project":p,"run":run,"sources":sources,"claims":entries,
                "estimated_provider_cost_usd":0,"total_infrastructure_cost_usd":None}
