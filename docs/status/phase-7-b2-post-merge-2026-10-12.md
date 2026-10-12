# Phase 7-B2 post-merge publication verification — owner-direct-merge record (2026-10-12)

Status: **PUBLISHED / POST-MERGE VERIFIED / OWNER-DIRECT-MERGE**

## 1. What happened

On 2026-10-12T03:36:11Z the repository owner merged
[PR #4](https://github.com/blooddrunk/turtle-value-engine/pull/4) directly
through the GitHub UI as `blooddrunk`, producing merge commit
`595afa47ddeb457b59dd7d491f1ae4b94f8c53d2` (parents `3c3974c` main +
`3203e6e` the verified release head).

This is a real human publication decision performed by the owner. It
supersedes the documented Phase 7-B2-B2 precondition (an `APPROVED` GitHub
review from a reviewer distinct from the PR author before merge) for this
single-owner personal repository: **zero reviews existed at merge time**
(`GET /pulls/4/reviews` length 0), and no approval is synthesized or claimed
by this record. The automation (coding agent) neither submitted a review nor
performed the merge; it only verified the result afterwards, as recorded
below.

## 2. Post-merge publication verification (all machine-checked)

Verified from the Git object database and independently from the GitHub
API at the merge commit:

- Merge commit `595afa4` is a true merge of main `3c3974c` and release head
  `3203e6efaf4c8ae019dfd305388694003037271a` (the exact B2-B1-verified PR
  head at merge time).
- `git diff --name-status 3c3974c..595afa4` is exactly:
  - `A docs/releases/strict-v2/release-candidate.json`
  - `A rules/strict-v2.yaml`
- `rules/strict-v2.yaml` on merged main:
  SHA-256 `adba44b799fdb42a6e443d55891dd3262842aee1dbc441e823b2a3155396dd7d`
  — equal to the release manifest `release_profile_sha256`, to the committed
  PR-head blob, and byte-identical (`cmp`) to the fresh isolated
  authoritative reproduction retained from B2-B1.
- `docs/releases/strict-v2/release-candidate.json` on merged main: file
  SHA-256 `604226f405fe03303e45f16e416b68ce4dd27b51f5db260095116e3b356f250d`,
  manifest content SHA-256
  `c0d6cb5b60595c8eb67d45735fc8ef05a9a13b6db0f90bf3468f635ec99c61e8`,
  byte-identical to the fresh reproduction.
- `rules/strict-v1.yaml` unchanged:
  `e3618f78b2f8e4d1e8e81ce3065da977685ad5256bd0ab3332b3a8054e0b6333`.
- `config/project.example.toml` unchanged (`9c621217285ade015e8537321378c2ad8869ffce1f0665e1e539c3898e45b049`,
  identical to the pre-merge base); `[profiles] default = "strict-v1"` and
  all CLI/loader defaults remain `strict-v1`.
- The merge introduced no source, configuration, CI, dependency or workflow
  change (the two-file diff above is exhaustive); every `strict-v2` mention
  in `src/` is the pre-existing B1/B2-A guard code that *forbids* assigning
  the release name to candidates.
- GitHub contents API at `595afa4` returns the same `rules/strict-v2.yaml`
  hash (`adba44b7…`).
- strict-v2 is **not** the default profile and is **not** applied anywhere:
  publication only adds the versioned profile file.

## 3. CI evidence

- Merge commit: Actions run `38200401199` — workflow `CI`, event `push`,
  status `completed`, conclusion `success`, `head_sha`
  `595afa47ddeb457b59dd7d491f1ae4b94f8c53d2` (exact-head match).
- PR-head run (pre-merge evidence, unchanged): `38195962676` / `success` at
  `3203e6efaf4c8ae019dfd305388694003037271a`.
- Tooling commit: `38195573858` / `success` at
  `85fe69913032da242b50fad872e3d96ee4319c59`.

## 4. Boundary statement

The Phase 7 controlled-evolution chain is complete for strict-v2:
calibration → R2 freeze → admission → B1 materialization → B2-A release →
B2-B1 PR with exact-head CI → owner merge → post-merge verification. The
release manifest's fixed literals (`requires_human_approval=true`,
`automatic_merge_allowed=false`, `automatic_application_allowed=false`)
record the process contract; the human decision was the owner's direct
merge. No automation approved, merged or applied anything, and the default
profile remains `strict-v1`. Making `strict-v2` the default or active
profile is a separate explicit owner decision outside this record.
