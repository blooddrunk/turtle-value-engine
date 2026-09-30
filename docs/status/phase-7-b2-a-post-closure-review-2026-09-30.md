# Phase 7-B2-A post-closure review — remote publication readiness

Status: **B2-A CLOSURE PRESERVED / PHASE 7-B2-B1 SELECTED**
Date: 2026-09-30

Reviewed implementation:
`726e47bfde6b24ff6ece9df9622c9d55a922c141`

Closure commit:
`8a53118a5b16a118b5449297f61abbd9855f3263`

Implementation CI:
`36695960818` — CI / push / completed / success / exact implementation head SHA.

Closure-commit CI:
`36696507634` — CI / push / completed / success / exact closure-commit head SHA.

Selected next package:
`docs/goals/phase-7-b2-b1-pr-construction-exact-head-ci.md`

## 1. Verdict

Phase 7-B2-A remains correctly CLOSED. Independent review found no B2-A-R1
blocker that should delay the first GitHub publication step.

The implementation preserves the intended authority split:

- the supplied B1 candidate/materialization pair is resolved but is not treated
  as bearer authority;
- the authoritative R2 freeze/binding is resolved from the calibration
  workspace, controlled-evolution admission is rerun, and B1 materialization
  is reproduced in memory before release projection;
- exact candidate bytes, candidate hash, materialization id and
  materialization content hash must agree with that fresh reproduction;
- only the next strict lineage is accepted;
- the candidate-to-release rule payload is unchanged and the base-to-release
  scalar rule diff must equal the authoritative B1 rule changes;
- the release manifest fixes human-approval-required / no-auto-merge /
  no-auto-application semantics;
- publication is immutable prerequisite-first / manifest-last and the
  read-only resolver rejects incomplete, symlinked, tampered or hash-mismatched
  bundles;
- B2-A writes no active rule, creates no GitHub client and leaves strict-v1
  unchanged while strict-v2 remains absent on main.

Both the implementation commit and the later documentation closure commit have
successful exact-head CI runs. There is therefore no reason to reopen B2-A.

## 2. Important authority observation for the next phase

The B2-A release bundle is deterministic and internally hash-validated, but its
hashes are not a signature and the release manifest is not a remote approval.
B2-B must not treat release.json alone as authorization to publish strict-v2.

Before any branch or pull request is created, the next phase must freshly
reproduce the B2-A release from the authoritative R2/B1 evidence and require
byte-for-byte equality of BOTH the release profile and release manifest with
the supplied B2-A bundle. A stale, foreign or merely self-consistent release
bundle must fail closed before remote mutation.

## 3. Split B2-B around the unavoidable human authority

Keeping branch creation, CI polling, human review, merge and post-merge
verification in one coding-agent run would create an artificial wait point and
encourage vague partial-closure language. Split the remaining B2 boundary:

- **Phase 7-B2-B1 — PR Construction and Exact-Head CI Gate** is selected now.
  It is intended to be fully automated. It reproduces B2-A authority, creates
  the real release branch/commit/PR, proves the PR diff and hashes, polls CI to
  success for the exact PR head SHA, requests an eligible human reviewer, and
  then stops before approval or merge.
- **Phase 7-B2-B2 — Human Approval Verification, Merge and Post-Merge
  Publication** follows only after the real GitHub review exists. It verifies
  the reviewer and approval against the exact current PR head, then performs
  merge and post-merge publication verification automatically.

This leaves exactly one intentionally human act between the two packages:
submit a real GitHub APPROVED review on the exact B2-B1 PR head.

## 4. B2-B1 repository mutation contract

B2-B1 should create or resume one deterministic release branch from the exact
selected main baseline. Before the first push it must prove that main contains
no rules/strict-v2.yaml and that the target branch is not being reused for
different bytes.

The PR change set should be intentionally tiny and machine-allowlisted:

1. `rules/strict-v2.yaml` — byte-for-byte equal to the freshly reproduced
   B2-A release profile;
2. `docs/releases/strict-v2/release-candidate.json` — byte-for-byte equal to
   the freshly reproduced immutable B2-A release manifest.

No strict-v1 edit, default-profile change, code change, workflow change,
dependency change or unrelated documentation change belongs in the publication
PR. If implementation of a reusable helper becomes genuinely necessary, land
and verify that helper separately before constructing the release PR rather
than mixing tooling changes with the rule publication decision.

## 5. Required B2-B1 automatic checks

At minimum, automate all of the following:

1. refresh main and pin the exact base SHA before branch creation;
2. resolve the supplied complete B2-A bundle;
3. rerun the authoritative R2 admission, B1 materialization and B2-A release
   generation in an isolated temporary directory;
4. require exact profile bytes and exact manifest bytes to match the supplied
   B2-A bundle;
5. require release manifest target path = rules/strict-v2.yaml and re-check all
   manifest model/hash invariants;
6. require strict-v1 bytes/hash to match the B2-A closure baseline;
7. create/resume a deterministic branch without force-pushing over foreign
   history;
8. commit only the two allowlisted publication files;
9. after commit, read the two blobs back from Git and re-hash them; do not trust
   the working tree alone;
10. open or resume exactly one PR against main and require its head SHA to equal
    the verified commit;
11. fetch changed filenames from GitHub and require the exact allowlist above;
12. compare the PR base/head and prove strict-v1 plus all default-profile
    configuration remain unchanged;
13. poll GitHub Actions/checks automatically until the exact PR head is
    completed and successful; stale green runs from another SHA do not count;
14. record PR number/URL, base SHA, head SHA, release candidate id, release
    profile SHA-256, manifest content SHA-256 and exact CI run ids/conclusions;
15. request an eligible human reviewer if credentials permit, but never submit
    or synthesize the approving review;
16. leave auto-merge disabled and do not merge in B2-B1.

## 6. Human boundary after B2-B1

The later human review is not a generic acknowledgement. The reviewer must
inspect the actual PR and submit GitHub's APPROVED review for the exact head SHA
reported by B2-B1. The PR author is not an eligible approving reviewer, so the
workflow must preflight reviewer eligibility and use an authorized human account
distinct from the PR author.

No secret, private dataset or local credential value needs to be exposed to the
reviewer. The review scope is the two-file PR plus the provenance and CI
evidence surfaced in the PR.

B2-B2 must later re-query GitHub and verify at least: current PR head SHA,
review state APPROVED, approval commit/head identity, reviewer identity and
eligibility, absence of a later conflicting review/head update, release hashes,
and current CI success before merge.

## 7. Manual-intervention policy

No manual owner action is planned inside B2-B1 itself. The approval belongs
between B2-B1 and B2-B2.

If GitHub authentication, branch push, PR creation, reviewer request or CI
visibility cannot be automated in the coding-agent environment, do every other
check first and emit ALL seven fields below instead of a vague status:

1. exact command/API action attempted;
2. exact external blocker and returned error;
3. exact human action required;
4. exact credential/data boundary;
5. exact resume command/action;
6. machine-checkable success criterion;
7. exact remaining unverified scope.

Do not call B2-B1 complete while one of its automatic remote checks is merely
assumed.

## 8. Stop boundary

Stop B2-B1 only after the real PR exists and all required CI/checks are green
for its exact current head SHA, with the changed-file/hash invariants recorded.

Do not approve the PR, merge it, change the default profile, automatically apply
strict-v2, mutate strict-v1, expand providers/Bridge/FQGate, add notification or
Windows-bootstrap work, or add brokerage/trading behavior.

Human approval verification, merge and post-merge publication belong to
Phase 7-B2-B2.
