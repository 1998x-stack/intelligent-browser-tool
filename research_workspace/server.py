"""Loopback-only authenticated research API and static UI; NOT a hosted SaaS server."""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit, unquote
import json
import secrets
import re
import time

from .research import ResearchService, ResearchError

_ROOT = Path(__file__).resolve().parents[1] / "apps" / "evidence-demo"
_ASSETS = {".html":"text/html; charset=utf-8", ".css":"text/css; charset=utf-8", ".js":"text/javascript; charset=utf-8", ".json":"application/json; charset=utf-8"}


def handler_factory(service: ResearchService, token: str, *, static_root: Path = _ROOT, executor=None):
    if len(token) < 24:
        raise ValueError("Local access token must be at least 24 characters")
    root=Path(static_root).resolve()
    pool=executor or ThreadPoolExecutor(max_workers=1)

    class Handler(BaseHTTPRequestHandler):
        server_version="EvidenceRadarLocal/0.2"
        def _headers(self, code: int, kind: str, length: int):
            self.send_response(code)
            self.send_header("Content-Type",kind)
            self.send_header("Content-Length",str(length))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("Referrer-Policy","no-referrer")
            self.send_header("X-Frame-Options","DENY")
            self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()

        def _respond(self,code:int,obj:dict|list):
            raw=json.dumps(obj,ensure_ascii=False).encode("utf-8")
            self._headers(code,"application/json; charset=utf-8",len(raw))
            self.wfile.write(raw)

        def _error(self,code:int,name:str,message:str):
            self._respond(code,{"error":{"code":name,"message":message}})

        def _gate(self)->bool:
            host=self.headers.get("Host","").lower()
            serverport=self.server.server_address[1]
            if host not in (f"127.0.0.1:{serverport}",f"localhost:{serverport}"):
                self._error(403,"INVALID_HOST","Local server only")
                return False
            if self.command in ("POST","DELETE"):
                origin=self.headers.get("Origin")
                if origin and origin not in (f"http://127.0.0.1:{serverport}",f"http://localhost:{serverport}"):
                    self._error(403,"INVALID_ORIGIN","Cross-origin requests not accepted")
                    return False
            if self.path.startswith("/api/") and not secrets.compare_digest(
                self.headers.get("Authorization", ""),"Bearer "+token):
                self._error(401,"UNAUTHORIZED","Local session access token is required")
                return False
            return True

        def _body(self)->dict:
            raw_length=self.headers.get("Content-Length","")
            if not raw_length.isdigit() or not 0<int(raw_length)<=16_384:
                raise ResearchError("INVALID_REQUEST","JSON body must be 1..16384 bytes")
            if "application/json" not in self.headers.get("Content-Type", ""):
                raise ResearchError("INVALID_REQUEST","Content-Type must be application/json")
            try:
                data=json.loads(self.rfile.read(int(raw_length)))
            except (ValueError,UnicodeDecodeError) as exc:
                raise ResearchError("INVALID_REQUEST","Invalid JSON payload") from exc
            if not isinstance(data,dict):
                raise ResearchError("INVALID_REQUEST","JSON object required")
            return data

        def do_GET(self):
            if not self._gate():return
            try:
                if self.path=="/api/v1/projects":
                    return self._respond(200,{"projects":service.projects()})
                if self.path=="/api/v1/policy":
                    return self._respond(200,{"hosts":list(service.policy.hosts),
                                              "respect_robots":service.policy.respect_robots,
                                              "max_source_bytes":service.policy.max_bytes,
                                              "mode":"local_operator_only"})
                if match:=re.fullmatch(r"/api/v1/projects/([a-f0-9]{32})/schedule",self.path):
                    return self._respond(200,service.schedule(match[1]))
                if match:=re.fullmatch(r"/api/v1/projects/([a-f0-9]{32})/changes",self.path):
                    return self._respond(200,{"changes":service.changes(match[1])})
                if match:=re.fullmatch(r"/api/v1/projects/([a-f0-9]{32})/history",self.path):
                    return self._respond(200,service.history(match[1]))
                if match:=re.fullmatch(r"/api/v1/projects/([a-f0-9]{32})/digest",self.path):
                    return self._respond(200,service.digest(match[1]))
                if match:=re.fullmatch(r"/api/v1/projects/([a-f0-9]{32})/digest.md",self.path):
                    rendered=service.digest_markdown(match[1]).encode('utf-8')
                    self._headers(200,"text/markdown; charset=utf-8",len(rendered))
                    return self.wfile.write(rendered)
                if match:=re.fullmatch(r"/api/v1/projects/([a-f0-9]{32})/runs",self.path):
                    return self._respond(200,{"runs":service.runs(match[1])})
                if match:=re.fullmatch(r"/api/v1/projects/([a-f0-9]{32})",self.path):
                    return self._respond(200,service.project(match[1]))
                if match:=re.fullmatch(r"/api/v1/runs/([a-f0-9]{32})",self.path):
                    return self._respond(200,service.run_info(match[1]))
                if match:=re.fullmatch(r"/api/v1/projects/([a-f0-9]{32})/runs/([a-f0-9]{32})/dossier",self.path):
                    return self._respond(200,service.dossier(match[1],match[2]))
                if match:=re.fullmatch(r"/api/v1/projects/([a-f0-9]{32})/runs/([a-f0-9]{32})/export.md",self.path):
                    rendered=service.export_markdown(match[1],match[2]).encode("utf-8")
                    self._headers(200,"text/markdown; charset=utf-8",len(rendered))
                    return self.wfile.write(rendered)
                if self.path.startswith("/api/"):
                    return self._error(404,"NOT_FOUND","Unknown API route")
                # Serve only local checked-in assets, no arbitrary filesystem browsing.
                cleaned=unquote(urlsplit(self.path).path).lstrip("/") or "index.html"
                file=(root/cleaned).resolve()
                if not file.is_relative_to(root) or file.suffix not in _ASSETS or not file.is_file():
                    return self._error(404,"NOT_FOUND","Asset unavailable")
                payload=file.read_bytes()
                self._headers(200,_ASSETS[file.suffix],len(payload))
                self.wfile.write(payload)
            except ResearchError as e:
                self._error(404 if e.code=="NOT_FOUND" else 400,e.code,str(e))

        def do_POST(self):
            if not self._gate():return
            try:
                data=self._body()
                if self.path=="/api/v1/projects":
                    return self._respond(201,service.create_project(data))
                if self.path=="/api/v1/monitor/tick":
                    ids=service.due_runs(maximum=data.get('maximum',3))
                    for rid in ids: pool.submit(service.execute,rid)
                    return self._respond(202,{"run_ids":ids,"delivery":"local_inbox_only"})
                if match:=re.fullmatch(r"/api/v1/projects/([a-f0-9]{32})/schedule",self.path):
                    result=service.configure_schedule(
                        match[1],enabled=data.get('enabled'),
                        interval_seconds=data.get('interval_seconds',86400),
                        max_pages=data.get('max_pages',5),
                        max_bytes=data.get('max_bytes',1_000_000))
                    return self._respond(200,result)
                if match:=re.fullmatch(r"/api/v1/projects/([a-f0-9]{32})/changes/([a-f0-9]{32})/ack",self.path):
                    return self._respond(200,service.acknowledge_change(
                        match[1],match[2],data.get('read_state'))) 
                if match:=re.fullmatch(r"/api/v1/runs/([a-f0-9]{32})/reconcile",self.path):
                    return self._respond(200,{"changes":service.reconcile_run(match[1])})
                if match:=re.fullmatch(r"/api/v1/projects/([a-f0-9]{32})/runs",self.path):
                    run=service.new_run(match[1],max_pages=data.get("max_pages",5),
                                        max_bytes=data.get("max_bytes",1_000_000))
                    pool.submit(service.execute,run["id"])
                    return self._respond(202,run)
                if match:=re.fullmatch(r"/api/v1/runs/([a-f0-9]{32})/resume",self.path):
                    run=service.run_info(match[1])
                    if run["status"] not in ("PARTIAL","FAILED","BUDGET_EXHAUSTED","RUNNING"):
                        raise ResearchError("INVALID_STATE","Only interrupted/failed runs can be resumed")
                    if run["status"]=="RUNNING" and run.get("leased_until") and run["leased_until"]>time.time():
                        raise ResearchError("ALREADY_RUNNING","Current worker lease has not expired")
                    pool.submit(service.execute,run["id"])
                    return self._respond(202,{"run_id":run["id"],"queued":True})
                return self._error(404,"NOT_FOUND","Unknown API route")
            except ResearchError as e:
                self._error(404 if e.code=="NOT_FOUND" else 400,e.code,str(e))

        def do_DELETE(self):
            if not self._gate():return
            try:
                if match:=re.fullmatch(r"/api/v1/projects/([a-f0-9]{32})",self.path):
                    service.delete_project(match[1])
                    return self._respond(200,{"deleted":True})
                return self._error(404,"NOT_FOUND","Unknown API route")
            except ResearchError as e:
                self._error(404 if e.code=="NOT_FOUND" else 400,e.code,str(e))

        def log_message(self,fmt,*args):
            # Don't log source questions, Authorization headers, or evidence bodies.
            return

    return Handler


def serve(service:ResearchService, *, port:int=8765, token:str|None=None):
    if not 1024<=port<=65535:
        raise ValueError("Local port must be 1024..65535")
    secret=token or secrets.token_urlsafe(32)
    if len(secret)<24:raise ValueError("Access token must be at least 24 characters")
    with ThreadPoolExecutor(max_workers=1) as pool:
        server=ThreadingHTTPServer(("127.0.0.1",port),handler_factory(service,secret,executor=pool))
        print(f"Evidence Radar local workspace: http://127.0.0.1:{port}/live.html",flush=True)
        print(f"Local access token (keep private): {secret}",flush=True)
        print("LOCAL ONLY: not a public or multi-tenant browser service.",flush=True)
        try:server.serve_forever()
        except KeyboardInterrupt:pass
        finally:server.server_close()
