# Phase 7-A-R1 post-closure review — authoritative freeze provenance

Status: **R1 CLOSURE PRESERVED / R2 REQUIRED BEFORE 7-B**
Date: 2026-09-30

Reviewed implementation:
`aea01cb8e8aee17b4d7fcbaddbed31d6db3ec776`

R1 closure:
`docs/status/phase-7-a-r1-2026-09-30.md`

Current reviewed `main`:
`cbcf4cab5f361eb45d5be83a846e74c3b7f085cd`

Selected follow-up:
`docs/goals/phase-7-a-r2-authoritative-freeze-anchor-hardening.md`

Coding-agent handoff:
`docs/status/phase-7-a-r2-next-coding-agent-goal.md`

## 1. Verdict

Phase 7-A-R1 is accepted at the scope it actually implemented: the evidence
binding is internally deterministic and tamper-detecting, the evaluator
fail-closes when that supplied binding disagrees with the supplied evidence,
the evaluation model recomputes `evaluation_id` and `content_sha256`, and the
exact-head CI evidence is genuine.

R1 is **not yet sufficient authority for Phase 7-B materialization**. Two
narrow residual integrity gaps remain:

1. the supplied binding is self-consistent but is not uniquely anchored as
   *the binding committed when that calibration experiment was frozen*; and
2. the checked-in evaluation JSON Schema does not encode the same exact
   required-check sequence that the Pydantic model validator enforces.

No profile materialization, `strict-v2`, PR/approval workflow or investment-rule
change should start until those two gaps are closed.

## 2. Evidence independently re-checked

The implementation commit is `aea01cb8e8aee17b4d7fcbaddbed31d6db3ec776`.
GitHub Actions run `36663577065` is `success` and its `head_sha` is exactly that
implementation SHA. The run executed the repository CI workflow, including
Ruff, config validation, the deterministic Python suite, systemd verification,
generated-contract checks, Dashboard lint/typecheck/tests/build/security scan,
Wrangler dry-run and cross-stack smoke.

The CI job log independently records:

- `6920 passed, 2 skipped` for Python;
- `55 passed` for Dashboard tests;
- Ruff: `All checks passed!`.

The documentation-only closure head
`cbcf4cab5f361eb45d5be83a846e74c3b7f085cd` also has a successful push CI
run (`36663967738`). The historical R1 closure therefore remains valid; this
review is about the next trust boundary, not about retroactively discarding
the R1 work.

## 3. Blocker A — a fresh matching binding can be rebuilt after evidence substitution

### Current behavior

`build_calibration_evidence_binding()` is a public pure helper. It verifies
that the supplied manifest `dataset_id` matches the experiment's `manifest_id`
and that the experiment has a selected proposal, then derives a new
`binding_id` from the identities supplied to that call.

That is sufficient to detect tampering *relative to one already-trusted
binding*. It does not prove that the supplied binding is the unique binding
that existed when the experiment was originally frozen.

The gap is concrete because:

- `CalibrationExperiment.experiment_id` is derived from `manifest_id`, the
  base-profile identity, search space and split; it does not include manifest
  content or frozen observation provenance;
- canonical calibration scoring does not use
  `CalibrationObservation.source_hash`;
- `BacktestWorkspace.save_calibration_evidence_binding()` stores artifacts by
  `binding_id`, so two different bindings for the same `experiment_id` can
  coexist without conflict;
- `tve calibrate --evidence-binding-output` exports through the generic atomic
  writer, which replaces an existing destination path rather than making that
  destination an immutable calibration slot; and
- `tve evolution evaluate` accepts an arbitrary `--evidence-binding` file path
  and has no authoritative experiment->binding anchor to resolve.

Therefore a caller can take the same valid experiment, substitute a
same-`dataset_id` manifest and/or change only non-scoring observation
provenance, then call `build_calibration_evidence_binding()` again over those
substituted inputs. The new binding is internally valid and matches the
substituted evaluation inputs. The six R1 binding checks then compare the
substituted evidence to the substituted binding and have no earlier anchor
against which to reject it; canonical replay also remains unchanged for the
documented provenance-only case.

R2 must add a fail-on-current-main regression that demonstrates this exact
rebinding path before implementing the fix.

### Required invariant

For one frozen `CalibrationExperiment.experiment_id` inside the authoritative
calibration workspace there must be exactly one committed freeze identity. A
later attempt to associate the same experiment identity with a different
binding, manifest content, observation-set identity, proposal identity or
experiment content must fail closed without replacing the original bytes.

A sidecar file supplied by path may remain useful as an export or diagnostic
artifact, but it must not by itself be sufficient authority for
`READY_FOR_HUMAN_REVIEW`.

## 4. Blocker B — checked-in JSON Schema does not enforce the exact check sequence

The R1 Pydantic model correctly validates:

- exactly nineteen checks;
- exact canonical order;
- no omission;
- no duplicate or replacement;
- no unknown check name.

The checked-in JSON Schema is weaker. Its `checks` field currently has:

- `minItems = 19` and `maxItems = 19`;
- a generic item schema whose `name` is one of the nineteen enum values.

It has no per-position `prefixItems` (or equivalent exact-sequence
constraint) and no count-preserving uniqueness/exact-set constraint. A
nineteen-item array with two valid names swapped, or one valid name duplicated
while another is omitted, can therefore satisfy schema-only validation even
though `ControlledEvolutionEvaluationV1.model_validate()` rejects it.

The R1 closure text that described canonical order as enforced by both the
model validator and the checked-in schema is consequently too strong. The
model path is safe; schema-only semantic parity is not complete.

R2 must add schema-only fail-on-current-main regressions for at least:

1. a reordered nineteen-check dossier; and
2. a count-preserving duplicate/omission dossier.

Both must be rejected by the checked-in Draft 2020-12 schema after R2.

## 5. Selected next package

Select **Phase 7-A-R2 — Authoritative Calibration Freeze Anchor and Schema
Semantic Parity Hardening**.

R2 is deliberately narrower than Phase 7-B. It must:

- introduce an additive immutable authoritative calibration-freeze record/slot
  keyed by `experiment_id` (exact contract/name may differ if the invariant is
  clearer);
- commit that anchor from the calibration/freeze path and make it the only
  authority capable of enabling `READY_FOR_HUMAN_REVIEW`;
- make conflicting re-freeze attempts for the same experiment fail closed and
  preserve the original bytes;
- make the evaluation CLI resolve/verify the authoritative binding from the
  calibration workspace rather than trusting an arbitrary binding path;
- preserve the existing R1 binding contract as a readable/exportable artifact;
- harden the checked-in evaluation schema so schema-only validation rejects
  reordering and count-preserving duplicate/omission;
- preserve all Phase 7-A/R1 offline, no-network, proposal-only and
  no-automatic-application boundaries.

## 6. Verification policy

R2 must be proven primarily by automation.

Before implementation, run the committed focused regressions verbatim against
the exact R1 code baseline
`cbcf4cab5f361eb45d5be83a846e74c3b7f085cd` (or the implementation parent
`aea01cb8e8aee17b4d7fcbaddbed31d6db3ec776` when a test intentionally excludes
the documentation-only closure commit). Record the exact failing assertions
that demonstrate the unsafe behavior; do not count missing R2 symbols as a
proof.

After implementation, run the focused R2 suite and the complete current
CI-equivalent gate. Close R2 only when the required GitHub Actions run is
`success` and its `head_sha` exactly equals the implementation commit.

No manual owner action is planned. If a genuinely external authority or
environment limitation prevents one automatic check, record all seven items:

1. exact command/action attempted;
2. exact blocker;
3. exact human action required;
4. exact data/secret boundary;
5. exact resume command;
6. machine-checkable success criterion;
7. exact remaining unverified scope.

Do not replace those items with a generic statement that evidence is
incomplete.

## 7. Stop boundary

Stop when authoritative calibration-freeze provenance and schema semantic
parity are closed, fully regression-tested and exact-head CI is recorded.

Do **not** start candidate-profile materialization, `strict-v2`, rule-profile
PR creation/merge, human-approval recording, provider/Bridge/FQGate expansion,
notification-vendor work, Windows bootstrap, brokerage/trading or any
`strict-v1` semantic change.
