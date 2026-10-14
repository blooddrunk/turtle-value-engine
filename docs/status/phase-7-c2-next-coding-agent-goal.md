> **2026-10-14 post-closure review override:** The independent static code review in
> `docs/status/phase-7-c2-post-closure-review-2026-10-14.md` found
> planning-time trust/binding gaps and a create-only output race. The **selected
> next coding-agent package** is Phase 7-C2-R1:
> `docs/goals/phase-7-c2-r1-activation-plan-trust-boundary-hardening.md`.
> The older proposals below (real owner provenance source, then activation
> executor) are **deferred until C2-R1 has passed executable regression and
> exact-head CI verification**. No real acceptance or activation has occurred.

# Phase 7-C2 → next coding-agent handoff — 2026-10-13

Status: **C2 IMPLEMENTED (offline boundary)**. The authoritative scope was
`docs/goals/phase-7-c2-owner-policy-decision-and-activation-plan.md`; see
`docs/status/phase-7-c2-2026-10-13.md` for the closure record.

This document hands the next coding agent everything needed to proceed
after Phase 7-C2 without re-deriving state.

## Where things stand

- `rules/strict-v2.yaml` (SHA-256 `adba44b7…dd7`) is **published** on
  `main`, semantically audited (`POLICY_DECISION_REQUIRED` with
  `CDC_BAND_ORDER_VIOLATION:strict-v2` and
  `CDC_GATE_TIER_COHERENCE_VIOLATION:strict-v2`), **not default, not
  applied**; strict-v1 output, the release manifest bytes, the default
  profile and all investment math are unchanged.
- The C2 offline boundary now exists end to end: typed owner-decision
  input/record/revocation/resolution/validation contracts, the
  `OwnerDecisionVerifier` trust-model interface (injected verifier +
  allowlist; the CLI has no verifier selection), six-check fresh-audit
  validation, fail-closed record-set resolution (duplicates, conflicts,
  revocation, supersession, staleness), the read-only
  `ProfileActivationPlanV1` with config inventory and rollback, and the
  Chinese `tve evolution decision-dossier` material.
- **No owner decision record exists.** No exception is checked in. Nothing
  was accepted, rejected, approved or activated on the owner's behalf.
  Every CLI-recorded decision is necessarily
  `OWNER_AUTHORITY_UNVERIFIED` (an unsigned local JSON proves nothing),
  so every production plan today correctly reports
  `OWNER_AUTHORITY_UNVERIFIED` or `NO_OWNER_DECISION_RECORD`.

## The one genuinely human step (owner, not agent)

When the owner wants to decide the strict-v2 policy question, the flow is:

1. `tve evolution decision-dossier …` — automation generates the Chinese
   materials (exact hashes, 14% vs 12% thresholds, 13% contrast,
   `[8%,14%)` divergence window, accept/reject effects).
2. The owner authors `owner_policy_decision_input_v1` JSON
   (ACCEPT_WITH_EXCEPTION + the exact exception id/content hash, or
   REJECT) and submits it through a real authenticated source.
3. `tve evolution record-decision …` validates against a fresh audit and
   records it (create-only, idempotent).
4. `tve evolution plan-activation …` derives the read-only plan; it stays
   `BLOCKED` (`OWNER_AUTHORITY_UNVERIFIED`) until a verified authority
   source exists — that source is deliberately not implemented and must
   not be faked by an agent.

## Recommended next packages (select one; do not start without a review)

1. **Authenticated owner provenance source** — the first real
   `OwnerDecisionVerifier` implementation (e.g. signature over the
   decision bytes bound to the owner identity), plus the explicit opt-in
   network/evidence-capture operation with immutable captured evidence
   and offline replay. Until then C2 stays honestly unverified.
2. **Controlled activation executor** — the separately reviewed package
   that would consume a `READY_FOR_EXPLICIT_OWNER_EXECUTION` plan and
   actually switch `[profiles] default` (config mutation, monitoring
   migration checks, fresh audit at that head, rollback drill). It must
   not be started while authority is unverified.

## Hard boundaries for the next agent

- Do not check in an owner decision record, a policy exception or any
  approval/acceptance on the owner's behalf; do not synthesize authority.
- Do not change `rules/strict-v1.yaml`, `rules/strict-v2.yaml` or
  `docs/releases/strict-v2/release-candidate.json` bytes; do not switch
  the default profile; every plan must keep `execution_performed=false`.
- Do not treat CI success, publication, an allowlist match or a green
  audit as approval (`publication_is_not_activation_approval=true`).
- Do not start provider/Bridge/FQGate, notification-vendor,
  brokerage/trading, H-share-scope or Windows-bootstrap work.
- Keep new contracts additive with drift-parity schemas; keep the full
  automatic gate plus exact-head Actions closure as the only closure
  evidence.

## Reproduce the current state (authoritative commands)

```bash
# Fresh C1 audit of the published pair (exit 1 POLICY_DECISION_REQUIRED is correct)
python -m turtle_value_engine evolution audit-profile \
  --base-profile rules/strict-v1.yaml \
  --target-profile rules/strict-v2.yaml \
  --release-manifest docs/releases/strict-v2/release-candidate.json

# Chinese owner decision dossier (before any real acceptance is requested)
python -m turtle_value_engine evolution decision-dossier \
  --base-profile rules/strict-v1.yaml \
  --target-profile rules/strict-v2.yaml \
  --release-manifest docs/releases/strict-v2/release-candidate.json \
  --output /tmp/strict-v2-owner-decision-dossier.md

# Plan with no owner record on file (exit 1 NO_OWNER_DECISION_RECORD is correct)
python -m turtle_value_engine evolution plan-activation \
  --base-profile rules/strict-v1.yaml \
  --target-profile rules/strict-v2.yaml \
  --release-manifest docs/releases/strict-v2/release-candidate.json \
  --decision-record /tmp/absent-record.json \
  --project-config config/project.example.toml \
  --output /tmp/strict-v2-activation-plan.json
```
