# Goal: Phase 7-C4-D — Readiness summary identity contract decision (conditional)

**Selected by:** [R3 independent post-closure review](../status/phase-7-c4-c-r3-post-closure-review-2026-10-29.md). Phase 7-C4-C-R3 is accepted/CLOSED. C4-D is a narrow **identity/consumer-contract clarification, not a pre-authorized v2 implementation**. Treat the v1 collision as a *demonstrated property* but **not an automatically established defect requiring redesign**.

## 0. Synchronize newest source before ANY action

```bash
git status --short
git fetch origin --prune
git switch main
git pull --ff-only origin main
git rev-parse HEAD
git log -8 --oneline
```

Preserve a dirty worktree in a dedicated branch/worktree; never silently reset/discard/stash. Inspect current open PRs, issues, recent commits and this selection PR; if this docs PR is still open, review its *exact final head* CI before merging, or read this goal from its review branch, reconciling against actual latest main. **Do not assume the October 29 review SHA is still main.** Read `AGENTS.md`, `docs/spec/`, the C4-C/R1–R3 goals and status docs, the owner-readiness handoff manual, the v1 schema, `src/turtle_value_engine/evolution/owner_readiness.py`, CLI parser/handlers, `tests/test_owner_readiness_summary*.py`, `docs/roadmap.md`, and affected consumers. Use a new isolated feature branch.

## 1. Questions and existing evidence

`summary_id` presently hashes a selected *observed core*: published profile/manifest identities+hashes, plan id/content hash, activation store **status**, project-config SHA, and journey state. It omits store problems, guidance and presentation text. `content_sha256` hashes the full canonical summary payload excluding the hash field itself. `OwnerReadinessSummaryV1` validates the latter self-hash. R1's existing real regression `test_diagnostic_summary_id_shared_across_distinct_store_problems` verifies two different corrupt-store observations with the **same `summary_id`**, but **different problems and content hashes**.

Determine the intended meaning and user expectations of each field. Is `summary_id` a durable/coarse observed-core grouping/replay ID, while `content_sha256` is the exact projection discriminator? Does any real local, dashboard, store, CLI automation, or other consumer deduplicate/cache/authorize on `summary_id` alone? Search exact usages and document absence where bounded; **never claim to prove no external consumers exist**.

Avoid conflating semantic ID, same-jou​rney grouping, a stable fingerprint of material decision facts, exact projection equality and cryptographic authority. Never use an informational summary as owner permission.

## 2. Tests-first characterization (must NOT invent a failure)

1. On a pristine newest main, run the existing R1 diagnostic unchanged and capture exact output. Add pure/disposable characterization controls for (a) byte-identical replay => equal `summary_id` and `content_sha256`, (b) changed store problems with same status => equal `summary_id` but changed `content_sha256`, (c) presentation-only text/CLI-path effects when safely observable => clear id vs content behavior, (d) meaningful core identity change => different `summary_id`, (e) model validation rejects a tampered full projection with stale self-hash, (f) read-only execution performs no writes, network or authentication mutation. Clearly distinguish old established tests from new probes.
2. Inspect actual schema/model validation and identify gaps in *documentation or consumer assumptions*, not speculative security defects. Inventory both repo-local and configured consuming surfaces by source path, exact usage and expected interpretation; include stdout and CLI library callers, any persisted store, operator docs and dashboards. Report any consumer you cannot inspect as unknown, not absent.
3. Write a **decision table** covering at least: keep existing v1 semantic/core ID + existing exact hash; correct a demonstrated consumer that needs full-projection identity; or introduce a separately versioned opt-in v2. Explicitly evaluate benefits, downsides, compatibility risk, hash cycles, schema/CLI rollout and what would trigger each option.

## 3. Mandatory decision gate

**Default / preferred if no demonstrated broken consumer:** select **v1 semantic-core ID + `content_sha256` exact-content identity**. Deliver a precise normative explanation in the owner-readiness manual and appropriate schema/model documentation, plus characterization tests that describe—not change—the deliberately distinct roles. Keep `owner_readiness_summary_v1`, `schema_version=1.0.0`, existing field names, every ID/hash byte, validator algorithm, 11 journey states, read-only next-step commands and the existing R1 collision diagnostic unchanged. Update a focused status decision record. Do not implement v2 just because the ID is not a full-projection hash.

**If a real existing consumer bug is reproduced:** write a failing consumer-level regression on untouched baseline, then correct **only that consumer** to use a deliberately specified exact-content key (or a pair `(summary_id, content_sha256)` if grouping + exact variant is necessary), plus an isolated compatibility test. Do not alter v1 ID. If this cannot be bounded, stop and write a separate future goal.

**Only if clear external/persisted consumer requirements invalidate both paths:** produce *design-only* ADR/contract and a separately scoped future implementation goal for an **additive, opt-in, versioned v2**; do NOT ship a runtime v2 in C4-D. Design must specify canonical ID derivation without self-reference, independent full projection hash, v1/v2 output coexistence, selected CLI flag/default, schema drift parity, serialization and migration semantics, and why changed hint text should/should not change identity. Formal user approval would be required for a breaking default/semantic change; don't assume it.

## 4. Verification automation and protected boundaries

Run automatically from a clean, synchronized worktree:

```bash
python -m pytest tests/test_owner_readiness_summary_r1_probes.py tests/test_owner_readiness_summary_r2_probes.py tests/test_owner_readiness_summary_r3_probes.py tests/test_owner_readiness_summary.py -q
python -m ruff check .
python -m turtle_value_engine config validate --input config/project.example.toml
python -m pytest -q
```

Add and run new focused tests for the chosen path **twice**, validate checked-in schema/model parity and no writes/network by whole-tree snapshots and socket guards, run the *current* `.github/workflows/ci.yml` full matrix (systemd, pnpm frozen install, OpenAPI/Types, Dashboard lint/typecheck/test/build, client secret scan, Wrangler dry-run and cross-stack smoke). Do not assume test totals remain 7,555/2 skipped: that is R3's last verified baseline, not a guarantee. The AKShare opt-in live tests are deliberately allowed to skip, with the skip condition `TVE_RUN_AKSHARE_LIVE=1` recorded.

Verify byte-for-byte blob identity for:
- `rules/strict-v1.yaml` baseline `e34f4ca0`;
- `rules/strict-v2.yaml` baseline `0e75b02e`;
- `docs/releases/strict-v2/release-candidate.json` baseline `ded56064`;
- `config/project.example.toml` baseline `a9cff0de`.

No strict-v2 approval/default/activation; no owner signing keys, trust-root mutation, real decision, `--apply`, rollback, provider network, market data, model-dependent investment math or trading. Disposable fixtures only. **No manual engineering test is anticipated.** If a gate cannot run, record exact command, environment/error, observed vs expected, source of evidence, blocker status and responsible CI gate; no vague "evidence incomplete". Actual real owner policy review/signature/activation is a separately authorized human workflow and is not part of this task.

## 5. Deliverable and PR rules

Prefer a minimal docs + tests PR, with no runtime changes unless a precisely reproduced consumer bug mandates a bounded correction. Produce `docs/status/phase-7-c4-d-YYYY-MM-DD.md` including baseline SHA; consumer inventory; characterization results and unchanged diagnostic; explicit decision; actual commands/output; test/CI evidence; protected blob hashes; and remaining unknown external consumers. Document a *non-selected* v2 design only if truly justified.

Check changed files and exact final PR-head commit; obtain GitHub Actions success **at that SHA** before merging. Re-run if head changes; then confirm merged-main commit and Actions success. Never merge on stale CI or bypass a real failing gate. If a new bug is disproven, close the bounded task as documented behavior rather than manufacturing new code. End by stating if further Phase 7 work is actually needed, or whether to stop and wait for a real owner policy decision.
