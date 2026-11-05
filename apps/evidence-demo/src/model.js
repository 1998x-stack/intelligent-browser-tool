/** Pure, deterministic transformations of the synthetic Evidence Radar fixture. */
export const STATES = Object.freeze({
  supported: 'Source-backed',
  insufficient: 'Evidence insufficient',
  conflicted: 'Conflicting sources',
});

export function validateDataset(data) {
  const problems = [];
  if (data?.mode !== 'offline_fixture') problems.push('Demo must be explicitly marked offline_fixture');
  const ids = new Set();
  const sourceMap = new Map();
  for (const source of data?.snapshots ?? []) {
    if (!source.id || ids.has(source.id)) problems.push(`Duplicate or missing snapshot: ${source.id}`);
    ids.add(source.id);
    sourceMap.set(source.id, source);
    let fictionalUrl = false;
    try {
      const parsed = new URL(source.url);
      fictionalUrl = parsed.protocol === 'https:' && parsed.hostname.endsWith('.example') && !parsed.username && !parsed.password;
    } catch { /* unparseable URLs are never admitted */ }
    if (!source.fixture || !fictionalUrl) problems.push(`Snapshot is not fictional: ${source.id}`);
    if (!/^[a-f0-9]{64}$/.test(source.sha256 || '')) problems.push(`Invalid SHA256: ${source.id}`);
  }
  const factIds = new Set();
  const fieldSet = new Set(data?.project?.fields?.map(field => field.id) ?? []);
  const products = new Set(data?.project?.products ?? []);
  for (const fact of data?.facts ?? []) {
    if (!fact.id || factIds.has(fact.id)) problems.push(`Duplicate fact: ${fact.id}`);
    factIds.add(fact.id);
    if (!fieldSet.has(fact.field) || !products.has(fact.product)) problems.push(`Unknown field/product: ${fact.id}`);
    if (!(fact.state in STATES)) problems.push(`Unknown state: ${fact.id}`);
    if (fact.state === 'supported' && !fact.evidence?.some(ref => ref.stance === 'supports')) problems.push(`Unsupported claim labelled supported: ${fact.id}`);
    if (fact.state === 'conflicted' && new Set((fact.evidence ?? []).map(ref => ref.snapshot_id)).size < 2) problems.push(`Conflict has fewer than two distinct sources: ${fact.id}`);
    for (const ref of fact.evidence ?? []) {
      if (!['supports', 'conflicts', 'context'].includes(ref.stance)) problems.push(`Invalid evidence stance: ${fact.id}`);
      const source = sourceMap.get(ref.snapshot_id);
      if (!source) { problems.push(`Missing source: ${fact.id}`); continue; }
      if (!Number.isInteger(ref.start) || !Number.isInteger(ref.end) || ref.start < 0 || ref.end <= ref.start || ref.end > source.text.length) problems.push(`Invalid evidence range: ${fact.id}`);
    }
  }
  for (const template of data?.templates ?? []) {
    if (!template.fields?.every(field => fieldSet.has(field))) problems.push(`Unknown template field: ${template.id}`);
  }
  if (!data?.templates?.length || !data?.facts?.length) problems.push('No demonstration content');
  return problems;
}

export function selectTemplate(data, templateId) {
  const template = data.templates.find(item => item.id === templateId);
  if (!template) throw new Error(`Unknown demo template: ${templateId}`);
  const facts = template.fields.flatMap(field => data.project.products.map(product => {
    const matches = data.facts.filter(fact => fact.product === product && fact.field === field);
    if (matches.length !== 1) throw new Error(`Expected one fact for ${product}/${field}`);
    return matches[0];
  }));
  return { template, facts, fields: template.fields.map(id => data.project.fields.find(field => field.id === id)) };
}

export function sourceEvidence(data, fact) {
  const sourceMap = new Map(data.snapshots.map(snapshot => [snapshot.id, snapshot]));
  return (fact.evidence ?? []).map(ref => {
    const source = sourceMap.get(ref.snapshot_id);
    if (!source) throw new Error(`Missing evidence for ${fact.id}`);
    if (ref.start < 0 || ref.end > source.text.length || ref.end <= ref.start) throw new Error(`Invalid anchor ${fact.id}`);
    return { source, stance: ref.stance, quote: source.text.slice(ref.start, ref.end), before: source.text.slice(0, ref.start), after: source.text.slice(ref.end) };
  });
}

export function summaryStats(data, templateId) {
  const { facts } = selectTemplate(data, templateId);
  return {
    sourceCount: new Set(facts.flatMap(f => f.evidence.map(e => e.snapshot_id))).size,
    factCount: facts.length,
    supported: facts.filter(f => f.state === 'supported').length,
    insufficient: facts.filter(f => f.state === 'insufficient').length,
    conflicted: facts.filter(f => f.state === 'conflicted').length,
  };
}

export function buildDossier(data, templateId) {
  const { template, facts, fields } = selectTemplate(data, templateId);
  return {
    schema_version: data.schema_version,
    mode: 'offline_fixture',
    notice: data.fixture_notice,
    project: data.project.title,
    question: template.question,
    source_count: summaryStats(data, templateId).sourceCount,
    fields: fields.map(field => ({
      ...field,
      entries: data.project.products.map(product => {
        const fact = facts.find(f => f.field === field.id && f.product === product);
        return { id: fact.id, product, value: fact.value, qualifier: fact.qualifier,
          state: fact.state, evidence: sourceEvidence(data, fact).map(entry => ({
            source: entry.source.label, snapshot_id: entry.source.id,
            source_url: entry.source.url, captured_at: entry.source.captured_at,
            sha256: entry.source.sha256, stance: entry.stance, quote: entry.quote,
          })) };
      }),
    })),
  };
}

function mdCell(value) { return String(value).replaceAll('|', '\\|').replaceAll('\n', ' '); }
export function dossierMarkdown(dossier) {
  const products = dossier.fields[0]?.entries.map(entry => entry.product) ?? [];
  const lines = [`# ${dossier.project}`, '', `> ${dossier.notice}`, '', `**Research question:** ${dossier.question}`, '',
    `| Field | ${products.map(mdCell).join(' | ')} |`, `|---|${products.map(()=>'---').join('|')}|`];
  for (const field of dossier.fields) lines.push(`| ${mdCell(field.label)} | ${field.entries.map(entry => mdCell(`${entry.value} (${entry.state})`)).join(' | ')} |`);
  lines.push('', '## Sources and evidence', '');
  for (const field of dossier.fields) {
    lines.push(`### ${field.label}`, '');
    for (const entry of field.entries) {
      lines.push(`- **${entry.product}: ${entry.value}** — ${entry.qualifier} — ${STATES[entry.state]}`);
      if (!entry.evidence.length) lines.push('  - No supporting excerpt available.');
      for (const evidence of entry.evidence) {
        lines.push(`  - ${evidence.source} · ${evidence.captured_at} · ${evidence.stance} · ${evidence.source_url}`);
        lines.push(`    - Evidence: ${evidence.quote}`);
      }
    }
    lines.push('');
  }
  lines.push('This report is produced from synthetic offline fixtures. It is not current market intelligence.', '');
  return lines.join('\n');
}

/** Check integrity at runtime as well as in CI before displaying a dataset. */
export async function verifySnapshotDigests(data) {
  if (!globalThis.crypto?.subtle) throw new Error('Secure browser crypto is required to verify fixtures');
  const encoder = new TextEncoder();
  for (const source of data.snapshots) {
    const digest = await globalThis.crypto.subtle.digest('SHA-256', encoder.encode(source.text));
    const actual = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2,'0')).join('');
    if (actual !== source.sha256) throw new Error(`Source snapshot integrity check failed: ${source.id}`);
  }
  return true;
}
