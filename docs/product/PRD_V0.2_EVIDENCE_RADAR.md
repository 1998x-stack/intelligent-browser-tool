# PRD V0.2 — Evidence Radar: Reproducible Research, with Proof

**Document type:** Product Requirements Document / concept-to-build specification  
**Status:** Proposal, pending discovery and privacy/security release gates  
**Date:** 2026-11-03  
**Repository:** 1998x-stack/intelligent-browser-tool  
**Research basis:** [Voice of Customer 2026](./VOICE_OF_CUSTOMER_2026.md)  
**Launch companion:** [Validation and Product Hunt plan](./VALIDATION_AND_LAUNCH.md)

---

## 1. Executive decision

### Product thesis

Turn a user's specific web research question into a **reproducible, evidence-linked dossier** that remains useful when source websites change.

### Positioning

**Evidence Radar — Turn live websites into research you can verify and revisit.**

Not "another AI browser", not a general website change monitor, and not "search with citations" alone. The advantage to test is the complete **research question → sourced claims → contradiction/missing-data handling → frozen evidence → repeated checking → digest and share** workflow.

### First ICP

Independent SaaS founders, small product teams, competitive intelligence researchers and technical product marketers following **public competitor pricing/features/changelogs**. We choose this use case because outputs are structured and source-checkable. This does not prove demand: recruit actual users and test the workflow before broad investment.

### First release promise

Users can run a curated, public-web research demo without signup, inspect every cited fact, identify missing/unconfirmed information, and export/share a sanitized dossier. For unrestricted cloud URL entry and scheduled monitoring, complete the separate network/security review first.

### Value hierarchy

1. **Trust:** Facts are associated with inspectable evidence and normalized value/unit/context.
2. **Repeatability:** Subsequent runs compare facts rather than merely screenshots.
3. **Predictability:** Fixed task budget, deterministic fetch/extract where feasible, explicit failure states.
4. **Speed to value:** Demo produces a useful inspectable result with minimal setup.
5. **Shareability:** A read-only result can be shown to a colleague with sources and verification status intact.

### Sharp exclusions

NO universal browser agent, form submission, checkout, credential import, browser user-profile CDP, arbitrary logged-in site automation, stealth bot-bypass marketing, mass scraping marketplace, CRM, custom visual workflow editor, or model marketplace in V0.2. We do not promise "guaranteed true" claims.

## 2. Why this instead of a generic web monitor?

Public product pages already reveal that Firecrawl launched /monitor, Browse AI and Visualping cover monitoring, and changedetection.io offers strong self-hosted tracking. PH reviewers request multi-step enrichment and usable automations; HN comments emphasize cost caps, deterministic replay, hallucination and security. Refer to research IDs PH-01..09 and HN-01..13 in the VOC ledger.

**Hypothesis:** Product teams will prefer a living comparison **brief** that can cite specific before/after sources over isolated "page changed" notifications, even when they already have web monitoring tools.

**Falsification:** When asked to choose between (A) their existing tool plus manual research and (B) a verified dossier, fewer than 50% of target users choose B to complete a real upcoming task, or fewer than 25% return in a week. These are **proposed stop/go thresholds**, not observed outcomes.

## 3. Personas, situations and jobs-to-be-done

| Persona | Trigger | Existing workaround | Successful outcome | Typical blocker |
|---|---|---|---|---|
| A. Solo SaaS founder (primary) | Competitor changes product tiers or releases a feature | 10–30 tabs, saved notes, occasional AI summary | Relevant, fact-checked 1-page brief with exact prices, dates and links | Can't trust interpretation or afford continuous API calls |
| B. Product manager, 3–20 person team (primary) | Weekly competitor review | Screenshots, spreadsheets, team chat | Diff against last report, attributed change rationale, share link | Noise, stale data, source contradictions |
| C. Research analyst (secondary) | One entity is partially documented | Manual search, browsing multiple sources | Missing fields surfaced, provenance and conflicts shown | Apparent completeness when evidence is absent |
| D. Developer / OSS user (secondary) | Needs repeatable extraction for a known set of public pages | Scripts, CLI, HN/OSS tools | Deterministic runs, JSON exports, run budgets | Configuration and maintenance |

### JTBD

- When I need to **compare three publicly documented competing tools**, help me create an audit-friendly table quickly so I can make a decision without checking each item manually.
- When a competitor **changes a price or plan**, show the old and new values with exact evidence so I can tell whether action is warranted.
- When a claim is **not present or conflicts across sources**, display uncertainty and suggest the next public source to verify, instead of inventing a value.
- When a run fails or exceeds budget, show me which source failed and allow safe resume without losing prior reviewed evidence.
- When I share a result, colleagues should be able to trace it to source, version and collection time without seeing private project notes or credentials.

## 4. Information architecture

    Landing / Demo
      ├── Templates (Compare SaaS pricing / Product feature mapping / Documentation delta)
      └── Instant public demo (pre-approved sites and frozen evidence)
    Workspace
      ├── Inbox / Projects
      ├── Research project (scope, questions, watch policy)
      │   ├── Brief (executive summary with source-linked claims)
      │   ├── Comparison (fact matrix, unknowns and conflicts)
      │   ├── Evidence (source snapshots and highlighted anchors)
      │   ├── Changes (version comparison, significance, acknowledge)
      │   └── Runs (logs, cost, failures, retry/resume)
      └── Saved / Shared briefs
    Preferences
      ├── Privacy, exports and retention
      ├── Execution budgets and allowed sources
      └── Notifications (P1; disabled until configured)

The initial dashboard should **not** show raw browser sessions and infrastructure metrics. Technical panels remain accessible through the Run detail page.

## 5. First 120 seconds: demo / onboarding contract

**Two safe entry points:**
- No-account demo: a frozen, published and licensed/approved set of public pages; optional sandboxed browser playback inside the product; never fetch arbitrary URL from an anonymous visitor.
- Authenticated research: public URLs within the approved domain policy, only after server-side tenancy/auth, quotas, sandbox and real proxy egress hardening are implemented.

### Demo storyboard

**0–15 s — Ask.** Landing hero says "Compare competitors with evidence, not guesses." One primary "Try the demo" action. Start with 3 known products, an editable research question and a visible note: "Example snapshots, last checked [date]."

**15–35 s — Observe.** A short trace shows "3 sources loaded → 12 candidate facts extracted → 9 checked / 3 unresolved". Counts are sample UI data, not a live run guarantee. Display live progress only when the work is genuinely executing; frozen demo must be labeled "Demo replay".

**35–70 s — Understand.** A comparison matrix appears; each data cell has a source, date and verification indicator. Unknowns are visible, not blankly completed.

**70–95 s — Verify.** Clicking a price opens source evidence side by side with a highlighted excerpt and a snapshot timestamp. If the source moved, the archived excerpt remains available under retention policy.

**95–120 s — Act.** Click "Export brief" or "Save this research". Sharing is an explicit action; account creation is deferred until someone chooses a persistent workflow. No signup wall before first value.

### Empty, error and partial states

- **No source data:** "We couldn't retrieve this page. No facts were inferred from it." Show attempt status.
- **Budget exhausted:** "Stopped at your cost limit. 2 of 3 sources completed." Offer resume with explicit limit change.
- **Contradictory facts:** show both values and source contexts, never choose silently.
- **Source disappeared:** keep historical evidence and label current verification as unavailable.
- **Source stale:** last verified timestamp displayed separately from last attempted timestamp.
- **Snapshot forbidden or sensitive:** omit raw capture, retain permitted URL/citation and warning; do not bypass restrictions.
- **Long tasks:** show stages and intermediate verified outputs, allow cancellation and leave checkpoint for safe resume.

## 6. Product requirements with acceptance tests

### P0-F01 — Structured research project creation

**Inputs:** research question; 1–5 public approved seed URLs; supported template; output fields; optional locale/currency; max pages and spending budget.

**Outputs:** project ID, run ID, scope, source policy and audit trail.

**Acceptance:** project initiation from template ≤3 meaningful input actions; duplicate source URLs canonicalized; unsafe/private/loopback targets rejected; source list visible before execution. An imported URL is not treated as user authorization for any other domain.

### P0-F02 — Evidence-preserving source capture

Store immutable snapshot metadata (source URL, fetched_at UTC, final URL, status, content hash, extraction version, allowed-content pointer). Persist full captured content only where lawful/permitted and within retention limits.

**Acceptance:** all displayed claims link to a snapshot and a text-span/DOM anchor or explicitly show "unanchored, not verified"; bad offsets are rejected; stale anchor reports relocation failure, not a fabricated match. Original source URL may no longer serve the same content; user sees snapshot and fetch time.

### P0-F03 — Typed facts / claims and verification states

Model data as subject–predicate–value+unit+conditions, not a string summary alone. Examples: product P / plan Pro / monthly USD / 29 / billed annually vs monthly; feature availability / product P / platform Linux / supported.

Verification state machine:

    CANDIDATE → SUPPORTED
              → CONFLICTED
              → INSUFFICIENT
              → REJECTED
    SUPPORTED → OUTDATED (on material new evidence)
    Any state → NEEDS_REVIEW

A claim is SUPPORTED **only if** the recorded evidence entails that claim within the recorded context; a citation existing is insufficient. "Confidence score" is not a replacement for evidence or adjudication.

**Acceptance:** no unanchored candidate can be labeled supported; numeric currency/units/period normalized; sources that disagree produce conflicted; contradicted or unsupported claims do not silently appear as facts in the brief. Evaluator has separate author and held-out labels.

### P0-F04 — Cross-source comparison and missing data

Matrix rows are fields; columns are products/entities. Each cell has value or explicit Unknown / Not accessible / Ambiguous / Conflict, a source and last-verified timestamp.

Optional source expansion is a bounded plan approved by user or confined to a pre-approved public source list; no recursive uncontrolled browsing.

**Acceptance:** missing data not inferred from industry norm; at least one unresolved cell is called out with next verification action; cannot compare yearly and monthly prices without explicit conversion labels.

### P0-F05 — Research brief and constrained sharing

Provide one-screen executive summary, comparison table, evidence appendix, run status and downloadable Markdown/JSON exports. Read-only public share link is disabled by default and requires explicit user action, owner authorization, redaction and a time-limited or revocable share token.

**Acceptance:** private notes and credentials never appear in shared payload; source evidence metadata is retained; all important statements are traceable; re-opened shared brief is immutable to viewers; share revoked → subsequent access denied.

### P0-F06 — Budget and deterministic-first execution

Budget fields: max_pages, max_browser_minutes, max_model_tokens, max_estimated_cost_usd and per-source timeouts. Report estimated spend vs actual measured spend, with pricing/version assumptions.

Prefer HTTP fetch → extraction heuristic → stable selector/structured data. Escalate to browser rendering or model-based extraction **only when required** and allowed. Cache page hashes and extraction recipes, invalidate deterministically if checks fail.

**Acceptance:** hard limits stop new work before crossing configured maximum except bounded in-flight uncertainty; run reports budget-exhausted state, never success; recording/replay path produces the same fields under unchanged inputs in goldens; record/model versions attached.

### P0-F07 — Run observability, resume and error recovery

Run statuses: CREATED → QUEUED → RUNNING → PARTIAL / COMPLETED / FAILED / CANCELLED / BUDGET_EXHAUSTED; RESUMING returns to RUNNING. All transitions persist with timestamp, idempotency key and reason.

**Acceptance:** restart during a page result+discovered child transaction preserves either both committed or neither; lease expiry cannot allow stale result overwrite; timeouts, blocked pages and parse failures are distinct statuses; user knows precisely what finished.

### P0-F08 — Ethical, safe execution

Domain allowlist, robots/sitemap policy honoring (subject to legitimate deployment policy), rate limiting, payload caps, timeouts, egress isolation and no arbitrary cloud URL execution until verified. Protect internal routes, link-local, metadata IPs, redirects, subresources, WebSocket/IPv6 and DNS rebinding at network layer. Block or isolate HTML script execution in evidence preview.

**Acceptance:** isolated real-browser test suite includes direct egress denial and blocked subresources. Production Squid/firewall-specific tests and independent security review are separate release gates; successful demo must not imply arbitrary URL cloud safety.

### P1-F09 — Fact-level semantic changes

Track changed facts (price, feature, policy) across snapshots, not generic HTML diff. Keep layout/boilerplate noise suppressed with reasons that can be inspected. Categorize Added / Changed / Removed / Uncertain / ParsingFailure. Require source-confirmed old/new values.

**Acceptance:** on a labeled benchmark, change precision ≥90% and important-change recall ≥95% before enabling notifications to a beta cohort. These are **hypothesis targets** requiring verified dataset and blind labels. Alerts must distinguish "no change" from "fetch failed".

### P1-F10 — Recurring research and meaningful digest

Schedules only after user activation and quota consent. Weekly digest defaults to changes that affect fields in the dossier, not every DOM movement. User sets channel, event filters and quiet time. Export an RSS feed only if audience interviews indicate need.

**Acceptance:** no duplicate alerts for the same semantic event and source version; every alert has link to evidence diff; digest honors user's notification choices; failures shown in a health view; simple folders/projects supported.

### P1-F11 — Review and corrections

Users flag a claim as wrong, outdated or missing context. Revisions are append-only with actor/version/reason and preserved old claim. Creator of a claim does not independently certify it.

**Acceptance:** reviewers can accept/reject and see lineage; corrected facts propagate to the report deterministically; no public share of unreviewed sensitive notes.

### P2 — API, connectors and team collaboration

Open API for immutable briefs, structured export, webhooks and MCP; role-based workspace collaboration, team change inbox, integrations, billing and dedicated self-hosted deployment. Defer until retention and willingness-to-pay data exist.

## 7. Core user stories and negative scenarios

| ID | Story | Acceptance examples |
|---|---|---|
| US-01 | As founder, compare 3 SaaS plans from official pages | Normalized price periods, link-backed evidence, missing values visible |
| US-02 | As PM, track competitor feature changes over one month | At least one material change has old/new snapshots and evidence |
| US-03 | As analyst, identify which claim has weak support | Filter for insufficient/conflicted and see source gaps |
| US-04 | As researcher, rerun after network timeout | Completed sources remain, failed one retried, no duplicate report rows |
| US-05 | As cost-conscious developer, cap expensive tasks | Limit enforced, ledger visible, model not called when cached extraction sufficient |
| US-06 | As collaborator, share a report without exposing raw notes | Redacted read-only link, revocable, immutable report version |
| US-07 | As user, see why an alert was suppressed | Show ignored diff with reason and restore action |
| US-08 | As self-hosting developer, inspect dependencies and licenses | SBOM/licensing disclosed, OSS attributions explicit |
| US-09 | As user, stop and delete research data | Remove owned snapshots/reports per retention contract, subject to backup expiry |
| US-10 | As site operator, control excessive crawling | Respect documented robots policy and rate limits; transparent user-agent/contact |

## 8. UI screens and component states

### Screen A — Marketing / instant demo

Hero: "Know what changed. Prove why it matters." One CTA. A live example section demonstrates a specific price/feature claim with a clickable evidence anchor. Trust footer: limits, snapshot freshness, data sources, self-hosted route.

**Not:** system architecture diagram, source-code metrics, fake progress animation or repeated login prompt.

### Screen B — Research setup

Wizard collapsed into a single page: goal textarea, website chips, comparison template, estimated run budget and "Start research". Advanced controls in a disclosure panel. Source validation inline. Unsafe or unallowlisted URL gives an actionable, neutral error.

### Screen C — Evidence Workspace (primary)

Two-column desktop: left ~65% claim matrix/brief, right ~35% evidence pane. Mobile: stacked tabs "Brief / Evidence / Changes". Top strip: source coverage, last verified, cost, partial failures. Source entries carry domain, snapshot time and content hash via details.

Essential interactions:
1. Click claim -> highlight evidence excerpt; keyboard focus and screen-reader text announce source.
2. Click conflict -> show evidence from both sources, different conditions and last run.
3. Click missing -> ask the user to confirm public-source expansion; never silently invent.
4. Compare version -> old/new side by side with normalized units and explicit uncertainty.
5. Save/export -> confirmation including disclosure of what will be shared.

### Screen D — Runs, budget and diagnosis

Show Stage, Attempts, Last Error, Est. Remaining Cost, Actual Tokens/Browser Minutes, source list, retry control, cancel, results retained. A retry is disabled when scope or budget would change without confirmation.

### Screen E — Watch (P1)

List monitored research questions rather than ungrouped raw URLs; clusters by project; unread meaningful changes, failure state, alert snooze and channel. Allow "mark irrelevant", feeding evaluator labels with consent.

### Visual language and accessibility

- Semantic status text and neutral icons; never convey evidence state with color alone.
- Clear labels for "Source found", "Claim supported", "Human reviewed" — these are not equivalent.
- Body text scalable, WCAG AA contrast, accessible tables and reduced-motion mode.
- Skeleton state for real asynchronous work, predictable focus, no optimistic "saved" before persistence completes.
- Default brief is scannable; technical trace sits one click deeper.
- Mobile first-run avoids horizontally overflowing tables by presenting per-product comparison cards.
- Design approval requires user usability testing, not just screenshot aesthetics.

## 9. Proposed data contract and schema

Logical tables/entities, implementable in SQLite initially with strict migrations:

| Entity | Key fields | Required invariants |
|---|---|---|
| Workspace | id, owner_id, policy_version, created_at | Owner-scoped; namespaced identity is not access control |
| ResearchProject | id, workspace_id, question, field_schema_version, created_at | Versioned question and target fields |
| Source | id, project_id, canonical_url, allowed_domain, source_type | Reject private or unauthorized targets |
| Snapshot | id, source_id, run_id, fetched_at, resolved_url, status, content_hash, allowed_content_ref | Immutable capture; source timestamps and hashes recorded |
| Fact | id, subject, predicate, typed_value, unit, period, conditions, extraction_version | No string-only ambiguous price comparisons |
| EvidenceAnchor | id, snapshot_id, start_offset, end_offset, quote_hash, DOM_path, status | Must point to snapshot and exact verifiable span |
| Claim | id, project_id, normalized_fact_key, verification_state, current_revision_id | State cannot be SUPPORTED without justified anchors |
| ClaimEvidence | claim_revision_id, evidence_anchor_id, stance, rationale | Evidence is many-to-many with claim revisions |
| ClaimRevision | id, claim_id, actor, created_at, prior_revision_id, decision_reason | Append-only, auditable |
| ChangeEvent | id, fact_key, prior_snapshot_id, next_snapshot_id, change_kind, significance, evidence_status | Deduplicate by version+fact key |
| Run | id, project_id, status, lease_token, attempt, started_at, completed_at, error_code | At-least-once execution, fenced commits |
| BudgetLedger | run_id, model_tokens, browser_seconds, estimated_cost, billed_cost, pricing_version | Never present estimated dollars as actual charge |
| ShareGrant | id, owner_id, report_version, token_hash, expires_at, revoked_at | Least privilege; can revoke |
| AlertDelivery | event_id, recipient_id, channel, delivered_at, idempotency_key | No duplicate notifications for same event |

### Fact and evidence example

    {
      "subject": {"product": "ExampleTool", "plan": "Pro"},
      "predicate": "monthly_price",
      "value": {"amount": 29, "currency": "USD", "billing_period": "month", "billing_condition": "annual_commitment"},
      "source_snapshot_id": "snap_123",
      "evidence_anchor": {"start_offset": 841, "end_offset": 879, "quote_hash": "sha256:..."},
      "claim_state": "SUPPORTED",
      "verification_method": "independent_rule_v1",
      "verified_at_utc": "2026-11-03T00:00:00Z"
    }

Illustrative fixture only; neither price nor source is a factual claim about a real vendor.

### Source anchoring semantics

Use normalized raw Unicode text for offsets, save extraction transform and content hash. If a newer fetch changes text, do NOT reuse raw offsets. Re-anchor with exact quote hash and local context; if ambiguous, label anchor_stale and require review. Validate preview escaping to prevent HTML injection; never execute source-site scripts inside the Evidence pane.

### Decision on contradiction and uncertainty

- Supported: evidence directly supports a precise claim within conditions.
- Conflicted: two or more admissible sources give mutually inconsistent facts after unit/period normalization; show both.
- Insufficient: no adequate evidence; cannot "prove absence" from a failed fetch.
- Outdated: evidence was superseded by a more recent snapshot; preserve prior revision.
- Rejected: evidence does not actually entail claim.

"Verified" means **traceably supported by the available evidence under recorded conditions**, not universally true or independently audited by a human.

## 10. API and execution proposal (not yet implemented)

### Read endpoints (versioned)

    POST /api/v1/projects
    GET  /api/v1/projects/{project_id}
    POST /api/v1/projects/{project_id}/runs
    GET  /api/v1/runs/{run_id}
    GET  /api/v1/runs/{run_id}/events
    POST /api/v1/runs/{run_id}/cancel
    POST /api/v1/runs/{run_id}/resume
    GET  /api/v1/projects/{project_id}/brief?version=...
    GET  /api/v1/claims/{claim_id}/evidence
    POST /api/v1/claims/{claim_id}/review
    GET  /api/v1/projects/{project_id}/changes
    POST /api/v1/projects/{project_id}/shares
    DELETE /api/v1/shares/{share_id}

### Error contract

    {
      "error": {
        "code": "SOURCE_OUTSIDE_POLICY",
        "message": "This source cannot be accessed under this project's policy.",
        "retryable": false,
        "source_id": "src_123",
        "run_id": "run_123"
      }
    }

Stable codes include SOURCE_OUTSIDE_POLICY, FETCH_TIMEOUT, ROBOTS_RESTRICTED, CONTENT_UNAVAILABLE, EXTRACTION_FAILED, ANCHOR_STALE, BUDGET_EXHAUSTED, LEASE_EXPIRED, CONFLICT_NEEDS_REVIEW, SHARE_REVOKED and INTERNAL_ERROR. Never return raw proxy credentials, cookies, request headers or internal addresses in API errors.

### Execution pipeline

    ResearchProject + approved source policy + budget
      → SourcePlan (bounded, deduplicated)
      → FetchDecision (HTTP by default; browser only if needed)
      → Immutable Capture (hash + permitted content)
      → Normalize & Extract (DOM / Text / small LLM where necessary)
      → Candidate Facts
      → Evidence Anchor + independent verification
      → Claim Store (append-only revisions)
      → Cross-source Reconciliation
      → Dossier renderer
      → Optional change detection on later runs
      → Optional user-approved share / alert

**Caching:** cache by URL + extraction policy + source hash + parser/model version, never by URL only. Cache invalidation must honor scope and access policy. Do not silently share cache across users when data access is not public.

## 11. Mapping to the existing repository

| Existing module | Reuse | Proposed new owner |
|---|---|---|
| browser_engine.py | HTTP / Selenium page fetch; fail-closed boundaries | adapters/fetch.py (later; no breaking rewrite required) |
| url_policy.py + network_policy.py | Preflight rules and browser proxy settings | security/egress_contract.py with deployment tests |
| frontier_state.py + durable_queue.py | SQLite leasing, result+children transaction, task identity | runtime/job_store.py + run event log |
| content_extractor.py | Trafilatura/BeautifulSoup extraction | extraction/document_ir.py and evidence offsets |
| content_analyzer.py | LLM analysis | claim_extractor.py, independent claim_verifier.py |
| report_generator.py | Markdown/JSON reports | dossiers/render.py, evidence references |
| crawler.py | Orchestration | service layer with project/run domain model |
| .github/workflows | CI and real browser tests | golden datasets, visual review, contract tests |

**Recommended architecture:** keep the Python core until MVP outcome is proven. A slim FastAPI service and Next.js web client may be added behind stable contracts after first UX prototype. Avoid a distributed microservice rewrite at this phase. Use an in-process task runner/SQLite for small controlled self-hosted pilots, then move to managed queue and tenant-isolated workers only when measured concurrency warrants it.

## 12. Security, data rights and privacy gates

**Non-negotiable for public hosted URL execution:**

This is explicitly a **server-side request forgery (SSRF)** threat boundary: application-layer URL/DNS preflight alone cannot prevent internal-network access if the real browser, proxy, redirect, subresource, alternate scheme or DNS resolution path can bypass the policy. Treat all extracted web content as untrusted input.

- Service-side authorization (not merely a hashed namespace); tenant-specific storage and quotas.
- Browser workers with no direct public egress; production proxy ACL tested for IPv4/IPv6, redirects, DNS rebinding, metadata IP and WebSockets.
- Separate, ephemeral browser profiles; no user's existing Chrome profile or stored passwords.
- Robots policies, reasonable request intervals and source Terms of Service; explicit user-agent/contact where appropriate.
- Strict content-size caps, response streaming/backpressure and safe file/media MIME handling.
- Untrusted web-page text is DATA, never executable instruction to the LLM or crawler; prompt-injection tests.
- Permission checks before evidence/snapshot/share export; share tokens hashed, revocable and scoped.
- Content retention defaults, owner-initiated deletion, audit trail, encrypted secrets, credential redaction.
- OSS attribution + license audit, especially if reusing changedetection.io or similar projects.
- Security and legality review for uploaded documents, third-party content storage and public quote display.

**MVP shortcut:** Demo from bundled non-sensitive, permission-vetted snapshots. This does not authorize exposing raw user URL crawling to anonymous traffic. Do not claim current repo CI alone certifies unrestricted multi-tenant safety.

## 13. Independent quality evaluation

### Dataset design

- 60 hand-labeled fixture snapshots from 12 page-template classes (pricing cards, tables, changelogs, multi-lingual units, JS-rendered content, redirects, blocked content, conflicting terms, empty results, reordered DOM, timestamps and duplicated content).
- 20 held-out version pairs for semantic change evaluation, including noise-only, material price changes, billing-condition changes, feature add/remove and inaccessible-source cases.
- At least 20 benchmark research tasks with blind labels (manual source-to-claim audit), stratified across simple and ambiguous questions.
- Separate training/dev and held-out evaluation; no prompt tuning on held-out labels.
- Two independent annotators, disagreement adjudication and per-category error tracking. Record inter-annotator agreement rather than hiding conflicts.

**These are target dataset sizes**, not existing fixtures.

### Proposed launch gates

| Metric | Measurement | Proposed minimum |
|---|---|---|
| Time to first inspectable demo result | P75 over >=30 cold new-user sessions | ≤120 seconds |
| Demo completion | User reaches evidence-backed result without help | ≥70% |
| Claim evidence precision | Blind manual audit of SUPPORTED claims | ≥98% |
| Numeric/unit correctness | Golden price/period/currency test | ≥99% |
| Important change recall (P1) | Held-out version pairs | ≥95% |
| Alert precision (P1) | Held-out noise and real changes | ≥90% |
| Resume integrity | Fault injection before/after DB commits | 100% invariant passes |
| Cost budget | Measured run cost compared to cap | 0 unauthorized task starts above cap |
| Core task success | Independent reviewer assesses complete real-world brief | ≥85% |
| Share safety | Cross-tenant and revoked link tests | Zero unauthorized access |
| 7-day return in beta | Real pilot cohort (not test accounts) | ≥25% |

These are provisional release thresholds, not population forecasts. A strong engineering CI pass does **not** imply they have been achieved.

### Error taxonomy and negative evidence

Record fetch failures separately from "field absent"; maintain the evaluation's precision/recall denominator for missing/unavailable. Annotator cannot use an LLM's own answer as the ground truth. For strict schema outputs, contract-check extraction with deterministic validators. User-visible "confidence" should never mask a broken source chain.

## 14. Product instrumentation and funnel

Event schema:
- demo_viewed, demo_started, brief_rendered, claim_opened, evidence_anchor_viewed, missing_field_opened, comparison_exported, signup_started, signup_completed, research_saved, schedule_activated, digest_opened, share_link_created, share_link_opened, run_failed, retry_requested, user_marked_alert_irrelevant.
- Every event carries anonymous_session_id or workspace_id (not both without documented consent), product_version, run_mode, template_id, experiment_variant and timestamp.
- Performance counters: time_to_first_evidence_ms, sources_requested, sources_succeeded, claims_extracted, claims_supported, claims_conflicted, budget_used_estimate, actual_provider_bill where available.
- Collect aggregate metrics with privacy safeguards; don't log raw page contents, credentials, arbitrary customer URLs or private research questions into general analytics by default.

North-star hypothesis: **weekly evidence-backed research briefs opened or shared by a real active workspace**. Guardrail metrics: false-supported claim rate, source coverage, failed runs, cost per usable brief, notification opt-outs, privacy incidents.

Funnel targets require actual cohorts:
Demo landing → start → brief viewed → evidence opened → export or save → 7-day revisit. Measure causal drop-offs before expanding features.

## 15. Pricing and packaging experiments (not commitments)

Test three concepts with real pilots:
- **Local OSS:** GitHub repository and self-hosted CLI; MIT only if current license and dependency audits permit this representation.
- **Starter hosted (hypothesis):** a free guided demo plus limited public-source dossiers; no arbitrary public URL until security passed.
- **Paid hosted (hypothesis):** $15–29 / month for a solo user and $49–99 / month for a small team, usage and budget caps visible, evidence archive and weekly digests. These are **test prices**, not validated prices or live offerings.

Use fixed-scope paid pilot interviews, price-sensitivity experiments and provider cost accounting; do not present paid tiers until COGS and support volume are measured. Charging per browser action is less intelligible to the ICP than charging for useful research workflows, but cost ceilings must remain transparent.

## 16. Delivery phases with stop/go decisions

### V0.2-A — Evidence demo (2 weeks, estimate)

Build fixture dataset and visual user journey, brief renderer, evidence cards, explicit unknown/conflict states and first 120-second guided walkthrough. User-test 10 participants; each must validate a specific claim without developer assistance.

**Stop if:** at least half cannot identify the source for the headline claim, or most users prefer manual flow.

### V0.2-B — Real public research behind safe deployment (3 weeks, estimate)

Bounded source planning, capture and normalization, structured facts, claim evidence verification, budgets, secure scoped auth, saved briefs and end-to-end fixture/live validation. Independent privacy and security review required before arbitrary URLs.

**Stop if:** factuality thresholds or cost budget fail.

### V0.3 — Continuous research (2–3 weeks, estimate)

Fact-level diff, source freshness, failure health, weekly digest, folders, alert acknowledgement and precision/recall evaluation. Add schedule only after safe egress and quotas.

**Stop if:** too many false alerts or inadequate meaningful-return rate.

### V0.4 — Growth and integrations (post-evidence)

Paid pilot, team access, API/export, RSS/webhooks and advanced evidence/workflows only if beta users demonstrate repeat work. Evaluate whether a self-hosted version is central to acquisition.

### Product Hunt ship gate

At least 20 target-user interviews, ≥30 new-user demo sessions, real repeat use, stable public demo, independently audited evidence, share privacy test, known security limits, prelaunch content and human support coverage. Product Hunt ranking is a *distribution outcome*, not proof of product-market fit.

## 17. Decisions, open questions and risks

| Decision / uncertainty | Current proposal | Owner / validation |
|---|---|---|
| Primary ICP | Solo SaaS builders / small PM teams | 20 interviews with recent real tasks |
| Product wedge | Evidence dossier, not just page monitoring | Blind side-by-side task choice |
| Anonymous demo | Approved frozen source snapshots | Legal/source audit |
| First real collector | Approved public sources only; tenant-isolated once safe | Security and ops review |
| Cross-source expansion | Scoped, bounded, user-visible | Accuracy/cost benchmark |
| Claim truth state | Supported vs insufficient vs conflicted | Independent human goldens |
| Snapshot retention | Configurable and minimized | Privacy/legal review |
| Competitive monitoring | P1 after single-brief value proven | Watch precision + revisit |
| B2B distribution | PH for discovery, developer/PM communities for feedback | Attribution and cohort conversion |
| Business model | No validated pricing yet | Paid pilot with disclosed limits |
| Browser SDK | Reuse existing Python stack; avoid rewrite | Benchmarks and actual requirements |
| Name | Working name Evidence Radar | Trademark/domain check |

### Final product principle

The user is not paying to watch a browser click, collect a pile of HTML or receive an unverified AI paragraph. The proposed product's unit of value is **one maintained, evidence-backed answer to a recurring practical question**, with transparent uncertainty, retry behavior and cost.

Until independent testing supports that benefit, keep the claim framed as a hypothesis and the product labeled a prototype.
