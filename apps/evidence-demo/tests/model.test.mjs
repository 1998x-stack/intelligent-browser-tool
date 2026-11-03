import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import {
  STATES, validateDataset, selectTemplate, sourceEvidence, summaryStats,
  buildDossier, dossierMarkdown, verifySnapshotDigests,
} from '../src/model.js';

const source = JSON.parse(readFileSync(new URL('../data/demo.json', import.meta.url), 'utf8'));
const clone = () => structuredClone(source);

test('fixture is complete, fictional and internally consistent', () => {
  assert.deepEqual(validateDataset(source), []);
  assert.equal(source.snapshots.length, 4);
  assert.equal(source.facts.length, 9);
  assert.equal(source.mode, 'offline_fixture');
  assert.ok(source.fixture_notice.toLowerCase().includes('fictional'));
  assert.ok(source.snapshots.every(item => item.url.includes('.example/')));
});

test('all snapshot digests exactly match source text bytes', () => {
  for (const snapshot of source.snapshots) {
    const actual = createHash('sha256').update(snapshot.text, 'utf8').digest('hex');
    assert.equal(actual, snapshot.sha256, snapshot.id);
  }
});

test('all evidence anchors are exact, in-bounds slices', () => {
  for (const fact of source.facts) {
    const items = sourceEvidence(source, fact);
    assert.ok(items.length, `${fact.id} has inspectable evidence`);
    for (const item of items) {
      assert.ok(item.quote.trim().length > 15);
      assert.equal(item.before + item.quote + item.after, item.source.text);
      assert.ok(item.source.sha256.length === 64);
    }
  }
});

test('fact and uncertainty status are never inferred from absence', () => {
  const states = source.facts.reduce((a, item) => (a[item.state] = (a[item.state] || 0) + 1, a), {});
  assert.deepEqual(states, {supported: 7, insufficient: 1, conflicted: 1});
  assert.equal(STATES.insufficient, 'Evidence insufficient');
  const price = source.facts.find(fact => fact.id === 'cedar-price');
  assert.equal(price.state, 'insufficient');
  assert.notEqual(price.value, '$0 / mo');
  const conflict = source.facts.find(fact => fact.id === 'cedar-api');
  assert.equal(conflict.state, 'conflicted');
  assert.equal(new Set(conflict.evidence.map(e => e.snapshot_id)).size, 2);
});

test('all templates are functional and preserve all evidence', () => {
  for (const template of source.templates) {
    const selected = selectTemplate(source, template.id);
    assert.equal(selected.facts.length, 9);
    assert.deepEqual(selected.fields.map(f => f.id), template.fields);
    const stats = summaryStats(source, template.id);
    assert.deepEqual(stats, {sourceCount: 4, factCount: 9, supported: 7, insufficient: 1, conflicted: 1});
  }
});

test('source provenance, conditions and quote survive JSON export', () => {
  const result = buildDossier(source, 'pricing');
  assert.equal(result.mode, 'offline_fixture');
  assert.ok(result.notice.includes('Fictional'));
  const aster = result.fields[0].entries[0];
  assert.match(aster.qualifier, /billed annually/i);
  assert.equal(aster.evidence.length, 1);
  assert.match(aster.evidence[0].quote, /billed annually/i);
  assert.equal(aster.evidence[0].source_url, 'https://asterflow.example/pricing');
  assert.equal(aster.evidence[0].sha256.length, 64);
  const roundtrip = JSON.parse(JSON.stringify(result));
  assert.deepEqual(roundtrip, result);
});

test('Markdown export is explicit about synthetic content, unresolved states and sources', () => {
  const md = dossierMarkdown(buildDossier(source, 'pricing'));
  assert.match(md, /synthetic offline fixtures/i);
  assert.match(md, /Conflicting sources/);
  assert.match(md, /Evidence insufficient/);
  assert.match(md, /https:\/\/docs\.cedarstack\.example\/api/);
  assert.match(md, /No public monthly price is listed/);
  assert.ok(md.startsWith('# SaaS Competitor Intelligence'));
});

test('malformed evidence offset and non-fixture source are rejected', () => {
  const badAnchor = clone(); badAnchor.facts[0].evidence[0].end = 999999;
  assert.match(validateDataset(badAnchor).join(' '), /Invalid evidence range/);
  const badUrl = clone(); badUrl.snapshots[0].url = 'https://real-company.com/pricing';
  assert.match(validateDataset(badUrl).join(' '), /not fictional/);
});

test('supported claim without a supporting anchor is rejected', () => {
  const bad = clone(); bad.facts[0].evidence[0].stance = 'conflicts';
  assert.match(validateDataset(bad).join(' '), /Unsupported claim/);
});

test('duplicate fact id and invalid template field are rejected', () => {
  const bad = clone(); bad.facts[1].id = bad.facts[0].id;
  bad.templates[1].fields[0] = 'made-up-field';
  const issues = validateDataset(bad);
  assert.ok(issues.some(issue => issue.includes('Duplicate fact')));
  assert.ok(issues.some(issue => issue.includes('Unknown template field')));
});

test('arbitrary template ids fail closed', () => {
  assert.throws(() => selectTemplate(source, '__proto__'), /Unknown demo template/);
});


test('browser-compatible SHA-256 digest check rejects tampered fixture', async () => {
  assert.equal(await verifySnapshotDigests(source), true);
  const tampered = clone(); tampered.snapshots[0].text += ' Modified';
  await assert.rejects(() => verifySnapshotDigests(tampered), /integrity check failed/);
});

test('fictional-domain validation rejects misleading host suffix', () => {
  const bad = clone();bad.snapshots[0].url='https://safe.example.evil.net/pricing';
  assert.match(validateDataset(bad).join(' '), /not fictional/);
});
