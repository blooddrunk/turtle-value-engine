# Phase 6-D2B-R2 post-closure review / D3 selection — 2026-09-23

Status: **REVIEWED / D3 SELECTED**

Audited main head:
`e747db94ed08e6c8c31838d2b3b2d97e6fcd55a9`

R2 implementation SHA:
`69326c95543c92e28e288edadc781236fced2b65`

Exact R2 implementation Actions run:
`35812884688` — **success**, exact head-SHA match

Canonical R2 goal:
`docs/goals/phase-6-d2b-r2-orphan-retry-budget-hardening.md`

Selected next goal:
`docs/goals/phase-6-d3-read-only-monitoring-dashboard.md`

Coding-agent handoff:
`docs/status/phase-6-d3-next-coding-agent-goal.md`

## 1. Review result

Phase 6-D2B-R2 is accepted as **CLOSED**. This audit found no structural defect
that requires reopening R2.

The implementation matches the selected crash-recovery invariant:

- the durable `MonitoringDispatchClaimV1` set `1..N` is the retry-budget
  ledger for one `delivery_id`;
- every possible outbound transport entry consumes one durable claim slot before
  the transport can write request bytes;
- `max_attempts` therefore bounds authorized outbound transport entries across
  the complete durable ledger lifetime, including process death after possible
  dispatch and before attempt-outcome persistence;
- receiver-declared idempotency can permit a later bounded resend only by
  allocating a **new monotonic slot**; the receiver-facing
  `Idempotency-Key` remains the same deterministic `delivery_id`;
- the default non-idempotent orphan policy remains terminal
  `AMBIGUOUS / ORPHANED_DISPATCH` with zero automatic resend;
- over-budget, gapped/non-contiguous, foreign-bound and slotless-attempt
  evidence fails closed before transport;
- R1's per-delivery OS single-flight, overall monotonic HTTP deadline, secret
  boundary and read-only pointer truthfulness remain intact.

The exact implementation CI evidence is also valid: Actions run
`35812884688` is a completed successful `push` run whose `head_sha` is
exactly `69326c95543c92e28e288edadc781236fced2b65`. The job records Ruff,
project-config validation, `6659 passed, 2 skipped`, systemd verification,
generated OpenAPI/API/Wrangler checks, Dashboard lint/typecheck/tests
(`44 passed`)/build, client-bundle secret scan, Wrangler dry-run and the real
cross-stack smoke as green.

## 2. D3-specific semantic note discovered during review

D3 must not collapse delivery accounting into one misleading "retry count".

After R2:

- `state.attempt_count` means **persisted attempt outcomes**;
- `dispatch_claim_count` means **durable authorized transport slots already
  consumed**;
- `unresolved_claim_numbers` identifies slots whose terminal outcome never
  became durable;
- the attempt set may legitimately contain numbering gaps because an orphaned
  slot remains consumed while a later receiver-idempotent recovery uses a new
  slot.

A Dashboard that labels `attempt_count` as "total sends" or "used retries"
would reintroduce the exact ambiguity R2 removed. D3 must expose the two
concepts separately and preserve `AMBIGUOUS`, `ORPHANED_DISPATCH`,
`MISSING`, `STALE_REPAIRABLE` and hard conflict states truthfully.

## 3. Decision

Select:

**Phase 6-D3 — Read-only Monitoring Operations Dashboard Projection**

D3 is an observation package, not another runtime package. It will expose a
versioned, secret-free, bounded read model over the already-implemented Phase
6-A / 6-C / D1 / D2A / D2B stores through the existing read-only
FastAPI -> Worker allowlist -> React Dashboard stack.

The first D3 slice is anchored to one explicitly configured runner rather than
recursively discovering arbitrary local state:

```text
explicit RunnerConfigV1 + ProjectConfig
  -> MonitoringWorkspace.status(watchlist)
  -> RunnerStore / RunnerLease read-only status
  -> current or latest activation identity
  -> that activation's D1 cycle status
  -> only re-analysis jobs referenced by that cycle
  -> only deliveries bound to that activation
  -> MonitoringOperationsProjectionV1
  -> GET /v1/monitoring/operations
  -> Worker allowlist /api/v1/monitoring/operations
  -> read-only /monitoring Dashboard
```

No request path may invoke acquisition, analysis, model/research execution,
cycle execution, delivery transport, repair, retry, resend, acknowledgement,
pointer publication or any other mutation.

Phase 6-E remains the bounded real-owner acceptance package for actual VPS
cadence/restart behavior, credentials, live acquisition and live notification
delivery. D3 must not consume 6-E merely to prove a read-only UI.

## 4. Automatic verification policy

D3 should be software-closable almost entirely by automation. The coding agent
owns every check that can be automated.

At minimum it must automatically prove:

1. the projection is generated only from explicit configured roots/identities
   and never recursive arbitrary filesystem discovery;
2. projection reads do not mutate any monitored store — byte/file inventory
   before and after a read remains unchanged;
3. provider, analyst/model, cycle execution and delivery transport sentinels
   are never called by the projection/API/UI request path;
4. empty/not-yet-run state is represented as unavailable/empty rather than
   fabricated success;
5. corrupt/contradictory store evidence fails closed and is not silently
   omitted;
6. local absolute paths, endpoint URLs, bearer tokens, lease holder tokens and
   raw untrusted response content never enter the API/browser payload;
7. D2B-R2 semantics remain visible: persisted outcome count and consumed
   dispatch-slot count are distinct, unresolved slot numbers are preserved,
   and pointer status is not flattened;
8. the Python API is GET/HEAD-only for the new surface and the Worker proxies
   only the fixed monitoring route;
9. the Dashboard contains no run/retry/repair/resend/acknowledge/trade/order or
   other mutation control;
10. deterministic Python, Worker and React tests plus a real local cross-stack
    smoke cover the new route;
11. the complete existing repository gate stays green;
12. the exact closing implementation SHA has a successful GitHub Actions run
    with matching `head_sha`.

## 5. Manual-intervention boundary

No manual step may substitute for API semantics, store immutability, security,
read-only enforcement, D2B-R2 accounting, cross-stack routing, build, tests or
CI. Those are mandatory automatic evidence.

The only acceptable manual fallback is **visual/layout inspection** if the
execution environment genuinely has no usable browser automation and no
installed headless Chromium/Edge path. In that case the agent must:

1. first complete all semantic and cross-stack automated checks;
2. provide the exact command that starts the deterministic local D3 fixture and
   preview, plus the exact local URL;
3. ask the owner to open that URL at roughly 1440x900 and verify no clipped or
   overlapping primary monitoring content;
4. open the same `/monitoring` page at roughly 390x844 and verify no
   horizontal page overflow or unusable controls;
5. expand the technical/audit details and verify IDs/hashes remain readable
   without dominating the primary page;
6. confirm the visible delivery section labels persisted outcomes separately
   from consumed dispatch slots and shows unresolved slots when present;
7. confirm there is no write/retry/resend/repair/acknowledge control;
8. record the exact failed step and visible symptom if any item fails.

That manual fallback proves **layout only**. It does not prove API correctness,
security, immutability or delivery semantics. Until the visual step is recorded,
the goal must be marked `BLOCKED_BY_VISUAL_VERIFICATION`, not vaguely
"evidence incomplete".

If browser automation is available, automate the same desktop/mobile checks and
the manual boundary is **NONE**.
