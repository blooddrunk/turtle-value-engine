# Phase 7-B1-R1 — Immutable Materialization Publication and Active-Rule Path Hardening

Status: **CLOSED / AUTOMATIC CI CLOSURE**
Date: 2026-09-30
Post-closure review: `docs/status/phase-7-b1-r1-post-closure-review-2026-09-30.md` preserves this closure and selects Phase 7-B2-A before the later human/PR B2-B boundary.
Selected after: Phase 7-B1 post-closure review

Closure record: `docs/status/phase-7-b1-r1-2026-09-30.md`

Selection audit:
`docs/status/phase-7-b1-post-closure-review-2026-09-30.md`

Reviewed baseline:
`76066f620c9f10b8375818ec4811c2624f0f9d1f`

Coding-agent handoff:
`docs/status/phase-7-b1-r1-next-coding-agent-goal.md`

## 1. Objective

Harden the already-closed B1 candidate/materialization publication boundary
so its create-only, non-destructive and active-rules guarantees remain true
under concurrent writers, injected filesystem failures and non-repository
execution layouts.

Do not redesign B1 calibration semantics, authoritative re-admission,
candidate projection or PIT replay. R1 is a persistence/path-integrity patch
before the later B2 GitHub PR + human approval boundary.

## 2. Source of truth

Read and follow, in order:

1. `AGENTS.md`
2. `docs/status/phase-7-b1-post-closure-review-2026-09-30.md`
3. `docs/status/phase-7-b1-2026-09-30.md`
4. `docs/goals/phase-7-b1-materializable-candidate-profile-foundation.md`
5. `docs/architecture/candidate-profile-materialization.md`
6. `src/turtle_value_engine/cli.py` publication/path helpers
7. `src/turtle_value_engine/backtest/workspace.py` immutable create-only precedent
8. relevant monitoring/historical immutable stores using temp + fsync + hardlink
9. `tests/test_evolution_materialize.py`

The exact reviewed baseline is
`76066f620c9f10b8375818ec4811c2624f0f9d1f`. Preserve B1 closure unless
a separate concrete defect is proven with a focused regression.

## 3. Defects R1 must close

### 3.1 Check-then-replace is not immutable publication

The current `_commit_materialization_outputs()` checks `path.exists()` and
later calls `os.replace(temporary_path, path)`. A competing writer can create
a different final file between those operations, after which `os.replace`
overwrites it.

Final candidate/materialization artifacts must never be published by an
overwrite-capable primitive. Use the repository's established immutable
publication semantics (temp file, file fsync, no-replace finalization such as
hardlink/exclusive create, and directory fsync where appropriate), or an
equivalent implementation with the same machine-proven guarantees.

On a publication race:

- identical bytes may converge idempotently;
- different bytes must produce a deterministic conflict;
- existing winner bytes must remain unchanged.

### 3.2 Pair publication needs an explicit authority-last rule

Candidate YAML and materialization JSON form one review pair. Publish the
candidate prerequisite first and the materialization record last. The record
already carries the candidate content hash and is the authority marker for a
complete pair.

Provide one canonical resolver/validator for downstream B2 that:

- requires both artifacts to be regular, non-symlink files;
- parses/validates `CandidateProfileMaterializationV1`;
- hashes the exact candidate bytes and compares them with
  `candidate_content_sha256`;
- optionally re-validates the candidate as `RuleProfile` and its recorded id;
- rejects incomplete, corrupt, mismatched or foreign pairs.

If a normal error occurs after this invocation created the candidate but
before the materialization record is committed, remove only the candidate
whose creation ownership is provable. Never delete a pre-existing or
concurrently published file.

A process crash may leave an orphan candidate prerequisite. Do not claim
cross-filesystem atomicity that is not available. The machine-enforced truth
must instead be: without the final valid materialization record, no
materialization is committed or admissible to B2. Deterministic rerun must
converge safely.

### 3.3 Bind path safety to the supplied active base profile

The existing rule-directory refusal recognizes source-tree/CWD `rules/` roots
but the CLI accepts an arbitrary `--base-profile` path.

R1 must derive the active rule root from the actual supplied base-profile
path or an equivalent canonical authority source. A candidate/materialization
output must not be allowed into that active rule root even when the command is
executed from another CWD or an installed package.

Canonicalize/validate the exact destinations that will be used during final
publication. Final symlinks, non-regular occupied files, and redirection into
input/workspace/rule authority roots must fail closed.

## 4. Required implementation behavior

Keep the current CLI shape unless a small additive flag/API is required.
Whichever shape is chosen, preserve:

- create-only/idempotent behavior for byte-identical reruns;
- exit 0 only for a complete valid pair;
- exit 1 for B1 semantic/materialization blockers;
- exit 2 for invalid paths/filesystem publication conflicts;
- no partial completed pair on normal failure;
- no network/provider/model/transport construction;
- no mutation of authoritative calibration workspace or active rules.

Do not silently weaken the current candidate/materialization hashes or
identity contracts.

## 5. Fail-on-B1-baseline regressions

Before implementation, run focused tests against the pristine baseline
`76066f620c9f10b8375818ec4811c2624f0f9d1f` and record the exact observed
failure/unsafe behavior for all three defects:

1. **Concurrent overwrite race** — deterministically inject a foreign
   different final file after the current last existence check but before
   `os.replace`; prove the baseline overwrites foreign bytes.
2. **Second-publish failure** — inject a conflict/error only on materialization
   finalization after candidate finalization succeeds; prove the baseline
   leaves the candidate behind.
3. **External active-rules root** — execute with CWD outside the repository,
   copy the base profile to `<tmp>/active/rules/strict-v1.yaml`, target
   `<tmp>/active/rules/candidate.yaml`, and prove the baseline guard accepts
   the destination.

These are real behavioral regressions. Do not replace them with tests that
only fail because R1 helper symbols do not exist.

## 6. Required post-fix verification

Focused tests must prove at least:

1. concurrent different publisher never overwrites winner bytes;
2. concurrent identical publishers converge idempotently;
3. second-stage conflict/error leaves no completed pair and rolls back only
   artifacts definitely created by the current invocation;
4. process-crash/incomplete-pair simulation is rejected by the complete-pair
   resolver;
5. candidate bytes changed after publication fail hash/id validation;
6. final symlink/non-regular path fails closed;
7. output redirection into manifest/experiment/holdout/observations/base
   profile/calibration workspace/active rules fails closed;
8. external active rule root is derived from the supplied base profile and
   refused independently of CWD/package layout;
9. byte-identical rerun remains idempotent;
10. all existing B1 semantic/replay tests remain green;
11. full B1 library + CLI socket guards remain zero-network;
12. `rules/strict-v1.yaml` stays byte-identical;
13. any new persisted schema has generated/check-in drift parity.

Run the complete current CI-equivalent gate:

- Ruff;
- config validation;
- full Python suite;
- systemd unit verification;
- generated OpenAPI/API/Wrangler type checks;
- Dashboard lint/typecheck/tests/build and client-bundle secret scan;
- Wrangler strict dry-run;
- cross-stack smoke.

After push, query GitHub Actions automatically. Do not close R1 unless the
required run is `success` and `head_sha` exactly equals the implementation
commit. Record exact SHA, run id/conclusion, focused regression counts, full
Python pass/skip count, Dashboard count, race/rollback/path proof, no-network
proof and strict-v1 byte identity.

## 7. Manual-intervention policy

No manual owner action is planned for R1.

If and only if a genuinely external authority/environment makes one check
impossible, record all seven items:

1. exact command/action attempted;
2. exact blocker;
3. exact human action required;
4. exact data/secret boundary;
5. exact resume command;
6. machine-checkable success criterion;
7. exact remaining unverified scope.

Continue every other automatic verification. Never replace this with a vague
statement that evidence is incomplete.

## 8. Stop boundary

Stop after immutable publication, complete-pair validation, active-rule path
hardening and exact-head CI closure.

Do not create/name/install `strict-v2`, write an approved profile into active
`rules/`, open or merge a rule-profile PR, record GitHub/human approval or
rejection, mutate `strict-v1`, automatically apply a candidate, add
provider/Bridge/FQGate or notification-vendor/Windows-bootstrap scope, or add
brokerage/trading behavior.

Phase 7-B2 remains the next candidate package only after R1 closes.
