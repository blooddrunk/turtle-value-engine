# Codex Goal — Phase 5R-A M2-T FQGate Deployment-Neutral Endpoint Transport

Work in repository `blooddrunk/turtle-value-engine` on current `main`.

Read and follow, in source-of-truth order:

- `AGENTS.md`
- `docs/spec/`
- `rules/strict-v1.yaml`
- `schemas/`
- `docs/architecture/`
- `docs/goals/phase-5r-a-m2-t-fqgate-endpoint-transport.md`
- `docs/goals/phase-5r-a-m2-h-share-history-source-selection.md`
- `docs/status/phase-5r-a-2026-09-17.md`
- `docs/operations/phase-5r-a-acquisition.md`
- `src/turtle_value_engine/historical/fqgate.py`
- `src/turtle_value_engine/historical/acquisition.py`
- `tests/test_fqgate_historical.py`
- `tests/test_phase_5r_acquisition.py`

Cross-repository context to verify before relying on any remote contract:

- `blooddrunk/fqgate-remote-bridge`
- its `docs/architecture.md`, `docs/security.md`, `docs/roadmap.md`

Current facts:

- Phase 5R-A M2-A is complete on main at baseline
  `9316355ca17cdb0b952834bf5b17040a23b46d35`.
- Current FQGate adapter is local-only by semantics: adapter id
  `fqgate-local-market-history`, loopback-oriented diagnostics, no `credential_ref`, and
  401/403 currently mean FQGate entitlement denial.
- `fqgate-remote-bridge` Phase 2 is complete, but Cloudflare Tunnel is Phase 3 and stable
  machine-authenticated read-only remote API is Phase 4. Do not fabricate a remote route,
  auth contract or live success if those are not yet present on that repo's main branch.
- The goal is to make Turtle's FQGate acquisition topology deployment-neutral without
  moving Tunnel/Access/FQGate lifecycle into Turtle.

Implement only M2-T. Do not start M2-B source selection in the same goal except for any
bounded compatibility smoke test strictly needed by M2-T.

Required behavior:

1. Preserve legacy compatibility.
   - Existing `fqgate-local-market-history` plans/receipts/batches remain readable and
     replayable.
   - Do not silently rename the persisted adapter identity in place.
   - Prefer adding a new deployment-neutral adapter identity, e.g. `fqgate-market-history`,
     while explicitly supporting the legacy decoder path.

2. Add explicit endpoint topology semantics.
   - Support a new explicit `LOCAL_DIRECT` mode and a `REMOTE_BRIDGE` mode through request
     parameters or another additive representation that does not break existing V1 hashes.
   - `LOCAL_DIRECT` may use plain HTTP only for loopback hosts and must preserve current
     successful canonical MARKET_BAR behavior.
   - `REMOTE_BRIDGE` must require explicit HTTPS endpoint configuration, no userinfo,
     credential query parameters, fragments or automatic local/remote fallback.
   - Do not derive or auto-discover an arbitrary bridge path.

3. Reuse the existing acquisition credential boundary.
   - Do not create a second secret store.
   - If the current remote bridge main branch has no frozen machine-auth contract, implement
     only the safe credential seam/fake-transport behavior and leave live remote auth
     explicitly unqualified.
   - If one secret/header is sufficient, reuse existing `credential_ref` + resolver/header
     mechanisms.
   - If multiple independent secret values are genuinely required by the now-frozen bridge
     contract, design an additive/versioned representation with explicit legacy compatibility;
     do not put resolved secrets in plan parameters, URIs, logs, receipts, probe reports or Git.
   - Missing required remote credential must fail before any network request.

4. Split diagnostics by trust layer.
   - Keep `FQGATE_LOCAL_GATEWAY_UNREACHABLE` for LOCAL_DIRECT local connection failures.
   - Introduce conservative remote diagnostics equivalent to:
     `FQGATE_REMOTE_ENDPOINT_UNREACHABLE`,
     `FQGATE_REMOTE_AUTH_DENIED`,
     `FQGATE_REMOTE_HTTP_ERROR_UNCLASSIFIED`.
   - Only add bridge-specific codes such as `FQGATE_BRIDGE_UNAVAILABLE` or
     `FQGATE_BRIDGE_UPSTREAM_UNAVAILABLE` when the bridge repository has a stable documented
     error contract proving those meanings.
   - REMOTE_BRIDGE 401/403 must not automatically set FQGate account entitlement to DENIED.
   - Generic remote 5xx must not be relabeled as an FQGate provider error.
   - Once a response is proven to be the supported provider envelope, retain the completed
     M2-A conservative provider-code and schema rules.

5. Preserve acquisition/replay semantics.
   - Exact response bytes still enter raw CAS before offline decode.
   - Compile/replay remains offline.
   - Do not alter `strict-v1`, CDC, Net Cash, Through Return, hard gates, valuation, A6,
     PIT or coverage semantics.
   - Do not manufacture identical raw/shard hashes between local and remote paths; each
     frozen batch only needs deterministic self-replay.

6. Harden authenticated remote HTTP behavior.
   - Ensure credentials cannot be forwarded to an untrusted redirect target.
   - Prefer rejecting redirects for authenticated REMOTE_BRIDGE requests unless safe
     same-origin handling is explicitly implemented and tested.
   - Do not weaken the generic network layer for the sake of FQGate if a provider-specific
     wrapper can enforce the rule safely.

Tests must cover at least:

- legacy local adapter success and replay;
- new LOCAL_DIRECT success;
- fake REMOTE_BRIDGE success using a supported response contract;
- REMOTE_BRIDGE rejects HTTP/non-explicit endpoint configuration;
- required remote credential missing -> fail before transport;
- auth material exists only on the outbound request, not persisted/logged;
- remote 401/403 -> remote auth/access diagnostic, not FQGate entitlement denial;
- remote DNS/TLS/transport failure -> remote endpoint unreachable;
- local transport failure remains local gateway unreachable;
- unknown remote 5xx remains layer-unclassified without bridge proof;
- supported provider error envelope retains M2-A semantics;
- unsupported remote/provider schema fails closed;
- credentialed redirect cannot leak auth cross-origin;
- old receipts/batches remain decodable;
- repeated offline compile/replay is deterministic for frozen local and remote fake batches.

Run at minimum:

```bash
python -m pytest tests/test_fqgate_historical.py -q
python -m pytest tests/test_phase_5r_acquisition.py -q
python -m ruff check .
python -m pytest
```

Current full-suite baseline is `6191 passed, 2 skipped`; do not regress it except for an
intentional documented test replacement. Normally the test count should increase.

Documentation updates required before declaring completion:

- update `docs/operations/phase-5r-a-acquisition.md` so FQGate is described as endpoint-
  neutral rather than intrinsically local-only, while still showing loopback as the current
  default/legacy path;
- update `docs/status/phase-5r-a-2026-09-17.md` with exact implemented state, verification
  results and any `REMOTE_BRIDGE_LIVE_UNPROVEN` blocker;
- update `docs/goals/phase-5r-a-m2-t-fqgate-endpoint-transport.md` if implementation proves
  a contract detail must change;
- if relevant, update `AGENTS.md` only for stable repository-wide behavior, not detailed
  implementation history.

Do not:

- implement cloudflared/Tunnel provisioning in Turtle;
- expose FQGate directly to the Internet;
- create a catch-all proxy or runtime API-doc scraping/discovery path;
- add trading/state-changing financial operations;
- remove Futu/AKShare fallback plans;
- contact live Cloudflare/FQGate in ordinary CI;
- claim H history from the existence of a Tunnel.

If the remote bridge machine API is not yet implemented upstream, finish Turtle's local/fake
remote abstraction and tests, record `REMOTE_BRIDGE_LIVE_UNPROVEN`, and stop. That is a valid
M2-T completion state. Then the next goal returns to M2-B, which may still use LOCAL_DIRECT.
