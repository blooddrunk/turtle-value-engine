# Coding-agent handoff — Phase 7-B2-B1 PR Construction and Exact-Head CI Gate

Status: **READY FOR HANDOFF**
Date: 2026-09-30

Canonical goal:
`docs/goals/phase-7-b2-b1-pr-construction-exact-head-ci.md`

Selection audit:
`docs/status/phase-7-b2-a-post-closure-review-2026-09-30.md`

Reviewed baseline:
`8a53118a5b16a118b5449297f61abbd9855f3263`

## Handoff

goal

Execute Phase 7-B2-B1 — GitHub PR Construction and Exact-Head CI Gate for blooddrunk/turtle-value-engine.

Read and follow, in order:
1. AGENTS.md
2. docs/status/phase-7-b2-a-post-closure-review-2026-09-30.md
3. docs/goals/phase-7-b2-b1-pr-construction-exact-head-ci.md
4. docs/status/phase-7-b2-a-2026-09-30.md
5. docs/goals/phase-7-b2-a-versioned-profile-release-bundle.md
6. docs/architecture/candidate-profile-materialization.md
7. src/turtle_value_engine/evolution/profile_release.py
8. src/turtle_value_engine/evolution/release_pair.py
9. rules/strict-v1.yaml

Preserve all Phase 7-A/R1/R2, B1/R1 and B2-A closures. This task is the
fully-automatable half of the remote publication boundary. Do not start B2-B2.

Mission:
- use the complete B2-A release bundle plus the authoritative R2/B1 inputs;
- before any branch/push, rerun authoritative admission, B1 materialization and
  B2-A release generation in a clean temporary location;
- require exact byte equality of BOTH the regenerated release profile and
  release manifest with the supplied B2-A bundle; release.json is not bearer
  authority;
- refresh main and pin the exact base SHA; if main moved, rerun collision and
  authority checks against the new base;
- require rules/strict-v2.yaml absent on main and strict-v1 bytes/hash unchanged;
- create or safely resume a deterministic release branch without force-pushing
  over foreign history;
- commit exactly two publication files: rules/strict-v2.yaml and
  docs/releases/strict-v2/release-candidate.json, each byte-identical to the
  freshly reproduced B2-A outputs;
- read both blobs back from the Git object database and re-hash/revalidate them;
- open or resume exactly one PR to main;
- query GitHub for PR metadata and changed filenames; require the exact two-file
  allowlist and prove no strict-v1/default-profile/configuration change;
- run the local CI-equivalent gate where executable, push, then poll GitHub
  Actions/checks automatically until the exact current PR head SHA is terminal
  and successful; stale green runs do not count;
- record PR number/URL, base SHA, head SHA, release candidate id, release profile
  SHA-256, release manifest content SHA-256, exact changed-file list and every
  relevant CI run id/conclusion;
- request an eligible real human reviewer if permitted, but do NOT approve,
  enable auto-merge or merge the PR;
- preflight reviewer eligibility: the intended approver must be distinct from
  the PR author.

Automatic verification is mandatory. Fail closed before remote mutation on any
authority/hash mismatch. Fail closed before merge on any PR/head/diff/CI
ambiguity. Prefer GitHub API/CLI reads and machine assertions over prose or
screenshots.

Do not add a general GitHub runtime dependency to TVE unless strictly necessary.
If tooling changes are genuinely required, land and verify them separately from
the two-file strict-v2 publication PR so the human review remains focused on
the exact release bytes and provenance manifest.

No manual action is planned inside B2-B1. If GitHub authentication/permission
prevents one automatic action, complete everything else and report ALL seven:
1. exact command/API action attempted;
2. exact blocker/error;
3. exact human action required;
4. exact credential/data boundary;
5. exact resume command/action;
6. machine-checkable success criterion;
7. exact remaining unverified scope.
Never write a vague evidence-not-recorded placeholder.

Stop boundary:
Stop when the real PR is open, its exact two-file diff/hashes are proven and all
required CI/checks are green for its exact current head SHA. Do not submit an
APPROVED review, do not merge, do not change the default profile, do not apply
strict-v2 automatically, do not mutate strict-v1, and do not add unrelated
provider/Bridge/FQGate, notification/Windows or brokerage/trading scope.

Return the exact PR URL/number, base/head SHAs, release hashes and CI evidence so
the human reviewer can approve the exact head and Phase 7-B2-B2 can later
verify that real approval, merge and perform post-merge publication checks.
