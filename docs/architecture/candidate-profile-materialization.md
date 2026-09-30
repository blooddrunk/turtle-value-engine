# Candidate Profile Materialization Architecture

Phase 7-B1 implements the first safe bridge from an admitted
`CandidateProfileProposal` to a deterministic **candidate-only**
`RuleProfile` artifact. It creates the semantics, projection and replay
boundaries Phase 7-B2 will build its PR/human-approval workflow on. It does
not create `strict-v2`, writes nothing into active `rules/`, opens no pull
request and records no approval.

```text
calibration search space (with materialization_semantics reference)
frozen observations + manifest + experiment + holdout
        -> authoritative R2 freeze (unchanged Phase 7-A-R2 chain)
        -> resolve_anchored_calibration_evidence(...)      # workspace authority
        -> evaluate_controlled_evolution(...)              # fresh re-admission
        -> READY_FOR_HUMAN_REVIEW
        -> classify_proposal_materializability(...)        # frozen semantics
        -> project_candidate_profile(...)                  # candidate bytes
        -> replay_candidate_profile(...)                   # engine PIT replay
        -> CandidateProfileMaterializationV1               # immutable record
```

## Materializable parameter semantics

`CalibrationSearchSpace.materialization_semantics` (additive, optional) is a
`MaterializationSemanticsReferenceV1`: the `semantics_id`, version and content
hash of one **installed** semantics set. Because the search space is part of
the deterministic experiment identity — and therefore of the evidence
binding and the authoritative R2 freeze — a semantics-bearing search space
freezes the meaning of its parameters **before any trial is scored**.

`backtest/materialization_semantics.py` owns the installed registry
(`materializable_parameter_semantics_set_v1`, schema
`schemas/materializable-parameter-semantics.schema.json`). Each parameter
entry binds:

- a stable parameter key that is exactly the built-in scorer's operator
  prefix plus the observation feature (`min_cdc_yield` →
  `MIN_FEATURE_THRESHOLD` on `feature_values["cdc_yield"]`), so the frozen
  semantics describe the filter the calibration actually applied;
- a concrete `RegisteredRuleTargetV1`: the dotted YAML-visible path of one
  scalar `RuleProfile` leaf (for example `cdc.yield_bands.pass`), its scalar
  type (`FLOAT`/`INT`) and an explicit range contract mirroring the model's
  own constraints;
- a deterministic `semantics_id` recomputed from the version and parameter
  payload, plus a `content_sha256` over the whole set.

`CalibrationRunner` validates the reference at construction: it must resolve
against an installed set (id, version and content hash all equal), every
search-space parameter must be registered, and every candidate value must
satisfy the registered type/range contract. The identical validation runs
inside evaluation reproduction, so a registry that drifted since calibration
fail-closes `CANONICAL_REPRODUCTION` before any dossier can be READY.

Legacy/unbound search spaces (the entire pre-B1 history, including the
canonical `min_quality` fixture) carry no reference: they remain readable and
evaluable, and `classify_proposal_materializability` classifies their
proposals `NON_MATERIALIZABLE` with the stable reason
`NO_FROZEN_MATERIALIZATION_SEMANTICS`. Semantics are never inferred from
parameter names, feature names, candidate ids, rationale text or score
behavior; a mapping first supplied at materialization time cannot match the
frozen reference and fails closed.

## Candidate-only projection

`evolution/candidate_projection.py` is a pure function over the exact
base-profile bytes. It verifies the bytes against
`CandidateProfileProposal.base_profile_sha256`, parses them through the
ordinary YAML → `RuleProfile` validation, verifies the base profile id, and
applies **only** the registered overrides to an in-memory copy. Only scalar
leaves reachable through registered dotted paths can change: there is no
caller-provided path surface, structural (list/object) targets are not
representable in the contract, and one leaf may receive at most one override.

The projection then assigns deterministic candidate-only metadata — the
profile `id` becomes the proposal's `candidate_profile_id` (never the human
release name `strict-v2`; `status` becomes `candidate-proposal`) — validates
the complete resulting `RuleProfile` again, serializes canonical candidate
bytes (sorted-key YAML of the aliased model dump) and proves those bytes
round-trip through profile validation. The recorded diff separates
`rule_changes` (exactly the registered leaves, before → after) from
`metadata_changes` (the four deterministic profile metadata fields), so no
hidden semantic change can hide inside metadata.

## Authoritative re-admission before materialization

A persisted `READY_FOR_HUMAN_REVIEW` dossier is audit evidence, never a
bearer authorization token. `tve evolution materialize-candidate` requires
the authoritative `--calibration-workspace` (there is no sidecar or dossier
input), resolves the `CalibrationFreezeRecordV1` and referenced binding
through the unchanged R2 workspace loader, re-runs the full
`evaluate_controlled_evolution` admission over the supplied manifest,
experiment, holdout, observations and base-profile bytes, and requires a
fresh READY result. `materialize_candidate_profile` additionally cross-checks
that the fresh evaluation is bound to exactly the supplied anchored
identities (`ANCHORED_IDENTITY_MISMATCH` otherwise). Every blocker before
this point produces zero candidate output.

## Profile-aware frozen point-in-time replay

`evolution/replay.py` proves candidate **semantics** by rerunning the
unchanged deterministic engine (`run_analyze`) over the frozen
point-in-time normalized inputs embedded in the manifest's
`HistoricalDecisionArtifact` rows — once under the exact base profile and
once under the projected candidate profile (each frozen input is replayed
unchanged except that `profile_id` is rebound to the candidate id so the
engine executes under the projected profile; the rebind is recorded in the
replay contract). The generic calibration feature-filter score is not used
and is not proof of candidate rule behavior.

Replay scope is exactly the search stage (train + validation) of the frozen
chronological split; holdout rows are never replayed, inspected or scored.
Each observation must reference its decision artifact through
`source_observation_id`; the referenced artifact must exist, embed a
`normalized_input`, match the observation's `source_hash`, and not be
future-dated relative to the observation (`as_of`/`available_at` ordering).
Missing inputs raise explicit blockers (`MISSING_FROZEN_NORMALIZED_INPUT`,
`OBSERVATION_PROVENANCE_MISMATCH`, `FUTURE_FROZEN_INPUT`) — there is no
fallback to baseline decisions, baseline analyses or generic filtering.
Each row records both decision states and full analysis digests, so any
semantic difference under the candidate profile is machine-visible.

## The materialization record

`CandidateProfileMaterializationV1` (`candidate_profile_materialization_v1`,
schema `schemas/candidate-profile-materialization.schema.json`) binds, behind
one deterministic `materialization_id` and `content_sha256`:

- the fresh evaluation id/content hash, freeze-anchor id/hash,
  evidence-binding id/hash, experiment id/hash and proposal id/payload hash;
- the exact base-profile id/hash and the frozen parameter-semantics
  id/version/content hash;
- the exact rule-leaf changes and the deterministic metadata changes;
- the candidate profile id and the candidate content hash;
- the embedded `CandidateProfileReplayV1` (its own deterministic
  `replay_id`, rows and digests);
- `requires_human_approval = true` and `automatic_application_allowed =
  false`, enforced by the model.

The record and the candidate bytes are review input only.

## CLI boundary

```text
tve evolution materialize-candidate
  --calibration-workspace <authoritative-root>
  --manifest <frozen-manifest>
  --experiment <frozen-experiment>
  --holdout <frozen-holdout>
  --observations <frozen-observations>
  --base-profile rules/strict-v1.yaml
  --candidate-output <review-dir>/candidate.yaml
  --materialization-output <review-dir>/materialization.json
```

Outputs are create-only and non-destructive: paths are refused when they
collide with a supplied input, each other, the authoritative workspace or
anything under the active `rules/` directory; an occupied path must already
hold byte-identical content (an idempotent repeat) and different content
fails closed before any byte is published; all blockers fire before the
first write, so a blocked run leaves no partial candidate artifact. Exit
codes: `0` materialized, `1` classified blocker (`NON_MATERIALIZABLE` /
`MATERIALIZATION_BLOCKED` with a machine-readable `reason_code`), `2`
invalid input/path. The command constructs no network socket, invokes no
provider, model or transport, and never writes a rule, PR or approval state.

## R1 immutable publication and pair admission

The CLI resolves each output against its canonical parent, refuses symlink or
non-regular finals and derives the active rule root from the supplied
`--base-profile` directory as well as repository conventions. At publication,
an opened directory descriptor anchors each output to the validated parent;
temporary files are written and fsynced through that descriptor, then linked
into place without replacement. The directory is fsynced after each new final.
An occupied final is acceptable only when its bytes are identical. A competing
different writer keeps its file and causes a conflict.

The candidate is published first; the materialization JSON is published last
and is the authority marker. On a normal second-stage failure, the CLI removes
only a candidate inode it created and can still identify, and only when no
materialization record is present. A crash can leave an orphan candidate. That
orphan is not a committed materialization: downstream consumers must call
`resolve_complete_materialization_pair`, which requires two regular,
non-symlink files, validates the materialization contract and candidate
`RuleProfile` identity, and compares the hash of the **exact candidate bytes**
with `candidate_content_sha256`. The two files are not a cross-filesystem
atomic transaction; a deterministic rerun can safely reuse identical bytes.
# Phase 7-B2-A release projection

`tve evolution prepare-profile-release` accepts a complete B1 candidate and
materialization pair as review evidence. It resolves the authoritative R2
calibration freeze and binding from the supplied workspace, reruns admission,
and reruns B1 materialization in memory. Candidate bytes, candidate hash,
materialization ID and materialization content hash must all equal the supplied
pair before release projection begins. A persisted pair therefore cannot grant
release authority by itself.

The release projection accepts only the next `strict-vN` lineage. It copies
every typed rule-bearing field from the reproduced candidate and replaces only
top-level `profile` metadata: the next ID and deterministic name, with status
and description restored from the exact base profile. The typed profile must
round-trip through canonical YAML. Its rule-payload hash must equal the
candidate's; the complete base-to-release scalar diff must equal the B1
materialization's registered rule changes.

The `VersionedProfileReleaseCandidateV1` manifest binds the source chain,
exact release byte hash, rule-payload identities, metadata and rule diffs,
and the intended `rules/strict-v2.yaml` target. It is review evidence with
human approval required, and never an approval or application. The CLI uses
the same B1-R1 two-stage immutable publisher: release bytes first, manifest
last. Identical writers converge; different bytes never overwrite. Normal
second-stage failure removes only a release inode proved to belong to that
invocation and only when no authority manifest exists. Process death may
leave an orphan release profile; the read-only resolver rejects it until a
matching final manifest exists. No output is permitted under active `rules/`,
the calibration workspace or a supplied input path.
