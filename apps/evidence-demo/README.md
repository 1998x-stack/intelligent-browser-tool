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
