# Product Experiments & Product Hunt Launch Plan — Evidence Radar

**Status:** proposed execution playbook; no claim that beta metrics, published pages or pricing tiers currently exist.  
**Date:** 2026-11-03  
**Inputs:** [Research ledger](./VOICE_OF_CUSTOMER_2026.md), [PRD](./PRD_V0.2_EVIDENCE_RADAR.md).

## 1. The bet we should try to disprove

We hypothesize that independent SaaS founders and small product teams will favor a **maintained, evidence-linked competitor research brief** over basic webpage monitoring or a general AI answer.

The HN/PH comments give plausible product direction but **do not validate purchasing demand**. Good reviews about existing crawlers can mean the market is satisfied; multiple incumbents have close functionality.

The order of proof:

1. **Problem:** Do users have recurring, consequential cross-site questions?
2. **Usability:** Can first-time users build/understand a dossier without training?
3. **Trust:** Can they correctly assess where a claim came from, what was not verified, and why it changed?
4. **Retention:** Do they reopen the same research project next week?
5. **Economics:** Does the measured cost/support workload support a price users actually pay?
6. **Distribution:** Does the experience generate authentic shares and qualified signups?

Avoid calling a Product Hunt top position evidence of product-market fit.

## 2. Candidate demand segments and recruitment

| Group | Sample target | Screening | Desired real task |
|---|---:|---|---|
| SaaS solo founders | 8 | Checked ≥3 competitors in last 30 days | Compare features and pricing |
| Product managers / marketers | 6 | Presented competitor findings to team recently | Weekly competitive brief |
| Independent researchers | 4 | Need to reconcile multiple sources | Investigate missing/conflicting attributes |
| OSS developers / self-hosters | 4 | Operated or evaluated crawler/monitor recently | Repeat extraction under cost ceiling |

Total **22 interview targets**, not achieved sample. Balance current users of Visualping, Firecrawl, Browse AI, manual spreadsheets and non-paying OSS tools. Recruit with voluntary consent; avoid incentives tied to favorable public reviews or upvotes.

### Research protocol

1. Ask participant to show the last real research job and what decision it influenced.
2. Observe the current workflow and record time, pages, manual verification and handoff.
3. Ask for the last failure or misleading result and their mitigation.
4. Present two randomized mock outputs with identical facts: standard AI brief and Evidence Radar dossier.
5. Let participant verify one contested fact and export one brief without instructions.
6. Ask what they would substitute and what effort is required to switch.
7. Invite the participant to bring a real upcoming task next week; observe return rather than reported intent.
8. Only when real value is demonstrated, present price options and optional paid pilot.

Capture anonymized notes with consent. Do not upload proprietary competitor spreadsheets into a public demo without explicit permission.

### Interview exit criteria (proposal)

Proceed from discovery if ≥12/22 participants have a recurring research job documented by an artifact and ≥8/22 independently complete or request a real repeated project; otherwise revise ICP. These are deliberately demanding **planning thresholds**, not facts.

## 3. Experiments and decision table

| Exp ID | Hypothesis | Design | Independent judge | Pass / fail criteria |
|---|---|---|---|---|
| EXP-01 — Value comprehension | Users understand the product in 10s | 30 unmoderated landing visitors; ask "What does it do?" | Blind coding by two assessors | ≥24/30 state multi-source research or evidence rather than generic chatbot |
| EXP-02 — First-result | Demo creates clear value without onboarding | 30 first-time task sessions | Event logs + task recording | P75 ≤120s, ≥70% inspect output unaided |
| EXP-03 — Evidence advantage | Evidence cards reduce verification work and errors | Counterbalanced A/B crossover with same task data | Manual gold labels + timed tasks | ≥25% median verification time reduction without worse correctness |
| EXP-04 — Completeness | Multi-source expansion reduces false missing fields | 20 incomplete research tasks; bounded source sets | Independent gold matrix | More fields correctly resolved; 0 fabricated "supported" values |
| EXP-05 — Monitor quality (P1) | Semantic alerts are more useful than raw diffs | 20 held-out site version pairs and 6-week beta | Manually annotated important changes | Precision ≥90%, important-change recall ≥95% |
| EXP-06 — Spend control | Replays reduce cost while remaining reliable | At least 20 paired uncached/cached runs | API billing logs, error budget | Net lower cost per successful task, equal or improved correctness |
| EXP-07 — Weekly retention | People want an ongoing dossier | 20-user consented beta | Product analytics; no test accounts | ≥25% reopen/reuse within 7 days |
| EXP-08 — Share behavior | Trustworthy dossiers spread organically | Sharing control available to beta | Privacy-aware share-open events | ≥20% of successfully completed projects intentionally shared |
| EXP-09 — Pricing | Value supports sustainable paid use | Real task + optional paid pilot offer | Actual paid commitment, not survey agreement | ≥3 pilot commitments; COGS + support tracked; not a statistically robust PMF claim |

**Failure policy:** never lower metric thresholds after evaluating held-out data without documenting the protocol change and rerunning on fresh holdout data.

## 4. Quantitative measurement definitions

- **TTFV (time-to-first-verifiable-value):** from click of real Try Demo until an evidence-linked result is visually available and clickable; exclude preloaded fake traces only if explicitly labeled.
- **Demo task completion:** participant reaches result AND opens one evidence anchor; landing click alone is not completion.
- **Claim-supported precision:** verified-supported claims genuinely entailed by associated source spans / all claims labeled supported, separately report pricing/units and cross-source contradiction subsets.
- **Change precision:** meaningful change events correctly labeled / all predicted meaningful changes.
- **Important-change recall:** meaningful annotated changes found / all meaningful annotated changes.
- **Return:** same consented workspace opens or reruns a research project on a different day within 7 days; do not count bot or test account activity.
- **Cost per successful brief:** sum provider charges + compute estimates + amortized support / usable successful research projects; disclose estimation assumptions.
- **Coverage:** successfully accessible sources / sources approved for each run; unavailable not treated as "content did not change".
- **False security confidence:** report number of publicly reachable arbitrary URL paths before egress validation (target 0), unauthorized share access tests (target 0).

Always report numerator, denominator, sample size and observation period. Do not present point estimates without context.

## 5. MVP backlog and dependency gates

| Stage | Work package | Output | Dependency / definition of done |
|---|---|---|---|
| DISC-01 | Interview and task archive | 20+ evidence-indexed interviews | Consent, artifacts, independent observer |
| UX-01 | Hero / instant demo / starter template | 120s demo with 3 pre-approved sources | Two blinded first-use tests, accessibility |
| EVD-01 | Snapshot, source and anchor contracts | Immutable SourceSnapshot / Anchor records | Golden offset and HTML-escape tests |
| EVD-02 | Claim extraction and verification | Typed facts and proof states | Independent accuracy labels, contradiction cases |
| RCH-01 | Bounded cross-source plan | Missing-value investigation | Budget/source caps and explicit unknowns |
| RPT-01 | Dossier + export / safe share | Versioned read-only research brief | Revocation and data-leak regression |
| OPS-01 | Run state and spend budget | Queue UI, recovery, measured costs | Fault injection, retry, hard limits |
| SEC-01 | Production browser network boundary | Safe hosted public-source execution | Real proxy/firewall external review |
| EVAL-01 | Quality goldens and evaluator | Holdout accuracy, benchmark reports | No training on held-out sets |
| MON-01 (P1) | Semantic changes + digest | Material-change timeline and notifications | ≥90% precision and ≥95% recall |
| GTM-01 | Launch visual assets and content | Working demo, gallery, short video, maker story | Human review; no false claims |

### Recommended dependency graph

    DISC-01 ─→ UX-01 ─────────────────────→ GTM-01
               ├→ RPT-01 (requires EVD-01)
    EVD-01 ────┴→ EVD-02 ─→ RCH-01 ───────→ EVAL-01
    OPS-01 ─────→ runtime service ─────────→ MON-01
    SEC-01 ─────→ authorization of real public URL SaaS collection
    EVAL-01 + UX-01 + SEC-01 + privacy review → hosted launch gate

The **first independently shippable artifact** is a non-live, visibly labeled demo from approved snapshots with functioning evidence interaction and report export. No hidden uncontrolled web crawling.

## 6. Implementation acceptance checklist

- [ ] Every published data cell points to a source snapshot and extractable, correctly anchored span, or is marked unknown/insufficient.
- [ ] Model output without supporting text never becomes a supported claim.
- [ ] Price values include currency, billing period, discount terms and collection date.
- [ ] Missing/contradictory/inaccessible are distinct states and independently testable.
- [ ] Retry after SQLite transaction failure never reports success before commit; child URLs survive restart together with source result.
- [ ] Fresh authenticated project creation enforces server-side user authorization and quotas.
- [ ] Anonymous demo does not allow unrestricted URL fetching or share sensitive data.
- [ ] No browser sandbox/production SSRF claim until actual production proxy/IPv6/DNS and WebSocket tests pass.
- [ ] Source HTML preview escapes scripts/attributes; DOM anchors validated.
- [ ] Download, share and permissions controls work via keyboard and screen reader.
- [ ] Run cost is labeled estimated vs actual and cap condition is actionable.
- [ ] Users can report a wrong claim and see source lineage after correction.
- [ ] Documentation contains actual screenshots, confirmed not concept mockups, before launch.
- [ ] No promotional feature claims appear on Product Hunt before shipping them.

## 7. Pricing research and unit economics

The "low cost" demand from HN does not give a valid universal price point. The $3.20 anecdote was one task; cloud browser, extraction and LLM spend vary by page and model. Price against successful research tasks, not tokens in isolation.

### Unit cost model

    COGS_per_brief =
       LLM_api_cost_actual
     + browser_cpu_seconds * hosting_rate
     + retained_snapshot_GB_days * storage_rate
     + worker_queue / network / notifications
     + estimated human support hours * cost_per_hour

    gross_margin = (price_received - COGS) / price_received

For a free demo: include CDN/transfer and abuse protection; for hosted recurring monitors: include repeated checks even when no change. Collect real usage before promises about unlimited monitors or unlimited pages.

### Packaging to test

- Open-source self-hosted core: free source and documented licensing; support optional.
- Hosted free test: public curated example, several exports, no unlimited arbitrary URLs.
- Solo paid pilot: test $15, $24, $29 per month options with explicit researched-project and compute limits.
- Team paid pilot: test $49 and $99 with workspace sharing and scheduled digests.
- Bring-your-own-model keys: research interest only; if supported, key handling and user billing remain explicit.

Do not publish those as real tiers until the service and billing exist, actual COGS is known, and target users choose the offering.

## 8. Product Hunt 2026 strategy

The official [2026 Product Hunt Launch Guide](https://help.producthunt.com/en/articles/17350772-launch-guide) describes: useful, live products; an understandable headline; original approach; high-quality visual assets; genuine maker engagement. It states a **60-character tagline cap** and a **260-character short description cap**. Avoid mixing with older guides that list a different description limit. The official [Featuring Guidelines](https://help.producthunt.com/en/articles/9883485-product-hunt-featuring-guidelines) emphasize **Useful / Novel / High Craft / Creative**. The [points explanation](https://help.producthunt.com/en/articles/10275873-what-are-points) explicitly combines upvotes with other meaningful engagement. The [commenting policy](https://help.producthunt.com/en/articles/10030102-commenting-guidelines) discourages low-value or AI-generated comments.

### Launch goal

Primary: reach qualified founders/PMs who complete a useful verified research task and return. Secondary: authentic discussion, GitHub traffic and high-quality demo feedback. **Product of the Day Top 5** is an aspiration, not a predictable KPI.

### Proposed name / category

**Evidence Radar** — working name; verify trademark and domain availability.

**Tagline option A:** AI web research with proof, not just answers.  
**Tagline option B:** Turn changing websites into verified research.  
**Tagline option C:** Know what changed. See the evidence.

**Short description draft (under 260 characters):**

Compare public websites, verify the details behind every claim, and track meaningful changes. Evidence Radar creates source-linked research briefs you can review, export, and share—without pretending missing information is a fact.

This is **proposed copy**, not ready to publish until named capabilities truly ship.

### Positioning decision in the first three seconds

Users must immediately understand what is delivered: one comparative report with real evidence. Do not lead with Selenium, SQLite, RAG, Agent Loop, MCP, LLM orchestration or "the world's best" claims. Tech can be explained in the implementation section for advanced users.

### Launch gallery: 5 planned frames

1. **Question → Brief:** three public URLs and one question, with a finished evidence-linked comparison. Label demo snapshots.
2. **Evidence Anchor:** side pane showing claim, exact source text and frozen capture date.
3. **Contradictions & Unknowns:** a real example of refusing to fabricate missing pricing/conditions.
4. **Fact-level Change:** old/new plans, terms, source snapshots and severity; only show after P1 actually ships.
5. **Share / Export / Self-hosted:** view-only link, Markdown/JSON, optional self-hosted architecture; do not promise functionality not available.

### 45–60 second demo script

- 0–7 s: "AI can summarize a website. But can you verify its claims?"
- 7–16 s: enter a precise competitor question, with three approved public sites.
- 16–29 s: show the running plan, evidence coverage and one explicitly unresolved fact.
- 29–42 s: click a data point, inspect its actual source text and collection time.
- 42–52 s: compare two sourced versions; explain an important change only if implemented.
- 52–60 s: export/share a useful brief; CTA to run demo, not a promise of unspecified automation.

Use real recording with accurate timestamps, no fake computation effects and no unsupported claims.

### Maker first comment outline

Explain the personal frustration (manual research and unsupported AI summaries), show the narrow supported use case and why sources remain inspectable. State what is live, what is missing (especially authenticated sources, unsupported domains, monitored-change limitations), privacy stance and genuine request for beta feedback. Do not request upvotes.

### Timeline relative to launch date T

| Time | Deliverables |
|---|---|
| T-30 to T-21 | Recruit 20 user interviews, test positioning, identify blocking failures |
| T-20 to T-14 | Complete demo and independent evidence goldens; obtain actual task-based feedback |
| T-13 to T-8 | Finish product page/gallery/video, baseline analytics and support FAQ |
| T-7 to T-3 | Final fresh-install + browser E2E + independent privacy/security checks; freeze major features |
| T-2 to T-1 | Dry run exact demo, check all public links, speed and mobile; schedule launch when staffed |
| T day | Monitor errors, reply to substantive comments, invite real user feedback; no mass voting requests |
| T+1 to T+7 | Publish failure/feedback learnings, identify pilot follow-ups, measure real reuse |
| T+8 to T+30 | Fix top user blockers, analyze qualified conversion and retention, decide next release |

PH's current guide says schedule at 12:01 Pacific to obtain a full launch day **only where it fits the team and audience**; time choice does not guarantee ranking. It allows self-hunting and prohibits direct upvote requests or engagement manipulation.

### Distribution channels beyond PH

- Hacker News: post an engineering Show HN only for a real working tool; include benchmark reproduction, source audit limitations and license attributions. Expect critical security/cost questions.
- GitHub: clear README, reproducible demo, self-hosted option and documented provenance.
- SaaS builders/PMs: share a useful public competitor report with source evidence; avoid mass automated outreach.
- Blog: publish measured before/after evidence verification and cost comparisons, not unverifiable speed/accuracy claims.
- Community feedback: voluntary, human-authored; no synthetic comments, purchased reactions or rewards for voting.

## 9. Launch diagnostics and decision rules

### Funnel

Landing visitors → demo starts → evidence opened → brief exported/saved → qualified workspace → repeat use after 7 days → paid pilot.

Instrument exactly those transitions with privacy-aware logs. Record failures (timeouts, denied sources, evidence gaps) and total sample counts. Use cohort analysis by use case, not only PH referral traffic.

### Go/no-go

**GO** only if demo genuinely works for first-timers, claim/source checks pass held-out goldens, share permissions are safe, production network perimeter is independently verified for the offered mode, COGS is under control and there are real completed pilot tasks.

**DEFER** if users enjoy seeing the demo but cannot use an output for a real decision, if stale claims appear as current, if any anonymous endpoint can fetch arbitrary untrusted URLs before security review, or if the source clickthrough repeatedly fails.

**PIVOT** from competitor radar if users show high enthusiasm but no recurring task or switching willingness. Consider evidence-backed documentation change tracking (technical teams) or analyst-grade source reconciliation after collecting explicit job evidence; do not simply add more features.

## 10. Feedback triage after launch

For every substantive issue record: source, task ID (if user consented), source domain class, failure stage, reproducibility, user impact, type (bug / workflow blocker / product gap / pricing), proposed fix, assigned owner and verification method.

Weekly review changes the roadmap based on **failed tasks and completed user workflows**, not votes, social praise or promotional comments.

### Representative review response policy

- Admit and show reproducible error if credible; avoid defensiveness.
- Distinguish technical limitations from permission/access restrictions.
- Publish known failure modes and supported domains.
- Give direct actionable next step; do not promise exact future delivery timing without engineering commitment.
- Ask for private logs only after consent; strip authentication and sensitive content.

## 11. Security and ethics before growth

Do not allow Product Hunt traffic to become an unrestricted browser proxy or a scraper abuse platform. Crawler honoring rules, egress enforcement, per-user quotas, cost bounds, SSRF protection and data deletion are release gates. Public report snippets should remain within permitted source usage. Credit third-party/open-source dependencies clearly, including components whose upstream licenses may impose obligations; follow legal review.

HN Site Spy's 2026 attribution dispute is direct evidence that OSS provenance can affect trust even if a product has a polished interface. Reusing another OSS engine is fine only when license obligations are followed and the relationship is accurately disclosed.

## 12. Execution ownership and deliverable index

| Responsibility | Minimum output |
|---|---|
| Product | Interview corpus, evidence-ranked PRD, explicit stop/go memo |
| Design | First 120s interactive flow, evidence card, empty/error/mobile states, accessibility testing |
| Backend | Source snapshot, claim/fact/evidence models, bounded job orchestration, cost and retention |
| Evaluation | Independent goldens, provenance and contradiction scorer, regression dashboard |
| Security/Operations | Sandbox deployment, real egress/proxy controls, abuse detection, incident / deletion protocols |
| Marketing | PH-ready working demo, truthful copy, gallery, authentic maker engagement and follow-up |
| Founder | Run real user studies, accept or reject roadmap decisions, own release gate |

The documents propose a delivery plan; they **do not assert that these artifacts, customers, paid pilots or hosted features already exist**.
