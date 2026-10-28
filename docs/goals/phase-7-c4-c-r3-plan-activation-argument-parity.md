# Goal: Phase 7-C4-C-R3 — Plan Export Argument Compatibility and Operator Handoff

**Selected by:** `docs/status/phase-7-c4-c-r2-post-closure-review-2026-10-25.md`. R2 is merged and accepted, but this independent source review finds one further bounded operator-guidance/CLI-argument mismatch. This R3 is a **small hint-only repair**, not the separately deferred `summary_id` identity-contract phase.

## 0. First: synchronize actual latest code and reconcile existing work

Before **any edits**, execute and record:

```bash
git status --short
git fetch origin --prune
git switch main
git pull --ff-only origin main
git rev-parse HEAD
git log -6 --oneline
```

Never discard a dirty tree: preserve it in a dedicated branch/worktree; no blind reset/stash. Check current open PRs/issues/commits and whether this R3 goal/review PR is merged. If still open, inspect the PR, verify its latest exact-head CI, and reconcile or merge the docs-only PR before implementation when authorized; otherwise fetch the branch and use the goal with correct ancestry. The reviewer saw main `51106bd`, **not a frozen development base**. Read `AGENTS.md`, this goal, R2 status and post-closure review, C4-C/R1/R2 goals, `docs/operations/owner-readiness-handoff.md`, relevant `docs/spec/`, `src/turtle_value_engine/evolution/owner_readiness.py`, `src/turtle_value_engine/cli.py` parser and handlers, and all `test_owner_readiness_summary*.py`.

## 1. Confirmed defect and exact boundaries

`_next_steps_zh` builds two variants of the optional `plan_activation_step` hint. Both variants tell the operator to reuse **all** `readiness-summary` inputs for `plan-activation`, plus `--output`.

Yet the real argparse subcommands differ:

- `readiness-summary`: optional `--activation-root` to inspect status; unlike `plan-activation`, no `--output` and no reference-inventory flags.
- `plan-activation`: **does not** accept `--activation-root`; **requires** at least one `--decision-record` and `--output`; also accepts explicit `--watchlist`, `--normalized-input`, `--backtest-manifest`, `--surface-snapshot` and `--runner-config` (repeatable) as additional reference inputs.
- A readiness replay with `--activation-root` cannot be mechanically copied as plan argv. Merely dropping the root does not prove that a full activation-plan inventory is the same as the informational summary. The handoff prose should teach shared-input reuse and command-specific differences, not overclaim parity.

**Repair only:** optional plan-export **prose** and the Chinese handoff manual, if needed. Continue to disclose both file-writing commands as opt-in and leave every executable read-only hint's literal-copy contract intact. Do **not** generate a runnable plan/write command or silently trigger `--output`.

## 2. Tests-first red evidence (mandatory)

Before changing the production hint strings, introduce a focused `tests/test_owner_readiness_summary_r3_probes.py` based on the real CLI parser (`_build_parser`) and existing R1/R2 fixtures.

1. Reproduce real parser incompatibility **without executing any handler**: build a deterministic valid argv with shared required inputs + decision record + chosen disposable `--output`, and show that appending the readiness-only `--activation-root` raises argparse `SystemExit(2)`; removing it parses successfully. Assert the plan subparser's required `--decision-record`/`--output` and its extra reference flags from actual parser definitions rather than relying solely on a prose search. Never invoke the `plan-activation` handler or write a plan file in this parser probe.
2. Drive a genuine `ACTIVATION_BLOCKED` readiness journey (using existing deterministic fixtures), once with an explicitly supplied `--activation-root` and once without where possible. Assert that **both branches** of the plan-export hint: (a) no longer say “全部/完全相同的输入” without a compatibility qualification, (b) tell the operator explicitly that `--activation-root` is **not** a plan-activation option and must be omitted, (c) require a real decision record and a deliberate `--output` path, (d) distinguish common source options from additional plan-only reference inventory options, (e) say the export writes a chosen file, (f) do not claim the summary's inputs capture all affected references.
3. Confirm the plan-export step remains **prose-only**, never a paste-ready command after the last full-width colon, even with hostile/Unicode input paths. Assert no command-bearing step uses `--output`/`--apply`/rollback, and the literal read-only tails still match the unchanged R2 rules.
4. Add a source-grounded invariant: compare the two parsers' accepted option sets to a documented command-compatibility rule (shared arguments / summary-only / plan-only / plan required). Do not mutate parsers merely to make the prose pass, and do not freeze unrelated parser internals unnecessarily.
5. Preserve the current diagnostic `test_diagnostic_summary_id_shared_across_distinct_store_problems` with its existing expected collision (unchanged and green). Repeat zero-write/no-network/tree-snapshot and no-secret probes for readiness and all advertised executable hints.

Record the baseline commit SHA, exact test command and actual failures for the new *expected guidance* assertions on pristine main (red), while the parser mismatch controls should pass as confirmation of the defect. If a real parser inspection disproves this finding, stop speculative edits and document the conclusion rather than altering implementation. Do not weaken R1/R2 test extractors or expected shell arguments to manufacture green.

## 3. Minimal implementation and accepted behavior

- Change only the two `plan_activation_step` prose variants in `owner_readiness.py` (and scoped manual/test/status files). Clearly separate **shared** inputs (profiles, release manifest, config, optional decision/exception/trust/evidence/lifecycle/boundary inputs, preserving any necessary repetition) from `readiness-summary`-only `--activation-root`. Explicitly tell the operator **not** to pass `--activation-root` to `plan-activation`.
- State that `plan-activation` requires real `--decision-record` and a **user-chosen** `--output`, and that the output **writes a plan file**. The operator must verify any extra affected-reference paths such as `--watchlist` and `--runner-config` separately; a readiness-summary invocation is not a substitute for a complete plan inventory. `plan-activation --help` is the command-specific option authority.
- No generated executable plan-activation or decision-dossier command (even with a guessed `--output`). Leave read-only retry/status/preview commands, `shlex.join`, literal-tail format, paths/order/multiplicity and 11 journey states untouched.
- No source changes to `activation_execution.py`, `activation_status.py`, CLI parser/handlers, policy audit, plan/authorization/verifier, owner trust store, schemas or identity math. This is **not** a versioned contract migration. `owner_readiness_summary_v1`, `schema_version=1.0.0`, field set, `summary_id` algorithm, self-validating `content_sha256`, journey values, fixed authority literals and exit classes stay unchanged (only guidance text and thus resulting content self-hash may differ).
- Keep `rules/strict-v1.yaml`, `rules/strict-v2.yaml`, `docs/releases/strict-v2/release-candidate.json` and `config/project.example.toml` byte-identical. Strict-v1 remains the default; strict-v2 stays published but not approved, not default and not applied.

## 4. Automatic verification and evidence (no manual owner action)

After the minimal repair, run the focused R3 suite **twice green**, existing R2/R1 and C4-C readiness suites, C4-A/C4-B execution/status suites, C2/C3 owner authority/provenance suites, and:

```bash
python -m pytest tests/test_owner_readiness_summary_r3_probes.py -q
python -m pytest tests/test_owner_readiness_summary_r3_probes.py -q
python -m pytest tests/test_owner_readiness_summary_r2_probes.py tests/test_owner_readiness_summary_r1_probes.py tests/test_owner_readiness_summary.py -q
python -m ruff check .
python -m turtle_value_engine config validate --input config/project.example.toml
python -m pytest -q
```

Follow **the actual latest** `.github/workflows/ci.yml` for systemd verify, deterministic OpenAPI export check, Dashboard frozen pnpm install, api/types/lint/typecheck/test/build, client-bundle secret scan with CI sentinel environment, Wrangler strict dry-run and cross-stack smoke. Use the CI matrix rather than substituting an incomplete checklist. The R2 baseline on reviewed main was 7,543 Python passed / 2 skipped, 55 Dashboard passed, but report **actual** new totals and full commands. Record the four protected blob SHAs (R2 baseline: `e34f4ca0` / `0e75b02e` / `ded56064` / `a9cff0de`); validate schema parity and that no forbidden file changed. All tests that do not require real credentials or live services MUST be automatic. Opt-in live-AKShare tests may remain skipped with the exact skip condition stated; do not silently mark them passed.

**No engineering acceptance requires a human operator.** No actual `plan-activation --output` execution, trust root mutation, private key, human ACCEPT/REJECT, signing, `--apply`, rollback, trading or policy threshold changes. If an environment truly cannot run a gate, document the **exact command**, tool/permission error, expected versus observed result, whether it blocks merge, and the responsible automated CI gate; no bare “evidence incomplete” claim. Any later real owner decision/activation is an entirely separate opt-in human workflow requiring a fresh read-only plan, hashes and explicit authorization, **outside R3**.

## 5. Deliverable, PR and follow-up

Produce a narrow implementation PR with tests-first red commit, tiny hint/manual change, green verification and `docs/status/phase-7-c4-c-r3-YYYY-MM-DD.md`. Include a parser-accepted vs parser-rejected argv table (from actual parser probes; never execute writing handlers), source/line references, exact base/PR SHAs, CI commands/results, immutable artifact hashes and clear residual boundaries. Review final PR diff, verify the **exact final head SHA's** GitHub Actions run is **success** before merging, then verify merged-main SHA and corresponding Actions success. If any gate fails, fix and re-run at the new final head; never merge on stale CI.

**After R3**, independently scope the deferred `summary_id` collision as a version-aware identity-contract design; analyze semantic vs complete projection identity, old persisted v1 summaries and consumers, possible opt-in v2 schema/CLI behavior, no hash cycles and appropriate deduplication keys *before* any implementation. Do not silently change identity semantics inside R3.
