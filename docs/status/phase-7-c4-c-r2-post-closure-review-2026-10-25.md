# Phase 7-C4-C-R2 — Independent post-closure review (2026-10-25)

**Disposition:** ACCEPT R2 within its two explicitly scoped fixes. The exact PR-head, merged-main and latest closure-main CI all passed. Do **not** re-open the safe copy boundary or the two-write disclosure. An additional, independently identified *operator guidance / CLI argument-compatibility* problem warrants a narrow **Phase 7-C4-C-R3** before any summary identity migration. No owner decision, authorization or activation is implied.

## 1. Exact evidence, repository state and limits

- Repository: blooddrunk/turtle-value-engine. Reviewed main: **51106bdfdb23b2c474bbe867847f50510429e6ae** (2026-10-25T14:11:54Z, post-merge R2 evidence commit). This SHA is the *reviewed* base, not a fixed development base; a future agent MUST synchronize latest origin/main before working.
- Implementation: [PR #36](https://github.com/blooddrunk/turtle-value-engine/pull/36), final head **5e240944e9b3d36a1d040fab03e2ecbfba68cc95**; exact-head [run 40199308181](https://github.com/blooddrunk/turtle-value-engine/actions/runs/40199308181) completed **success**.
- Merged as **f11dcea82d13fe67c43819748378a6e543f947ce**; merged-main [run 40200117465](https://github.com/blooddrunk/turtle-value-engine/actions/runs/40200117465) completed **success**. Post-closure main **51106bd** [run 40201106329](https://github.com/blooddrunk/turtle-value-engine/actions/runs/40201106329) completed **success**, exact head SHA verified.
- Independently inspected the latter run's job steps and raw log: **7,543 passed / 2 skipped / 9 warnings** in Python; **55 Dashboard tests passed**; Ruff, config validation, systemd, OpenAPI, generated TS types, lint/typecheck/build, client bundle security scan, Wrangler dry-run and cross-stack smoke passed.
- GitHub compare from **4e0097577a157a282cd4ddc87d1dd189a6b7e7a5** to **51106bd** lists exactly five expected files: `docs/operations/owner-readiness-handoff.md`, `docs/status/phase-7-c4-c-r2-2026-10-25.md`, `src/turtle_value_engine/evolution/owner_readiness.py`, `tests/test_owner_readiness_summary_r1_probes.py`, `tests/test_owner_readiness_summary_r2_probes.py`. No executor, activation status, schema, rule, release manifest or config template changed.
- Scope reviewed through connected GitHub source and Actions; this environment could not resolve github.com for a local checkout. **No independently executed local repository pytest or CLI replay is claimed.** GitHub CI is direct remote execution evidence; the new R3 finding below is an independently source-confirmed parser mismatch to be tests-first reproduced by the implementing agent.

## 2. R2 acceptance: two repairs confirmed

1. **Literal copy boundary:** in `_next_steps_zh`, all executable command-bearing hints end at the quoted command after the last full-width colon, with no external terminal `。`. The `shlex.join` argv encoder is unchanged; a genuine `。` in a quoted filename is retained. The R1 extractor no longer silently strips punctuation. New R2 probes cover raw literal tails, stub argv, hostile paths, 11 journey states, real read-only CLI replay and zero-write/no-network boundaries.
2. **Write-step accuracy:** `decision-dossier --output` and `plan-activation --output` are explicitly described as *separate* optional writing actions, both with an operator-selected output path and neither advertised as a paste-ready read-only command. The erroneous claim “唯一写文件步骤” has been removed.

No claim of a policy approval, new real signature, private configuration change or strict-v2 activation is made. The strict-v1 default remains unchanged.

## 3. New finding F1 (P2): plan export guidance claims incompatible arguments

Source: `src/turtle_value_engine/evolution/owner_readiness.py::_next_steps_zh`, both branches of `plan_activation_step` (currently emitted in the `ACTIVATION_BLOCKED` journey). They ask operators to pass inputs **“与上述重放命令完全相同的输入”** / **“与本次 readiness-summary 完全相同的全部输入”** to `tve evolution plan-activation`, plus `--output`.

Source comparison in `src/turtle_value_engine/cli.py`:

- `readiness-summary` accepts optional `--activation-root` to inspect the activation store and include it in exact retry hints.
- `plan-activation` does **not** accept `--activation-root` at all. It requires `--decision-record` and `--output`. It additionally accepts reference inventory flags (`--watchlist` / `--normalized-input` / `--backtest-manifest` / `--surface-snapshot` / `--runner-config`) not exposed by `readiness-summary`.
- Therefore copying all options from a readiness-summary replay that includes `--activation-root` into a plan-activation invocation cannot pass the plan parser. Even after dropping that flag, the summary's inputs are **not necessarily a complete activation-plan inventory**, so guidance must not promise the same full plan by blind option reuse.
- The R2 F2 probes check disclosure of `--output` and that writers stay prose; they do not check compatibility between command-specific option sets. This is a *new scope*, not a failure of R2's documented two narrow repairs.

**Impact:** misleading instructions and a likely parser-exit-2 during an optional export step; no known authorization bypass or automatic write. The operator still explicitly chooses `--output`, so this is not a zero-write/read-only breach. Confirm the exact argument failure through safe parser-only tests in R3 (do not execute a writer).

## 4. Deferred issue: summary identity, not part of R3

`summarize_owner_readiness` currently derives `summary_id` from profile/manifest identities, plan identity/content, `store.status`, config SHA and journey; it does **not** bind `activation_store_problems` or guidance. The R1 diagnostic `test_diagnostic_summary_id_shared_across_distinct_store_problems` demonstrates distinct projections with equal `summary_id` but different `content_sha256`. The content self-hash distinguishes the outputs; this is not evidence of an authority bypass. Do not silently reinterpret `owner_readiness_summary_v1`; the next **separate** phase after R3 must first decide the semantic-vs-full-projection identity contract, compatibility for persisted v1 outputs, the versioned schema/CLI exposure and consumer deduplication key, and only then choose whether to introduce an opt-in v2. Preserve the old diagnostic unchanged through R3.

## 5. Selected next action

[Phase 7-C4-C-R3 — Plan Export Argument Compatibility and Operator Handoff](../goals/phase-7-c4-c-r3-plan-activation-argument-parity.md).

Tests-first minimal hint/manual correction, with argument-set proof against the real CLI parser; run every existing R1/R2/C4 readiness/owner regression plus complete CI, exact final PR-head CI and merged-main CI. No actual writing command needs to be executed to prove this guidance repair; parser-only tests and read-only/stub probes suffice. No human engineering step, no real owner signature or activation.
