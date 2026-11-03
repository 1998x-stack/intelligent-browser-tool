"""A bounded, operator-authorized research service using durable SQLite checkpoints."""
from __future__ import annotations
import json
import re
from pathlib import Path
import threading
import time
from .fetcher import SourcePolicy, BoundedFetcher, FetchError
from .store import ResearchStore, uid
from .extraction import claims_for, validate_anchors, digest
from .monitoring import Monitoring


class ResearchError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


_KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


class ResearchService:
    """Local operator-owned service; not a public multi-tenant SaaS API."""
    def __init__(self, db_path: str | Path, policy: SourcePolicy, *, fetcher=None,
                 owner: str = "local"):
        self.store=ResearchStore(db_path)
        self.monitor=Monitoring(self.store)
        self.policy=policy
        self.fetcher=fetcher if fetcher is not None else BoundedFetcher(policy)
        self.owner=owner
        self._locks_guard=threading.Lock()
        self._locks: dict[str,threading.Lock]={}

    def create_project(self, payload: dict) -> dict:
        question=payload.get("question", "")
        sources=payload.get("sources")
        fields=payload.get("fields")
        if not isinstance(question,str) or not 8 <= len(question.strip()) <= 500:
            raise ResearchError("INVALID_QUESTION","Question must be 8..500 characters")
        if not isinstance(sources,list) or not 1 <= len(sources) <= 5:
            raise ResearchError("INVALID_SOURCES","Provide 1..5 sources")
        if not isinstance(fields,list) or not 1 <= len(fields) <= 8:
            raise ResearchError("INVALID_FIELDS","Provide 1..8 extraction fields")
        cleaned=[]
        used=set()
        for entry in sources:
            if not isinstance(entry,dict) or not isinstance(entry.get("url"),str):
                raise ResearchError("INVALID_SOURCES","Every source must have a URL")
            try:
                url=self.policy.validate(entry["url"],resolve_dns=False)
            except FetchError as exc:
                raise ResearchError("SOURCE_OUTSIDE_POLICY",str(exc)) from exc
            if url in used:
                continue
            used.add(url)
            label=entry.get("label") or url.split("/")[2]
            if not isinstance(label,str) or not 1<=len(label)<=80:
                raise ResearchError("INVALID_SOURCES","Source label must be 1..80 characters")
            cleaned.append({"url":url,"label":label})
        normalized=[]
        keys=set()
        for field in fields:
            if not isinstance(field,dict):
                raise ResearchError("INVALID_FIELDS","Each extraction field is an object")
            key,kind,hint=field.get("key"),field.get("kind"),field.get("hint", "")
            label=field.get("label",key)
            if not isinstance(key,str) or not _KEY.fullmatch(key) or key in keys:
                raise ResearchError("INVALID_FIELDS","Field keys must be distinct snake_case identifiers")
            if kind not in ("price","keyword"):
                raise ResearchError("INVALID_FIELDS","Only deterministic price and keyword extraction are supported")
            if not isinstance(hint,str) or (kind=="keyword" and not 2<=len(hint)<=80):
                raise ResearchError("INVALID_FIELDS","Keyword fields need a 2..80 character hint")
            if not isinstance(label,str) or not 1 <= len(label) <= 80:
                raise ResearchError("INVALID_FIELDS","Each field needs a short label")
            keys.add(key)
            normalized.append({"key":key,"kind":kind,"hint":hint,"label":label})
        pid=self.store.create_project(self.owner,question.strip(),cleaned,normalized)
        return self.project(pid)

    def project(self, pid: str) -> dict:
        p=self.store.project(self.owner,pid)
        if not p: raise ResearchError("NOT_FOUND","Research project not found")
        return p

    def projects(self) -> list[dict]:
        return self.store.projects(self.owner)

    def runs(self, pid: str) -> list[dict]:
        self.project(pid)
        return self.store.runs(self.owner,pid)

    def new_run(self,pid: str, *, max_pages: int = 5, max_bytes: int = 1_000_000) -> dict:
        p=self.project(pid)
        if type(max_pages) is not int or not 1<=max_pages<=5:
            raise ResearchError("INVALID_BUDGET","max_pages must be 1..5")
        if type(max_bytes) is not int or not 1024<=max_bytes<=5_000_000:
            raise ResearchError("INVALID_BUDGET","max_bytes must be 1024..5000000")
        rid=self.store.create_run(self.owner,p,pages_limit=max_pages,bytes_limit=max_bytes)
        return self.run_info(rid)

    def run_info(self,rid: str) -> dict:
        r=self.store.get_run(self.owner,rid)
        if not r: raise ResearchError("NOT_FOUND","Run not found")
        return r

    def execute(self,rid: str) -> dict:
        run=self.run_info(rid)
        project=self.project(run["project_id"])
        with self._locks_guard:
            lock=self._locks.setdefault(rid,threading.Lock())
        if not lock.acquire(blocking=False):
            raise ResearchError("ALREADY_RUNNING","This run is already executing")
        token=None
        try:
            if run["status"]=="COMPLETED":
                self.monitor.reconcile(self.owner, project["id"], rid)
                return run
            try:token=self.store.claim_run(rid)
            except ValueError as e:raise ResearchError("ALREADY_RUNNING",str(e)) from e
            started=time.monotonic()
            for source in run["sources"]:
                if source["state"]=="SUCCESS" or source["attempts"]>=2:
                    continue
                current=self.run_info(rid)
                if current["pages_used"]>=current["pages_limit"]:
                    self.store.finish_run(rid,token,"BUDGET_EXHAUSTED",detail="Page budget exhausted")
                    token=None
                    self.monitor.reconcile(self.owner, project["id"], rid)
                    return self.run_info(rid)
                remaining=current["bytes_limit"]-current["bytes_used"]
                if remaining<=0:
                    self.store.finish_run(rid,token,"BUDGET_EXHAUSTED",detail="Byte budget exhausted")
                    token=None
                    self.monitor.reconcile(self.owner, project["id"], rid)
                    return self.run_info(rid)
                if time.monotonic()-started>=60:
                    self.store.finish_run(rid,token,"PARTIAL",detail="Execution time cap reached")
                    token=None
                    self.monitor.reconcile(self.owner, project["id"], rid)
                    return self.run_info(rid)
                try:
                    fetched=self.fetcher.fetch(source["url"],byte_limit=min(self.policy.max_bytes,remaining))
                    if fetched.bytes_read>min(self.policy.max_bytes,remaining):
                        raise FetchError("Fetched response exceeded remaining byte budget")
                    sid=uid()
                    claims=claims_for(fetched.text,project["fields"],sid)
                    self.store.save_source(rid,source["url"],fetched,claims,lease_token=token)
                except (FetchError,ValueError) as exc:
                    self.store.fail_source(rid,source["url"],str(exc)[:350],lease_token=token)
                # Unexpected SQLite/IO exceptions propagate for independent
                # review; release_on_error permits safe retry of uncommitted URL.
            final=self.run_info(rid)
            if all(s["state"]=="SUCCESS" for s in final["sources"]):
                status,detail="COMPLETED","All approved sources completed"
            elif any(s["state"]=="SUCCESS" for s in final["sources"]):
                status,detail="PARTIAL","Some approved sources failed or exhausted retry attempts"
            else:
                status,detail="FAILED","No approved source completed"
            self.store.finish_run(rid,token,status,detail=detail)
            token=None
            self.monitor.reconcile(self.owner, project["id"], rid)
            return self.run_info(rid)
        finally:
            if token:
                try:self.store.release_on_error(rid,token)
                except Exception:pass  # DB may itself be unavailable
            lock.release()

    def schedule(self,pid:str)->dict:
        self.project(pid)
        return self.monitor.schedule(self.owner,pid)

    def configure_schedule(self,pid:str,*,enabled:bool,interval_seconds:int=86400,
                           max_pages:int=5,max_bytes:int=1_000_000)->dict:
        self.project(pid)
        try:
            return self.monitor.configure(self.owner,pid,enabled=enabled,
                                          interval_seconds=interval_seconds,
                                          pages_limit=max_pages,bytes_limit=max_bytes)
        except ValueError as e:
            raise ResearchError("INVALID_SCHEDULE",str(e)) from e

    def due_runs(self,*,maximum:int=3)->list[str]:
        try:return self.monitor.claim_due(self.owner,maximum=maximum)
        except ValueError as e:raise ResearchError("INVALID_SCHEDULE",str(e)) from e

    def run_due(self,*,maximum:int=3)->list[dict]:
        """Explicit one-shot local scheduler. Invoke from cron or systemd timer.

        Does not install a daemon or send outbound notifications. A failed
        worker is left at a durable checkpoint for a subsequent tick.
        """
        results=[]
        for rid in self.due_runs(maximum=maximum):
            results.append(self.execute(rid))
        return results

    def changes(self,pid:str,*,unread_only:bool=False)->list[dict]:
        self.project(pid)
        return self.monitor.changes(self.owner,pid,unread_only=unread_only)

    def history(self,pid:str)->dict:
        self.project(pid)
        return self.monitor.history(self.owner,pid)

    def digest(self,pid:str)->dict:
        self.project(pid)
        return self.monitor.digest(self.owner,pid)

    def digest_markdown(self,pid:str)->str:
        self.project(pid)
        return self.monitor.digest_markdown(self.owner,pid)

    def acknowledge_change(self,pid:str,event_id:str,read_state:str)->dict:
        self.project(pid)
        try:return self.monitor.acknowledge(self.owner,pid,event_id,read_state)
        except ValueError as e:raise ResearchError("NOT_FOUND",str(e)) from e

    def reconcile_run(self,rid:str)->list[dict]:
        run=self.run_info(rid)
        try:return self.monitor.reconcile(self.owner,run['project_id'],rid)
        except ValueError as e:raise ResearchError("INVALID_STATE",str(e)) from e

    def delete_project(self,pid:str)->None:
        self.project(pid)
        try:self.store.delete_project(self.owner,pid)
        except ValueError as e:raise ResearchError("INVALID_STATE",str(e)) from e

    def dossier(self,pid:str,rid:str)->dict:
        result=self.store.dossier(self.owner,pid,rid)
        if not result: raise ResearchError("NOT_FOUND","Dossier or run not found")
        # Reconcile only facts about the SAME labeled entity. Different
        # competitors are not contradictions merely because prices differ.
        cells=[]
        for label in sorted({x["label"] for x in result["project"]["sources"]}):
            urls={s["url"] for s in result["project"]["sources"] if s["label"]==label}
            for field in result["project"]["fields"]:
                matched=[c for c in result["claims"] if c["source_url"] in urls and c["field"]==field["key"]]
                supported=[c for c in matched if c["status"]=="SUPPORTED"]
                distinct={json.dumps(c["value"],sort_keys=True) for c in supported}
                if len(distinct)>1 or any(c["status"]=="CONFLICTED" for c in matched):
                    state="CONFLICTED";value=None
                elif supported:
                    state="SUPPORTED";value=supported[0]["value"]
                elif any(c["status"]=="NEEDS_REVIEW" for c in matched):
                    state="NEEDS_REVIEW";value=None
                else:
                    state="INSUFFICIENT";value=None
                cells.append({"subject":label,"field":field["key"],"status":state,
                              "value":value,"supporting_sources":len(supported),
                              "examined_sources":len(matched),"expected_sources":len(urls)})
        result["comparison"]=cells
        return result

    def latest_dossier(self,pid:str)->dict:
        self.project(pid)
        with self.store.db() as db:
            row=db.execute("SELECT id FROM runs WHERE project_id=? ORDER BY created_at DESC LIMIT 1",(pid,)).fetchone()
        if not row:raise ResearchError("NOT_FOUND","Project has no runs")
        return self.dossier(pid,row["id"])

    def export_markdown(self,pid:str,rid:str)->str:
        d=self.dossier(pid,rid)
        lines=["# Evidence Radar — local research dossier","",
               "> Live public-source extraction; exact quotations prove text presence only, not real-world factual truth.","",
               f"Question: {d['project']['question']}",f"Run: {rid} · {d['run']['status']}","",
               "| Source | Field | Result | State |", "|---|---|---|---|"]
        for c in d["claims"]:
            value=c["value"]
            label=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)
            def safe(x):return str(x).replace("|","\\|").replace("\n"," ")
            lines.append(f"| {safe(c['source_url'])} | {safe(c['field'])} | {safe(label)} | {c['status']} |")
        lines.extend(["","## Original source evidence",""])
        for c in d["claims"]:
            lines.append(f"### {c['field']} — {c['source_url']} ({c['status']})")
            lines.append(c["reason"])
            for a in c["evidence"]:
                lines.append(f"> {a['quote']}")
            lines.append(f"Captured at: {c['captured_at']} · Snapshot: {c['snapshot_id']} · SHA-256: {c['content_sha256']}")
            lines.append("")
        lines.append("Unresolved, conflicted and failed results are not silently inferred. No AI model was invoked by this deterministic workflow.")
        return "\n".join(lines)+"\n"
