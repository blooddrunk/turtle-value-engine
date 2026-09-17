# Phase 5R-A M2-T — FQGate Deployment-Neutral Endpoint Transport

Status: **COMPLETE at the Turtle-side contract boundary — 2026-09-17**
Date: 2026-09-17  
Baseline: `9316355ca17cdb0b952834bf5b17040a23b46d35`  
Cross-repository dependency: `blooddrunk/fqgate-remote-bridge`

## 1. Decision

M2-A is complete. Before resuming the existing M2-B bounded H-share selection probe,
insert one transport-portability package: **M2-T**.

The implementation is complete at the Turtle-side local/fake-remote code and contract
boundary. The live remote proof remains explicitly deferred as
`REMOTE_BRIDGE_LIVE_UNPROVEN` because the checked `fqgate-remote-bridge` `main`
(`ce30a4f`) is still at the completed Phase 2 local bridge boundary and does not publish
the Phase 3/4 machine-authenticated read-only market-history contract.

The FQGate source must no longer be modeled as intrinsically tied to
`127.0.0.1:17281`. The provider is FQGate; the deployment topology is a separate concern.
A request may reach the provider through either:

```text
LOCAL_DIRECT
  turtle-value-engine
    -> http://127.0.0.1:17281/v1/market/history/klines
    -> FQGate

REMOTE_BRIDGE
  turtle-value-engine
    -> HTTPS machine endpoint
    -> Cloudflare Access / Tunnel
    -> fqgate-remote-bridge (loopback-only)
    -> FQGate (loopback-only)
```

`turtle-value-engine` must not own `cloudflared`, Tunnel provisioning, Cloudflare Access
policy, FQGate lifecycle, QR login, browser API documentation, or remote-bridge upgrades.
Those remain responsibilities of `fqgate-remote-bridge`. Turtle consumes an explicitly
configured, authenticated market-data endpoint and preserves its own acquisition/CAS/
compile/replay boundaries.

This package is intentionally inserted without renumbering the existing M2-B/M2-C/M2-D/
M2-E decision tree. Once M2-T closes at its code/contract boundary, M2-B resumes. A live
REMOTE_BRIDGE proof is not required to block local M2-B when the bridge's read-only machine
API is not yet available.

## 2. Why this package is required now

The current implementation still carries local-only assumptions that become incorrect when
the same logical FQGate request crosses a remote bridge:

- adapter identity is `fqgate-local-market-history`;
- connection failures are classified as `FQGATE_LOCAL_GATEWAY_UNREACHABLE`;
- `credential_ref` is rejected because the local FQGate session itself needs no API key;
- HTTP 401/403 is classified as FQGate entitlement denial;
- docs and tests use the loopback URL as if it were part of the provider identity.

Those assumptions are valid for `LOCAL_DIRECT` and must remain backward compatible, but
they cannot safely describe a Cloudflare/bridge path. A remote 401/403 may be Cloudflare
Access denial, a bridge policy denial, or an upstream FQGate/provider denial. A remote DNS,
TLS, Tunnel or bridge failure is not a local-gateway failure. The code must preserve those
trust boundaries instead of collapsing them into provider diagnostics.

The existing Phase 5R-A acquisition layer already provides the right common primitives:
explicit `--network=allow`, credential references/resolvers, injected network transports,
header-capable requests, safe URI persistence, raw CAS and offline replay. M2-T should reuse
those primitives rather than create a second secret or transport system.

## 3. Cross-repository contract

At the current `fqgate-remote-bridge` baseline, Phase 2 local TanStack bridge acceptance is
complete. Its roadmap places manual Cloudflare Tunnel integration in Phase 3 and Cloudflare
Access/machine authentication plus read-only remote API smoke tests in Phase 4.

Therefore M2-T must distinguish two things:

1. **Turtle-side transport readiness** — can be implemented and tested now with injected
   transports and an explicit endpoint profile.
2. **Live remote endpoint readiness** — remains unproven until `fqgate-remote-bridge`
   publishes an allowlisted read-only market-history route, a stable response/error
   contract and a machine-auth contract.

Do not invent a bridge route, infer one from browser/API-doc pages, add a generic FQGate
reverse proxy, or make Turtle dynamically discover arbitrary upstream operations. The
remote bridge must remain deny-by-default and explicitly allowlisted.

If the bridge eventually exposes browser-readable FQGate API documentation, that is useful
for humans and compatibility investigation but is not a runtime source-of-truth for Turtle.
Turtle must bind to a versioned machine contract, not scrape or mirror API docs.

## 4. Endpoint profile

Prefer an additive request-parameter profile so existing persisted V1 plan/batch/report
hash semantics do not change merely to introduce transport topology. Exact names may be
adjusted to repository style, but the semantic model should be equivalent to:

```json
{
  "endpoint_kind": "LOCAL_DIRECT",
  "source_uri": "http://127.0.0.1:17281/v1/market/history/klines",
  "response_contract": "fqgate-envelope-v1",
  "market": "USHA",
  "code": "600000",
  "canonical_market": "A",
  "currency": "CNY"
}
```

or:

```json
{
  "endpoint_kind": "REMOTE_BRIDGE",
  "source_uri": "https://<configured-machine-host>/<bridge-owned-market-history-route>",
  "response_contract": "fqgate-envelope-v1",
  "market": "<explicit-observed-market>",
  "code": "<explicit-observed-code>",
  "canonical_market": "H",
  "currency": "HKD"
}
```

The second example is a configuration shape, not evidence that the route exists today.

### LOCAL_DIRECT rules

- permit plain HTTP only for loopback hosts;
- default/legacy behavior remains compatible with the current local endpoint;
- no machine-auth credential is required;
- local transport failures retain `FQGATE_LOCAL_GATEWAY_UNREACHABLE`;
- current M2-A provider diagnostics remain valid after a response is known to originate
  from the local FQGate endpoint.

### REMOTE_BRIDGE rules

- require HTTPS;
- require an explicit absolute endpoint; never derive a hostname or path;
- no userinfo, credential query strings or fragments;
- never automatically fall back from remote to local or from local to remote inside one
  request;
- machine authentication, if required, must come only from declared credential references;
- fail before the network when required remote credentials are unavailable;
- authenticated redirects must not be allowed to forward secrets to an untrusted origin;
  prefer rejecting redirects for this path unless same-origin behavior is explicitly and
  safely implemented;
- raw response bytes/provenance still enter CAS before offline decoding;
- only a response contract explicitly supported by the FQGate decoder may be normalized.

## 5. Authentication boundary

The existing `HistoricalAcquisitionRequestV1` has a single `credential_ref`. Do not place
Cloudflare client IDs/secrets, bearer values, cookies, Tunnel tokens or any other resolved
secret inside request parameters, `source_uri`, receipts, probe reports, logs or Git.

M2-T must not silently mutate an existing persisted V1 contract in a way that changes old
request/batch identities. Use the smallest safe option after inspecting the actual bridge
Phase 4 machine-auth contract:

- if one resolved secret/header is sufficient, reuse the existing credential reference and
  header-capable transport pattern;
- if the bridge requires multiple independent secret values, either resolve one explicitly
  documented credential bundle behind a single non-secret reference, or introduce an
  additive/versioned auth/request contract with explicit legacy-hash compatibility;
- do not hard-code a guessed Cloudflare service-token representation before the bridge
  contract is frozen.

Ordinary CI must use fake/injected credentials only. Live CLI rules about environment-backed
credential references remain fail closed.

## 6. Diagnostic layering

Diagnostics must identify the layer actually observed. Suggested stable prefixes are:

```text
FQGATE_LOCAL_GATEWAY_UNREACHABLE        # existing LOCAL_DIRECT meaning
FQGATE_REMOTE_ENDPOINT_UNREACHABLE      # DNS/TLS/Tunnel/connection path failed
FQGATE_REMOTE_AUTH_DENIED               # remote edge/bridge auth denied when origin is known
FQGATE_REMOTE_HTTP_ERROR_UNCLASSIFIED   # remote HTTP failure whose layer is not established
FQGATE_BRIDGE_UNAVAILABLE               # only when a stable bridge error contract proves it
FQGATE_BRIDGE_UPSTREAM_UNAVAILABLE      # only when a stable bridge contract proves it
FQGATE_ENTITLEMENT_DENIED               # reserve for evidence-supported FQGate/provider denial
```

Rules:

- a REMOTE_BRIDGE 401/403 must not automatically set FQGate account entitlement to `DENIED`;
  without proof that the response came from the FQGate/provider layer, entitlement remains
  `UNKNOWN`;
- a generic remote 5xx must not be relabeled as an FQGate provider failure;
- stable bridge error codes may be mapped only after they are frozen/documented by the
  bridge repository;
- provider error code semantics remain governed by the completed M2-A conservative rules;
- H market/code identity remains explicit and must never be inferred from endpoint topology.

If existing `SourceProbeReportV1` fields can represent these facts safely, keep it unchanged.
Only add a versioned/additive sidecar if implementation proves the current report cannot do
so without ambiguity.

## 7. Persisted compatibility

Do not rename the existing persisted adapter identity in place and thereby orphan old raw
receipts/batches.

Preferred approach:

- keep `fqgate-local-market-history` readable and registered for legacy plans/receipts;
- add a deployment-neutral adapter identity for new plans, for example
  `fqgate-market-history`, with an incremented adapter version;
- let the offline decoder support both explicitly known adapter identities/contracts, or
  provide a separate compatibility decoder while keeping canonical MARKET_BAR semantics
  unchanged;
- old M1/M2-A plans, receipts, probe reports, raw CAS and compiled manifests must remain
  readable/replayable.

A local and remote acquisition of the same observations need not have identical raw hashes,
request identities or shard identities because source URI/headers/bridge envelope/provenance
may differ. The required invariant is deterministic replay for each frozen batch; never
rewrite provenance to manufacture cross-transport identity equality.

## 8. Mergeable work packages

### M2-T1 — Endpoint/topology abstraction

Implement the deployment-neutral FQGate request details and legacy compatibility.

Expected surface:

- `src/turtle_value_engine/historical/fqgate.py`;
- adapter registration/decoder wiring under `historical/`;
- `tests/test_fqgate_historical.py`;
- operations/status docs.

Acceptance:

- legacy local plans still pass unchanged;
- new `LOCAL_DIRECT` mode produces the same canonical fields;
- `REMOTE_BRIDGE` accepts only explicit HTTPS endpoints and a supported response contract;
- no live remote endpoint is claimed merely because fake transport tests pass.

### M2-T2 — Remote auth and layered diagnostics

Implement the smallest auth path that the frozen bridge contract can support safely.
If the bridge machine-auth contract is not yet frozen, implement the internal seam and fake
transport behavior, document the blocker, and leave live remote auth unqualified rather
than guessing.

Acceptance:

- missing required credential blocks before network;
- secrets never enter persisted artifacts or diagnostics;
- remote 401/403 is not misclassified as provider entitlement denial;
- remote transport failure is not labeled local gateway failure;
- credentialed redirects cannot leak credentials cross-origin;
- bridge-specific error mapping exists only for published stable bridge codes.

### M2-T3 — Cross-repository live proof (deferred-capable)

Trigger only after `fqgate-remote-bridge` has an Access-protected allowlisted read-only
market-history operation.

Run a bounded A-share smoke probe against both deployment paths when available:

```text
LOCAL_DIRECT  -> probe -> optional bounded acquire -> offline compile/replay
REMOTE_BRIDGE -> probe -> optional bounded acquire -> offline compile/replay
```

Use the same explicit FQGate market/code/date semantics. Record only redacted endpoint-mode,
coverage and compatibility conclusions in Git. Keep hostnames, credentials and private raw
responses under private operator storage when appropriate.

A successful remote A smoke test proves only transport compatibility. It does not prove H
history, delisted retention, lifecycle, actions, market-wide coverage or stronger A6 claims.

If Phase 3/4 of the bridge is not ready, M2-T may close at the turtle-side code/contract
boundary with `REMOTE_BRIDGE_LIVE_UNPROVEN`, then continue M2-B via LOCAL_DIRECT.

## 9. Required offline tests

Cover at least:

1. legacy `fqgate-local-market-history` local success replay;
2. new deployment-neutral LOCAL_DIRECT success;
3. fake REMOTE_BRIDGE success with the supported response envelope;
4. REMOTE_BRIDGE refuses HTTP/non-explicit endpoints;
5. missing remote credential blocks before transport;
6. remote auth headers are sent only at request time and never persisted/logged;
7. remote 401/403 -> remote auth/access diagnostic, not FQGate entitlement denial;
8. remote DNS/TLS/transport failure -> remote endpoint unreachable;
9. local failure retains local-gateway diagnostic;
10. unknown remote 5xx remains layer-unclassified unless a stable bridge error contract
    proves the origin;
11. provider error envelope after successful transport retains M2-A conservative semantics;
12. unsupported bridge/provider response schema fails closed;
13. credentialed redirect/cross-origin behavior cannot leak auth material;
14. old receipts/batches remain decodable;
15. repeated compile/replay from each frozen batch has stable identities.

Verification:

```bash
python -m pytest tests/test_fqgate_historical.py -q
python -m pytest tests/test_phase_5r_acquisition.py -q
python -m ruff check .
python -m pytest
```

The full baseline must not regress below the current M2-A baseline except for an intentional,
documented test replacement; normally the count should increase from `6191 passed, 2 skipped`.

### 9.1 Implemented closure record — 2026-09-17

The Turtle-side implementation uses the following additive boundary:

- `fqgate-local-market-history` remains the v1 legacy local adapter and decoder path;
- `fqgate-market-history` is the v2 deployment-neutral adapter identity;
- new requests carry an explicit `endpoint_kind` (`LOCAL_DIRECT` or `REMOTE_BRIDGE`);
- `LOCAL_DIRECT` is restricted to the loopback FQGate history operation, while
  `REMOTE_BRIDGE` requires an explicit HTTPS operation URI and the supported
  `fqgate-envelope-v1` response contract;
- the legacy v1 parser keeps accepting the explicit HTTP(S) endpoint shape it already
  accepted for old plans/receipts, so compatibility replay is not retroactively narrowed;
  the loopback restriction applies to the new explicit `LOCAL_DIRECT` mode;
- remote credentials, when the endpoint contract requires them, use the existing
  `credential_ref`/resolver/header seam and are never included in persisted artifacts;
- remote HTTP/transport failures use remote-layer diagnostics, and remote 401/403 retain
  entitlement `UNKNOWN`; no bridge-specific code is mapped because the bridge contract is
  not yet published;
- the built-in HTTP transport rejects redirects by default, and the FQGate adapter rejects
  any response whose URL differs from the requested endpoint;
- `SourceProbeReportV1`, raw CAS, receipt/batch identity rules, offline compiler/replay,
  PIT/A6 and `strict-v1` semantics are unchanged. The legacy raw metadata path is kept
  byte-for-byte compatible for old request identities.

The checked `fqgate-remote-bridge` `main` is `ce30a4f`: Phase 2 is complete, while Phase 3
Tunnel and Phase 4 Access/machine-authenticated read-only market-history work are not yet
implemented. No live remote route, authentication header, H capability or live success is
claimed. The next goal is M2-B, which may continue through `LOCAL_DIRECT`.

Verification on 2026-09-17:

```text
python3 -m pytest tests/test_fqgate_historical.py -q -> 44 passed
python3 -m pytest tests/test_phase_5r_acquisition.py -q -> 60 passed
python3 -m ruff check . -> PASS
python3 -m pytest -> 6212 passed, 2 skipped
```

## 10. Non-goals

M2-T must not:

- implement Cloudflare Tunnel provisioning or `cloudflared` lifecycle in Turtle;
- expose FQGate directly to the Internet;
- add a catch-all proxy or arbitrary upstream route discovery;
- scrape browser API docs to decide runtime capabilities;
- add trading or state-changing financial operations;
- make FQGate mandatory or remove Futu/AKShare fallback branches;
- change `strict-v1`, CDC, Net Cash, Through Return, gates or valuation;
- weaken A6, PIT, coverage, raw provenance or offline replay semantics;
- make ordinary CI contact Cloudflare, FQGate or any other provider;
- store Cloudflare/FQGate credentials in Git, plans, receipts or logs.

## 11. Resume the original M2 plan

After M2-T closes at least at its local/fake-remote contract boundary, resume the existing
M2 source-selection plan:

```text
M2-A  diagnostic hardening                         COMPLETE
  |
M2-T  deployment-neutral FQGate endpoint transport NEXT
  |
M2-B  bounded H FQGate selection probe
  |
  +-- success -> select FQGate bounded H research source -> M2-E
  |
  +-- failure/unqualified -> M2-C Futu OpenD
                              |
                              +-- failure -> M2-D AKShare/Eastmoney
                                              |
                                              -> M2-E selection record
```

M2-B may use LOCAL_DIRECT or a proven REMOTE_BRIDGE endpoint. The transport used is provenance,
not a new source-selection result: both paths still represent FQGate. H capability continues
to depend on the exact observed FQGate market/code and returned historical rows, never on the
existence of a Tunnel.

## 12. Codex execution rule

Treat this document as the active next goal. Implement M2-T in small reviewable commits.
Do not wait for a live Cloudflare endpoint to finish the turtle-side transport abstraction
and offline tests. Conversely, do not fabricate a bridge route, machine-auth contract or live
success while `fqgate-remote-bridge` Phase 3/4 is incomplete.

When the contract boundary is complete, update the Phase 5R-A status and operations docs,
run the full verification suite, record exact blockers, and stop before starting M2-B in the
same goal unless M2-T itself requires a bounded compatibility smoke test.
