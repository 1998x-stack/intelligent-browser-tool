"""V04-01: automatic WAL-safe backup, v3 identity migration, invariants.

No test pretends that local aliases are authenticated multi-user identities.
"""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3

import pytest

from research_workspace.identity import WorkspaceRepository
from research_workspace.identity.migrations import migrate_v3, stable_local_ids
from research_workspace.store import ResearchStore


LEGACY_V2 = """
PRAGMA foreign_keys=ON;
CREATE TABLE projects(id TEXT PRIMARY KEY,owner TEXT NOT NULL,question TEXT NOT NULL,
    sources_json TEXT NOT NULL,fields_json TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE runs(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),
    status TEXT NOT NULL,pages_limit INTEGER NOT NULL,bytes_limit INTEGER NOT NULL,
    pages_used INTEGER NOT NULL DEFAULT 0,bytes_used INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
    worker_token TEXT,leased_until REAL);
CREATE TABLE run_sources(run_id TEXT REFERENCES runs(id),url TEXT NOT NULL,
    ordinal INTEGER NOT NULL,state TEXT NOT NULL DEFAULT 'PENDING',attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,snapshot_id TEXT,PRIMARY KEY(run_id,url));
CREATE TABLE snapshots(id TEXT PRIMARY KEY,run_id TEXT REFERENCES runs(id),url TEXT NOT NULL,
    final_url TEXT NOT NULL,captured_at TEXT NOT NULL,content_sha256 TEXT NOT NULL,
    content_type TEXT NOT NULL,text TEXT NOT NULL,byte_count INTEGER NOT NULL,
    UNIQUE(run_id,url));
CREATE TABLE claims(id TEXT PRIMARY KEY,snapshot_id TEXT REFERENCES snapshots(id),
    field_key TEXT NOT NULL,status TEXT NOT NULL,value_json TEXT NOT NULL,
    anchors_json TEXT NOT NULL,reason TEXT NOT NULL,UNIQUE(snapshot_id,field_key));
CREATE TABLE run_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT NOT NULL,
    kind TEXT NOT NULL,detail TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE research_schedules(project_id TEXT PRIMARY KEY REFERENCES projects(id),
    enabled INTEGER NOT NULL,interval_seconds INTEGER NOT NULL,
    next_due_epoch REAL NOT NULL,pages_limit INTEGER NOT NULL,bytes_limit INTEGER NOT NULL,
    last_run_id TEXT,updated_at TEXT NOT NULL);
CREATE TABLE research_changes(id TEXT PRIMARY KEY,project_id TEXT REFERENCES projects(id),
    previous_run_id TEXT REFERENCES runs(id),current_run_id TEXT REFERENCES runs(id),
    subject TEXT NOT NULL,field_key TEXT NOT NULL,kind TEXT NOT NULL,
    severity TEXT NOT NULL,old_value_json TEXT,new_value_json TEXT,
    old_evidence_json TEXT NOT NULL,new_evidence_json TEXT NOT NULL,
    read_state TEXT NOT NULL DEFAULT 'UNREAD',created_at TEXT NOT NULL,
    UNIQUE(current_run_id,subject,field_key));
CREATE TABLE research_reconciliations(run_id TEXT PRIMARY KEY REFERENCES runs(id),
    previous_run_id TEXT,reconciled_at TEXT NOT NULL);
PRAGMA user_version=2;
"""


def v2_database(path: Path, *, owners=("alice", "bob"), leave_open=False):
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA wal_autocheckpoint=0")
    db.executescript(LEGACY_V2)
    for i, owner in enumerate(owners):
        pid = "project-" + str(i)
        rid = "run-" + str(i)
        db.execute("INSERT INTO projects VALUES(?,?,?,?,?,?)",
                   (pid,owner,"Question " + owner,"[]","[]","2026-01-01"))
        db.execute("INSERT INTO runs(id,project_id,status,pages_limit,bytes_limit,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                   (rid,pid,"COMPLETED",1,1024,"2026-01-01","2026-01-01"))
        db.execute("INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?,?)",
                   ("snapshot-"+str(i),rid,"https://example.com","https://example.com","2026-01-01",
                    "abc","text/plain","Original source text " + owner,25))
        db.execute("INSERT INTO claims VALUES(?,?,?,?,?,?,?)",
                   ("claim-"+str(i),"snapshot-"+str(i),"pricing","SUPPORTED","{}","[]","fixture"))
        db.execute("INSERT INTO research_schedules VALUES(?,?,?,?,?,?,?,?)",
                   (pid,0,86400,100,1,2048,None,"2026-01-01"))
        db.execute("INSERT INTO research_reconciliations VALUES(?,?,?)",
                   (rid,None,"2026-01-01"))
    if leave_open:
        return db
    db.close()
    return None


def count(db, table):
    return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_fresh_v3_store_and_legacy_project_link(tmp_path):
    path=tmp_path/"fresh.db"
    store=ResearchStore(path)
    assert store.migration_backup is None
    assert store.project("local","missing") is None
    pid=store.create_project("local","question",[],[])
    with store.db() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0]==3
        row=db.execute("SELECT owner,workspace_id,created_by FROM projects WHERE id=?",(pid,)).fetchone()
        assert row["owner"]=="local"
        assert (row["created_by"],row["workspace_id"])==stable_local_ids("local")
        assert count(db,"users")==1
        assert count(db,"workspaces")==1
        assert count(db,"workspace_memberships")==1
        assert count(db,"legacy_owner_bindings")==1
        assert db.execute("PRAGMA foreign_key_check").fetchall()==[]
        assert db.execute("PRAGMA quick_check").fetchone()[0]=="ok"
    other=ResearchStore(path)
    assert other.migration_backup is None
    assert other.project("local",pid)["workspace_id"]==row["workspace_id"]


def test_v2_backfills_distinct_local_workspaces_and_retains_all_evidence(tmp_path):
    path=tmp_path/"old.db"
    v2_database(path,owners=("alpha","beta","alpha"))
    store=ResearchStore(path)
    backup=store.migration_backup
    assert backup is not None and backup.is_file() and backup != path
    assert os.stat(backup).st_mode & 0o777 == 0o600
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM projects").fetchone()[0]==3
        assert db.execute("PRAGMA quick_check").fetchone()[0]=="ok"
    with store.db() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0]==3
        assert count(db,"users")==2
        assert count(db,"workspaces")==2
        assert count(db,"workspace_memberships")==2
        assert count(db,"snapshots")==3
        assert count(db,"claims")==3
        assert count(db,"runs")==3
        assert count(db,"research_schedules")==3
        assert count(db,"research_reconciliations")==3
        assert db.execute("PRAGMA foreign_key_check").fetchall()==[]
        for owner,wsid,userid in db.execute("SELECT owner,workspace_id,created_by FROM projects"):
            assert (userid,wsid)==stable_local_ids(owner)
    # No second automatic backup, no schema downgrade and no data loss on restart.
    again=ResearchStore(path)
    assert again.migration_backup is None
    assert len(list(tmp_path.glob("old.db.pre-v3-*.sqlite3")))==1


def test_pre_migration_backup_includes_uncheckpointed_wal(tmp_path):
    path=tmp_path/"wal.db"
    writer=v2_database(path, owners=("wal-user",), leave_open=True)
    try:
        writer.execute("INSERT INTO run_events(run_id,kind,detail,created_at) VALUES(?,?,?,?)",
                       ("run-0","TEST","WAL included in online backup","2026-01-01"))
        store=ResearchStore(path)
        assert store.migration_backup is not None
        with sqlite3.connect(store.migration_backup) as backup:
            assert backup.execute("SELECT detail FROM run_events").fetchone()[0] == "WAL included in online backup"
        with store.db() as db:
            assert db.execute("SELECT detail FROM run_events").fetchone()[0] == "WAL included in online backup"
    finally:
        writer.close()


def test_migration_failure_rolls_back_schema_backfill_and_version(tmp_path,monkeypatch):
    path=tmp_path/"rollback.db"
    v2_database(path,owners=("first","second"))
    import research_workspace.identity.migrations as migration
    original=migration.ensure_legacy_binding
    def explode_on_second(db,alias):
        if alias=="second":
            raise RuntimeError("injected migration failure")
        return original(db,alias)
    monkeypatch.setattr(migration,"ensure_legacy_binding",explode_on_second)
    with sqlite3.connect(path,isolation_level=None) as db:
        db.row_factory=sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(RuntimeError,match="injected"):
            migrate_v3(db)
        assert db.execute("PRAGMA user_version").fetchone()[0]==2
        assert "workspace_id" not in {x[1] for x in db.execute("PRAGMA table_info(projects)")}
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='legacy_owner_bindings'").fetchone()
        assert count(db,"projects")==2
        assert db.execute("PRAGMA quick_check").fetchone()[0]=="ok"
    monkeypatch.setattr(migration,"ensure_legacy_binding",original)
    assert ResearchStore(path).project("first","project-0")


def test_unknown_future_schema_fails_without_modification_or_backup(tmp_path):
    path=tmp_path/"future.db"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=11")
        db.execute("CREATE TABLE future_schema(id INTEGER PRIMARY KEY)")
    with pytest.raises(RuntimeError,match="future"):
        ResearchStore(path)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0]==11
        assert db.execute("SELECT count(*) FROM future_schema").fetchone()[0]==0
    assert not list(tmp_path.glob("*.pre-v3-*"))


def test_isolated_legacy_aliases_do_not_gain_access_to_each_others_projects(tmp_path):
    store=ResearchStore(tmp_path/"scope.db")
    a=store.create_project("one","private",[],[])
    b=store.create_project("two","private",[],[])
    assert store.project("one",b) is None
    assert store.project("two",a) is None
    identities=WorkspaceRepository(store)
    assert identities.get_local_binding("one")["workspace_id"] != identities.get_local_binding("two")["workspace_id"]


def test_new_project_scoping_constraints_and_identity_key(tmp_path):
    store=ResearchStore(tmp_path/"invariants.db")
    store.create_project("one","normal",[],[])
    store.create_project("two","normal",[],[])
    one=WorkspaceRepository(store).get_local_binding("one")
    two=WorkspaceRepository(store).get_local_binding("two")
    with store.db() as db:
        with pytest.raises(sqlite3.IntegrityError,match="Project creator"):
            db.execute("INSERT INTO projects(id,owner,question,sources_json,fields_json,created_at) VALUES(?,?,?,?,?,?)",
                       ("malformed","one","x","[]","[]","now"))
        with pytest.raises(sqlite3.IntegrityError,match="Project creator"):
            db.execute("""INSERT INTO projects
                (id,owner,question,sources_json,fields_json,created_at,workspace_id,created_by)
                VALUES(?,?,?,?,?,?,?,?)""",
                ("cross","one","x","[]","[]","now",two["workspace_id"],one["user_id"]))


def test_last_owner_cannot_be_demoted_removed_or_suspended(tmp_path):
    store=ResearchStore(tmp_path/"roles.db")
    ids=WorkspaceRepository(store)
    creator=ids.create_unverified_user("Product Owner")
    ws=ids.create_workspace(creator,"Research Team")
    with pytest.raises(sqlite3.IntegrityError,match="active owner"):
        ids.set_role(ws,creator,creator,"viewer")
    with pytest.raises(sqlite3.IntegrityError,match="active owner"):
        ids.set_state(ws,creator,creator,True)
    with pytest.raises(sqlite3.IntegrityError,match="active owner"):
        ids.remove_member(ws,creator,creator)
    with store.db() as db:
        assert count(db,"membership_audit")==1
        assert count(db,"workspace_memberships")==1


def test_membership_role_changes_owner_transfer_audit_and_revocation(tmp_path):
    store=ResearchStore(tmp_path/"team.db")
    ids=WorkspaceRepository(store)
    a=ids.create_unverified_user("A")
    b=ids.create_unverified_user("B")
    c=ids.create_unverified_user("C")
    ws=ids.create_workspace(a,"Team")
    ids.add_member(ws,a,b,"editor")
    ids.add_member(ws,a,c,"viewer")
    assert {x["role"] for x in ids.members(ws,a)}=={"owner","editor","viewer"}
    with pytest.raises(ValueError, match="administrator"):
        ids.add_member(ws,c,ids.create_unverified_user("D"),"viewer")
    ids.set_role(ws,a,b,"admin")
    ids.add_member(ws,b,ids.create_unverified_user("E"),"viewer")
    with pytest.raises(ValueError,match="Only an owner"):
        ids.set_role(ws,b,c,"owner")
    ids.set_role(ws,a,b,"owner")
    ids.set_role(ws,b,a,"viewer")  # permitted once there is another owner
    ids.set_state(ws,b,a,True)
    with pytest.raises(ValueError,match="administrator"):
        ids.members(ws,a)
    ids.remove_member(ws,b,a)
    assert all(x["user_id"]!=a for x in ids.members(ws,b))
    with store.db() as db:
        assert count(db,"membership_audit")>=8
        assert db.execute("SELECT count(*) FROM workspace_memberships WHERE workspace_id=? AND role='owner' AND state='ACTIVE'",(ws,)).fetchone()[0]==1


def test_role_state_restrictions_and_no_external_identity_routes(tmp_path):
    store=ResearchStore(tmp_path/"auth-staged.db")
    repo=WorkspaceRepository(store)
    user=repo.create_unverified_user("Admin")
    ws=repo.create_workspace(user,"Company")
    with pytest.raises(ValueError,match="role"):
        repo.add_member(ws,user,user,"superadmin")
    with pytest.raises(ValueError,match="already exists"):
        repo.add_member(ws,user,user,"owner")
    with store.db() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO workspace_memberships VALUES(?,?,?,?,?,?)",
                       (ws,user,"root","ACTIVE","now","now"))
    from research_workspace import server
    assert "/api/v1/users" not in Path(server.__file__).read_text("utf-8")
    assert "/api/v1/workspaces" not in Path(server.__file__).read_text("utf-8")


def test_invalid_legacy_alias_rejected(tmp_path):
    store=ResearchStore(tmp_path/"bad.db")
    with pytest.raises(ValueError,match="Invalid legacy"):
        store.create_project("", "question", [], [])
    with store.db() as db:
        assert count(db,"projects")==0
        assert count(db,"users")==0


def test_legacy_owner_blank_or_long_backfilled_without_loss(tmp_path):
    path=tmp_path/"unusual.db"
    v2_database(path,owners=("", "x"*500))
    store=ResearchStore(path)
    with store.db() as db:
        rows=db.execute("SELECT owner,created_by,workspace_id FROM projects").fetchall()
        for row in rows:
            assert (row["created_by"],row["workspace_id"])==stable_local_ids(row["owner"])
        assert count(db,"legacy_owner_bindings")==2
    with pytest.raises(ValueError):
        store.create_project("","new",[],[])
    with pytest.raises(ValueError):
        store.create_project("x"*500,"new",[],[])


def test_audit_is_append_only_and_placeholder_cannot_join_team(tmp_path):
    store=ResearchStore(tmp_path/"audit.db")
    store.create_project("local","legacy",[],[])
    placeholder=WorkspaceRepository(store).get_local_binding("local")["user_id"]
    repo=WorkspaceRepository(store)
    owner=repo.create_unverified_user("Human pending verification")
    ws=repo.create_workspace(owner,"Workspace")
    with pytest.raises(ValueError,match="cannot be invited"):
        repo.add_member(ws,owner,placeholder,"viewer")
    with store.db() as db:
        audit_id=db.execute("SELECT id FROM membership_audit").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("DELETE FROM membership_audit WHERE id=?",(audit_id,))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("UPDATE membership_audit SET action='REMOVED' WHERE id=?",(audit_id,))


def test_v2_snapshot_can_restore_into_new_path(tmp_path):
    import shutil
    path=tmp_path/"live.db"
    v2_database(path, owners=("one","two"))
    active=ResearchStore(path)
    restored=tmp_path/"restored.db"
    shutil.copyfile(active.migration_backup, restored)
    with sqlite3.connect(restored) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0]==2
        assert db.execute("SELECT count(*) FROM snapshots").fetchone()[0]==2
    rebuilt=ResearchStore(restored)
    with rebuilt.db() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0]==3
        assert count(db,"snapshots")==2
        assert count(db,"projects")==2


def test_concurrent_migration_is_transactionally_idempotent(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    path=tmp_path/"parallel.db"
    v2_database(path,owners=("one","two"))
    def reopen(_):
        return ResearchStore(path)
    with ThreadPoolExecutor(max_workers=3) as pool:
        stores=list(pool.map(reopen,range(3)))
    with stores[0].db() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0]==3
        assert count(db,"users")==2
        assert count(db,"workspace_memberships")==2
        assert db.execute("PRAGMA foreign_key_check").fetchall()==[]
