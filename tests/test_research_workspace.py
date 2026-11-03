"""V0.2-B: independent source/claim/storage/security/transport verification."""
from __future__ import annotations
from http.server import ThreadingHTTPServer
from threading import Thread
import json
import sqlite3
import time
import urllib.error
import urllib.request
import hashlib
from pathlib import Path

import pytest
import requests
from research_workspace import ResearchService, ResearchError, SourcePolicy, FetchError, BoundedFetcher
from research_workspace.extraction import claims_for, digest, validate_anchors
from research_workspace.fetcher import FetchedPage, html_to_text
from research_workspace.server import handler_factory


URL_A="https://alpha.example/pricing"
URL_B="https://beta.example/pricing"


class FakeFetcher:
    def __init__(self, pages=None, fail_once=None):
        self.pages=pages or {URL_A:"Alpha Pro $29/month. API available.", URL_B:"Beta $49/year. Free plan."}
        self.fail_once=set(fail_once or [])
        self.calls=[]

    def fetch(self,url,*,byte_limit=None):
        self.calls.append((url,byte_limit))
        if url in self.fail_once:
            self.fail_once.remove(url)
            raise FetchError("Simulated transient timeout")
        text=self.pages[url]
        if len(text.encode())>byte_limit:raise FetchError("Fixture exceeded remaining byte budget")
        return FetchedPage(url,text,len(text.encode()),"text/html")


@pytest.fixture
def spec():
    return {"question":"Compare current pricing and API evidence",
            "sources":[{"url":URL_A,"label":"Alpha"},{"url":URL_B,"label":"Beta"}],
            "fields":[{"key":"monthly_price","kind":"price","label":"Published price"},
                      {"key":"api","kind":"keyword","hint":"API","label":"API statement"}]}


@pytest.fixture
def service(tmp_path):
    fetcher=FakeFetcher()
    s=ResearchService(tmp_path/"workspace.db",SourcePolicy(("alpha.example","beta.example"),respect_robots=False),fetcher=fetcher)
    return s,fetcher


def test_project_run_dossier_with_real_anchored_extract(service,spec):
    svc,fetcher=service
    project=svc.create_project(spec)
    run=svc.new_run(project["id"])
    completed=svc.execute(run["id"])
    assert completed["status"]=="COMPLETED"
    assert completed["pages_used"]==2
    data=svc.dossier(project["id"],run["id"])
    assert data["mode"]=="local_live" and len(data["sources"])==2
    assert len(data["claims"])==4
    price=[c for c in data["claims"] if c["field"]=="monthly_price"]
    assert {c["status"] for c in price}=={"SUPPORTED"}
    assert {c["value"]["period"] for c in price}=={"month","year"}
    assert all(c["evidence"] and all(e["valid"] for e in c["evidence"]) for c in price)
    assert all(s["content_sha256"]==digest(s["text"]) for s in data["sources"])
    assert any(c["status"]=="NEEDS_REVIEW" for c in data["claims"])
    assert all(not f["value"] for f in data["claims"] if f["status"]=="INSUFFICIENT")
    markdown=svc.export_markdown(project["id"],run["id"])
    assert "Original source evidence" in markdown and "No AI model" in markdown
    assert "SUPPORT" in markdown


def test_missing_keyword_never_marked_supported(service,spec):
    svc,_=service
    pid=svc.create_project(spec)["id"]
    rid=svc.new_run(pid)["id"]
    svc.execute(rid)
    d=svc.dossier(pid,rid)
    beta_api=next(c for c in d["claims"] if c["source_url"]==URL_B and c["field"]=="api")
    assert beta_api["status"]=="INSUFFICIENT" and beta_api["value"] is None
    assert beta_api["evidence"]==[]


def test_conflicting_prices_never_silently_chosen():
    text="Pro is $29/month and Team is $49/month."
    c=claims_for(text,[{"key":"pricing","kind":"price","hint":""}],"id")[0]
    assert c["status"]=="CONFLICTED" and c["value"] is None
    validate_anchors(text,c["anchors"])


def test_random_keyword_is_not_proof():
    text="Users mention API support but the limitations are unclear."
    c=claims_for(text,[{"key":"api","kind":"keyword","hint":"API"}],"id")[0]
    assert c["status"]=="NEEDS_REVIEW" and len(c["anchors"])==1
    validate_anchors(text,c["anchors"])


def test_html_is_safe_plain_text():
    raw=b'<html><body><nav>Ignore me</nav><p>Pro $29/month</p><script>alert(1)</script><button>Buy</button></body></html>'
    t=html_to_text(raw)
    assert t=="Pro $29/month"
    assert "<" not in t


def test_invalid_anchor_rejected():
    with pytest.raises(ValueError):
        validate_anchors("abc",[{"start":0,"end":2,"quote":"zz"}])
    with pytest.raises(ValueError):
        validate_anchors("abc",[{"start":-1,"end":2,"quote":"ab"}])


@pytest.mark.parametrize("url",[
    "http://127.0.0.1/internal", "http://localhost/admin", "file:///etc/passwd",
    "https://alpha.example:8080/", "https://user:pass@alpha.example/",
    "https://alpha.example.evil.com/", "https://169.254.169.254/latest/meta-data",
    "http://[::1]/", "http://alpha.example@127.0.0.1/",
])
def test_cannot_create_unauthorized_source(service,spec,url):
    svc,_=service
    spec["sources"]=[{"url":url}]
    with pytest.raises(ResearchError) as exc:
        svc.create_project(spec)
    assert exc.value.code=="SOURCE_OUTSIDE_POLICY"


def test_operator_allowlist_rejects_private_networks():
    for host in ["127.0.0.1","localhost","10.0.0.1","169.254.169.254","::1"]:
        with pytest.raises(ValueError):SourcePolicy((host,))


def test_project_validation_and_deduplicate(service,spec):
    svc,_=service
    spec["sources"].append({"url":URL_A+"#fragment","label":"Duplicate"})
    assert len(svc.create_project(spec)["sources"])==2
    spec["fields"].append({"key":"api","kind":"keyword","hint":"API"})
    with pytest.raises(ResearchError):svc.create_project(spec)


def test_project_and_dossier_scoped_to_owner(tmp_path,spec):
    file=tmp_path/"shared.db"
    s1=ResearchService(file,SourcePolicy(("alpha.example","beta.example"),respect_robots=False),
                       owner="one",fetcher=FakeFetcher())
    s2=ResearchService(file,SourcePolicy(("alpha.example","beta.example"),respect_robots=False),
                       owner="two",fetcher=FakeFetcher())
    p=s1.create_project(spec)
    rid=s1.new_run(p["id"])["id"]
    s1.execute(rid)
    with pytest.raises(ResearchError):s2.project(p["id"])
    with pytest.raises(ResearchError):s2.run_info(rid)
    with pytest.raises(ResearchError):s2.dossier(p["id"],rid)


def test_restart_preserves_success_and_retries_only_failed(tmp_path,spec):
    path=tmp_path/"resumable.db"
    first=FakeFetcher(fail_once=[URL_B])
    p=SourcePolicy(("alpha.example","beta.example"),respect_robots=False)
    one=ResearchService(path,p,fetcher=first)
    project=one.create_project(spec)
    rid=one.new_run(project["id"],max_pages=3)["id"]
    assert one.execute(rid)["status"]=="PARTIAL"
    assert len(one.dossier(project["id"],rid)["sources"])==1
    two=ResearchService(path,p,fetcher=FakeFetcher())
    assert two.execute(rid)["status"]=="COMPLETED"
    assert len(two.dossier(project["id"],rid)["sources"])==2
    assert two.run_info(rid)["pages_used"]==3
    assert two.fetcher.calls==[(URL_B,400_000)]


def test_page_budget_exhaustion_preserves_completed_result(service,spec):
    svc,fetcher=service
    pid=svc.create_project(spec)["id"]
    rid=svc.new_run(pid,max_pages=1)["id"]
    result=svc.execute(rid)
    assert result["status"]=="BUDGET_EXHAUSTED"
    assert len(svc.dossier(pid,rid)["sources"])==1
    assert svc.execute(rid)["status"]=="BUDGET_EXHAUSTED"
    assert fetcher.calls==[(URL_A,400_000)]


def test_byte_budget_hard_stop(service,spec):
    svc,fetcher=service
    pid=svc.create_project(spec)["id"]
    rid=svc.new_run(pid,max_bytes=1024)["id"]
    assert svc.execute(rid)["status"]=="COMPLETED"
    assert all(limit<=1024 for _,limit in fetcher.calls)


def test_db_fault_rolls_back_page_and_evidence(service,spec):
    svc,_=service
    pid=svc.create_project(spec)["id"]
    rid=svc.new_run(pid)["id"]
    with svc.store.db() as db:
        db.execute("""CREATE TRIGGER reject_claim BEFORE INSERT ON claims
                      BEGIN SELECT RAISE(ABORT,'injected fault'); END""")
    with pytest.raises(sqlite3.IntegrityError):svc.execute(rid)
    assert svc.run_info(rid)["sources"][0]["state"]=="PENDING"
    with svc.store.db() as db:
        assert not db.execute("SELECT 1 FROM snapshots WHERE run_id=?",(rid,)).fetchone()
        db.execute("DROP TRIGGER reject_claim")
    assert svc.execute(rid)["status"]=="COMPLETED"


def test_expired_run_source_cannot_commit_twice(service,spec):
    svc,fetcher=service
    pid=svc.create_project(spec)["id"]
    rid=svc.new_run(pid)["id"]
    svc.execute(rid)
    from research_workspace.extraction import claims_for
    snap=svc.dossier(pid,rid)["sources"][0]
    fetched=FetchedPage(snap["final_url"],snap["text"],snap["byte_count"],"text/html")
    with pytest.raises(ValueError,match="Stale"):svc.store.save_source(
        rid,URL_A,fetched,claims_for(fetched.text,spec["fields"],"newid"),lease_token="stale")


def test_robots_policy_default_enabled():
    assert SourcePolicy(("example.com",)).respect_robots


class DummyResponse:
    def __init__(self,code=200,body=b"<p>OK</p>",typ="text/html",location=None):
        self.status_code=code
        self.headers={"Content-Type":typ}
        if location:self.headers["Location"]=location
        self.body=body
    def iter_content(self,chunk_size):
        yield self.body
    def __enter__(self):return self
    def __exit__(self,*args):pass


class DummySession:
    def __init__(self,responses):self.responses=list(responses);self.calls=[];self.headers={};self.trust_env=True
    def get(self,url,**kwargs):
        self.calls.append((url,kwargs))
        return self.responses.pop(0)


def test_real_fetcher_does_not_follow_cross_domain_redirect(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo",lambda *a,**kw: [(None,None,None,None,("93.184.216.34",443))])
    session=DummySession([DummyResponse(302,location="https://attacker.example/private")])
    reader=BoundedFetcher(SourcePolicy(("alpha.example",),respect_robots=False,min_interval_seconds=0),session=session)
    with pytest.raises(FetchError,match="outside"):
        reader.fetch(URL_A)
    assert len(session.calls)==1 and session.calls[0][1]["allow_redirects"] is False
    assert session.trust_env is False


def test_real_fetcher_limits_body_and_content_type(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo",lambda *a,**kw: [(None,None,None,None,("93.184.216.34",443))])
    for responses, msg in [([DummyResponse(body=b"a"*500)],"byte limit"),
                           ([DummyResponse(200,typ="application/octet-stream")],"HTML/plain-text")]:
        session=DummySession(responses)
        reader=BoundedFetcher(SourcePolicy(("alpha.example",),respect_robots=False,max_bytes=100,min_interval_seconds=0),session=session)
        with pytest.raises(FetchError,match=msg):reader.fetch(URL_A)


def test_real_fetcher_no_redirect_success(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo",lambda *a,**kw: [(None,None,None,None,("93.184.216.34",443))])
    reader=BoundedFetcher(SourcePolicy(("alpha.example",),respect_robots=False,min_interval_seconds=0),session=DummySession([
        DummyResponse(body=b"<div>Pro $29/month</div>")]))
    page=reader.fetch(URL_A)
    assert page.text=="Pro $29/month" and page.bytes_read==24


@pytest.fixture
def running_server(service):
    svc,_=service
    token="localsecret-"+"x"*40
    instance=ThreadingHTTPServer(("127.0.0.1",0),handler_factory(svc,token))
    t=Thread(target=instance.serve_forever,daemon=True); t.start()
    yield f"http://127.0.0.1:{instance.server_port}",token
    instance.shutdown();instance.server_close();t.join(timeout=3)


def _api(base,path,*,token=None,method="GET",data=None,headers=None):
    hdr=dict(headers or {})
    if token:hdr["Authorization"]="Bearer "+token
    if data is not None:hdr["Content-Type"]="application/json"
    raw=json.dumps(data).encode() if data is not None else None
    req=urllib.request.Request(base+path,headers=hdr,data=raw,method=method)
    try:
        with urllib.request.urlopen(req,timeout=5) as response:
            body=response.read(); return response.status, dict(response.headers),json.loads(body) if "json" in response.headers.get("Content-Type","") else body.decode()
    except urllib.error.HTTPError as exc:
        return exc.code,dict(exc.headers),json.loads(exc.read())


def test_api_auth_host_origin_and_static_csp(running_server,spec):
    base,token=running_server
    code,_,_= _api(base,"/api/v1/projects")
    assert code==401
    code,_,_= _api(base,"/api/v1/projects",token="wrong")
    assert code==401
    code,h,landing=_api(base,"/live.html")
    assert code==200 and "local research" in landing.lower()
    assert h["X-Content-Type-Options"]=="nosniff" and "script-src 'self'" in h["Content-Security-Policy"]
    code,_,_= _api(base,"/api/v1/projects",token=token,method="POST",data=spec,headers={"Origin":"https://attacker.example"})
    assert code==403
    code,_,_= _api(base,"/api/v1/projects",token=token,headers={"Host":"evil.example"})
    assert code==403
    code,_,_= _api(base,"/../../etc/passwd")
    assert code==404


def test_api_authenticated_create_run_and_export(running_server,spec):
    base,token=running_server
    code,_,project=_api(base,"/api/v1/projects",token=token,method="POST",data=spec)
    assert code==201
    code,_,run=_api(base,f"/api/v1/projects/{project['id']}/runs",token=token,method="POST",data={"max_pages":5})
    assert code==202
    for i in range(40):
        _,_,run=_api(base,f"/api/v1/runs/{run['id']}",token=token)
        if run["status"] not in ("CREATED","RUNNING"):break
        time.sleep(.03)
    assert run["status"]=="COMPLETED"
    code,_,dossier=_api(base,f"/api/v1/projects/{project['id']}/runs/{run['id']}/dossier",token=token)
    assert code==200 and len(dossier["claims"])==4
    code,_,md=_api(base,f"/api/v1/projects/{project['id']}/runs/{run['id']}/export.md",token=token)
    assert code==200 and "Original source evidence" in md


def test_cross_source_same_subject_conflict_not_different_competitors(service,spec):
    svc,fetcher=service
    pid=svc.create_project(spec)["id"]
    rid=svc.new_run(pid)["id"]
    svc.execute(rid)
    cells=svc.dossier(pid,rid)["comparison"]
    assert all(c["status"]=="SUPPORTED" for c in cells if c["field"]=="monthly_price")

    spec["sources"]=[{"url":URL_A,"label":"One brand"},{"url":URL_B,"label":"One brand"}]
    pid2=svc.create_project(spec)["id"]
    rid2=svc.new_run(pid2)["id"]
    svc.execute(rid2)
    all_cells=svc.dossier(pid2,rid2)["comparison"]
    price=next(c for c in all_cells if c["field"]=="monthly_price")
    assert price["status"]=="CONFLICTED" and price["value"] is None
    assert price["examined_sources"]==2


def test_worker_lease_fences_second_process_and_stale_token(tmp_path,spec):
    database=tmp_path/"lease.db"
    policy=SourcePolicy(("alpha.example","beta.example"),respect_robots=False)
    one=ResearchService(database,policy,fetcher=FakeFetcher())
    two=ResearchService(database,policy,fetcher=FakeFetcher())
    pid=one.create_project(spec)["id"]
    rid=one.new_run(pid)["id"]
    original=one.store.claim_run(rid)
    with pytest.raises(ResearchError,match="already leased"):
        two.execute(rid)
    with pytest.raises(ValueError,match="Stale"):
        one.store.finish_run(rid,"wrong","COMPLETED")
    with one.store.db() as db:
        db.execute("UPDATE runs SET leased_until=0 WHERE id=?",(rid,))
    newer=two.store.claim_run(rid)
    assert newer!=original
    with pytest.raises(ValueError,match="Stale"):
        one.store.finish_run(rid,original,"COMPLETED")
    two.store.finish_run(rid,newer,"PARTIAL",detail="Reclaimed after stale worker")
    assert two.execute(rid)["status"]=="COMPLETED"
    assert "worker_token" not in two.run_info(rid)


def test_deletion_removes_all_owned_source_data_and_stops_running(service,spec):
    svc,_=service
    pid=svc.create_project(spec)["id"]
    rid=svc.new_run(pid)["id"]
    token=svc.store.claim_run(rid)
    with pytest.raises(ResearchError,match="Cannot delete"):
        svc.delete_project(pid)
    svc.store.finish_run(rid,token,"PARTIAL")
    svc.execute(rid)
    svc.delete_project(pid)
    assert svc.projects()==[]
    with pytest.raises(ResearchError):svc.project(pid)
    with svc.store.db() as db:
        assert db.execute("SELECT count(*) FROM snapshots").fetchone()[0]==0
        assert db.execute("SELECT count(*) FROM claims").fetchone()[0]==0
        assert db.execute("SELECT count(*) FROM run_events").fetchone()[0]==0
        assert db.execute("SELECT count(*) FROM run_sources").fetchone()[0]==0


def test_api_delete_project_and_access_policy(running_server,spec):
    base,token=running_server
    assert _api(base,"/api/v1/policy",token=token)[2]["hosts"]==["alpha.example","beta.example"]
    _,_,project=_api(base,"/api/v1/projects",token=token,method="POST",data=spec)
    code,_,_= _api(base,f"/api/v1/projects/{project['id']}",method="DELETE",token=token,headers={"Origin":"https://evil.example"})
    assert code==403
    code,_,body=_api(base,f"/api/v1/projects/{project['id']}",method="DELETE",token=token)
    assert code==200 and body=={"deleted":True}
    assert _api(base,"/api/v1/projects",token=token)[2]["projects"]==[]


def test_error_recover_run_not_marked_complete(service,spec):
    svc,_=service
    pid=svc.create_project(spec)["id"]
    rid=svc.new_run(pid)["id"]
    with svc.store.db() as db:
        db.execute("""CREATE TRIGGER interrupt_commit BEFORE INSERT ON snapshots
                      BEGIN SELECT RAISE(ABORT,'storage unavailable'); END""")
    with pytest.raises(sqlite3.IntegrityError):svc.execute(rid)
    assert svc.run_info(rid)["status"]=="PARTIAL"
    with svc.store.db() as db:db.execute("DROP TRIGGER interrupt_commit")
    assert svc.execute(rid)["status"]=="COMPLETED"


def test_independent_labeled_extraction_goldens():
    cases=json.loads((Path(__file__).parent/"fixtures"/"research_goldens.json").read_text(encoding="utf-8"))
    assert len(cases)>=12
    for case in cases:
        field={"key":"field","kind":case["kind"],"hint":case["hint"]}
        result=claims_for(case["text"],[field],"snap")[0]
        assert result["status"]==case["expected_status"],case["name"]
        for key,field in [("expected_amount","amount"),("expected_currency","currency"),
                           ("expected_period","period"),("expected_billing","billing_condition")]:
            if key in case:assert result["value"][field]==case[key],case["name"]
        validate_anchors(case["text"],result["anchors"])
