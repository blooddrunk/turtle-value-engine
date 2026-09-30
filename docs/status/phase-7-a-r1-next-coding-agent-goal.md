# Coding-agent handoff — Phase 7-A-R1 Frozen Evidence Binding and Dossier Integrity Hardening

Status: **CONSUMED** (implementation delivered; see
`docs/status/phase-7-a-r1-2026-09-30.md`)
Date: 2026-09-30

Canonical goal:
`docs/goals/phase-7-a-r1-frozen-evidence-binding-hardening.md`

Selection audit:
`docs/status/phase-7-a-post-closure-review-2026-09-30.md`

Pre-R1 baseline:
`32f77c57a58f1b350d5871165958bd0de443bd4c`

## Mission

Close the three concrete Phase 7-A post-closure gaps before any Phase 7-B work:

1. a valid manifest with the same `dataset_id` but different content is not tied to the
   calibration run;
2. non-scoring frozen-observation provenance such as `source_hash` is not tied to the
   calibration run and can change while canonical replay stays identical;
3. `ControlledEvolutionEvaluationV1` can currently validate a READY dossier with a
   truncated check set or arbitrary non-empty `evaluation_id` if the content hash is
   recomputed.

The solution must remain offline, deterministic, additive and non-mutating with respect to
all rule profiles.

## Required preflight

Read before editing:

- `AGENTS.md`;
- `docs/status/phase-7-a-post-closure-review-2026-09-30.md`;
- `docs/goals/phase-7-a-r1-frozen-evidence-binding-hardening.md`;
- `docs/status/phase-7-a-2026-09-30.md`;
- `docs/architecture/controlled-evolution-evaluation.md`;
- `src/turtle_value_engine/evolution/contracts.py`;
- `src/turtle_value_engine/evolution/evaluate.py`;
- `src/turtle_value_engine/backtest/contracts.py`;
- `src/turtle_value_engine/backtest/calibration.py`;
- `src/turtle_value_engine/backtest/workspace.py`;
- `src/turtle_value_engine/cli.py`;
- `tests/test_evolution_evaluation.py`;
- current `.github/workflows/ci.yml`.

Confirm the actual starting main SHA. If it differs from the baseline above, rebase the
test-first proof onto the new head and document the difference before changing behavior.

## Test-first proof — mandatory

On the pristine pre-R1 baseline, add/run focused tests that demonstrate all four unsafe
behaviors:

- same-id manifest/content substitution still returns READY;
- `CalibrationObservation.source_hash` substitution with scoring inputs unchanged still
  returns READY;
- a READY dossier missing required checks still validates after recomputing
  `content_sha256`;
- a dossier with a wrong `evaluation_id` still validates after recomputing
  `content_sha256`.

Record the exact baseline SHA, exact test command and exact failing/asserted behavior before
implementing the fix.

## Implementation requirements

1. Add a versioned immutable calibration evidence-binding contract and checked-in schema.
2. Generate it at the calibration/freeze boundary from the exact manifest + exact
   observations + resulting experiment; do not synthesize the expected identities inside
   the evaluator.
3. Keep existing `CalibrationExperiment` v1 readable; prefer an additive sidecar/envelope
   and additive library/CLI/workspace path.
4. Require the prior binding for READY admission. Missing binding is fail-closed.
5. Compare exact manifest content hash, experiment content hash, observation-set hash/count
   and base-profile identity/hash; include proposal identity/hash if the binding carries it.
6. Preserve all existing canonical scorer and separate holdout replay checks.
7. Make `ControlledEvolutionEvaluationV1` require the exact canonical check set for its
   version and recompute/validate `evaluation_id`.
8. Keep deterministic output and checked-in schema parity.
9. Do not touch `strict-v1`, create `strict-v2`, open a PR for a profile, record human
   approval, or add economic thresholds.

## Automatic verification

Run the focused R1 suite, then every current CI-equivalent command from the canonical goal.
Do not delegate normal verification to the owner.

After push, query GitHub Actions yourself. Close R1 only on a required `success` run with
`head_sha` exactly equal to the implementation SHA. Record exact focused count, full
Python pass/skip count, Dashboard count, SHA, run id/conclusion, schema parity, no-network
proof and strict-v1 byte identity.

No manual owner work is expected. If an external authority/environment limit genuinely
blocks one step, record the exact command, blocker, required human action, data/secret
boundary, exact resume command, machine-checkable success criterion and exact remaining
unverified scope, then continue all other automatable checks.

## Stop

Stop at Phase 7-A-R1 closure. Do not start candidate profile materialization, `strict-v2`,
profile PR creation/merge, approval recording, provider/Bridge/FQGate expansion,
notification-vendor work, Windows bootstrap or brokerage/trading.
