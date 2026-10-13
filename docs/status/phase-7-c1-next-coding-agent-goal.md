# Phase 7-C1 → next coding-agent handoff — 2026-10-13

Status: **READY** (Phase 7-C1 closed at its audit boundary; see
`docs/status/phase-7-c1-2026-10-13.md`)

This document hands the next coding agent everything needed to proceed
after Phase 7-C1 without re-deriving state.

## Where things stand

- `rules/strict-v2.yaml` (SHA-256 `adba44b7…dd7`) is **published** on
  `main` and **semantically audited**: `tve evolution audit-profile`
  reports `POLICY_DECISION_REQUIRED` with reason codes
  `CDC_BAND_ORDER_VIOLATION:strict-v2` and
  `CDC_GATE_TIER_COHERENCE_VIOLATION:strict-v2` (gate at 14% above the
  retained S band 12% and the extreme-safety tier hurdle 12%).
  Everything structural (identity, hashes, lineage, manifest, registered
  rule diff) is PASS, and the audit proves by real-engine replay that the
  behavioral divergence window is exactly CDC yield `[0.08, 0.14)`.
- strict-v2 is **not** default, not applied; strict-v1 output is
  byte-identical to before; the default profile is unchanged.
- No policy exception and no approval claim is on file. C1 deliberately
  did not create either: the economic decision belongs to the owner.

## Recommended next package: Phase 7-C2 — Owner Policy Decision Recording and Conditional Activation Boundary

Scope (to be selected canonically by the owner or a post-C1 review):

1. An offline, typed decision-recording boundary that accepts exactly one
   owner decision for the audited strict-v2 head: either
   - **ACCEPT_WITH_EXCEPTION** — the owner declares the
     `CDC_GATE_ABOVE_S_BAND_PERMITTED` policy exception (the
     `VersionedPolicyExceptionV1` contract already exists and the audit
     already proves coverage flips the findings to covered and the
     classification to `READY_FOR_POLICY_DECISION`), or
   - **REJECT** — strict-v2 stays a published research artifact and the
     corrected thresholds go through a new `strict-v3` release built by
     the unchanged 7-A→B1→B2 chain (do not mutate published bytes).
2. Recording must be human-authored and attributable (the Phase 6-F
   EnvironmentFile/owner-identity patterns are precedent); automation may
   verify, never synthesize, the decision.
3. Only after a recorded ACCEPT_WITH_EXCEPTION may a later boundary
   change the default/active profile — as its own reviewed step, with the
   audit re-run fresh at that head, monitoring/backtest config migrations
   checked, and an explicit rollback path.

## Hard boundaries for the next agent

- Do not change `rules/strict-v1.yaml`, `rules/strict-v2.yaml` or
  `docs/releases/strict-v2/release-candidate.json` bytes.
- Do not check in a policy exception or approval for strict-v2 on the
  owner's behalf; do not treat a green audit, CI run or manifest as
  approval (`publication_is_not_activation_approval=true` is fixed in the
  audit contract).
- Do not start provider/Bridge/FQGate, notification-vendor,
  brokerage/trading or Windows-bootstrap scope.
- Keep new contracts additive and drift-parity-schemas; keep the full
  automatic gate plus exact-head Actions closure as the only closure
  evidence.

## Reproduce the audit (authoritative command)

```bash
python -m turtle_value_engine evolution audit-profile \
  --base-profile rules/strict-v1.yaml \
  --target-profile rules/strict-v2.yaml \
  --release-manifest docs/releases/strict-v2/release-candidate.json
```

Exit 1 with `activation_readiness: POLICY_DECISION_REQUIRED` is the
expected, correct result for the published pair today.
