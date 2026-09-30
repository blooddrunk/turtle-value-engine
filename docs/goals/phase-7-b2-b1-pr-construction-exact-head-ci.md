# Phase 7-B2-B1 — GitHub PR Construction and Exact-Head CI Gate

Status: **SELECTED / NOT IMPLEMENTED**
Date: 2026-09-30
Selected after: Phase 7-B2-A post-closure review

Selection audit:
`docs/status/phase-7-b2-a-post-closure-review-2026-09-30.md`

Reviewed baseline:
`8a53118a5b16a118b5449297f61abbd9855f3263`

Coding-agent handoff:
`docs/status/phase-7-b2-b1-next-coding-agent-goal.md`

## 1. Objective

Construct the real GitHub pull request that publishes the exact Phase 7-B2-A
release as strict-v2, and automatically close every machine-verifiable gate up
to—but not including—the human approval decision.

B2-B1 is an operational publication package, not a new investment-semantic
feature. Prefer existing TVE release primitives plus git/GitHub automation over
adding runtime dependencies or a general GitHub client to the engine.

At B2-B1 completion:

- one real PR against main exists;
- its head contains the exact reproduced strict-v2 bytes and immutable release
  manifest only;
- all required CI/checks are successful for the exact current PR head SHA;
- the PR is ready for an eligible human reviewer;
- no approval has been synthesized and no merge has happened.

## 2. Source of truth

Read and follow, in order:

1. `AGENTS.md`
2. `docs/status/phase-7-b2-a-post-closure-review-2026-09-30.md`
3. `docs/status/phase-7-b2-a-2026-09-30.md`
4. `docs/goals/phase-7-b2-a-versioned-profile-release-bundle.md`
5. `docs/architecture/candidate-profile-materialization.md`
6. `src/turtle_value_engine/evolution/profile_release.py`
7. `src/turtle_value_engine/evolution/release_pair.py`
8. `src/turtle_value_engine/evolution/materialize.py`
9. `src/turtle_value_engine/backtest/calibration_freeze.py`
10. `rules/strict-v1.yaml`

Preserve every Phase 7-A/R1/R2, B1/R1 and B2-A authority, chronology, replay,
immutability and no-silent-application invariant.

## 3. Inputs and authoritative reproduction

Do not accept a B2-A release manifest as bearer authority.

The task must have access to:

- the complete B2-A release profile and release manifest;
- the source B1 candidate and materialization pair;
- authoritative calibration workspace;
- exact frozen manifest, experiment, holdout and observations;
- exact base profile bytes;
- Git repository and authenticated GitHub remote capable of branch/PR actions.

Before any remote mutation:

1. resolve the supplied complete B2-A release bundle;
2. resolve the source B1 pair;
3. rerun authoritative R2 admission from the calibration workspace;
4. rerun B1 materialization;
5. rerun B2-A release projection/publication into a fresh isolated temporary
   location;
6. require exact byte equality of both reproduced release files with the
   supplied B2-A release files;
7. require the release manifest target to be exactly rules/strict-v2.yaml;
8. require rules/strict-v2.yaml absent from the selected main baseline;
9. require strict-v1 exact bytes/hash unchanged from the B2-A closure evidence.

Any mismatch must stop before branch creation or push.

## 4. Branch and commit contract

Refresh the remote main branch immediately before branch creation and pin the
exact base SHA. If main moved after the selected planning baseline, re-run all
authority and collision checks against the new base instead of silently using
stale assumptions.

Use a deterministic release branch name derived from target profile plus release
identity. If that branch already exists:

- resume it only if its ancestry and publication blobs match the expected
  release exactly;
- otherwise fail closed; never force-push over foreign or ambiguous history.

The release commit must contain exactly these publication changes:

- `rules/strict-v2.yaml` = exact reproduced release-profile bytes;
- `docs/releases/strict-v2/release-candidate.json` = exact reproduced B2-A
  release-manifest bytes.

Do not edit strict-v1, default-profile configuration, application code, CI,
dependencies or unrelated docs in this PR.

After commit, verify from the Git object database—not just the working tree—
that both committed blobs are byte-identical to the reproduced release bundle.

## 5. Pull request contract

Open or resume exactly one PR from the release branch to main.

The PR body should surface machine-verifiable review facts:

- target profile id/path;
- release candidate id;
- source materialization id/content hash;
- release profile SHA-256;
- release manifest content SHA-256;
- base main SHA and PR head SHA;
- statement that requires_human_approval=true;
- statement that automatic merge/application are forbidden;
- concise instructions for reviewing the two publication files.

Do not rely on PR-body text as authority; all facts must be re-derived from the
committed bytes and GitHub metadata.

Immediately after PR creation/resume:

1. query PR metadata and require base branch main;
2. require current PR head SHA equals the verified release commit;
3. fetch changed filenames across all pages and require the exact two-file
   allowlist;
4. compare base/head and prove strict-v1 has no diff;
5. prove no default-profile/configuration file changed;
6. fetch the committed strict-v2 blob from the PR head and require its SHA-256
   equals release_profile_sha256;
7. fetch the committed release-candidate JSON and validate the full model/hash
   contract again.

## 6. Exact-head CI gate

Run the repository's complete local CI-equivalent gate before push when the
environment supports it, then query GitHub after push.

GitHub closure evidence must be tied to the exact current PR head SHA. Poll
until all required runs/checks are terminal. Fail closed on failure,
cancellation, missing required checks or head movement.

Record at least:

- PR number and URL;
- PR base SHA and current head SHA;
- every relevant Actions run id/name/event/status/conclusion/head SHA;
- release candidate id;
- release profile SHA-256;
- release manifest content SHA-256;
- exact changed-file list;
- strict-v1 unchanged proof.

Stale green CI for an earlier branch commit does not count. If the PR head
changes, repeat blob/diff/hash checks and CI verification for the new head.

## 7. Reviewer gate preparation

After exact-head CI is green, request an eligible human reviewer if the
authenticated GitHub identity has permission to do so.

The selected reviewer must be a real human account and must not be the PR
author. Preflight and record the PR author plus intended reviewer identity.

B2-B1 must NOT:

- submit an APPROVED review itself;
- treat a comment, issue label, local file, CLI flag, commit message or agent
  assertion as approval;
- enable auto-merge;
- merge the PR.

If no distinct authorized human reviewer is currently available, B2-B1 may
still finish its machine gates and report the exact reviewer-access blocker,
but it must clearly mark that B2-B2 cannot begin until an eligible reviewer
exists and approves the exact head.

## 8. Required automatic verification

Automate at least these cases/invariants:

1. supplied B2-A bundle resolves cleanly;
2. fresh authoritative R2 -> B1 -> B2-A replay reproduces exact profile AND
   manifest bytes;
3. foreign/stale/tampered bundle fails before remote mutation;
4. strict-v2 already present on main fails closed;
5. existing release branch with foreign ancestry/content is never overwritten;
6. release commit contains only the two allowed publication files;
7. committed Git blobs equal the fresh release bytes exactly;
8. PR base/head identities are exact;
9. GitHub changed-file list is exactly the allowlist;
10. strict-v1 bytes/hash and default-profile configuration are unchanged;
11. PR-head strict-v2 hash equals manifest release_profile_sha256;
12. checked-in release manifest validates and its content hash is correct;
13. local CI-equivalent gate is green when executable;
14. GitHub CI/checks are green for the exact current PR head SHA;
15. auto-merge remains disabled and PR remains unmerged;
16. no approval is created by automation.

Use automatic assertions and GitHub API/CLI reads wherever possible. Do not
replace any of these with screenshots or prose-only claims.

## 9. Manual-intervention policy

No manual action is planned during B2-B1. The deliberately manual decision is
the APPROVED review after B2-B1 completes.

If an external GitHub permission/environment limitation prevents one B2-B1
automatic action, complete all other checks and document ALL seven items:

1. exact command/API action attempted;
2. exact blocker/error;
3. exact human action required;
4. exact secret/data boundary;
5. exact resume command/action;
6. machine-checkable success criterion;
7. exact remaining unverified scope.

Never use phrases such as evidence not fully recorded without the seven-field
intervention packet.

## 10. B2-B1 closure criterion

B2-B1 is complete only when:

- a real open PR exists against main;
- the exact two-file publication diff is proven;
- strict-v2 and release-candidate bytes/hashes match fresh authoritative
  reproduction;
- strict-v1/default configuration are unchanged;
- required CI/checks are successful for the exact current PR head;
- reviewer eligibility is known/requested where possible;
- PR is not approved by automation and is not merged.

Return/record the exact PR URL, PR number, base SHA, head SHA, release hashes and
CI evidence needed for the human review and later B2-B2 resume.

## 11. Stop boundary

Stop before human approval and merge.

Do not change the default profile, automatically apply strict-v2, mutate
strict-v1, add provider/Bridge/FQGate or notification/Windows work, or add
brokerage/trading scope.

Phase 7-B2-B2 is the later package that consumes a real human GitHub APPROVED
review for the exact B2-B1 head, revalidates all remote authority, merges, and
performs post-merge publication verification.
