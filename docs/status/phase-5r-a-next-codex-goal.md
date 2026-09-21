# Phase 6-B next Codex goal — opt-in live event acquisition

Status: **PHASE 6-B IMPLEMENTED / CLOSED (2026-09-21) — closure evidence in
`docs/status/phase-6-b-2026-09-21.md`; the next package requires a fresh
selection audit**

Baseline selection commit is the commit that introduced this file revision.
Phase 6-A is verified CLOSED on main; selection evidence is recorded in
`docs/status/phase-6-b-selection-2026-09-21.md`.

Phase 5R strict A6 / `PRODUCTION_ELIGIBLE` remains `ACTIVE / PARTIAL`.
This Phase 6-B handoff does not claim otherwise. It is allowed to proceed
because bounded personal-research monitoring is not gated by that optional
strict production-corpus claim.

## Active package

**Phase 6-B — Opt-in Live Event Acquisition and Canonicalization**

Source of truth:

`docs/goals/phase-6-b-live-event-acquisition.md`

Primary objective: add an explicit network-gated, provider-neutral acquisition
boundary that maps auditable source records into the frozen Phase 6-A
`MonitoringEventV1` / `MonitoringEventBatchV1` contracts, then proves that
those batches replay through the existing monitoring planner/workspace without
advancing cursors before atomic commit.

The first source family should reuse the existing official filing/disclosure
boundary. Do not invent a second scraper architecture. A concrete live source
must be selected from current evidence and kept narrow; CNINFO is a candidate,
not a permission to guess an endpoint.

## Cross-repository FQGate note

`blooddrunk/fqgate-remote-bridge` has now closed its Phase 5 remote-machine
read-only boundary and has real Access/Tunnel acceptance plus a filtered
machine OpenAPI. Its only implemented market operation is currently bounded
instrument lookup; quote/history/event operations are not published.

Therefore:

- do not block Phase 6-B waiting for the Bridge;
- do not hard-code Bridge semantics into the monitoring contracts;
- keep the provider interface additive so a future Bridge event/history
  operation can be plugged in;
- never move Cloudflare/FQGate lifecycle or Bridge authorization ownership into
  Turtle.

## Verification discipline

Codex must prefer automatic verification.

Before edits:

1. synchronize main by fast-forward only;
2. record `git status --short`, HEAD and remotes;
3. discover the owner checkout under `D:\\code\\research` or
   `/mnt/d/code/research`;
4. verify green GitHub Actions for the exact baseline;
5. run baseline tests.

During implementation automate all deterministic acceptance cases listed in the
goal, especially network deny-by-default, PIT, source/provenance validation,
idempotency/conflict behavior, and the rule that acquisition failures or
successes do not move committed cursors.

When a bounded live source is technically available, Codex must run the live
probe and the subsequent offline replay itself. Human intervention is allowed
only for a genuine CAPTCHA/login/consent boundary, and then the handoff must
provide exact pre-step command, human action, resume command, expected success
output and remaining boundary.

Before closure run at least:

```bash
python -m ruff check .
python -m pytest
```

plus every generated-contract/Dashboard gate enforced by current CI. After
push, verify green GitHub Actions for the exact closing commit. Never mark the
package complete with vague “manual verification recommended” or “evidence
incomplete” wording.

Do not start Phase 6-C, 6-D or 6-E inside this package.
