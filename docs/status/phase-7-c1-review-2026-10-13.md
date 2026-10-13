# Phase 7-C1 independent review and C1-R1 repair — 2026-10-13

Reviewed main: `5edfcfe331bb52b8cbe100a8256d20686dcbd09e`.
Implementation reviewed: `37dda800e42cc401de3c85cf05065fd70dc3d3be`.

## Finding and repair

The C1 audit/CLI, fixed no-activation literals, structural checks, boundary
replay and profile-aware decision labels satisfy the documented boundary,
subject to one reproduced exception-coverage defect repaired in this review.

`_gate_above_band_anomaly` checked s >= a and watch >= fail_below but omitted
a >= watch. A manifest-consistent synthetic strict-v2 with pass=14%, s=12%,
a=10%, watch=11%, 13% or 15% incorrectly allowed a hash-bound pass-above-S
exception to cover the unrelated band-order violation and reached
READY_FOR_POLICY_DECISION. No actual activation occurred, but that result
violated the narrow-coverage contract and could mislead a later activation gate.

Repair: require pass > s and s >= a >= watch >= fail_below > 0. Parametrize the
existing arbitrary-disorder regression across a=20% and the three watch values.
Before the repair: 3 failed / 1 passed. After: all 49 focused C1 tests pass.
The original legitimate strict-v2 exception case remains covered, while the
unrelated disorder stays POLICY_DECISION_REQUIRED. Published profile bytes,
release manifest bytes, investment math, schemas and default remain unchanged.

## Automated verification and limits

- Original implementation Actions run
  https://github.com/blooddrunk/turtle-value-engine/actions/runs/38334476461:
  exact implementation SHA, success; every Python, systemd, Dashboard, Wrangler
  and cross-stack step confirmed successful through GitHub job metadata.
- Local Python 3.12: Ruff clean, focused tests 49 passed, config valid with
  default strict-v1, OpenAPI current, reference systemd unit verification clean.
- Full local runs before/after repair: respectively 7084/7087 passed, 2 skipped,
  the same 3 unrelated host failures. Two real-user-systemd proofs cannot connect
  to the user bus (No medium found); the loopback HTTP smoke initially fails
  because the inherited SOCKS proxy lacks socksio. This is not a fully green
  local-suite claim. The existing AKShare live skips remain opt-in.
- The complete unmodified CI workflow on the repair commit is the authoritative
  portable full gate; its final exact-head result is recorded separately below
  after completion. No manual owner validation is required for this repair.

The published audit still reports POLICY_DECISION_REQUIRED with
CDC_BAND_ORDER_VIOLATION:strict-v2 and CDC_GATE_TIER_COHERENCE_VIOLATION:strict-v2,
approval ABSENT, no structural blocker. Its id and content hash remain
profile-semantic-audit-3f7e99497a21d66316c9bcf2 and
185028506356067b5999661ed74036c1329f3c8edddf40b84568b54baf754dec.

## Selected next package

`docs/goals/phase-7-c2-owner-policy-decision-and-activation-plan.md` selects
owner-decision records and read-only activation/rollback plans. It explicitly
separates authenticated provenance from a username/unsigned claim, binds full
exception content hashes, handles stale/conflicting/revoked records and tests
all branches automatically. Actual activation is deferred. Owner economic
acceptance is not required to finish implementation; when requested later the
goal provides the exact human choice, rationale, submission and verification
boundary, with automation preparing all evidence first.

## C1-R1 exact-head CI closure

- Repair implementation: `e587f765ce04c47531330e410497f9ec80ce2610`.
- CI: https://github.com/blooddrunk/turtle-value-engine/actions/runs/38343678534
  completed successfully for that exact SHA; job `115120100473` and every
  workflow step succeeded. Logs confirm **7090 passed / 2 opt-in AKShare skips**,
  Dashboard **55 passed**, plus lint/config/schema checks, systemd unit verify,
  Dashboard build/secret scan, strict Wrangler dry-run and cross-stack smoke.
- The local loopback failure was also resolved automatically by removing
  inherited proxy variables for that test: 1 passed. The two local systemd
  manager tests remain unavailable in this container; they passed in CI. No
  owner intervention or altered/skipped CI gate was used.
- Reviewed published files remain byte-identical to `5edfcfe`; the real audit
  id/content hash above is unchanged. C1 is accepted after this narrow repair.
- This closure update changes documentation only; CI evidence above refers
  explicitly to the tested implementation SHA, not a later documentation SHA.
