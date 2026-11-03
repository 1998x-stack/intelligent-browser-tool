import { STATES, validateDataset, selectTemplate, sourceEvidence, summaryStats, buildDossier, dossierMarkdown, verifySnapshotDigests } from './model.js';

const root = document.getElementById('research-app');
const content = document.getElementById('research-content');
const evidenceDetails = document.getElementById('evidence-details');
const evidenceTitle = document.getElementById('evidence-title');
const live = document.getElementById('live-message');
const workspace = document.getElementById('workspace');
const state = { data: null, templateId: 'pricing', view: 'brief', selectedFact: null };

function node(tag, className = '', text = null) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== null) element.textContent = String(text);
  return element;
}
function add(parent, ...children) { children.filter(Boolean).forEach(child => parent.append(child)); return parent; }
function announce(message) { live.textContent = message; }
function statePill(kind) { return node('span', `state-pill ${kind}`, STATES[kind]); }
function textWithEmphasis(text, bold) { const item = node('span'); add(item, node('strong', '', bold), document.createTextNode(text)); return item; }

function renderTemplates() {
  const container = document.getElementById('template-buttons');
  container.replaceChildren();
  for (const template of state.data.templates) {
    const button = node('button', 'template-btn', template.label);
    button.type = 'button'; button.dataset.template = template.id;
    button.setAttribute('aria-pressed', String(state.templateId === template.id));
    button.title = template.subtitle;
    button.addEventListener('click', () => selectResearchTemplate(template.id));
    container.append(button);
  }
}
function selectResearchTemplate(id) {
  state.templateId = id;
  state.selectedFact = null;
  state.view = 'brief';
  renderAll();
  announce(`Template selected: ${selectTemplate(state.data, id).template.label}. Fictional offline research ready.`);
}
function renderStats() {
  const data = summaryStats(state.data, state.templateId);
  const target = document.getElementById('metrics');
  target.replaceChildren();
  for (const [label, count] of [
    ['Source snapshots', data.sourceCount], ['Linked claims', data.factCount],
    ['Unresolved facts', data.insufficient + data.conflicted], ['External fetches', 0],
  ]) {
    const item = node('div', 'metric');
    add(item, node('div', 'metric-number', String(count).padStart(2, '0')), node('div', 'metric-label', label));
    target.append(item);
  }
}
function findFact(product, field) {
  return state.data.facts.find(fact => fact.product === product && fact.field === field);
}
function factButton(fact) {
  const button = node('button', 'fact-btn', fact.value);
  button.type = 'button';
  button.setAttribute('aria-label', `${fact.product}, ${state.data.project.fields.find(field => field.id === fact.field).label}: ${fact.value}; ${STATES[fact.state]}. Inspect evidence`);
  button.dataset.fact = fact.id;
  if (state.selectedFact === fact.id) button.setAttribute('aria-current', 'true');
  button.addEventListener('click', () => inspectFact(fact.id));
  return button;
}
function matrixView() {
  const { fields } = selectTemplate(state.data, state.templateId);
  const holder = node('div', 'matrix-scroll');
  const table = node('table', 'matrix');
  const caption = node('caption', 'sr-only', 'Comparison of fictional products and source-backed or unresolved research facts');
  const thead = node('thead');
  const headRow = node('tr');
  const first = node('th', '', 'Research field'); first.scope = 'col'; headRow.append(first);
  for (const product of state.data.project.products) { const h = node('th', '', product); h.scope = 'col'; headRow.append(h); }
  thead.append(headRow);
  const tbody = node('tbody');
  for (const field of fields) {
    const row = node('tr');
    const heading = node('th', '', field.label); heading.scope = 'row'; row.append(heading);
    for (const product of state.data.project.products) {
      const fact = findFact(product, field.id);
      const td = node('td');
      add(td, factButton(fact), node('div', 'fact-detail', fact.qualifier), statePill(fact.state));
      row.append(td);
    }
    tbody.append(row);
  }
  add(table, caption, thead, tbody);
  holder.append(table);
  return holder;
}
function briefView() {
  const container = node('div');
  const first = node('div', 'intro-card');
  add(first, node('div', 'content-kicker', 'EVIDENCE-LINKED SUMMARY'), node('h4', '', 'The useful answer, with its caveats.'),
    node('p', '', 'Two products publish annual-billing monthly rates, one omits a public price, and CedarStack’s API documentation contradicts its pricing page. All examples are fictional.'));
  container.append(first);
  const findings = node('div', 'brief-bullets');
  const highlighted = [
    ['aster-price','AsterFlow lists ', ' with annual billing, not month-to-month pricing.'],
    ['cedar-price','CedarStack’s monthly price is ', ' in the available fixture.'],
    ['cedar-api','CedarStack API access is ', ' across two snapshots.'],
  ];
  highlighted.forEach(([id, pre, post], index) => {
    const fact = state.data.facts.find(item => item.id === id);
    const item = node('div', 'brief-finding');
    const finding = node('div', 'finding-text');
    add(finding, document.createTextNode(pre), factButton(fact), document.createTextNode(post));
    add(item, node('div','finding-no',`0${index+1}`),finding); findings.append(item);
  });
  add(container, findings, node('h4', 'section-subhead', 'Full comparison'), matrixView());
  return container;
}
function sourcesView() {
  const container = node('div');
  add(container, node('div', 'content-kicker', 'FROZEN SOURCE REFERENCES'), node('h4', 'section-subhead', 'Four fictional snapshots, all bundled locally.'));
  for (const source of state.data.snapshots) {
    const card = node('div', 'source-card');
    add(card, node('h4', '', source.label), node('p', 'url', source.url),
      node('p', '', `Fixture capture: ${source.captured_at.slice(0, 10)} · SHA-256 ${source.sha256.slice(0, 14)}…`));
    const related = state.data.facts.filter(f => f.evidence.some(ref => ref.snapshot_id === source.id));
    const links = node('p'); links.append(document.createTextNode('Related facts: '));
    related.forEach((fact, index) => {
      if (index) links.append(document.createTextNode(' · '));
      const btn = node('button', 'source-evidence-btn', fact.id.replaceAll('-', ' '));
      btn.type = 'button'; btn.addEventListener('click', () => inspectFact(fact.id)); links.append(btn);
    });
    add(card, links); container.append(card);
  }
  return container;
}
function runsView() {
  const container = node('div');
  add(container, node('div', 'content-kicker', 'REPLAY LOG — NOT A LIVE CRAWL'), node('h4', 'section-subhead', 'A deterministic look at the research steps.'));
  const steps = [
    ['01','Load snapshots','Read bundled JSON fixtures from the same origin. No network navigation to the fictional sources occurs.'],
    ['02','Verify anchors','Check that every quoted source excerpt points into an actual snapshot span.'],
    ['03','Reconcile claims','Preserve supported, insufficient, and conflicting statuses without guessing missing values.'],
    ['04','Render research','Show comparison, evidence, and exportable Markdown / JSON from one data model.'],
  ];
  for (const [number, name, description] of steps) {
    const row = node('div', 'run-row'); const body = node('div'); add(body, node('h4', '', name), node('p', '', description)); add(row, node('span', 'run-index', number), body); container.append(row);
  }
  add(container, node('p', 'run-note', 'This is a local product UX demonstration—not an executed crawler job. Browser automation, authenticated workspaces, custom URL research and scheduled monitoring are out of scope for V0.2-A.'));
  return container;
}
function renderView() {
  const viewTitle = { brief: 'Research brief', compare: 'Full comparison', sources: 'Source snapshots', runs: 'Run details' };
  for (const tab of document.querySelectorAll('[role="tab"][data-view]')) {
    tab.setAttribute('aria-selected', String(tab.dataset.view === state.view));
    tab.tabIndex = tab.dataset.view === state.view ? 0 : -1;
  }
  content.setAttribute('aria-labelledby', `tab-${state.view}`);
  const view = {brief: briefView, compare: matrixView, sources: sourcesView, runs: runsView}[state.view];
  content.replaceChildren(view());
  content.setAttribute('aria-label', viewTitle[state.view]);
}
function inspectFact(id) {
  const fact = state.data.facts.find(item => item.id === id);
  if (!fact) return;
  state.selectedFact = id;
  document.querySelectorAll('[data-fact]').forEach(btn => {
    if (btn.dataset.fact === id) btn.setAttribute('aria-current', 'true'); else btn.removeAttribute('aria-current');
  });
  const fieldLabel = state.data.project.fields.find(field => field.id === fact.field).label;
  evidenceTitle.textContent = `${fact.product} · ${fieldLabel}`;
  evidenceDetails.replaceChildren();
  add(evidenceDetails, node('p', 'fact-detail', fact.qualifier), statePill(fact.state));
  const sources = sourceEvidence(state.data, fact);
  for (const item of sources) {
    const block = node('section', 'source-block');
    const url = item.source.url;
    add(block, node('h5', 'source-label', item.source.label),
      node('p', 'source-meta', `${url}\nFixture captured ${item.source.captured_at.slice(0, 10)} · SHA-256 ${item.source.sha256.slice(0, 12)}…`));
    const quote = node('blockquote', 'source-quote');
    add(quote, document.createTextNode('“'), node('mark', '', item.quote), document.createTextNode('”'));
    block.append(quote);
    if (fact.state === 'conflicted') block.append(node('p', 'fact-detail', 'This snapshot disagrees with another synthetic source. Neither is silently preferred.'));
    const details = node('details'); const summary = node('summary', 'source-full', 'View full frozen source text');
    add(details, summary, node('pre', 'source-fulltext', item.source.text)); block.append(details);
    evidenceDetails.append(block);
  }
  if (fact.state === 'insufficient') evidenceDetails.append(node('p', 'run-note', 'The fixture documents that no public price is listed. It does not establish what a private quote would be.'));
  if (fact.state === 'conflicted') evidenceDetails.append(node('p', 'run-note', 'Conflicting source claims require further verification. This demo deliberately does not guess a winner.'));
  evidenceTitle.focus({ preventScroll: true });
  if (window.matchMedia('(max-width: 780px)').matches) document.getElementById('evidence-pane').scrollIntoView({ block: 'start', behavior: 'auto' });
  announce(`Evidence panel: ${fact.product}, ${fieldLabel}, ${STATES[fact.state]}. ${sources.length} source excerpts.`);
}
function renderAll() {
  renderTemplates(); renderStats();
  const selected = selectTemplate(state.data, state.templateId);
  document.getElementById('active-question').textContent = selected.template.question;
  document.getElementById('active-description').textContent = selected.template.subtitle;
  renderView();
  if (!state.selectedFact) {
    evidenceTitle.textContent = 'Select a claim';
    evidenceDetails.replaceChildren(node('p','empty-hint','Choose a value in the brief or comparison to inspect its exact supporting text.'));
  } else inspectFact(state.selectedFact);
}
function download(name, contentText, mime) {
  const blob = new Blob([contentText], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = node('a'); link.href = url; link.download = name;
  document.body.append(link); link.click(); link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  announce(`${name} downloaded. The file contains synthetic demo data only.`);
}
async function loadDemo() {
  document.getElementById('error-state').hidden = true;
  document.getElementById('loading-state').hidden = false;
  root.hidden = true;
  try {
    const response = await fetch('./data/demo.json', { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const issues = validateDataset(data);
    if (issues.length) throw new Error(issues.join('; '));
    await verifySnapshotDigests(data);
    state.data = data;
    state.templateId = 'pricing'; state.view = 'brief'; state.selectedFact = null;
    renderAll();
    document.getElementById('loading-state').hidden = true;
    root.hidden = false;
    announce('Offline sample research is ready. All sources are synthetic.');
  } catch (error) {
    console.error('Could not load evidence demo:', error);
    document.getElementById('loading-state').hidden = true;
    document.getElementById('error-state').hidden = false;
    announce('The demo fixture could not be loaded. Retry is available.');
  }
}
function initControls() {
  function toDemo() {workspace.scrollIntoView({block:'start',behavior:'auto'}); document.getElementById('workspace-heading').setAttribute('tabindex','-1'); document.getElementById('workspace-heading').focus({preventScroll:true}); announce('Interactive demo section. Choose a research template or inspect the prepared brief.');}
  for (const id of ['top-demo','hero-demo']) document.getElementById(id).addEventListener('click', toDemo);
  document.getElementById('retry-demo').addEventListener('click', loadDemo);
  document.getElementById('reset-demo').addEventListener('click', () => { if (!state.data) return; selectResearchTemplate('pricing'); announce('Demo reset to the pricing template. No live work was run.'); });
  document.querySelectorAll('[role="tab"][data-view]').forEach(tab => {
    tab.addEventListener('click', () => { state.view = tab.dataset.view; renderView(); announce(`Showing ${tab.textContent}.`); });
    tab.addEventListener('keydown', event => {
      if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
      const tabs = [...document.querySelectorAll('[role="tab"][data-view]')];
      let next = tabs.indexOf(event.currentTarget);
      if (event.key === 'ArrowRight') next = (next+1)%tabs.length;
      if (event.key === 'ArrowLeft') next = (next-1+tabs.length)%tabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = tabs.length-1;
      event.preventDefault(); tabs[next].click(); tabs[next].focus();
    });
  });
  document.getElementById('download-md').addEventListener('click', () => {
    if (!state.data) return;
    download('evidence-radar-synthetic-demo.md', dossierMarkdown(buildDossier(state.data,state.templateId)), 'text/markdown;charset=utf-8');
  });
  document.getElementById('download-json').addEventListener('click', () => {
    if (!state.data) return;
    download('evidence-radar-synthetic-demo.json', JSON.stringify(buildDossier(state.data,state.templateId),null,2)+'\n', 'application/json;charset=utf-8');
  });
}
initControls();
loadDemo();
