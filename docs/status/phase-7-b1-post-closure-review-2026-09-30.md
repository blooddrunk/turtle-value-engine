# Phase 7-B1 post-closure review — Materialization Publication Integrity

Status: **B1 CLOSURE PRESERVED / B2 BLOCKED PENDING B1-R1**
Date: 2026-09-30

Reviewed closure:
`docs/status/phase-7-b1-2026-09-30.md`

Reviewed implementation:
`ad4f3580894d65e2c15b40723f9faf6583710d11`

Closure commit:
`76066f620c9f10b8375818ec4811c2624f0f9d1f`

Selected hardening package:
`docs/goals/phase-7-b1-r1-materialization-publication-hardening.md`

## 1. Verdict

Phase 7-B1 remains correctly CLOSED at its intended semantic boundary:
materializable parameter semantics are frozen before selection, legacy
unbound proposals fail closed, authoritative R2 evidence is freshly
re-admitted, candidate-only RuleProfile bytes are projected deterministically,
and frozen PIT engine replay is recorded without mutating strict-v1.

The review does not reopen those semantics. It identifies a narrower
publication-integrity defect in the CLI output boundary that should be fixed
before Phase 7-B2 creates a PR/human-approval workflow over these artifacts.

Select **Phase 7-B1-R1 — Immutable Materialization Publication and Active-Rule
Path Hardening**. B2 remains next after R1 closes.

## 2. Independent closure evidence re-checked

GitHub Actions run `36685558492` was independently queried:

- workflow: `CI`;
- event: `push`;
- `head_sha`: `ad4f3580894d65e2c15b40723f9faf6583710d11`, exactly the B1 implementation;
- conclusion: `success`;
- the job log records `7006 passed, 2 skipped` for Python;
- Dashboard tests record `55 passed`;
- Ruff, systemd verification, generated contract checks, Dashboard build,
  client-bundle secret scan, Wrangler strict dry-run and cross-stack smoke all
  completed successfully.

The implementation and closure records therefore remain valid. This review is
about a boundary not exercised by the existing single-process collision tests.

## 3. Finding A — the advertised create-only boundary has a TOCTOU overwrite

`_commit_materialization_outputs()` in `src/turtle_value_engine/cli.py` stages
temporary files, checks whether the final path exists, then publishes with
`os.replace(temporary_path, path)`.

That sequence is not create-only under concurrency. A different process can
create the final path after the last `path.exists()` check and before
`os.replace()`. POSIX replace semantics then allow this invocation to replace
the concurrently created file. The current code can therefore overwrite
foreign bytes even though B1 documents the outputs as immutable/create-only.

This is inconsistent with the repository's established immutable-store
pattern. `BacktestWorkspace._write()` and several monitoring/historical stores
use temp + fsync + hardlink publication, where an occupied destination causes
a create conflict rather than replacement.

R1 must remove every overwrite-capable primitive from the immutable candidate
and materialization finalization path. A concurrent identical writer may be
accepted idempotently after byte comparison; a concurrent different writer
must preserve the winner and fail closed.

## 4. Finding B — the two-output publication can leave a partial pair

The current publisher finalizes candidate output and materialization output
sequentially. If the candidate publish succeeds and the second publish then
fails because of a concurrent conflict or injected filesystem error, the first
published candidate remains.

The existing test `test_cli_refuses_occupied_output_with_different_bytes` only
covers a conflict visible before publication starts. It does not inject a
failure or competing writer between the two final publishes.

R1 must define the pair's authority explicitly:

1. immutable candidate bytes are a prerequisite artifact;
2. the materialization record is published last and binds the candidate hash;
3. a normal second-stage failure rolls back any prerequisite created by that
   invocation where that rollback can be proven safe;
4. a process crash may leave an orphan prerequisite, but downstream code must
   have a machine-enforced resolver that refuses any pair lacking the final
   materialization record or whose candidate bytes do not match its recorded
   hash;
5. directory durability must be fsync'd where the platform supports the
   repository's existing persistence pattern.

This mirrors the already-established R2 rule: prerequisites may be orphaned by
a crash, but authority moves last and can never point at missing/conflicting
content.

## 5. Finding C — active-rules refusal is tied to package/CWD heuristics

`_guard_materialization_output_path()` currently recognizes two rules roots:
the source/package repository root and `Path.cwd() / "rules"`.

The CLI also accepts an arbitrary `--base-profile` path. When the program is
run from an installed package or from a different working directory, a supplied
active profile such as `/some/deployment/rules/strict-v1.yaml` does not make
`/some/deployment/rules/` a forbidden root. A candidate output beside that
profile can therefore pass the current guard even though B1's contract says
that active rules/ is never a materialization destination.

R1 must bind the output guard to the actual supplied base-profile/rule root,
not only to package/CWD guesses, and must publish to the same canonical paths
that were validated. Symlink/final-path substitution must fail closed rather
than redirect an approved destination into an authority/input/rules root.

## 6. Why this is B1-R1 rather than B2

The defect is local to B1's persistence boundary. It does not require a
GitHub API, PR workflow, reviewer identity, approval state or a new versioned
rule profile. Carrying it into B2 would force the approval pipeline to build
on artifacts whose claimed immutability is weaker than the rest of the
repository.

Therefore B1 stays closed for semantic functionality, while B1-R1 hardens
publication before the first remote/human approval boundary.

## 7. Required B1-R1 invariants

R1 must at minimum:

1. preserve all B1 semantics, replay and authoritative re-admission behavior;
2. publish immutable finals with a no-overwrite primitive; no check-then-
   replace sequence is admissible;
3. classify concurrent identical publication as idempotent and concurrent
   different publication as a conflict that preserves existing bytes;
4. make the materialization record the last authoritative member of the pair;
5. provide a machine-enforced complete-pair resolver/validator that checks
   candidate bytes against `candidate_content_sha256` and rejects incomplete,
   symlinked, corrupt or foreign pairs;
6. remove a candidate created by the current invocation if a normal later
   publication step fails and safe ownership of that candidate is provable;
7. document crash semantics honestly: orphan prerequisites may exist, but
   they are never authoritative and a rerun is deterministic/idempotent;
8. derive active-rule path refusal from the supplied base profile/rule root
   in addition to repository conventions, and re-check canonical output
   destinations at the finalization boundary;
9. preserve offline/no-network behavior and `rules/strict-v1.yaml` byte
   identity;
10. stop before opening/merging any rule-profile PR, naming/installing
    `strict-v2`, or recording approval.

## 8. Required automatic verification

Before changing production code, add regressions that demonstrate the current
B1 weaknesses on the pristine closure baseline `76066f620c9f10b8375818ec4811c2624f0f9d1f`:

- inject a competing different final file after the last existence check and
  before the current `os.replace`; prove current B1 overwrites it;
- inject failure/conflict on the second publish after the first succeeds;
  prove current B1 leaves a partial candidate;
- run with a copied base profile under an external active `rules/` root while
  CWD is elsewhere; prove current B1 accepts a candidate destination inside
  that active rule root.

After hardening, prove automatically:

- concurrent different bytes are never overwritten;
- concurrent identical writers converge idempotently;
- second-stage failure returns no completed pair and cleans any safely owned
  prerequisite;
- an orphan candidate without the final materialization record is rejected by
  the pair resolver;
- candidate tampering/hash mismatch is rejected;
- symlink/non-regular finals and output redirection into input/workspace/rules
  roots fail closed;
- external active-rules roots derived from `--base-profile` are refused;
- all existing 40 B1 focused tests remain green;
- socket guards still prove zero network construction;
- strict-v1 bytes remain identical;
- every changed/new persisted contract keeps schema drift parity.

Then run the complete CI-equivalent repository gate. After push, query GitHub
Actions automatically and close R1 only when the required run is `success`
with `head_sha` exactly equal to the implementation commit.

## 9. Manual-intervention policy

No manual owner action is planned for B1-R1.

If and only if a genuinely external authority/environment prevents an
automatic check, record all seven items:

1. exact command/action attempted;
2. exact blocker;
3. exact human action required;
4. exact data/secret boundary;
5. exact resume command;
6. machine-checkable success criterion;
7. exact remaining unverified scope.

Continue every other automatic check. Do not use a vague evidence-not-recorded
placeholder.

## 10. Stop boundary

Stop after publication/path hardening and exact-head CI closure.

Do not create or install `strict-v2`, write an approved profile into active
`rules/`, open/merge a rule-profile PR, record human/GitHub approval or
rejection, mutate `strict-v1`, add provider/Bridge/FQGate scope, add
notification vendors/Windows bootstrap, or add brokerage/trading behavior.

Those remain Phase 7-B2 or separately selected later work.
