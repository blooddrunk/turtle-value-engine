# Phase 6-F-R1 coding-agent handoff — Production Credential Boundary and Manual-Resume Hardening

Status: **SELECTED / NOT IMPLEMENTED**

Canonical goal:
`docs/goals/phase-6-f-r1-production-credential-boundary-hardening.md`

Selection audit:
`docs/status/phase-6-f-r1-selection-2026-09-29.md`

Predecessor closure:
`docs/status/phase-6-f-2026-09-29.md`

## Mission

Implement only Phase 6-F-R1.

The post-closure audit accepted Phase 6-F itself, but found three dormant-path
hardening defects:

1. EnvironmentFile-only secret values are not merged into the effective
   artifact-scan/journal-redaction set;
2. the documented private EnvironmentFile boundary is not fully enforced
   (private-root containment/symlink/permissions);
3. Windows-bootstrap, linger and missing-secret render boundaries do not all
   emit an exact parser-valid resume command with the real production-config
   path.

Fix those defects without changing monitoring, delivery-ledger, provider,
Dashboard, valuation or investment semantics.

## Execution rules

- Read the canonical goal and source-of-truth docs before editing.
- Add focused regressions that fail on current main first.
- Keep all tests offline and host-mutation-free.
- Never request or print a real secret.
- Run the complete automatic gate; do not delegate machine-verifiable checks
  to the owner.
- If the existing private production config is locally available, rerun only
  the goal-specified non-destructive production gate/preflight/verify/report.
- Push the exact implementation SHA and close R1 only after the matching
  required GitHub Actions run succeeds.
- Record exact commands/results/test counts in a dated closure document.
- Do not start any package beyond R1.

## Required deliverables

- hardened `scripts/monitoring_production_ops.py`;
- focused deterministic regressions in
  `tests/test_monitoring_production_ops.py`;
- any narrowly required documentation updates;
- dated R1 closure record with exact-head CI evidence;
- next-package handoff left **unselected** pending a fresh post-R1 review.
