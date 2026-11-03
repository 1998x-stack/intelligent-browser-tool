# V0.1.4 Unified Core — release candidate

## Intent

Single GitHub PR against the latest main. Incorporates prior feature work
without rebasing or force-pushing historical PRs. Maintains PR #2's
installable CLI and safe link-domain checks, while bringing the SQLite Frontier,
network gate, evaluation, task namespace, retention and Chrome E2E from the
previously stacked PRs #4 and #5.

## Correctness invariants

1. A completed page, its serialized result, and admitted child URLs commit in
   **one SQLite transaction**. A simulated SQLite trigger failure rolls the
   entire transaction back; the in-memory lease token survives for retry.
2. Expired workers cannot complete newer leases. Multiple SQLite connections
   can lease different URLs concurrently without duplicates.
3. A task ID's persisted identity includes logical namespace, original URL,
   intent, allowlisted domains and depth policy; identity mismatch fails closed.
4. Retention removes only old terminal URLs with known finish timestamps;
   queued and leased tasks are preserved.
5. A resumed report is aggregated from durable results, one row per URL.
6. Chrome is exercised both with a host-local enforcing test proxy and from
   a strictly internal Docker network with a deny-by-default test proxy.
7. Packaging declares all executable new modules: `durable_queue`,
   `frontier_state`, `network_policy`. The installed CLI remains compatible.

## Validation gates

- Python 3.10 and 3.12 test matrix + installed CLI smoke.
- Python 3.11 offline suite + repeatable queue benchmark.
- Real Chrome browser E2E on the host.
- Real Chrome E2E on a Docker internal-only network; no WebDriver port
  published, direct public browsing must fail, cross-domain resources are denied.
- Verify GitHub PR mergeability against main and no conflict markers.
- Keep versioned results attached to the PR; do not declare a deployment
  production-safe from the synthetic proxy alone.

## Known risks / not a production security certification

- `URLPolicy.validate` is DNS preflight, not socket-level IP pinning;
  production needs **real** deny-by-default egress control.
- The tested proxy is a small controlled fixture, **not production Squid**.
  The production Squid ACL example must undergo independent integration,
  deployment, DNS, IPv6, WebSocket and cloud metadata access tests.
- Namespace hashing is a logical partition, not authorization, encryption,
  tenant filesystem access control or OS-level isolation.
- SQLite offers at-least-once queue delivery. External HTML, media and
  report artifacts may be duplicated if a worker crashes after writing them;
  only DB page results and child discovery are committed atomically.
- The historical V0.1.3 task DB lacked a verified tenant identity, so it is
  not automatically imported; users must audit migration explicitly.
- Synthetic benchmarks do not characterize network or LLM throughput.

## Rollout

Keep durable mode opt-in and do not enable multi-tenant arbitrary-URL access.
Audit production proxy and firewall configuration, real DNS rebinding/IPv6/
WebSocket coverage and artifact idempotency separately before release.
