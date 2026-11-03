/** V0.2-B local first; all untrusted source content uses DOM text nodes. */
const byId = id => document.getElementById(id);
const state = { token: '', project: null, run: null, dossier: null, poll: null };
function el(tag, text, css) { const e=document.createElement(tag); if(text!==undefined)e.textContent=String(text); if(css)e.className=css;return e; }
function reportError(message) { const target=byId('error');target.textContent=String(message);target.hidden=false;byId('status-line').textContent='Research could not continue. Review the error and retry.'; }
function clearError() {byId('error').hidden=true;byId('error').textContent='';}
async function api(path, options={}) {
  const result=await fetch(path,{...options,headers:{'Authorization':`Bearer ${state.token}`,...options.headers},cache:'no-store'});
  let body;const typ=result.headers.get('Content-Type')||'';
  if(typ.includes('application/json'))body=await result.json();else body=await result.text();
  if(!result.ok)throw new Error(body?.error?.message||`Request failed: ${result.status}`);
  return body;
}
function download(text,name,type) {
  const blob=new Blob([text],{type}); const url=URL.createObjectURL(blob);
  const a=el('a');a.href=url;a.download=name; document.body.append(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function connect(){
  clearError();state.token=byId('token').value.trim();
  if(!state.token){reportError('Enter the local session token.');return;}
  try {
    const policy=await api('/api/v1/policy');
    byId('approved-hosts').textContent=`Approved public hosts: ${policy.hosts.join(', ')}. Robots policy: ${policy.respect_robots?'on':'test-only off'}.`;
    await loadProjects();
  }catch(error){reportError(error.message);}
}
async function loadProjects(){
  const list=byId('projects');list.replaceChildren();
  const response=await api('/api/v1/projects');
  for(const p of response.projects){
    const entry=el('div'); entry.className='saved-project';
    const button=el('button',p.question);button.type='button';
    button.addEventListener('click',async()=>{
      try{clearError();state.project=await api(`/api/v1/projects/${p.id}`);
        const runs=await api(`/api/v1/projects/${p.id}/runs`);
        if(!runs.runs.length){reportError('This project has no saved run yet. Create another run from the form.');return;}
        state.run=runs.runs[0];await renderRun();
      }catch(e){reportError(e.message);}
    });entry.append(button);
    const remove=el('button','Delete','delete');remove.type='button';
    remove.setAttribute('aria-label',`Delete research project ${p.question}`);
    remove.addEventListener('click',async()=>{
      if(!confirm('Permanently delete this project and its saved source snapshots?'))return;
      try{await api(`/api/v1/projects/${p.id}`,{method:'DELETE'});
        if(state.project?.id===p.id){state.project=null;state.run=null;state.dossier=null;byId('dossier').hidden=true;byId('run-progress').hidden=true;byId('run-state').textContent='Not started';}
        await loadProjects();}
      catch(e){reportError(e.message);}
    });entry.append(remove);list.append(entry);
  }
  if(!response.projects.length)list.append(el('p','No saved projects yet.','muted'));
}
function parseSources(raw){
  const lines=raw.split('\n').map(s=>s.trim()).filter(Boolean);
  if(!lines.length||lines.length>5)throw new Error('Enter 1–5 source pages, one per line.');
  return lines.map(line=>{
    const [label,url]=line.includes('|')?line.split('|',2).map(s=>s.trim()):['',line];
    if(!url)throw new Error('Missing source URL');
    return {label:label||new URL(url).hostname,url};
  });
}
async function start(evt){
  evt.preventDefault();clearError();state.token=byId('token').value.trim();
  if(!state.token)return reportError('Connect with the local token first.');
  byId('start').disabled=true;
  byId('status-line').textContent='Creating bounded research project…';
  try{
    const fields=[{key:'pricing',kind:'price',label:'Explicit published price'}];
    const keyword=byId('keyword').value.trim();
    if(keyword)fields.push({key:'additional',kind:'keyword',hint:keyword,label:`Mentions of ${keyword}`});
    state.project=await api('/api/v1/projects',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({question:byId('question').value,sources:parseSources(byId('sources').value),fields})});
    state.run=await api(`/api/v1/projects/${state.project.id}/runs`,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({max_pages:Number(byId('pages').value),max_bytes:Number(byId('bytes').value)})});
    await loadProjects();await renderRun();
  }catch(e){reportError(e.message);}finally{byId('start').disabled=false;}
}
function metric(title,value){const e=el('div',undefined,'metric');e.append(el('strong',value),el('span',title));return e;}
async function renderRun(){
  if(!state.run)return;
  if(state.poll)clearTimeout(state.poll);
  state.run=await api(`/api/v1/runs/${state.run.id}`);
  byId('run-state').textContent=state.run.status;
  byId('run-progress').hidden=false;
  byId('metrics').replaceChildren(metric('Page attempts',`${state.run.pages_used} / ${state.run.pages_limit}`),
    metric('Bytes consumed',`${state.run.bytes_used} / ${state.run.bytes_limit}`),
    metric('Succeeded',state.run.sources.filter(s=>s.state==='SUCCESS').length),
    metric('Failed',state.run.sources.filter(s=>s.state==='FAILED').length));
  const failures=state.run.sources.filter(s=>s.state==='FAILED').map(s=>`${s.url}: ${s.last_error}`);
  byId('run-errors').textContent=failures.join(' | ');
  const terminal=!['CREATED','RUNNING'].includes(state.run.status);
  byId('status-line').textContent=terminal?`Research finished with state ${state.run.status}; inspect each exact source excerpt.`:'Reading approved sources and persisting checkpoints…';
  const canRetry=state.run.sources.some(s=>s.state!=='SUCCESS' && s.attempts<2)
    && state.run.pages_used<state.run.pages_limit && state.run.bytes_used<state.run.bytes_limit;
  const expired=state.run.status==='RUNNING' && state.run.leased_until && state.run.leased_until*1000<Date.now();
  byId('resume').hidden=!(canRetry && (terminal||expired));
  byId('resume').textContent=expired?'Resume interrupted worker':'Retry failed sources';
  byId('new-run').hidden=!terminal;
  if(state.run.sources.some(s=>s.state==='SUCCESS')){
    try{state.dossier=await api(`/api/v1/projects/${state.project.id}/runs/${state.run.id}/dossier`);renderDossier();}
    catch(err){reportError(err.message);}
  }
  if(!terminal){state.poll=setTimeout(()=>renderRun().catch(e=>reportError(e.message)),850);}
}
function renderDossier(){
  const target=byId('comparison');target.replaceChildren(); byId('dossier').hidden=false;
  const data=state.dossier;
  const summary=el('div',undefined,'summary-cells');
  summary.append(el('h3','Comparison by product / research subject'));
  for(const cell of data.comparison||[]){
    const text=cell.value===null?'Unknown':JSON.stringify(cell.value);
    summary.append(el('p',`${cell.subject} · ${cell.field}: ${text} — ${cell.status} (${cell.examined_sources}/${cell.expected_sources} sources fetched)`));
  }
  target.append(summary);
  const table=el('table');table.append(el('caption',`Source evidence for ${data.project.question}`));
  const head=el('thead'),tr=el('tr');for(const x of ['Source','Research field','Observed value','Proof state'])tr.append(el('th',x));head.append(tr);table.append(head);
  const body=el('tbody');
  for(const claim of data.claims){
    const row=el('tr');row.append(el('td',claim.source_url),el('td',claim.field));
    const cell=el('td'),button=el('button',claim.value===null?'Unknown':typeof claim.value==='string'?claim.value:JSON.stringify(claim.value));
    button.type='button';button.setAttribute('aria-label',`Inspect ${claim.field} evidence for ${claim.source_url}, ${claim.status}`);
    button.addEventListener('click',()=>inspect(claim));cell.append(button);row.append(cell,el('td',claim.status,`pill ${claim.status}`));body.append(row);
  }
  table.append(body);target.append(table);
}
function inspect(claim){
  const pane=byId('evidence');pane.replaceChildren();
  pane.append(el('strong',`${claim.field} — ${claim.status}`),el('p',claim.reason),
    el('p',`${claim.source_url} · Captured ${claim.captured_at} · SHA-256 ${claim.content_sha256}`));
  const source=state.dossier.sources.find(s=>s.id===claim.snapshot_id);
  if(!source){pane.append(el('p','Snapshot not found.'));return;}
  if(!claim.evidence.length)pane.append(el('p','No supporting text span exists. This result is not established.'));
  for(const evidence of claim.evidence){
    if(!evidence.valid){pane.append(el('p','Evidence anchor failed integrity check.'));continue;}
    const p=el('p');p.append(document.createTextNode(source.text.slice(0,evidence.start)));
    p.append(el('mark',source.text.slice(evidence.start,evidence.end)));
    p.append(document.createTextNode(source.text.slice(evidence.end)));
    pane.append(p);
  }
  pane.focus();
}
async function saveJson(){if(state.dossier)download(JSON.stringify(state.dossier,null,2),`research-${state.run.id}.json`,'application/json');}
async function saveMd(){
  if(!state.project||!state.run)return;
  try{
    const md=await api(`/api/v1/projects/${state.project.id}/runs/${state.run.id}/export.md`);
    download(md,`research-${state.run.id}.md`,'text/markdown');
  }catch(e){reportError(e.message);}
}
async function resume(){
  try{
    clearError();await api(`/api/v1/runs/${state.run.id}/resume`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    byId('resume').hidden=true;
    state.poll=setTimeout(()=>renderRun().catch(e=>reportError(e.message)),200);
  }catch(e){reportError(e.message);}
}
byId('research-form').addEventListener('submit',start);
byId('connect').addEventListener('click',connect);
byId('resume').addEventListener('click',resume);
byId('new-run').addEventListener('click',async()=>{
  if(!state.project)return;
  try{clearError();state.run=await api(`/api/v1/projects/${state.project.id}/runs`,{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      max_pages:Number(byId('pages').value),max_bytes:Number(byId('bytes').value)})});
    state.dossier=null;byId('dossier').hidden=true;await renderRun();
  }catch(e){reportError(e.message);}
});
byId('export-json').addEventListener('click',saveJson);
byId('export-md').addEventListener('click',saveMd);

// This page must never solicit a token on a public static host.
if(!['localhost','127.0.0.1'].includes(location.hostname)){
  byId('status-line').textContent='Local backend unavailable: run python -m research_workspace serve on 127.0.0.1 to use live research. The public site contains only the offline demo.';
  byId('start').disabled=true;byId('connect').disabled=true;byId('token').disabled=true;
  byId('approved-hosts').textContent='Live research is disabled on public static hosting.';
}
