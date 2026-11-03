"""V0.3 fact-level research history, bounded schedules and an in-app change inbox.

This module does not send email, execute background timers or certify semantic
truth. Only exact, supported, normalized price facts become confirmed changes.
Uncertain/failed fetches cannot be treated as a verified price change.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from .store import uid, now, pack, unpack


MIN_INTERVAL = 3600  # one hour; local operator schedules only
MAX_INTERVAL = 30 * 86400


def ensure_schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS research_schedules (
          project_id TEXT PRIMARY KEY REFERENCES projects(id),
          enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
          interval_seconds INTEGER NOT NULL,
          next_due_epoch REAL NOT NULL,
          pages_limit INTEGER NOT NULL,
          bytes_limit INTEGER NOT NULL,
          last_run_id TEXT,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS research_schedule_due
          ON research_schedules(enabled,next_due_epoch);
        CREATE TABLE IF NOT EXISTS research_changes (
          id TEXT PRIMARY KEY,
          project_id TEXT NOT NULL REFERENCES projects(id),
          previous_run_id TEXT NOT NULL REFERENCES runs(id),
          current_run_id TEXT NOT NULL REFERENCES runs(id),
          subject TEXT NOT NULL,
          field_key TEXT NOT NULL,
          kind TEXT NOT NULL CHECK(kind IN ('CHANGED','ADDED','REVIEW_REQUIRED')),
          severity TEXT NOT NULL,
          old_value_json TEXT,
          new_value_json TEXT,
          old_evidence_json TEXT NOT NULL,
          new_evidence_json TEXT NOT NULL,
          read_state TEXT NOT NULL DEFAULT 'UNREAD'
            CHECK(read_state IN ('UNREAD','ACKNOWLEDGED','IGNORED')),
          created_at TEXT NOT NULL,
          UNIQUE(current_run_id,subject,field_key)
        );
        CREATE INDEX IF NOT EXISTS research_changes_project
          ON research_changes(project_id,created_at);
        CREATE TABLE IF NOT EXISTS research_reconciliations (
          run_id TEXT PRIMARY KEY REFERENCES runs(id),
          previous_run_id TEXT,
          reconciled_at TEXT NOT NULL
        );
    """)
    db.execute("PRAGMA user_version=2")


def _fact_state(rows):
    """Conservative reduction of multiple public pages for one subject/field."""
    if not rows:
        return ('INSUFFICIENT',None,[])
    evidence=[]
    values={}
    conflict=False
    needs_review=False
    for c in rows:
        if c['status']=='CONFLICTED': conflict=True
        if c['status']=='NEEDS_REVIEW': needs_review=True
        if c['status']!='SUPPORTED': continue
        value=unpack(c['value_json'])
        if not isinstance(value,dict):
            needs_review=True
            continue
        key=pack(value)
        values[key]=value
        anchors=unpack(c['anchors_json'])
        for a in anchors:
            if a.get('stance')=='supports':
                evidence.append({'source_url':c['url'],'snapshot_id':c['snapshot_id'],
                                 'content_sha256':c['content_sha256'],'captured_at':c['captured_at'],
                                 'quote':a['quote'],'start':a['start'],'end':a['end']})
    if conflict or len(values)>1: return ('CONFLICTED',None,evidence)
    if needs_review: return ('NEEDS_REVIEW',None,evidence)
    if len(values)==1 and evidence: return ('SUPPORTED',next(iter(values.values())),evidence)
    return ('INSUFFICIENT',None,[])


class Monitoring:
    def __init__(self, store):
        self.store=store

    def configure(self, owner, pid, *, enabled, interval_seconds=86400,
                  pages_limit=5, bytes_limit=1_000_000, clock=None):
        if type(enabled) is not bool:
            raise ValueError('enabled must be a boolean')
        if type(interval_seconds) is not int or not MIN_INTERVAL<=interval_seconds<=MAX_INTERVAL:
            raise ValueError('interval_seconds must be between 3600 and 2592000')
        if type(pages_limit) is not int or not 1<=pages_limit<=5:
            raise ValueError('pages_limit must be 1..5')
        if type(bytes_limit) is not int or not 1024<=bytes_limit<=5_000_000:
            raise ValueError('bytes_limit must be 1024..5000000')
        timestamp=time.time() if clock is None else clock
        with self.store.tx() as db:
            if not db.execute('SELECT 1 FROM projects WHERE id=? AND owner=?',(pid,owner)).fetchone():
                raise ValueError('Project unavailable')
            db.execute('''INSERT INTO research_schedules
              (project_id,enabled,interval_seconds,next_due_epoch,pages_limit,bytes_limit,updated_at)
              VALUES(?,?,?,?,?,?,?)
              ON CONFLICT(project_id) DO UPDATE SET enabled=excluded.enabled,
              interval_seconds=excluded.interval_seconds,next_due_epoch=excluded.next_due_epoch,
              pages_limit=excluded.pages_limit,bytes_limit=excluded.bytes_limit,
              updated_at=excluded.updated_at''',
              (pid,int(enabled),interval_seconds,timestamp+interval_seconds,
               pages_limit,bytes_limit,now()))
        return self.schedule(owner,pid)

    def schedule(self, owner, pid):
        with self.store.db() as db:
            r=db.execute('''SELECT s.* FROM research_schedules s
              JOIN projects p ON p.id=s.project_id WHERE p.owner=? AND p.id=?''',
              (owner,pid)).fetchone()
            if not r:
                return {'enabled':False,'interval_seconds':None,'next_due_epoch':None,
                        'last_run_id':None}
            result=dict(r)
            result['enabled']=bool(result['enabled'])
            return result

    def claim_due(self, owner, *, maximum=3, clock=None):
        """Atomic schedule advancement; no duplicate run per due interval.

        Recovers CREATED or expired RUNNING scheduled work before allocating new
        jobs. A worker may see the same unfinished job twice; run leases fence
        actual execution, and callers must be idempotent.
        """
        if type(maximum) is not int or not 1<=maximum<=20:
            raise ValueError('maximum must be between 1 and 20')
        timestamp=time.time() if clock is None else clock
        jobs=[]
        with self.store.tx() as db:
            schedules=db.execute('''SELECT s.* FROM research_schedules s
              JOIN projects p ON p.id=s.project_id WHERE p.owner=? AND s.enabled=1
              ORDER BY s.next_due_epoch, s.project_id''',(owner,)).fetchall()
            for s in schedules:
                if len(jobs)>=maximum:break
                pid=s['project_id']
                if s['last_run_id']:
                    existing=db.execute('SELECT id,status,leased_until FROM runs WHERE id=?',
                                        (s['last_run_id'],)).fetchone()
                    if existing and (existing['status']=='CREATED' or
                        (existing['status']=='RUNNING' and
                         (existing['leased_until'] is None or existing['leased_until']<=timestamp))):
                        jobs.append(existing['id'])
                        continue
                    if existing and existing['status']=='RUNNING':
                        continue
                if s['next_due_epoch']>timestamp:
                    continue
                # Do not start new scheduled runs while a manual/other run is active.
                busy=db.execute('''SELECT 1 FROM runs WHERE project_id=? AND
                  (status='CREATED' OR (status='RUNNING' AND leased_until>?)) LIMIT 1''',
                  (pid,timestamp)).fetchone()
                if busy:continue
                project=db.execute('SELECT sources_json FROM projects WHERE id=?',(pid,)).fetchone()
                rid=uid()
                db.execute('''INSERT INTO runs
                  (id,project_id,status,pages_limit,bytes_limit,created_at,updated_at)
                  VALUES(?,?,?,?,?,?,?)''',
                  (rid,pid,'CREATED',s['pages_limit'],s['bytes_limit'],now(),now()))
                sources=unpack(project['sources_json'])
                db.executemany('INSERT INTO run_sources(run_id,url,ordinal) VALUES(?,?,?)',
                               [(rid,x['url'],i) for i,x in enumerate(sources)])
                db.execute('''INSERT INTO run_events(run_id,kind,detail,created_at)
                  VALUES(?,?,?,?)''',(rid,'CREATED','Scheduled local research run',now()))
                # Skip backlogged intervals; do not fire an unbounded catch-up burst.
                db.execute('''UPDATE research_schedules SET last_run_id=?,
                  next_due_epoch=?,updated_at=? WHERE project_id=?''',
                  (rid,timestamp+s['interval_seconds'],now(),pid))
                jobs.append(rid)
        return jobs

    @staticmethod
    def _run_cells(db, project, rid):
        sources=unpack(project['sources_json'])
        fields=unpack(project['fields_json'])
        by_subject={}
        for source in sources:
            by_subject.setdefault(source['label'],[]).append(source['url'])
        statuses={r['url']:r['state'] for r in db.execute(
            'SELECT url,state FROM run_sources WHERE run_id=?',(rid,))}
        rows=list(db.execute('''SELECT c.*,s.url,s.content_sha256,s.captured_at
          FROM claims c JOIN snapshots s ON c.snapshot_id=s.id
          WHERE s.run_id=?''',(rid,)))
        result={}
        for subject,urls in by_subject.items():
            complete=all(statuses.get(url)=='SUCCESS' for url in urls)
            for field in fields:
                key=(subject,field['key'])
                relevant=[row for row in rows if row['url'] in urls and row['field_key']==field['key']]
                status,value,evidence=_fact_state(relevant)
                result[key]=(complete,status,value,evidence)
        return result

    def reconcile(self, owner, pid, rid):
        """Idempotent fact-level changes; compare only fully available subjects.

        A failed fetch is a health issue and NEVER a confirmed fact change.
        Multiple sources of a subject must all succeed in both runs.
        """
        with self.store.tx() as db:
            project=db.execute('SELECT * FROM projects WHERE owner=? AND id=?',(owner,pid)).fetchone()
            if not project:raise ValueError('Project unavailable')
            current=db.execute('SELECT id,status,rowid FROM runs WHERE id=? AND project_id=?',
                               (rid,pid)).fetchone()
            if not current:raise ValueError('Run unavailable')
            if current['status'] not in ('COMPLETED','PARTIAL','FAILED','BUDGET_EXHAUSTED'):
                raise ValueError('Run is not finished')
            done=db.execute('SELECT 1 FROM research_reconciliations WHERE run_id=?',(rid,)).fetchone()
            if done:return []
            prev=db.execute('''SELECT r.id FROM runs r WHERE r.project_id=? AND r.rowid<?
              AND r.status IN ('COMPLETED','PARTIAL','FAILED','BUDGET_EXHAUSTED')
              ORDER BY r.rowid DESC LIMIT 1''',(pid,current['rowid'])).fetchone()
            previous_id=prev['id'] if prev else None
            if previous_id:
                left=self._run_cells(db,project,previous_id)
                right=self._run_cells(db,project,rid)
                for (subject,field), (was_complete,old_state,old_value,old_evidence) in left.items():
                    is_complete,new_state,new_value,new_evidence=right[(subject,field)]
                    if not was_complete or not is_complete:
                        continue
                    kind=None
                    if old_state=='SUPPORTED' and new_state=='SUPPORTED':
                        if pack(old_value)!=pack(new_value):kind='CHANGED'
                    elif old_state=='INSUFFICIENT' and new_state=='SUPPORTED':
                        kind='ADDED'
                    elif old_state=='SUPPORTED' and new_state in ('CONFLICTED','NEEDS_REVIEW','INSUFFICIENT'):
                        # Disappearance from an accessible page is a review
                        # candidate, never an independently proved removal.
                        kind='REVIEW_REQUIRED'
                    elif old_state in ('CONFLICTED','NEEDS_REVIEW') and new_state=='SUPPORTED':
                        kind='REVIEW_REQUIRED'
                    elif ((old_state=='INSUFFICIENT' and new_state=='NEEDS_REVIEW') or
                          (old_state=='NEEDS_REVIEW' and new_state=='INSUFFICIENT')):
                        # Feature keyword presence/absence is not a verified
                        # feature launch or removal; this goes to review only.
                        kind='REVIEW_REQUIRED'
                    # Other transitions are not verified changes. A failed
                    # fetch (incomplete coverage) never becomes a deletion.
                    if kind:
                        db.execute('''INSERT OR IGNORE INTO research_changes
                          (id,project_id,previous_run_id,current_run_id,subject,field_key,kind,
                          severity,old_value_json,new_value_json,old_evidence_json,new_evidence_json,created_at)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                          (uid(),pid,previous_id,rid,subject,field,kind,
                           'HIGH' if kind=='CHANGED' else ('MEDIUM' if kind=='ADDED' else 'REVIEW'),
                           pack(old_value),pack(new_value),pack(old_evidence),pack(new_evidence),now()))
            db.execute('INSERT INTO research_reconciliations(run_id,previous_run_id,reconciled_at) VALUES(?,?,?)',
                       (rid,previous_id,now()))
        return self.changes(owner,pid,only_run=rid)

    def changes(self, owner, pid, *, only_run=None, unread_only=False):
        with self.store.db() as db:
            if not db.execute('SELECT 1 FROM projects WHERE owner=? AND id=?',(owner,pid)).fetchone():
                raise ValueError('Project unavailable')
            sql='SELECT * FROM research_changes WHERE project_id=?'
            params=[pid]
            if only_run:
                sql+=' AND current_run_id=?';params.append(only_run)
            if unread_only:
                sql+=" AND read_state='UNREAD'"
            sql+=' ORDER BY created_at DESC,rowid DESC'
            out=[]
            for row in db.execute(sql,params):
                d=dict(row)
                for k in ('old_value_json','new_value_json','old_evidence_json','new_evidence_json'):
                    d[k.removesuffix('_json')]=unpack(d.pop(k))
                out.append(d)
            return out

    def acknowledge(self,owner,pid,event_id,state):
        if state not in ('ACKNOWLEDGED','IGNORED','UNREAD'):
            raise ValueError('Invalid inbox state')
        with self.store.tx() as db:
            changed=db.execute('''UPDATE research_changes SET read_state=?
                WHERE id=? AND project_id=? AND EXISTS
                (SELECT 1 FROM projects p WHERE p.id=research_changes.project_id AND p.owner=?)''',
                (state,event_id,pid,owner))
            if changed.rowcount!=1:raise ValueError('Change event unavailable')
        return {'event_id':event_id,'read_state':state}

    def history(self,owner,pid):
        with self.store.db() as db:
            if not db.execute('SELECT 1 FROM projects WHERE owner=? AND id=?',(owner,pid)).fetchone():
                raise ValueError('Project unavailable')
            runs=[dict(r) for r in db.execute('''SELECT id,status,created_at,updated_at,
              pages_used,bytes_used FROM runs WHERE project_id=? ORDER BY rowid DESC''',(pid,))]
            issues=[dict(r) for r in db.execute('''SELECT rs.run_id,rs.url,rs.state,rs.last_error
                FROM run_sources rs JOIN runs r ON r.id=rs.run_id
                WHERE r.project_id=? AND rs.state !='SUCCESS'
                ORDER BY r.rowid DESC,rs.ordinal''',(pid,))]
            return {'runs':runs,'source_health':issues,
                    'change_count':db.execute('SELECT count(*) FROM research_changes WHERE project_id=?',
                                             (pid,)).fetchone()[0]}

    def digest(self,owner,pid):
        events=self.changes(owner,pid,unread_only=True)
        history=self.history(owner,pid)
        facts=[e for e in events if e['kind'] in ('CHANGED','ADDED')]
        review=[e for e in events if e['kind']=='REVIEW_REQUIRED']
        return {'project_id':pid,'generated_at':now(),'verified_changes':facts,
                'needs_review':review,'source_health':history['source_health'],
                'delivery':'local_inbox_only',
                'notice':'No email, webhook or RSS delivery has been sent. Changes describe literal source text, not external truth.'}

    def digest_markdown(self,owner,pid):
        report=self.digest(owner,pid)
        lines=['# Evidence Radar — local change digest','',
               '> Only approved public sources. No external notification delivery.','',
               f"Generated: {report['generated_at']}",'',
               '## Verified source-text changes','']
        if not report['verified_changes']:
            lines.append('No new supported fact changes. This is not proof that every website stayed unchanged.')
        for e in report['verified_changes']:
            lines.extend([f"### {e['subject']} / {e['field_key']} — {e['kind']}",
                          f"- Before: {json.dumps(e['old_value'],ensure_ascii=False)}",
                          f"- After: {json.dumps(e['new_value'],ensure_ascii=False)}",
                          f"- Source snapshots: {', '.join(x['snapshot_id'] for x in e['new_evidence'])}",''])
        lines.extend(['## Unresolved and source health',''])
        for e in report['needs_review']:
            lines.append(f"- Review required: {e['subject']} / {e['field_key']}")
        for issue in report['source_health']:
            if issue['state']=='FAILED':lines.append(f"- Fetch failure: {issue['url']} ({issue['last_error']})")
        if not report['needs_review'] and not any(x['state']=='FAILED' for x in report['source_health']):
            lines.append('No recorded unresolved review events or failed source attempts.')
        return '\n'.join(lines)+'\n'
