# Phase 7-B2-A — Versioned Profile Release Bundle and PR-Ready Provenance

Status: **CLOSED / EXACT-HEAD CI VERIFIED**
Date: 2026-09-30
Selected after: Phase 7-B1-R1 post-closure review
Post-closure review: `docs/status/phase-7-b2-a-post-closure-review-2026-09-30.md`
Selected next package: `docs/goals/phase-7-b2-b1-pr-construction-exact-head-ci.md`

Selection audit:
`docs/status/phase-7-b1-r1-post-closure-review-2026-09-30.md`

Reviewed baseline:
`d296fde91ab0ff2e65ae6306281e8a3407f95a20`

Coding-agent handoff:
`docs/status/phase-7-b2-a-next-coding-agent-goal.md`

## 1. Objective

Create a deterministic, offline, immutable and PR-ready versioned-profile
release bundle from a Phase 7-B1/R1 complete materialization pair, without
writing active rules or crossing the GitHub/human-approval authority boundary.

B2-A must produce the **exact bytes** that a later B2-B PR is allowed to place
at `rules/strict-v2.yaml` plus an immutable release manifest proving where
those bytes came from and that no rule semantics changed after B1
materialization.

No manual owner action is planned for B2-A.

## 2. Source of truth

Read and follow, in order:

1. `AGENTS.md`
2. `docs/status/phase-7-b1-r1-post-closure-review-2026-09-30.md`
3. `docs/status/phase-7-b1-r1-2026-09-30.md`
4. `docs/status/phase-7-b1-2026-09-30.md`
5. `docs/architecture/candidate-profile-materialization.md`
6. `docs/goals/phase-5-backtesting-calibration.md`
7. `src/turtle_value_engine/evolution/materialization_pair.py`
8. `src/turtle_value_engine/evolution/materialize.py`
9. `src/turtle_value_engine/backtest/calibration_freeze.py`
10. `src/turtle_value_engine/config/loader.py` and `config/models.py`
11. `rules/strict-v1.yaml`

The exact reviewed baseline is
`d296fde91ab0ff2e65ae6306281e8a3407f95a20`.

Preserve every Phase 7-A/R1/R2 and B1/R1 authority, chronology, replay,
no-network, non-destructive and strict-v1 invariant.

## 3. Authoritative input boundary

A complete B1 pair is coherent review evidence, not bearer authority.

The B2-A application/CLI boundary must require:

- candidate profile bytes;
- B1 materialization record;
- authoritative calibration workspace;
- exact frozen manifest;
- exact experiment;
- exact holdout result;
- exact frozen observations;
- exact base-profile bytes;
- explicit target versioned profile id.

Before generating release bytes:

1. call `resolve_complete_materialization_pair`;
2. resolve the authoritative R2 freeze/binding from the calibration workspace;
3. freshly run `evaluate_controlled_evolution`;
4. freshly run `materialize_candidate_profile` in memory;
5. require exact equality with the supplied pair:
   - candidate bytes;
   - candidate content hash;
   - materialization id;
   - materialization content hash.

Any mismatch is a classified blocker and produces zero release output.

Do not trust a persisted READY evaluation, materialization JSON or release
manifest by itself.

## 4. Version lineage and target path

For the current strict lineage, accept only `strict-vN` ids and require the
target to be exactly the next version of the source base profile:

`strict-v1 -> strict-v2`.

Reject:

- same version;
- skipped/backward version;
- arbitrary names;
- path separators/traversal;
- a target whose intended path is not exactly `rules/<target-id>.yaml`.

B2-A records the intended target path but must not write there.

If a checked-in `rules/<target-id>.yaml` already exists on the implementation
baseline, fail closed rather than overwrite/reinterpret it.

## 5. Deterministic release profile

Derive the release profile from the freshly reproduced B1 candidate.

Every rule-bearing field outside top-level `profile` metadata must be exactly
equal between candidate and release.

Use a deterministic metadata policy:

- `profile.id = <target-id>`;
- `profile.name` deterministically derived from the strict version, e.g.
  `Turtle Value Engine Strict v2`;
- `profile.status` preserved from the exact base profile;
- `profile.description` preserved from the exact base profile.

Validate the complete result with `RuleProfile`, serialize deterministically
using the repository's canonical profile serialization policy, and prove a
round-trip back to the same typed model.

Do not introduce a hidden semantic rewrite under metadata.

## 6. Release manifest

Add a versioned immutable persisted contract, suggested
`VersionedProfileReleaseCandidateV1`, with checked-in Draft 2020-12 JSON
Schema and deterministic id/content hash.

Bind at least:

- source materialization id/content hash;
- source evaluation/freeze/binding/experiment/proposal identities;
- base profile id/hash;
- candidate profile id/hash;
- target profile id;
- intended repository target path;
- release profile exact byte hash;
- deterministic hash/identity of the rule-bearing payload excluding top-level
  profile metadata;
- candidate and release rule-payload hashes, required equal;
- deterministic candidate -> release metadata changes;
- exact base -> release rule changes, required to agree with the source
  materialization's authoritative rule changes;
- `review_state = READY_FOR_HUMAN_PR_REVIEW` or equivalent fixed literal;
- `requires_human_approval = true`;
- `automatic_merge_allowed = false`;
- `automatic_application_allowed = false`.

The manifest is review evidence only. It is not an approval.

## 7. Output and CLI boundary

A thin offline command such as this is appropriate:

```text
tve evolution prepare-profile-release \
  --candidate <review-dir>/candidate.yaml \
  --materialization <review-dir>/materialization.json \
  --calibration-workspace <authoritative-root> \
  --manifest <frozen-manifest> \
  --experiment <frozen-experiment> \
  --holdout <frozen-holdout> \
  --observations <frozen-observations> \
  --base-profile rules/strict-v1.yaml \
  --target-profile-id strict-v2 \
  --release-output <release-dir>/strict-v2.yaml \
  --release-manifest-output <release-dir>/release.json
```

Exact spelling may differ if repository conventions suggest a clearer API.

Required behavior:

- release profile is a prerequisite artifact;
- release manifest is the final authority marker;
- immutable/no-overwrite/idempotent publication semantics must be at least as
  strong as B1-R1;
- a normal second-stage failure safely rolls back only output owned by this
  invocation;
- crash/orphan semantics are explicit and a complete-release resolver rejects
  a missing/tampered authority manifest;
- outputs under active `rules/`, calibration workspace or supplied inputs
  are refused;
- no GitHub/network/provider/model/transport client is constructed.

Prefer extracting/reusing a small tested immutable-publication primitive rather
than copying B1-R1 publication logic into a second ad hoc implementation.

## 8. Baseline evidence

B2-A is a new capability. Do not manufacture a fail-on-baseline test that only
fails because the new contract/CLI/helper does not exist.

Record the reviewed structural baseline instead:

- B1-R1 ends at a candidate/materialization review pair;
- no `VersionedProfileReleaseCandidateV1` or equivalent exists;
- no `prepare-profile-release` path exists;
- `rules/strict-v2.yaml` does not exist;
- no production path converts a B1 pair into exact PR-ready versioned-profile
  bytes;
- no current runtime path records human approval or automatically applies a
  candidate.

## 9. Required automatic verification

Focused B2-A tests must prove at minimum:

1. one honest registered B1 chain -> authoritative, deterministic
   `strict-v2` release bundle;
2. self-consistent but foreign/forged pair -> fail closed during fresh
   authoritative re-materialization;
3. wrong workspace/manifest/experiment/holdout/observations/base bytes ->
   fail closed with zero release outputs;
4. wrong or non-next target version -> fail closed;
5. candidate -> release diff is metadata-only;
6. candidate/release rule-payload identities are equal;
7. base -> release rule changes equal the source materialization's exact
   registered rule changes, with no hidden additional rule diff;
8. release profile validates and round-trips deterministically;
9. repeated run -> byte-identical release profile and release manifest;
10. concurrent identical publication converges; concurrent different
    publication never overwrites;
11. normal second-stage failure leaves no committed release and rolls back only
    provably owned prerequisite output;
12. orphan/tampered/symlinked release pair is rejected by a read-only resolver;
13. inputs/workspace/active-rules path collisions and redirection fail closed;
14. full B2-A library + CLI socket guards prove zero network socket;
15. `rules/strict-v1.yaml` stays byte-identical and
    `rules/strict-v2.yaml` stays absent;
16. new checked-in schema equals the model-generated schema and validates real
    instances;
17. all B1/R1 focused suites stay green.

Run the complete current CI-equivalent gate:

- Ruff;
- config validation;
- full Python suite;
- systemd unit verification;
- generated OpenAPI/API/Wrangler checks;
- Dashboard lint/typecheck/tests/build/client-bundle secret scan;
- Wrangler strict dry-run;
- cross-stack smoke.

After push, query GitHub Actions automatically. Do not close B2-A unless the
required run is `success` and `head_sha` exactly equals the implementation
commit. Record exact implementation SHA, run id/conclusion, focused counts,
full Python pass/skip count, Dashboard count, authoritative re-materialization
proof, metadata-only/rule-identity proof, immutable publication proof,
no-network proof and strict-v1/strict-v2 filesystem proof.

## 10. Manual-intervention policy

No manual owner action is planned for B2-A.

If and only if a genuinely external authority/environment blocks one automatic
check, document ALL seven items:

1. exact command/action attempted;
2. exact blocker;
3. exact human action required;
4. exact data/secret boundary;
5. exact resume command;
6. machine-checkable success criterion;
7. exact remaining unverified scope.

Continue every other automatic check. Never use a vague "evidence not fully
recorded" placeholder.

## 11. Stop boundary

Stop after exact PR-ready versioned-profile bytes and an immutable release
manifest are produced, resolved and exact-head CI closure is recorded.

Do not:

- write/create `rules/strict-v2.yaml`;
- open or merge a GitHub PR;
- record/forge human approval;
- change the default profile;
- automatically apply the candidate;
- mutate `strict-v1`;
- add provider/Bridge/FQGate, notification-vendor/Windows-bootstrap or
  brokerage/trading scope.

Those belong to Phase 7-B2-B or separately selected later work.

## 12. Implementation note

The reviewed B1-R1 baseline ended at the candidate/materialization pair: it
had no persisted release contract, release CLI, `rules/strict-v2.yaml`, PR-ready
conversion or automatic approval/application path. B2-A adds the offline
`prepare-profile-release` command, `VersionedProfileReleaseCandidateV1` and a
read-only complete-release resolver. The command reuses the B1-R1 immutable
two-stage publisher and requires a fresh authoritative R2/B1 replay before
publication. The release profile is a review artifact outside active rules;
the release manifest is the final authority marker. Exact verification and
CI closure are recorded in `docs/status/phase-7-b2-a-2026-09-30.md`.
