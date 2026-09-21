# Phase 6-B selection audit — 2026-09-21

Status: **SELECTED / READY FOR IMPLEMENTATION**

Baseline: `main@d28e1f037276cf9f186c29aea88d6482cdc2bd4c`

## 1. Phase 6-A audit result

Phase 6-A is accepted as CLOSED at the offline integration boundary.

Verified evidence:

- implementation commit `1060358da9f4bd0074ae267b45f7de93b43102a9`;
- push CI run `35556601120`: success;
- closure commit `d28e1f037276cf9f186c29aea88d6482cdc2bd4c`;
- push CI run `35556740919`: success;
- the closure CI job passed Ruff, project-config validation, the complete
  deterministic Python suite, generated API/type drift checks, Dashboard
  lint/typecheck/tests/build, secret scan, Wrangler validation and cross-stack
  smoke;
- the implementation changed the expected monitoring contracts, schemas,
  workspace/service/CLI/configuration, fixtures and focused monitoring tests;
- no provider transport, scheduler, notification, model/research runtime,
  automatic re-analysis, Cloudflare mutation or brokerage action was introduced.

No manual functional verification is deferred for Phase 6-A.

## 2. Why Phase 6-B is selected

Phase 6-A deliberately stops at already-frozen canonical events. The smallest
next useful boundary is to acquire real source events without changing
investment semantics or prematurely starting scheduling/re-analysis.

Selected next package:

**Phase 6-B — Opt-in Live Event Acquisition and Canonicalization**

Goal:
`docs/goals/phase-6-b-live-event-acquisition.md`

## 3. FQGate bridge cross-repository finding

Checked companion repository:
`blooddrunk/fqgate-remote-bridge`.

As of its current main around `f81e8b4`:

- Phase 5 remote-machine read-only API is CLOSED;
- machine authentication is isolated from human/admin contexts;
- filtered machine OpenAPI is registry-derived;
- real remote Access/Tunnel acceptance is recorded;
- the implemented market operation is
  `market.instruments.lookup` / `POST /api/v1/instruments/lookup`;
- quote was explicitly deferred;
- no historical-bars or monitoring-event operation exists;
- the repo is currently hardening FQGate 1.0.2 compatibility.

Conclusion: the Bridge is now technically credible as a future Turtle data
transport, but it is not yet an event/history provider. Phase 6-B must not wait
for it or hard-code Bridge semantics. Instead, the provider-neutral acquisition
contract must make a later Bridge adapter additive. When the Bridge eventually
publishes a typed/bounded read-only disclosure/event/history operation with
live machine acceptance, it should be evaluated as an optional and potentially
preferred source.

Turtle must consume the Bridge only as a client. Cloudflare provisioning,
Access policy, Tunnel lifecycle, FQGate update/lifecycle and Bridge operation
authorization remain in the Bridge repository.

## 4. Explicitly not selected

The following remain unopened:

- Phase 6-C re-analysis executor;
- Phase 6-D scheduler/notifications/Dashboard monitoring status;
- Phase 6-E owner live unattended acceptance;
- M4-D/M4-E;
- M2-D;
- a generic FQGate proxy;
- automatic trading, orders, transfers or any financial-state mutation.
