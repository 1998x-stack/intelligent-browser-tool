# Improvement History

### 2026-11-05 04:17 UTC — ChatGPT Portfolio Iteration
- Run ID: 20261105T0417Z-evidence-stance-7f3a
- Repo / Base SHA: 1998x-stack/intelligent-browser-tool @ 46a1ab5b46374ec3439493d5ddaad29ce667dbe5
- Historical context: `docs/improvements.md` did not exist on main (404); first entry. Reviewed README, model, tests, demo fixture, recent commits, PRs #11 and #12. Those PRs concern workspace/SQLite and integration, not this fixture validation bug.
- Product problem & expected user value: Research users rely on evidence labels; a contradictory claim could cite one source twice, and arbitrary stance strings could be accepted, weakening trust in the demo's evidence model.
- Engineering diagnosis & evidence: `apps/evidence-demo/src/model.js:validateDataset` checked only evidence array length for conflicted facts, not distinct snapshot IDs; it did not constrain `ref.stance` values. The duplicate-source fixture passed before the fix in direct V8 reproduction; the unknown-stance fixture already triggered an indirect supported-claim error but lacked explicit stance validation.
- Options & decision: P1 evidence integrity (5+4+5+5-1-1=17), P2 empty/loading UI recovery (3+2+3+3-3-2=6), P2 mobile navigation improvements (3+1+3+2-4-2=3). Selected minimal evidence-contract validation, avoiding broader open PR scope.
- Changes: `validateDataset` requires at least two distinct snapshot IDs for conflicted facts and restricts evidence stances to supports/conflicts/context; two regression tests added. No public APIs or dependencies changed.
- Validation: A — executed actual old and updated validator code in isolated V8 with a minimal URL parser: baseline fixture accepted; duplicate-source conflict was accepted before and rejected after; unknown stance now yields an explicit validation error (previously only an indirect unsupported-claim error). D — Node repository test suite added but not executed in a complete checkout; browser E2E not run. The isolated URL parser is not equivalent to the real WHATWG URL implementation.
- Security & regression review: Fail-closed validation of evidence metadata; no changes to network policy, credentials, deployment, fixture data or external APIs. Distinct-source rule does not require opposing stances because the current fixture marks both contradictory sources as conflicts.
- Risk & rollback: Existing custom fixtures with unsupported stance values or duplicate snapshot references will now fail validation; revert this PR if compatibility is required, or migrate those fixtures deliberately.
- Follow-up: Run `npm --prefix apps/evidence-demo test` in a full checkout, then add full schema checks for null/malformed evidence references.
- Commit: 1b46baed7dbfb0c7feb1af5cb7e918e5ba4a9a7c (initial implementation)
- PR: https://github.com/1998x-stack/intelligent-browser-tool/pull/13
