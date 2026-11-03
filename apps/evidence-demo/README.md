# Evidence Radar — V0.2-A Interactive Demo

**A product UX prototype, not a hosted crawler.** The app is a zero-dependency static HTML/CSS/JavaScript experience backed by **fictional, synthetic source snapshots**. It does **not** fetch the fictional vendor URLs or call an LLM. No account, API key, database, telemetry or payment is required.

## Run locally

From the repository root:

```bash
python3 -m http.server 8765 --directory apps/evidence-demo
# Open http://localhost:8765/
```

Do not use `file://` because browser security rules block module/JSON fetches. Use localhost or HTTPS. If hosted under a subpath (e.g. GitHub Pages), the relative asset paths continue to work.

## Test

```bash
npm --prefix apps/evidence-demo test
python3 -m unittest discover -s tests -p 'test_evidence_demo_static.py' -v
```

Optional Chrome E2E (requires `selenium>=4.25`, Chrome and an HTTP server at port 8765):

```bash
python3 -m unittest discover -s tests -p 'test_evidence_demo_browser.py' -v
```

GitHub CI performs these validations on Node 20/22 and actual Chrome, including a 390px mobile viewport and keyboard-driven tabs.

## User journey

1. Hero describes the value as a claim backed by a source rather than an AI assertion.
2. Click **Try the interactive demo**, choose among three scoped research questions. Only curated demo templates are supported.
3. Explore **Brief**, **Compare**, **Sources**, **Run details** tabs.
4. Select an evidence-linked fact to read an exact excerpt or full immutable synthetic snapshot. `supported`, `insufficient`, and `conflicted` are explicit distinct states.
5. Export Markdown or JSON; both are deterministic from the identical in-memory data model and clearly marked synthetic.

## Data and safety

- `data/demo.json` contains four fictional source snapshots and nine facts across AsterFlow, BirchDesk and CedarStack. All source addresses use the IANA-reserved `.example` TLD; **none are real vendors**.
- Source integrity uses saved SHA-256 hashes. Unit tests and the runtime verify all snapshot bytes before rendering.
- Evidence highlights use `textContent`/DOM nodes; raw text is never inserted as HTML. No third-party code, web fonts or remote assets are fetched.
- No claim about real-world pricing, performance, or market conditions is made. **Source-backed** means supported by the synthetic fixture text, not independently verified in reality.
- This static demo does not expose arbitrary URL crawling or user browser profiles. A production service requires auth, source permission, egress/SSRF review, quotas and additional privacy controls.

## Explicitly out of scope in V0.2-A

- Custom user URL input or arbitrary research questions
- Real crawling, semantic-change monitoring, recurring tasks or notifications
- Authenticated team workspace, persistent storage, paid plans or public share links
- Real-user first-time-value metric validation (requires independently recruited users)

## Product reference

See `docs/V0.2_A_IMPLEMENTATION.md` for requirement traceability and deployment gates; the full research-led V0.2 PRD is proposed in [PR #7](https://github.com/1998x-stack/intelligent-browser-tool/pull/7).

## V0.2-B — Local real research workspace

The V0.2-A offline demo remains unchanged in purpose and never fetches fictional vendor URLs. A separate **local-only** live research UI is available by starting the Python operator service:

```bash
python -m pip install -e '.[test]'
python -m research_workspace serve --allow-host www.python.org --port 8765
# Open http://127.0.0.1:8765/live.html and enter the printed local token.
```

This runs conservative real HTTP/HTML extraction and stores source snapshots, literal claims and exact evidence anchors in SQLite. It is not a hosted arbitrary URL browser service, and it is not a semantic LLM fact-checker. Source host allowlisting and robots checks are enforced; full cloud egress/SSRF compliance is not certified. For the implementation, API routes, tests and remaining release blockers see `docs/V0.2_B_IMPLEMENTATION.md`.

## V0.3 — Continuous Research (local operator only)

The **local live workspace** at `/live.html` now includes an opt-in, persisted
research schedule and fact-level change inbox. The original anonymous static
fictional demo remains offline-only and never fetches a URL.

After connecting with the local token, choose a saved project, run it twice,
then inspect **Important changes and review inbox**. Click **Inspect old and new
source evidence** for each event, mark it acknowledged/irrelevant, and export
Markdown digest. Only explicit anchored price values can produce verified
change events; keyword additions, removals, conflicts, and missing prices are
flagged for manual review. Failed page loads are shown as source health, never
reported as a verified fact change.

To activate recurring checks, enable a schedule in the local UI, then run a
periodic operator-controlled tick. For example (with audited hostnames):

```bash
python -m research_workspace tick \
  --allow-host example.com --db ./outputs/research_workspace.sqlite3
```

An enabled schedule **does not run unattended** without an OS-level cron or
systemd timer invoking the tick command. An explicit tick executes at most 3
due runs; SQLite idempotency prevents creating duplicate runs in the same
interval, and expired worker leases may be reclaimed. The in-app change inbox
and local Markdown digest are the only notification transports; **no email,
RSS push or webhooks are sent**.

Run V0.3 tests with
`python -m pytest -q tests/test_research_workspace.py tests/test_continuous_research.py`.
Read `docs/V0.3_CONTINUOUS_RESEARCH.md` for the schema, security limits,
source-evidence acceptance and deployment instructions.
