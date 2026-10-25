# Independent Phase 7-C4-A-R5 post-closure review (2026-10-25)

**Disposition: ACCEPTED at the declared engineering boundary.** Phase 7-C4-A-R5, C4-B and C4-B-R1 remain CLOSED. Do not invent R6 without a fresh, reproducible failure. This review neither accepts a real owner's policy choice nor authorizes strict-v2 activation.

## 1. Exact source and independent evidence

- Reviewed `main` at `0542cfd29a4419e752d822b8b3c9c7aea682c360` (GitHub merge of [PR #30](https://github.com/blooddrunk/turtle-value-engine/pull/30)); PR head `ada7137cda8588f21a44f8d728f23509910e7c3d`, implementation baseline `e60d7b436a0f6bac5788a6e9126324ada29eede8`.
- Exact-head [PR CI run 40094553425](https://github.com/blooddrunk/turtle-value-engine/actions/runs/40094553425): `success` at `ada7137c`. Merge/latest-main [run 40095071386](https://github.com/blooddrunk/turtle-value-engine/actions/runs/40095071386): `success` at `0542cfd`. Inspected both workflow job summaries and their raw logs, not merely the PR description: **7486 Python passed, 2 skipped, 9 warnings**; Dashboard **55 passed**; Ruff, config validation, systemd units, OpenAPI and generated types, lint/typecheck/build, client bundle secret scan, Wrangler dry-run and cross-stack smoke completed successfully.
- Independent commit comparison establishes the tests-first ordering: `e60d7b4...d90d2ae` adds only `tests/test_activation_execution_r5_probes.py` (504 lines); `d90d2ae...ada7137` changes only `src/turtle_value_engine/evolution/activation_execution.py` and adds `docs/status/phase-7-c4-a-r5-2026-10-24.md`. The 15 new probe cases are present in `main`.
- The R5 closure record reports unchanged baseline-red probes twice (**10 failed, 5 controls passed**), then post-fix probes twice (**15 passed**), and 177 focused activation/status cases. These local red/green invocations are **implementer-recorded evidence**, not a claim that this reviewer independently executed those tests.
- A reviewer-local `git ls-remote https://github.com/blooddrunk/turtle-value-engine.git HEAD` failed with `Could not resolve host: github.com`. Consequently no independent local checkout/test replay or baseline-red reproduction is claimed. The GitHub source diff, exact commit comparison and raw Linux CI logs are independently inspected remote evidence.

## 2. Source-level assessment

- `_load_verified_before_image` still verifies the receipt/before-image byte identities, then now catches only `TOMLDecodeError` and `UnicodeDecodeError` and maps them to existing `BEFORE_IMAGE_CONTENT_MISMATCH`; a non-table `profiles` is checked with `isinstance(dict)` instead of an unsafe nested `.get`.
- The prior-hash idempotence branch now calls `_prior_default_in_place`, returning false on malformed UTF-8/TOML or scalar `profiles` and following the pre-existing `ROLLBACK_PRECONDITION_VIOLATED` refusal rather than escaping an unclassified exception. A normal valid prior default still follows exactly the existing `ALREADY_RESTORED`/interrupted-finalization path.
- The new regressions cover malformed, scalar and invalid-UTF-8 hash-consistent forged inputs through library and CLI, no-clobber refusal, plus genuine apply/rollback/idempotence and recovery controls. They do not purport to prove cryptographic owner authorization for a self-consistent forged receipt.
- Current `main` Git tree independently confirms these exact unchanged protected blobs:
  - `rules/strict-v1.yaml` — `e34f4ca00ba822766e05e6ccd48d3398b0245e4a`.
  - `rules/strict-v2.yaml` — `0e75b02e9305415018bb57c9b9fb8418440eb090`.
  - `docs/releases/strict-v2/release-candidate.json` — `ded5606454d3ef0afc1a0fdc0fea937d3c6cc786`.
  - `config/project.example.toml` — `a9cff0de8fbc4e6f510f3ee5e8551f4b89aeaa03`.
  The runtime default remains `strict-v1`. There were no open PRs or open issues at the time of this review.

## 3. Bounded limitations, not reopened defects

- Error text for malformed, hash-identical prior bytes still says “intervening change” even though its hash fields are exact; this is an operator-wording imprecision, **not** an observed data-clobber or silent-success bug. Do not open an R6 on wording alone.
- Receipt content-hash self-consistency is not independent owner authority. `activation-status` is read-only and deliberately does not claim a globally atomic snapshot or freshly revalidate owner consent. No cross-host recovery or automatic rollback has been verified or newly promised.
- The GitHub Actions test result is strong independent **remote** validation, but it does not replace a reviewer-local baseline-red replay. If a future reproducer materially challenges the recorded red/green proof, capture exact clean SHAs and run it on a suitable checkout before any fix.
- The separate human economic-policy gate remains: published `strict-v2` uses a **14% CDC pass threshold** while its S band begins at **12%**. That mismatch requires an explicit owner choice to accept the documented policy exception or reject activation; it is not a CI defect, and no agent may make that choice.

## 4. Next bounded goal

Select [Phase 7-C4-C — Read-only owner readiness summary and handoff](../goals/phase-7-c4-c-read-only-owner-readiness-handoff.md). This is an **operator usability/readiness** slice, not another security-hardening R6 or permission to apply a new profile. Existing `audit-profile`, `decision-dossier`, `activate-profile` preview and `activation-status` remain the sources of truth; the next slice must not duplicate their authority or invent a new approval channel.

**Engineering gate:** automated tests and CI, disposable fixtures, no manual owner intervention. **Owner gate:** a real policy acceptance/rejection, optional signing of a real decision and explicit private apply are separate, optional and must never be automated by the engineering task.
