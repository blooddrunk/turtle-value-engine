# Controlled Evolution Evaluation Architecture

Phase 7-A implements the first executable stage of the roadmap's controlled
evolution chain — `proposal -> evaluation -> tests -> point-in-time
validation/backtest -> PR -> human approval` — and owns **evaluation only**.

The boundary turns one existing `PROPOSAL_ONLY` calibration result plus its
frozen evidence into an immutable, deterministic, schema-covered
evaluation/admission dossier.  It creates no rule profile, edits no profile,
opens no pull request and records no approval.

Phase 7-A-R1 adds a deterministic frozen-evidence binding boundary and hardens
the persisted dossier model. Phase 7-A-R2 closes the two residual R1 gaps: the
binding is now uniquely anchored as the one binding committed for an
`experiment_id` at calibration time through the authoritative
`CalibrationFreezeRecordV1` workspace slot, and the checked-in evaluation
schema encodes the exact canonical check sequence (Draft 2020-12
`prefixItems` with per-position `const`), so schema-only validation rejects
the same invalid permutations the Pydantic model rejects.

## Runtime boundary

```text
calibration/freeze boundary (Phase 5 calibration path)
frozen BacktestDatasetManifest + frozen CalibrationObservation rows
+ resulting CalibrationExperiment (embedded PROPOSAL_ONLY proposal)
        -> build_calibration_evidence_binding(...)          # pure, offline
        -> CalibrationEvidenceBindingV1                     # persisted prior artifact
        -> CalibrationFreezeRecordV1                        # authoritative anchor
        -> BacktestWorkspace commit: manifest -> experiment -> binding
           -> freeze record (published last, keyed by experiment_id)

frozen BacktestDatasetManifest
frozen CalibrationExperiment (embedded proposal + selected trial)
frozen CalibrationHoldoutResult
frozen CalibrationObservation rows
authoritative freeze record + referenced binding
  (resolved by the workspace loader from --calibration-workspace)
raw base-profile bytes (e.g. rules/strict-v1.yaml)
        -> evaluate_controlled_evolution(...)   # pure, offline, non-mutating
        -> ControlledEvolutionEvaluationV1
```

Both library functions are pure: they receive already-validated typed models
and byte inputs, perform no I/O of their own, construct no provider, model,
transport or network client, and never write to the supplied artifacts.  The
binding is produced only at the calibration/freeze boundary, where the exact
manifest, the exact observation rows and the resulting experiment are
simultaneously available; the evaluator never synthesizes the expected
evidence identity from its own supplied inputs.

The filesystem/workspace boundary is explicit and separate
(`backtest/calibration_freeze.py`).  `commit_calibration_freeze` commits the
prerequisite manifest, experiment and binding first and publishes the
experiment-keyed freeze record last, so a crash may leave unreferenced
prerequisites but never an authoritative anchor pointing at missing or
conflicting content; a repeated byte-identical freeze is idempotent, and a
conflicting freeze for the same `experiment_id` fails closed through the
workspace's immutable-store guard with every pre-existing authoritative byte
preserved.  `resolve_anchored_calibration_evidence` is the loader the
evaluation CLI uses: it resolves the freeze record by `experiment_id`, loads
the referenced experiment and binding, cross-validates every identity
(record↔experiment, record↔binding, binding↔experiment) and fails closed on
a missing, corrupt, foreign or mismatching anchor.  It supplies the pure
evaluator with already-validated anchored evidence; no I/O is hidden inside
the pure evaluation function.

The CLI wrappers are offline.  `tve calibrate --workspace <root>` persists the
compiled manifest, the calibration experiment, the evidence binding and the
authoritative freeze record into a `BacktestWorkspace` without manual JSON
assembly, and `--evidence-binding-output` remains a readable/exportable R1
sidecar artifact (its export paths are non-destructive: they refuse to
overwrite supplied inputs, each other, or an existing different artifact).
`tve evolution evaluate` takes exactly one anchor source —
`--calibration-workspace <root>` (the authoritative path, the only one that
can reach `READY_FOR_HUMAN_REVIEW`) or `--evidence-binding <file>` (the
unanchored R1 compatibility sidecar, which can only produce a `BLOCKED`
dossier naming `FREEZE_ANCHOR_PRESENT`) — refuses any `--output` path that
would overwrite a supplied input or write inside the calibration workspace,
writes the dossier atomically and prints it. Repeated execution
from byte-identical inputs produces a byte-identical dossier; neither contract
carries wall-clock fields.

## The calibration evidence binding

`CalibrationEvidenceBindingV1` (`calibration_evidence_binding_v1`, schema
`schemas/calibration-evidence-binding.schema.json`) binds, in one immutable
artifact with a deterministic `binding_id` and `content_sha256`:

- `manifest_id` and the exact `manifest_content_sha256`;
- `experiment_id` and the exact `experiment_content_sha256`;
- the exact canonical `observations_content_sha256` and the observation count;
- `base_profile_id` and the exact `base_profile_sha256`;
- the `proposal_id` and the canonical proposal payload SHA-256.

The model recomputes `binding_id` from the bound identities and
`content_sha256` from the persisted payload, so a tampered binding cannot
validate.  `build_calibration_evidence_binding` fail-closes on a manifest
whose identity disagrees with the experiment and on an experiment without a
selected proposal.  The canonical observation-set and proposal-payload hashes
are shared with the evaluator (`canonical_observations_sha256`,
`canonical_proposal_payload_sha256`), so a substitution that changes any
row content — including non-scoring provenance such as
`CalibrationObservation.source_hash` — changes the observation identity even
when every derived calibration and holdout score stays identical.

## The authoritative calibration-freeze anchor

`CalibrationFreezeRecordV1` (`calibration_freeze_record_v1`, schema
`schemas/calibration-freeze-record.schema.json`) is the Phase 7-A-R2
authority that makes one binding *the* binding frozen for one experiment.  It
binds, behind one deterministic `freeze_id` and `content_sha256`:

- the `experiment_id` and its exact `experiment_content_sha256`;
- the authoritative `binding_id` and the exact evidence-binding
  `binding_content_sha256`;
- its own contract identity (`calibration_freeze_record_v1`).

The authoritative workspace slot is keyed by `experiment_id` — never by the
content-derived `binding_id` — so two different bindings for one experiment
identity cannot coexist as authorities: the first valid freeze commits, a
byte-identical repeat is idempotent, and a different freeze for the same
`experiment_id` fails closed before any authoritative byte is replaced,
truncated or deleted.  The record is committed by the normal calibration
path (`tve calibrate --workspace`) with prerequisites first and the anchor
published last.  The record bytes alone are not the authority — the authority
is the committed workspace slot resolved by the loader; a record supplied as
a bare sidecar without the workspace resolution cannot produce
`READY_FOR_HUMAN_REVIEW`.

## The dossier contract

`ControlledEvolutionEvaluationV1` (`controlled_evolution_evaluation_v1`,
schema `schemas/controlled-evolution-evaluation.schema.json`) binds:

- a deterministic `evaluation_id` derived from every bound identity below,
  including the prior evidence binding identity and the authoritative
  freeze-anchor identity (and `null` components when no binding/anchor was
  supplied — a dossier that can never be READY);
- base `profile_id` and exact `base_profile_sha256` recomputed from the
  supplied profile bytes;
- frozen dataset identity (`dataset_id`, `manifest_content_sha256`);
- `experiment_id` and the experiment's content hash;
- `proposal_id` plus a SHA-256 over the canonical serialized proposal payload
  (the proposal contract itself carries no content-hash field and is not
  retroactively mutated);
- `candidate_profile_id` and the exact `parameter_overrides`;
- separate holdout-result and frozen-observation content hashes;
- `evidence_binding_id` / `evidence_binding_sha256` — the identity of the
  prior binding the evaluation ran against (both required for
  `READY_FOR_HUMAN_REVIEW`);
- `freeze_anchor_id` / `freeze_anchor_sha256` — the identity of the
  authoritative calibration-freeze record the binding was resolved from
  (both required for `READY_FOR_HUMAN_REVIEW`);
- machine-readable checks with stable names and explicit `PASS`/`BLOCKED`
  states plus non-secret detail;
- `admission_state` — only `READY_FOR_HUMAN_REVIEW` or `BLOCKED`;
- `requires_human_approval = true` and `automatic_application_allowed = false`;
- a deterministic `content_sha256`.

The Pydantic persisted model enforces semantic integrity for its version:
the checks must be exactly the canonical required-check set
(`REQUIRED_EVALUATION_CHECK_NAMES`, twenty-two checks) in canonical order — no
omission, duplicate, unknown substitution or reordering; `evaluation_id` is
recomputed from the bound identities (including the binding and freeze-anchor
identities) rather than accepted as arbitrary text; and `content_sha256` is
recomputed over the final persisted payload.

The checked-in JSON Schema is generated from the same two canonical sources —
the check model and `REQUIRED_EVALUATION_CHECK_NAMES` — so it cannot drift
from the Python contract.  The `checks` field carries an exact Draft 2020-12
sequence constraint: `prefixItems` pins each canonical check name to its
position with `const`, `items: false` forbids any element beyond the
sequence, and `minItems`/`maxItems` pin the exact count.  Schema-only
validation therefore rejects reordered checks, count-preserving
duplicate/omission, truncated sets, unknown names and extra items exactly
like the model validator.  Semantic validators JSON Schema cannot express —
recomputing `evaluation_id`, `freeze_id`, `binding_id` or any
`content_sha256`, and proving which workspace slot a record was committed to
— remain model/runtime responsibilities; the schema encodes structure only.

The dossier reports evidence admission only.  It contains no economic
performance threshold, no candidate ranking and no investment decision.

## Admission checks

Every check is recomputed independently from the supplied evidence.  The
evaluator emits exactly this canonical sequence:

| Check | Meaning |
| --- | --- |
| `BASE_PROFILE_BYTES_HASH` | supplied profile bytes hash to `base_profile_sha256` |
| `BASE_PROFILE_IDENTITY_AGREEMENT` | experiment, proposal and search space agree on the base profile |
| `EVIDENCE_BINDING_PRESENT` | a prior calibration evidence binding is supplied |
| `EVIDENCE_BINDING_MANIFEST_IDENTITY` | supplied manifest id/content hash equal the binding |
| `EVIDENCE_BINDING_EXPERIMENT_IDENTITY` | supplied experiment id/content hash equal the binding |
| `EVIDENCE_BINDING_OBSERVATIONS_IDENTITY` | supplied observation-set hash and count equal the binding |
| `EVIDENCE_BINDING_BASE_PROFILE_IDENTITY` | supplied base-profile id/hash equal the binding |
| `EVIDENCE_BINDING_PROPOSAL_IDENTITY` | supplied proposal id/payload hash equal the binding |
| `FREEZE_ANCHOR_PRESENT` | an authoritative calibration-freeze record is supplied |
| `FREEZE_ANCHOR_EXPERIMENT_IDENTITY` | the anchor binds exactly this experiment id/content |
| `FREEZE_ANCHOR_BINDING_IDENTITY` | the anchor references exactly the supplied binding |
| `MANIFEST_IDENTITY` | manifest identity and content hash match the experiment |
| `EXPERIMENT_CONTENT_HASH` | experiment content hash recomputes exactly |
| `PROPOSAL_EMBEDDING` | the proposal is the deterministic proposal of this experiment's selected trial |
| `SELECTED_TRIAL_AGREEMENT` | selected trial, candidate id and parameter overrides agree |
| `SEARCH_HOLDOUT_ISOLATION` | no search trial touches holdout rows or scores |
| `CHRONOLOGY_DISJOINT_ORDERED` | train/validation/holdout ranges stay ordered and disjoint |
| `PROPOSAL_STATUS_PROPOSAL_ONLY` | `PROPOSAL_ONLY` without automatic application |
| `HOLDOUT_BINDING` | holdout belongs to this experiment, proposal and date range |
| `HOLDOUT_CONTENT_HASH` | holdout content hash recomputes exactly |
| `CANONICAL_REPRODUCTION` | the canonical built-in scorer reproduces the experiment/proposal |
| `HOLDOUT_REPRODUCTION` | canonical holdout recomputation reproduces the artifact |

All checks `PASS` yields `READY_FOR_HUMAN_REVIEW`; any `BLOCKED` check yields
`BLOCKED` with the failing names and detail recorded in the dossier itself.
A missing evidence binding fail-closes: the dossier is `BLOCKED` (all six
binding checks plus the three anchor checks), never
`READY_FOR_HUMAN_REVIEW`.  Structurally unusable inputs (for example an
experiment without a selected proposal) fail closed before any dossier is
produced, and a broken authoritative anchor chain (missing, corrupt, foreign
or mismatched record/binding in the calibration workspace) fails closed
before any dossier is produced.

A same-`dataset_id` manifest with different valid content is `BLOCKED` on
`EVIDENCE_BINDING_MANIFEST_IDENTITY` — including the R2 attack of rebuilding
a fresh matching binding over the substituted manifest, which is additionally
unanchored and `BLOCKED` on `FREEZE_ANCHOR_PRESENT` when only a sidecar is
supplied.  A `source_hash`-only observation substitution with a freshly
rebuilt binding is likewise `BLOCKED`: against the authoritative workspace
the anchored binding pins the original observation-set identity, and without
the workspace the fresh binding is an unanchored sidecar.  Even when every
derived calibration and holdout score is unchanged, the substitution cannot
be admitted.

## Reproducibility policy

The reproduction check re-runs `CalibrationRunner` with the repository's
canonical built-in scorer over the frozen observations and the recorded
search space/split, then compares everything the canonical path determines
(all experiment fields except the recomputed `content_sha256` and the free
text `rationale`).  Because the experiment contract does not record a custom
scorer, an experiment produced with an unrecorded custom scorer cannot be
proven reproducible: it is `BLOCKED` rather than guessed compatible.
Reproduction is necessary but not sufficient: exact input identity is proven
separately against the calibration-time evidence binding.

## Verification posture

The focused suites cover the four documented pre-R1 unsafe behaviors
(same-id manifest substitution, `source_hash`-only observation substitution,
truncated READY dossier, wrong `evaluation_id` — each proven failing on the
pristine pre-R1 baseline before implementation) and the four documented R1
unsafe behaviors (fresh-binding manifest substitution, fresh-binding
provenance substitution with unchanged canonical replay, schema-only
reordered checks, schema-only count-preserving duplicate/omission — each
proven failing on the pristine R1 baseline `cbcf4ca` before R2
implementation), substitution of profile,
manifest, proposal, experiment, holdout, observations, binding, observation
count, base-profile and proposal identities inside the binding; selected-trial
mismatch; holdout leakage; corrupt chronology; non-`PROPOSAL_ONLY` input;
custom-scorer non-reproducibility; deterministic rerun/hash equality; schema
drift parity for all three contracts; socket-guarded no-network execution;
and byte identity of `strict-v1.yaml` and every supplied artifact across
evaluation.

The R2 suite additionally proves the authoritative anchor lifecycle:
freeze-record contract determinism and tamper rejection; workspace round-trip
keyed by `experiment_id`; byte-identical repeated freeze idempotency;
conflicting second freeze (different binding, or different manifest content)
rejected with every pre-existing authoritative byte preserved; the anchor
published last under a simulated prerequisite crash; fail-closed resolution
for missing, corrupt and foreign anchors and for anchors referencing missing,
mismatched or foreign bindings; the evaluator's three anchor checks with
precise blocked reasons; an unanchored sidecar binding never reaching
`READY_FOR_HUMAN_REVIEW`; the real
`calibrate --workspace -> evolution evaluate --calibration-workspace` CLI
chain reaching `READY_FOR_HUMAN_REVIEW`; non-destructive calibrate exports;
exact-sequence schema parity (canonical, reordered, count-preserving
duplicate/omission, truncated, unknown-name and extra-item dossiers rejected
in both the model and schema-only validation); and socket-guarded offline
execution of the commit, resolve and evaluation paths.

## Relationship to Phase 7-B1 materialization

Phase 7-B1 consumes this admission boundary unchanged and adds the
candidate-materialization semantics/projection/replay chain on top of it:
the materialization CLI requires the authoritative `--calibration-workspace`,
re-resolves the freeze record and binding through the R2 loader and re-runs
this evaluation immediately before projecting any candidate bytes. A
persisted READY dossier remains audit evidence only — never a bearer
authorization token. The full B1 boundary is documented in
[`candidate-profile-materialization.md`](candidate-profile-materialization.md).
