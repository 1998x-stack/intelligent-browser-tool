"""Internal-only workspace and membership management.

Callers must authenticate principals outside this module. No public routes,
credentials, account claiming, or self-service invitations are exposed in V04-01.
"""
from __future__ import annotations

import sqlite3
import uuid
from .models import ROLES
from .migrations import stable_local_ids
from ..store import now


class WorkspaceRepository:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _require_user(db, user_id):
        row = db.execute("SELECT id,kind,disabled_at FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None or row["disabled_at"] is not None:
            raise ValueError("User unavailable")
        return row

    @staticmethod
    def _require_actor(db, workspace_id, actor_id, *, owner_only=False):
        member = db.execute("""SELECT m.role FROM workspace_memberships m
            JOIN users u ON u.id=m.user_id
            WHERE m.workspace_id=? AND m.user_id=? AND m.state='ACTIVE'
              AND u.disabled_at IS NULL""", (workspace_id, actor_id)).fetchone()
        if not member or member["role"] not in (("owner",) if owner_only else ("owner", "admin")):
            raise ValueError("Active workspace administrator required")
        return member["role"]

    def create_unverified_user(self, display_name: str) -> str:
        """Privileged offline seed, not a signup or verified human account."""
        if not isinstance(display_name, str) or not 1 <= len(display_name.strip()) <= 200:
            raise ValueError("Invalid display name")
        user_id = "usr_" + uuid.uuid4().hex
        with self.store.tx() as db:
            db.execute("INSERT INTO users(id,display_name,kind,created_at) VALUES(?,?,?,?)",
                       (user_id, display_name.strip(), "unverified", now()))
        return user_id

    def create_workspace(self, creator_user_id: str, name: str) -> str:
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 200:
            raise ValueError("Invalid workspace name")
        workspace_id = "ws_" + uuid.uuid4().hex
        with self.store.tx() as db:
            user = self._require_user(db, creator_user_id)
            if user["kind"] != "unverified":
                raise ValueError("Imported local placeholders cannot create team workspaces")
            stamp = now()
            db.execute("INSERT INTO workspaces(id,name,kind,created_by,created_at) VALUES(?,?,?,?,?)",
                       (workspace_id,name.strip(),"team",creator_user_id,stamp))
            db.execute("""INSERT INTO workspace_memberships
                (workspace_id,user_id,role,state,joined_at,updated_at)
                VALUES(?,?,?,?,?,?)""", (workspace_id,creator_user_id,"owner","ACTIVE",stamp,stamp))
            self._audit(db,workspace_id,creator_user_id,creator_user_id,"CREATED",None,"owner")
        return workspace_id

    @staticmethod
    def _audit(db, workspace_id, actor_id, subject_id, action, old_role, new_role):
        db.execute("""INSERT INTO membership_audit
            (id,workspace_id,actor_user_id,subject_user_id,action,old_role,new_role,occurred_at)
            VALUES(?,?,?,?,?,?,?,?)""",
            (uuid.uuid4().hex,workspace_id,actor_id,subject_id,action,old_role,new_role,now()))

    def get_local_binding(self, alias: str) -> dict | None:
        user_id, workspace_id = stable_local_ids(alias)
        with self.store.db() as db:
            row = db.execute("SELECT owner_alias,user_id,workspace_id FROM legacy_owner_bindings WHERE owner_alias=?",
                             (alias,)).fetchone()
            if not row:
                return None
            if row["user_id"] != user_id or row["workspace_id"] != workspace_id:
                raise RuntimeError("Legacy owner mapping mismatch")
            return dict(row)

    def members(self, workspace_id: str, actor_id: str) -> list[dict]:
        with self.store.db() as db:
            self._require_actor(db,workspace_id,actor_id)
            return [dict(x) for x in db.execute("""SELECT user_id,role,state,joined_at,updated_at
                 FROM workspace_memberships WHERE workspace_id=? ORDER BY joined_at,user_id""",
                 (workspace_id,))]

    def add_member(self, workspace_id: str, actor_id: str, user_id: str, role: str) -> None:
        if role not in ROLES:
            raise ValueError("Unknown membership role")
        with self.store.tx() as db:
            actor_role = self._require_actor(db,workspace_id,actor_id)
            if role in ("owner", "admin") and actor_role != "owner":
                raise ValueError("Only an owner can grant privileged roles")
            user = self._require_user(db,user_id)
            if user["kind"] == "legacy_placeholder":
                raise ValueError("Legacy placeholder identities cannot be invited to team workspaces")
            if db.execute("SELECT 1 FROM workspace_memberships WHERE workspace_id=? AND user_id=?",
                          (workspace_id,user_id)).fetchone():
                raise ValueError("Membership already exists; use role-change operation")
            stamp=now()
            db.execute("""INSERT INTO workspace_memberships
               (workspace_id,user_id,role,state,joined_at,updated_at) VALUES(?,?,?,?,?,?)""",
               (workspace_id,user_id,role,"ACTIVE",stamp,stamp))
            self._audit(db,workspace_id,actor_id,user_id,"GRANTED",None,role)

    def set_role(self, workspace_id: str, actor_id: str, user_id: str, role: str) -> None:
        if role not in ROLES:
            raise ValueError("Unknown membership role")
        with self.store.tx() as db:
            actor_role=self._require_actor(db,workspace_id,actor_id)
            member=db.execute("SELECT role,state FROM workspace_memberships WHERE workspace_id=? AND user_id=?",
                              (workspace_id,user_id)).fetchone()
            if not member or member["state"]!="ACTIVE":
                raise ValueError("Active membership not found")
            if (role in ("owner","admin") or member["role"] in ("owner","admin")) and actor_role != "owner":
                raise ValueError("Only an owner can change privileged roles")
            if member["role"] == role:
                return
            db.execute("UPDATE workspace_memberships SET role=?,updated_at=? WHERE workspace_id=? AND user_id=?",
                       (role,now(),workspace_id,user_id))
            self._audit(db,workspace_id,actor_id,user_id,"ROLE_CHANGED",member["role"],role)

    def set_state(self, workspace_id: str, actor_id: str, user_id: str, suspended: bool) -> None:
        if type(suspended) is not bool:
            raise ValueError("suspended must be boolean")
        with self.store.tx() as db:
            actor_role=self._require_actor(db,workspace_id,actor_id)
            member=db.execute("SELECT role,state FROM workspace_memberships WHERE workspace_id=? AND user_id=?",
                              (workspace_id,user_id)).fetchone()
            if not member:
                raise ValueError("Membership not found")
            if member["role"] in ("owner","admin") and actor_role != "owner":
                raise ValueError("Only owner can change privileged member state")
            target="SUSPENDED" if suspended else "ACTIVE"
            if member["state"]==target:
                return
            db.execute("UPDATE workspace_memberships SET state=?,updated_at=? WHERE workspace_id=? AND user_id=?",
                       (target,now(),workspace_id,user_id))
            self._audit(db,workspace_id,actor_id,user_id,"SUSPENDED" if suspended else "REACTIVATED",
                        member["role"],member["role"])

    def remove_member(self, workspace_id: str, actor_id: str, user_id: str) -> None:
        with self.store.tx() as db:
            actor_role=self._require_actor(db,workspace_id,actor_id)
            member=db.execute("SELECT role FROM workspace_memberships WHERE workspace_id=? AND user_id=?",
                              (workspace_id,user_id)).fetchone()
            if not member:
                raise ValueError("Membership not found")
            if member["role"] in ("owner","admin") and actor_role!="owner":
                raise ValueError("Only owner can remove privileged member")
            db.execute("DELETE FROM workspace_memberships WHERE workspace_id=? AND user_id=?",(workspace_id,user_id))
            self._audit(db,workspace_id,actor_id,user_id,"REMOVED",member["role"],None)
