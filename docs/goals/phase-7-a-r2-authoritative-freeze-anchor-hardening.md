# Phase 7-A-R2 — Authoritative Calibration Freeze Anchor and Schema Semantic Parity Hardening

Status: **IMPLEMENTED / CLOSED** (2026-09-30)
Date: 2026-09-30
Selected after: Phase 7-A-R1 post-closure review
Closure record:
`docs/status/phase-7-a-r2-2026-09-30.md`

Selection audit:
`docs/status/phase-7-a-r1-post-closure-review-2026-09-30.md`

Predecessor:
`docs/goals/phase-7-a-r1-frozen-evidence-binding-hardening.md`

Predecessor closure:
`docs/status/phase-7-a-r1-2026-09-30.md`

Coding-agent handoff:
`docs/status/phase-7-a-r2-next-coding-agent-goal.md`

## 1. Objective

Make `READY_FOR_HUMAN_REVIEW` prove not only that a supplied evidence binding
is internally valid, but that it is the **unique immutable calibration-freeze
identity committed for this experiment in the authoritative workspace**.

At the same time, make the checked-in
`controlled-evolution-evaluation.schema.json` reject the same invalid
required-check permutations that the Pydantic model rejects.

R2 is an integrity/provenance hardening package. It does not choose a better
investment rule and it does not materialize or apply any candidate profile.

## 2. Frozen boundaries

Preserve all of the following:

- `rules/strict-v1.yaml` bytes and semantics;
- Phase 5 calibration scorer, chronological split and holdout semantics;
- existing `CalibrationExperiment` v1,
  `CalibrationEvidenceBindingV1` and `CandidateProfileProposal` readability;
- Phase 7-A/R1 offline and no-network evaluation boundary;
- `requires_human_approval = true` and
  `automatic_application_allowed = false`;
- no candidate-profile materialization, `strict-v2`, PR creation/merge or
  human-approval recording;
- no provider/source expansion, Bridge/FQGate integration,
  notification-vendor expansion, Windows bootstrap or brokerage/trading.

Do not add economic thresholds, candidate ranking or automated investment-rule
selection.

## 3. Authoritative calibration-freeze anchor

Introduce the smallest additive persisted contract/store boundary that proves
one immutable freeze identity per `CalibrationExperiment.experiment_id`.

A suggested shape is `CalibrationFreezeRecordV1`, but the exact name may
change. The invariant matters more than the name.

At minimum the authoritative record must bind:

- `experiment_id`;
- exact `experiment_content_sha256`;
- `binding_id`;
- exact evidence-binding `content_sha256`;
- enough contract/version identity to prevent cross-contract confusion.

The authoritative store slot must be keyed by `experiment_id`, not by the
content-derived `binding_id`. Saving byte-identical content is idempotent.
Saving different content for an already-frozen experiment must fail closed
before replacing or deleting the existing record.

The record must be committed by the normal calibration/freeze path. If
calibration persistence is multi-artifact, commit the authoritative anchor
last: a crash may leave unreferenced preparatory artifacts, but it must never
leave a published authoritative anchor pointing at missing or conflicting
content.

Existing R1 evidence-binding artifacts remain readable/exportable. Do not
rewrite historical R1 artifacts in place.

## 4. Calibration CLI/workspace boundary

Add an explicit normal CLI path that persists the calibration result, evidence
binding and authoritative freeze identity into a `BacktestWorkspace` without
manual JSON assembly. An additive `tve calibrate --workspace <root>` (or a
clearer equivalent) is preferred.

Acceptance requirements:

1. the workspace's calibration experiment is immutable under
   `experiment_id`;
2. the authoritative freeze slot is immutable under that same
   `experiment_id`;
3. a repeated byte-identical calibration/freeze is idempotent;
4. a same-`experiment_id` rerun with changed manifest content, changed
   observation provenance, changed binding identity or changed experiment
   content fails closed;
5. the failed conflicting run leaves every pre-existing authoritative file
   byte-identical;
6. a sidecar `--evidence-binding-output` may remain as an export, but it is
   not the authority used to admit R2 READY dossiers;
7. any export/output path that would overwrite a supplied input, the primary
   experiment output, or an existing different frozen artifact must be
   rejected or otherwise made provably non-destructive.

Do not solve this by adding timestamps or mutable "latest" pointers.

## 5. Evaluation authority

A `READY_FOR_HUMAN_REVIEW` result must prove that the evidence binding used by
evaluation is the binding referenced by the authoritative calibration-freeze
slot for the supplied `experiment_id`.

The CLI must not trust an arbitrary `--evidence-binding` path as sufficient
authority. Prefer resolving the authoritative freeze record and referenced
binding from an explicit calibration workspace, for example:

```text
tve evolution evaluate ... --calibration-workspace <root>
```

Compatibility behavior may still emit a `BLOCKED` dossier when only an
unanchored sidecar binding is supplied, but an unanchored binding must never
produce `READY_FOR_HUMAN_REVIEW`.

Add explicit machine-readable admission checks for the anchor if that keeps
the contract auditable. If the canonical check count changes, update the
contract, generated schema, architecture and closure records consistently.

The low-level pure evaluator may remain pure. The authoritative resolution
boundary may be a separate loader/service that supplies the evaluator with
already-validated anchored evidence; the CLI READY path must use that
boundary. Do not hide filesystem I/O inside an otherwise documented pure
function.

## 6. Required fail-on-current-R1 regressions

Before implementation, write focused tests that use only surfaces present on
R1 and execute them verbatim against
`cbcf4cab5f361eb45d5be83a846e74c3b7f085cd`.

The tests must demonstrate actual unsafe acceptance, not failure because an
R2 symbol does not exist.

### 6.1 Rebinding same-id manifest content

Starting from an honest R1 experiment:

1. create a separately valid manifest with the same `dataset_id` but different
   content/hash;
2. build a fresh valid `CalibrationEvidenceBindingV1` over that substituted
   manifest plus the original experiment and observations;
3. evaluate the substituted manifest using the fresh matching binding.

On R1 this path is expected to be admitted because the binding and supplied
evidence agree and canonical replay sees the same experiment. The regression
must prove that behavior before R2 and require fail-closed behavior after R2.

### 6.2 Rebinding non-scoring observation provenance

Starting from the honest R1 chain:

1. change only `CalibrationObservation.source_hash`;
2. prove canonical experiment/holdout reproduction remains unchanged;
3. build a fresh valid binding over the substituted observation rows;
4. evaluate with that matching fresh binding.

On R1 the fresh binding removes the mismatch that R1's original
`EVIDENCE_BINDING_OBSERVATIONS_IDENTITY` test relied on. Prove that this path
can reach READY before R2; require authoritative-anchor rejection after R2.

### 6.3 Schema-only reordered checks

Take a valid dossier, swap two canonical checks, recompute
`content_sha256`, and validate with `Draft202012Validator` against the
checked-in schema only.

Prove the R1 schema accepts it; require R2 schema rejection.

### 6.4 Schema-only duplicate/omission with count preserved

Replace one canonical check with a duplicate of another valid check so the
array still contains exactly the canonical item count, recompute
`content_sha256` and validate with the checked-in schema only.

Prove the R1 schema accepts it; require R2 schema rejection.

## 7. Schema semantic parity

The checked-in Draft 2020-12 schema must express the canonical check sequence,
not merely the allowed enum and total length.

A valid implementation may use `prefixItems`/per-position constants (plus an
appropriate `items` policy) or another Draft 2020-12 representation that
rejects reorder, duplicate and omission while preserving the canonical
persisted order.

Keep the checked-in schema deterministically generated from the model or a
single canonical schema source. Do not hand-edit a schema that silently drifts
from the Python contract.

Tests must cover:

- model/schema structural parity;
- canonical dossier validates in both layers;
- reordered checks rejected in both layers;
- count-preserving duplicate/omission rejected in both layers;
- truncated and unknown-name cases remain rejected.

Semantic validators that JSON Schema cannot express (for example recomputing
cryptographic hashes) remain model/runtime responsibilities; document that
boundary precisely instead of claiming impossible schema guarantees.

## 8. Additional automatic verification

Focused R2 tests must also prove:

- authoritative freeze save/load round-trip;
- byte-identical repeated freeze is idempotent;
- conflicting second freeze for one `experiment_id` is rejected;
- no original authoritative bytes change after conflict;
- corrupt/missing/foreign freeze record fails closed;
- freeze record pointing to a missing or mismatched binding fails closed;
- evaluator cannot become READY with sidecar binding alone;
- normal calibrate -> workspace freeze -> evaluate chain becomes READY;
- socket-guarded calibration-freeze resolution/evaluation stays offline;
- `rules/strict-v1.yaml` remains byte-identical.

Then run the complete current CI-equivalent gate, including at minimum:

```bash
python -m pip install ".[api,dev]"
python -m ruff check .
python -m turtle_value_engine config validate --input config/project.example.toml
python -m pytest
systemd-analyze verify deploy/monitoring/turtle-value-monitor.service deploy/monitoring/turtle-value-monitor.timer
pnpm --dir apps/dashboard install --frozen-lockfile
python scripts/export_surface_openapi.py --check
pnpm --dir apps/dashboard api:check
pnpm --dir apps/dashboard types:check
pnpm --dir apps/dashboard lint
pnpm --dir apps/dashboard typecheck
pnpm --dir apps/dashboard test --run
pnpm --dir apps/dashboard build
pnpm --dir apps/dashboard security:client-bundle
pnpm --dir apps/dashboard exec wrangler deploy --dry-run --config wrangler.jsonc --strict
python scripts/dashboard_cross_stack_smoke.py
```

Use the repository's then-current CI equivalent if commands change and record
every substitution explicitly.

After push, query GitHub Actions automatically. Close R2 only when the required
run is `success` and `head_sha` exactly equals the implementation commit.
Record focused-test results, full Python pass/skip count, Dashboard count,
schema-only adversarial results, no-network proof and `strict-v1` byte
identity.

## 9. Manual-intervention policy

No manual owner action is planned.

If a genuinely external authority/environment limitation blocks one automatic
step, record all seven items:

1. exact command/action attempted;
2. exact blocker;
3. exact human action required;
4. exact data/secret boundary;
5. exact resume command;
6. machine-checkable success criterion;
7. exact remaining unverified scope.

Continue every other automatic check that remains possible. Never replace this
record with a generic statement such as "evidence not fully recorded".

## 10. Stop boundary

Stop after the authoritative experiment->freeze->binding chain and schema
semantic parity are implemented, fail-on-R1 regressions are proven, the full
automatic gate is green, and exact-head Actions closure is recorded.

Do not start Phase 7-B, candidate-profile materialization, `strict-v2`,
profile PR creation/merge, human approval recording, provider/Bridge/FQGate
expansion, notification-vendor work, Windows bootstrap, brokerage/trading or
any `strict-v1` semantic change.
