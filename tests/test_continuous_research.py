"""V0.3 independent semantic-diff goldens, durable schedule, API and failure tests."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from threading import Thread
import json
import sqlite3
import time
import urllib.error
import urllib.request

import pytest
from research_workspace import ResearchService, SourcePolicy, FetchError, ResearchError
from research_workspace.fetcher import FetchedPage
from research_workspace.server import handler_factory

A='https://alpha.example/pricing'
A2='https://alpha.example/plans'
B='https://beta.example/pricing'


class FakeFetcher:
    def __init__(self, content=None):
        self.content=content or {A:'Alpha Pro is $29/month. API coming soon.',
                                 B:'Beta plans: $49/year.'}
        self.calls=[]
    def fetch(self,url,*,byte_limit=None):
        self.calls.append(url)
        text=self.content.get(url)
        if text is None: raise FetchError('Simulated source unavailable')
        if len(text.encode())>byte_limit: raise FetchError('Source exceeds byte budget')
        return FetchedPage(url,text,len(text.encode()),'text/plain')


@pytest.fixture
def system(tmp_path):
    policy=SourcePolicy(('alpha.example','beta.example'),respect_robots=False)
    fetcher=FakeFetcher()
    svc=ResearchService(tmp_path/'monitor.db',policy,fetcher=fetcher)
    spec={'question':'Compare documented pricing and API availability',
          'sources':[{'url':A,'label':'Alpha'},{'url':B,'label':'Beta'}],
          'fields':[{'key':'price','kind':'price','label':'Published price'},
                    {'key':'feature','kind':'keyword','hint':'API','label':'API claim'}]}
    pid=svc.create_project(spec)['id']
    return svc,fetcher,pid


def run(svc,pid):
    rid=svc.new_run(pid)['id']
    return rid, svc.execute(rid)


def test_price_change_has_old_and_new_proof_and_is_idempotent(system):
    svc,fetcher,pid=system
    old,_=run(svc,pid)
    assert svc.changes(pid)==[]  # no phantom first-run alert
    fetcher.content[A]='Alpha Pro is $39/month. Updated 2026-11-03. API coming soon.'
    current,res=run(svc,pid)
    assert res['status']=='COMPLETED'
    changes=svc.changes(pid)
    assert len(changes)==1
    event=changes[0]
    assert event['kind']=='CHANGED' and event['subject']=='Alpha' and event['field_key']=='price'
    assert event['old_value']['amount']=='29' and event['new_value']['amount']=='39'
    assert event['previous_run_id']==old and event['current_run_id']==current
    assert '29/month' in event['old_evidence'][0]['quote']
    assert '39/month' in event['new_evidence'][0]['quote']
    assert event['old_evidence'][0]['snapshot_id']!=event['new_evidence'][0]['snapshot_id']
    assert svc.reconcile_run(current)==[]
    assert len(svc.changes(pid))==1


def test_timestamp_dom_noise_same_facts_produces_no_changes(system):
    svc,fetcher,pid=system
    run(svc,pid)
    fetcher.content[A]='New site layout. Updated today 2026-11-03. Alpha Pro is $29/month. API coming soon.'
    run(svc,pid)
    assert svc.changes(pid)==[]


def test_failed_fetch_is_health_not_false_removed_price(system):
    svc,fetcher,pid=system
    run(svc,pid)
    fetcher.content.pop(A)
    rid,result=run(svc,pid)
    assert result['status']=='PARTIAL'
    assert svc.changes(pid)==[]
    hist=svc.history(pid)
    assert any(x['url']==A and x['state']=='FAILED' for x in hist['source_health'])
    digest=svc.digest(pid)
    assert digest['verified_changes']==[] and digest['delivery']=='local_inbox_only'


def test_missing_value_to_new_supported_price_is_added(system):
    svc,fetcher,pid=system
    fetcher.content[A]='Alpha Pro. Contact sales for quote.'
    run(svc,pid)
    fetcher.content[A]='Alpha Pro now costs $30/month.'
    run(svc,pid)
    changes=svc.changes(pid)
    assert len(changes)==1 and changes[0]['kind']=='ADDED'
    assert changes[0]['old_value'] is None and changes[0]['new_value']['amount']=='30'


def test_unknown_to_unknown_not_interpreted_as_price_change(system):
    svc,fetcher,pid=system
    fetcher.content[A]='Contact us for a quote.'
    run(svc,pid)
    fetcher.content[A]='Call us for enterprise pricing.'
    run(svc,pid)
    assert svc.changes(pid)==[]


def test_conflicted_public_price_requires_review_not_confirmed_change(system):
    svc,fetcher,pid=system
    run(svc,pid)
    fetcher.content[A]='Alpha Pro is $29/month and Team is $49/month.'
    run(svc,pid)
    events=svc.changes(pid)
    assert any(e['field_key']=='price' and e['kind']=='REVIEW_REQUIRED' for e in events)
    assert svc.digest(pid)['verified_changes']==[]
    assert any(e['field_key']=='price' for e in svc.digest(pid)['needs_review'])


def test_same_subject_two_sites_requires_full_coverage_and_normalization(tmp_path):
    svc=ResearchService(tmp_path/'x.db',SourcePolicy(('alpha.example',),respect_robots=False),
                        fetcher=FakeFetcher({A:'Alpha Pro is $29/month.',A2:'Alpha Pro is $29/month.'}))
    p=svc.create_project({'question':'Are pricing pages consistent across public sources?',
            'sources':[{'url':A,'label':'Alpha'},{'url':A2,'label':'Alpha'}],
            'fields':[{'key':'price','kind':'price','label':'Published price'}]})
    run(svc,p['id'])
    svc.fetcher.content[A2]='Alpha Pro is $40/month.'
    run(svc,p['id'])
    events=svc.changes(p['id'])
    assert len(events)==1 and events[0]['kind']=='REVIEW_REQUIRED'
    svc.fetcher.content.pop(A2)
    run(svc,p['id'])
    assert len(svc.changes(p['id']))==1 # no false alert when one source fails


def test_explicit_opt_in_schedule_validation_and_tick(system):
    svc,fetcher,pid=system
    assert svc.schedule(pid)['enabled'] is False
    with pytest.raises(ResearchError):svc.configure_schedule(pid,enabled=True,interval_seconds=10)
    cfg=svc.configure_schedule(pid,enabled=True,interval_seconds=3600)
    assert cfg['enabled'] is True
    assert svc.due_runs()==[] # schedule does not fire immediately
    with svc.store.db() as db:
        db.execute('UPDATE research_schedules SET next_due_epoch=? WHERE project_id=?',(time.time()-5,pid))
    jobs=svc.due_runs()
    assert len(jobs)==1
    # Recover a CREATED scheduled run before execution, never create duplicate.
    assert svc.due_runs()==jobs
    assert svc.execute(jobs[0])['status']=='COMPLETED'
    assert svc.due_runs()==[]
    assert svc.configure_schedule(pid,enabled=False,interval_seconds=3600)['enabled'] is False


def test_sqlite_scheduler_atomic_under_multiple_processes(system):
    svc,_,pid=system
    svc.configure_schedule(pid,enabled=True,interval_seconds=3600)
    with svc.store.db() as db:
        db.execute('UPDATE research_schedules SET next_due_epoch=? WHERE project_id=?',(time.time()-10,pid))
    p=SourcePolicy(('alpha.example','beta.example'),respect_robots=False)
    other=ResearchService(svc.store.path,p,fetcher=FakeFetcher())
    with ThreadPoolExecutor(max_workers=2) as pool:
        one,two=pool.map(lambda service: service.due_runs(),[svc,other])
    assert one==two and len(one)==1
    assert len(svc.runs(pid))==1


def test_local_digest_ack_ignore_and_project_deletion(system):
    svc,fetcher,pid=system
    run(svc,pid)
    fetcher.content[A]='Alpha Pro is $39/month.'
    rid,_=run(svc,pid)
    e=next(e for e in svc.changes(pid) if e['field_key']=='price')
    assert '39' in svc.digest_markdown(pid)
    assert svc.acknowledge_change(pid,e['id'],'IGNORED')['read_state']=='IGNORED'
    assert svc.digest(pid)['verified_changes']==[]
    assert any(e['kind']=='CHANGED' for e in svc.changes(pid))
    svc.configure_schedule(pid,enabled=True,interval_seconds=86400)
    svc.delete_project(pid)
    with svc.store.db() as db:
        for table in ['research_schedules','research_changes','research_reconciliations','runs','snapshots']:
            assert db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]==0


def test_monitoring_cross_owner_rejected(tmp_path):
    path=tmp_path/'shared.db';policy=SourcePolicy(('alpha.example',),respect_robots=False)
    a=ResearchService(path,policy,fetcher=FakeFetcher(),owner='operator-a')
    b=ResearchService(path,policy,fetcher=FakeFetcher(),owner='operator-b')
    pid=a.create_project({'question':'Compare published prices for Alpha plan',
        'sources':[{'url':A,'label':'Alpha'}],
        'fields':[{'key':'price','kind':'price','label':'Price'}]})['id']
    a.configure_schedule(pid,enabled=True,interval_seconds=86400)
    assert b.due_runs()==[]
    for fn in [lambda:b.changes(pid),lambda:b.history(pid),lambda:b.digest(pid),
               lambda:b.configure_schedule(pid,enabled=True),lambda:b.schedule(pid)]:
        with pytest.raises(ResearchError):fn()


def test_reconciliation_trigger_fault_rolls_back_idempotently(system):
    svc,fetcher,pid=system
    run(svc,pid)
    fetcher.content[A]='Alpha Pro is $39/month.'
    rid=svc.new_run(pid)['id']
    with svc.store.db() as db:
        db.execute('''CREATE TRIGGER stop_changes BEFORE INSERT ON research_changes
          BEGIN SELECT RAISE(ABORT,'injected failure'); END''')
    with pytest.raises(sqlite3.IntegrityError):svc.execute(rid)
    assert svc.run_info(rid)['status']=='COMPLETED'
    with svc.store.db() as db:
        assert not db.execute('SELECT 1 FROM research_reconciliations WHERE run_id=?',(rid,)).fetchone()
        assert not db.execute('SELECT 1 FROM research_changes WHERE current_run_id=?',(rid,)).fetchone()
        db.execute('DROP TRIGGER stop_changes')
    svc.reconcile_run(rid)
    assert sum(e['kind']=='CHANGED' for e in svc.changes(pid))==1


def _request(base,path,token,method='GET',body=None):
    payload=json.dumps(body).encode() if body is not None else None
    request=urllib.request.Request(base+path,data=payload,method=method,
      headers={'Host':base.split('//')[1],'Authorization':'Bearer '+token,
               'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=4) as r:
            raw=r.read();return r.status,json.loads(raw) if r.headers.get('Content-Type','').startswith('application/json') else raw.decode()
    except urllib.error.HTTPError as error:
        return error.code,json.loads(error.read())


def test_monitoring_api_auth_schedule_change_digest_and_ack(system):
    svc,fetcher,pid=system
    token='testtoken-'+'z'*35
    instance=ThreadingHTTPServer(('127.0.0.1',0),handler_factory(svc,token))
    thread=Thread(target=instance.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{instance.server_port}'
    try:
        assert _request(base,f'/api/v1/projects/{pid}/schedule','wrong')[0]==401
        result,body=_request(base,f'/api/v1/projects/{pid}/schedule',token,'POST',
                             {'enabled':True,'interval_seconds':86400})
        assert result==200 and body['enabled'] is True
        assert _request(base,f'/api/v1/projects/{pid}/schedule',token)[1]['enabled']
        assert _request(base,'/api/v1/monitor/tick',token,'POST',{})[1]['run_ids']==[]
        run(svc,pid)
        fetcher.content[A]='Alpha Pro is $39/month.'
        run(svc,pid)
        code,changes=_request(base,f'/api/v1/projects/{pid}/changes',token)
        assert code==200 and any(e['kind']=='CHANGED' for e in changes['changes'])
        ev=next(e for e in changes['changes'] if e['kind']=='CHANGED')
        assert _request(base,f'/api/v1/projects/{pid}/changes/{ev["id"]}/ack',token,'POST',
                        {'read_state':'ACKNOWLEDGED'})[1]['read_state']=='ACKNOWLEDGED'
        assert _request(base,f'/api/v1/projects/{pid}/digest',token)[1]['verified_changes']==[]
        code,md=_request(base,f'/api/v1/projects/{pid}/digest.md',token)
        assert code==200 and 'No new supported fact changes' in md
        assert _request(base,f'/api/v1/projects/{pid}/history',token)[1]['change_count']>=1
    finally:
        instance.shutdown();instance.server_close();thread.join(timeout=2)


def test_keyword_present_or_removed_is_review_candidate_only(system):
    svc,fetcher,pid=system
    fetcher.content[A]='Alpha Pro is $29/month.'
    run(svc,pid)
    fetcher.content[A]='Alpha Pro is $29/month. API preview available.'
    run(svc,pid)
    event=svc.changes(pid)[0]
    assert event['field_key']=='feature' and event['kind']=='REVIEW_REQUIRED'
    assert svc.digest(pid)['verified_changes']==[]


def test_accessible_source_price_disappearance_requires_review_not_removal(system):
    svc,fetcher,pid=system
    run(svc,pid)
    fetcher.content[A]='Alpha Pro: contact sales. API coming soon.'
    run(svc,pid)
    changes=svc.changes(pid)
    assert len(changes)==1 and changes[0]['kind']=='REVIEW_REQUIRED'
    assert changes[0]['new_value'] is None
    assert svc.digest(pid)['verified_changes']==[]


def test_blind_version_pair_goldens_for_strict_price_extraction(tmp_path):
    """Fixture-only check, NOT an observed real-world notification accuracy claim."""
    from pathlib import Path
    fixtures=json.loads((Path(__file__).parent/'fixtures'/'monitoring_goldens.json').read_text())
    assert len(fixtures)==20
    correct=0
    for item in fixtures:
        f=FakeFetcher({A:item['before']})
        s=ResearchService(tmp_path/(item['name']+'.db'),
          SourcePolicy(('alpha.example',),respect_robots=False),fetcher=f)
        pid=s.create_project({'question':'Check published price for the single Alpha plan',
           'sources':[{'url':A,'label':'Alpha'}],
           'fields':[{'key':'price','kind':'price','label':'Price'}]})['id']
        run(s,pid)
        if item['after'] is None:f.content.pop(A)
        else:f.content[A]=item['after']
        run(s,pid)
        event=s.changes(pid)
        observed=event[0]['kind'] if event else 'NONE'
        assert observed==item['expected'],item['name']
        correct+=(observed==item['expected'])
    assert correct==20


def test_v02b_database_migrates_without_replacing_earlier_runs(tmp_path):
    path=tmp_path/'existing.db'
    policy=SourcePolicy(('alpha.example',),respect_robots=False)
    from research_workspace.store import ResearchStore
    old=ResearchStore(path)
    with old.db() as db:
        db.execute('PRAGMA user_version=1')
    s=ResearchService(path,policy,fetcher=FakeFetcher())
    with s.store.db() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==2
    p=s.create_project({'question':'Price continuity in persisted local database',
       'sources':[{'url':A,'label':'Alpha'}],
       'fields':[{'key':'price','kind':'price','label':'Price'}]})
    s.execute(s.new_run(p['id'])['id'])
    other=ResearchService(path,policy,fetcher=FakeFetcher())
    assert other.runs(p['id'])
    assert other.history(p['id'])['runs']
