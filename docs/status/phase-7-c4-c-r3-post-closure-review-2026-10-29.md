# Phase 7-C4-C-R3 — Independent post-closure review (2026-10-29)

**Disposition: R3 ACCEPTED / CLOSED at its bounded operator-guidance scope.**
Do not re-open R3 or silently change the authorization/identity contracts.
Select only [Phase 7-C4-D — Readiness summary identity contract decision](../goals/phase-7-c4-d-readiness-summary-identity-contract-decision.md), a *decision-first, conditional* follow-up. No automatic strict-v2 policy activation, owner decision or trade is authorized by this review.

## 1. Independent evidence and execution boundary

- Reviewed repository `blooddrunk/turtle-value-engine`, `main` at exact **`26dba77b0ce09b578f0d27bc2fe33c1450874b5f`** (2026-10-29 inspection). The additional main commit after R3 merge modifies only `docs/status/phase-7-c4-c-r3-2026-10-28.md`. This SHA is an *audit observation*, not a pinned development base; the next agent MUST fetch/pull newest `origin/main` before work.
- R3 implementation [PR #38](https://github.com/blooddrunk/turtle-value-engine/pull/38), tests-first `94cfbff`, final head **`7e8d1d111463093a06520825250aee6e204f3e9b`**, merge **`d88cc575117d7384a0b3ee200119afda2f638f2b`**.
- Independently fetched the *actual* workflow-run/job metadata, individual step results and **raw job logs**:
  - [PR final-head run 40665405445](https://github.com/blooddrunk/turtle-value-engine/actions/runs/40665405445): completed/success at exact `7e8d1d1`; Python **7,555 passed / 2 skipped / 9 warnings**, Dashboard **55 passed**, client secret scan and cross-stack smoke successful.
  - [Merge-head run 40666947004](https://github.com/blooddrunk/turtle-value-engine/actions/runs/40666947004): completed/success at exact `d88cc57`; **7,555 passed / 2 skipped**, Dashboard **55 passed**, secret scan and smoke successful.
  - [Latest-main run 40668043242](https://github.com/blooddrunk/turtle-value-engine/actions/runs/40668043242): completed/success at exact `26dba77`; **7,555 passed / 2 skipped**, Dashboard **55 passed**, secret scan and smoke successful.
  - Every CI job step (Ruff, config validate, systemd, frozen pnpm, OpenAPI/API/types, lint, typecheck, Dashboard tests/build, secret scan, Wrangler strict dry-run, cross-stack smoke) reports success. The two skipped tests are separately opt-in *live* AKShare tests (`TVE_RUN_AKSHARE_LIVE=1`); they are **not** claimed as passed.
- Independently inspected PR #38's four changed paths: `src/turtle_value_engine/evolution/owner_readiness.py`, `tests/test_owner_readiness_summary_r3_probes.py`, `docs/operations/owner-readiness-handoff.md`, `docs/status/phase-7-c4-c-r3-2026-10-28.md`. No CLI parser, activation executor, authority verifier, Pydantic/schema or rule-profile modification.
- Source review confirmed both `_next_steps_zh` branches (roughly lines 633–664) now disclose that `plan-activation` rejects `--activation-root`, requires a real `--decision-record` and explicit `--output`, writes the selected plan file, and accepts plan-only affected-reference inventory flags not included in `readiness-summary`. Both remain prose-only, preserving the R1/R2 literal-copy read-only command boundary. New R3 tests inspect the real `_build_parser().parse_args()` without dispatching a writer and exercise blocked journeys and unchanged zero-write guards.
- Verified the four protected blob SHA prefixes on present main: `rules/strict-v1.yaml` **`e34f4ca0`**, `rules/strict-v2.yaml` **`0e75b02e`**, `docs/releases/strict-v2/release-candidate.json` **`ded56064`**, `config/project.example.toml` **`a9cff0de`**. Default remains strict-v1; strict-v2 is published but NOT approved/default/applied.
- Reviewer-local `git ls-remote https://github.com/blooddrunk/turtle-value-engine.git HEAD` failed solely with `Could not resolve host: github.com`; **no local checkout or local test run is claimed**. The baseline-red `4 failed / 8 passed` is implementation-agent-recorded evidence, source-reviewed here, *not independently replayed locally*. The exact-SHA GitHub Actions runs above are the separately verified remote execution evidence.
- At selection time the repository had **no open PR and no open issue** (GitHub API reads).

## 2. Independently confirmed residual: two different identities exist on purpose today

The v1 source `src/turtle_value_engine/evolution/owner_readiness.py:863–876` computes `summary_id` from profile/manifest identities and hashes, plan id/content, activation store **status**, observed config SHA and journey state. The ID does **not** include store `problems`/`guidance_zh`, next-step wording, supplied activation-root path or every other projection field.

The *separate* `content_sha256` at :933–935 hashes the canonical serialized complete payload **before** its own hash is appended; `OwnerReadinessSummaryV1.validate_summary` at :275–278 recomputes and validates it. There is no self-hash cycle in v1.

Existing committed regression `tests/test_owner_readiness_summary_r1_probes.py::test_diagnostic_summary_id_shared_across_distinct_store_problems` (roughly :985–1026) constructs two *genuinely distinct* corrupt-store observations with the same store status and decision context, and asserts:
- `activation_store_problems` differ;
- `summary_id` is the **same**;
- `content_sha256` is **different**.

This is **not** evidence of a signature bypass, changed deterministic investment math, loss of full-content hash discrimination, or an active deduplication bug. The current v1 ID is a coarser observed-core/journey identity, **not** a unique identifier for every rendered payload. The schema `schemas/owner-readiness-summary.schema.json` currently does not describe this distinction beyond its field definitions. Repository source/test/docs search did not establish any persisted/deduplicating production consumer of `summary_id`; this does NOT prove external consumers do not exist.

Risk: a *future or external* consumer treating `summary_id` alone as unique full-projection identity can collapse two different observations. The appropriate first action is to decide and document the intended semantic-vs-exact identity contract and consumer keys, not to mutate v1 blindly.

## 3. Selected next action — Phase 7-C4-D (decision-first, conditional)

The next goal must **first** inventory actual and prospective consumers and prove the present v1 behavior with disposable tests, then make an explicit contract decision:

1. **Prefer preserving v1** if it is intentionally a stable coarse/core identity and `content_sha256` already supplies exact-content discrimination. Document exact meanings, replay comparison vs. dedup keys, and demonstrate them in automated characterization tests. No code migration or new v2 merely to make IDs differ.
2. **Only if an actual contract/consumer need is evidenced**, design an *opt-in*, separately versioned v2 with explicit ID semantics, immutable v1 behavior, no hash cycles, schema/model parity, CLI/library coexistence and consumers/migration policy. Do not silently redefine `summary_id` inside `owner_readiness_summary_v1` or flip its diagnostic before selecting the new contract.
3. If a consumer erroneously deduplicates by v1 `summary_id`, prefer a bounded consumer correction to use an explicit exact-content key; prove the bug tests-first before implementation. Do not overexpand into unrelated activation or policy hardening.

**Gate:** fully automatic tests, schema drift parity and full current CI; immutable protected blobs; exact final PR-head CI before merge and merged-main CI afterward. Real human policy approval, a real owner signature/credential, activation, rollback, live provider access and trading remain entirely outside this engineering goal. No manual engineering test is presently necessary. If a gate cannot run, report exact command, error, expected/observed result, whether it blocks merge and which CI gate covers it; never label an unrun gate as green.
