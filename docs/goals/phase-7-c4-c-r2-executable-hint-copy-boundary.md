# Goal: Phase 7-C4-C-R2 — Executable Hint Copy Boundary and Write-Step Accuracy

**Selected by:** `docs/status/phase-7-c4-c-r1-post-closure-review-2026-10-25.md`. R1 is merged with successful CI; this is a **small post-closure repair**, not a redesign of the C4 readiness journey or an activation phase.

## 0. First: synchronize and establish actual base

Before editing, execute and record:

```bash
git status --short
git fetch origin --prune
git switch main
git pull --ff-only origin main
git rev-parse HEAD
git log -5 --oneline
```

Never discard a dirty tree: preserve it in a dedicated branch/worktree; no blind reset/stash. The reviewer observed main `3c282f92aa513fd77a87c0f727a3c7dbed1b89c3`, **not** a fixed execution base. Re-check merged commits, active PRs and issues for this same task first. If the selection PR is still open, inspect its goal and only begin after reconciling it against the latest main. Read `AGENTS.md`, relevant `docs/spec/`, `docs/roadmap.md`, current R1 goal/status and post-closure review, `src/turtle_value_engine/evolution/owner_readiness.py`, CLI parser/handler, R1 tests, and `docs/operations/owner-readiness-handoff.md`.

## 1. Two narrow, source-grounded defects

**F1 (P2, reproduced with stdlib tokenization):** `_next_steps_zh` interpolates a `shlex.join`-quoted complete `tve evolution ...` command and appends `。` sentence punctuation **after** the command. For the documented copy-ready tail (the entire text after the final `：`), the punctuation is part of the *last* shell argument. A genuine operator file path `/tmp/config with spaces.toml` becomes `/tmp/config with spaces.toml。` when pasted as displayed. Existing R1 extractor `_executable_hints` strips `。` before parsing; that masks the copyability failure. Read-only output must not silently retarget a path.

**F2 (P3, source-confirmed):** `dossier_step` states `decision-dossier` is the “唯一写文件步骤”, but `plan_activation_step` truthfully states `plan-activation --output` also writes. Both are opt-in file-writing operations. The misleading exclusivity sentence must be corrected.

**Not in scope:** The R1 diagnostic's reproduced `summary_id` collision across different activation-store problems with different `content_sha256`. Keep the diagnostic intact, with a separate version-aware identity-contract goal only after explicit design/compatibility analysis. Do not silently change `summary_id`, schema or `contract` in R2.

## 2. Required observable behaviour and minimal change

1. Every **advertised copy-ready** `next_steps_zh` command is the exact, complete final segment after the **last** full-width colon `：`. That segment must be directly usable as shell input **with no trimming** of a trailing `。`, whitespace annotation, Markdown, prose or fake placeholder. Human-readable punctuation belongs before the colon, not after the command. If not safe or incomplete, return plain prose, not a purported command.
2. Retain `shlex.join`/safe argv quoting; preserve exact paths with spaces, quote marks, semicolons, `$`, backticks, redirection symbols, non-ASCII text **and an actual final Chinese full stop within a legitimate filename**. Never “fix” F1 by stripping punctuation off the user's original path. Preserve optional/repeatable paths, their order/multiplicity, and R1 same-observation replay behaviour.
3. Avoid punctuation changes to non-command prose unless required. For the write disclosure, say `decision-dossier --output` **writes** the selected Markdown file and `plan-activation --output` **also writes** a selected plan file; remove “唯一” or equivalent exclusive claim. Neither may be presented as read-only/paste-ready.
4. Preserve informational boundary, 11 `journey_state` values, exit classes 0/2, existing `content_sha256` self-check, fixed truth/authority literals and source facts. No schema/identity change. Never suggest executable `--apply`, rollback, signing, `--output` or another writing command.
5. No change to `activation_execution.py`, `activation_status.py`, trust/authorization/verifier logic, deterministic investment mathematics, `rules/strict-v1.yaml`, `rules/strict-v2.yaml`, release manifest, config template, or default profile.

## 3. Mandatory automated red-before-green proof

Create a small focused `tests/test_owner_readiness_summary_r2_probes.py` (or clearly scoped equivalent) **before production edits**. Against clean synchronized main, capture and retain failing assertions:

- Use genuine R1 test helpers and throwaway fixtures for at least `OWNER_DECISION_REQUIRED`, authenticated `PREVIEW_READY`, blocked authority, corrupt store `STORE_NEEDS_ATTENTION`, recovery pending and rolled-back paths. Extract command tails **literally** using `step.rsplit("：", 1)[1]`; **never** silently `rstrip("。")`, `.strip("。")` or pre-fix the data. Verify `shlex.split(tail)` equals the expected exact argv. Expect baseline red on the last path argument. Run the exact tail only through a no-op `tve` stub in a disposable sandbox; compare NUL-separated argv and confirm no stray redirections/files. No real activation CLI in shell proofs.
- Repeat with paths containing spaces, single/double quotes, shell operators, Chinese text and a **genuine filename ending in `。`**. Its punctuation must remain in the argv because it is part of that operator-supplied path; the *sentence* punctuation must never become a path suffix.
- Inspect all 11 journey states (generating real fixtures where feasible; otherwise use deterministic pure helper tests) so no new copy-ready command is incomplete and prose-only instructions are not misdetected. No auto-`--apply`, file-writing `--output` or placeholder emission.
- Pin the exact F2 exclusivity defect against the baseline. Assert both commands are unambiguously described as opt-in writes and no hint calls either the only writing step.
- Verify replay still reproduces the same `summary_id`, `content_sha256`, journey, authority and relevant blocker/store projections for unchanged inputs. Full tree snapshots before/after, no sockets/no network, no leaked secret contents, and unchanged published artifacts. The diagnostic collision test stays **unchanged and green**; do not “fix” it implicitly.

Run the new suite on pristine main and preserve exact failures/exit codes. If F1 or F2 is disproved by an actual end-to-end baseline test, stop, document the reason and do not make speculative runtime edits. Otherwise make the minimum code/manual edit; re-run the focused suite twice green, plus `tests/test_owner_readiness_summary*.py`, `tests/test_activation_status*.py`, `tests/test_activation_execution*.py`, applicable owner C2/C3 suites. Existing R1 tests may require a minimal extractor adjustment, but must not weaken their safety assertions to obtain green.

## 4. Full verification and release gate (automatic)

On the implementation head:

```bash
python -m pytest tests/test_owner_readiness_summary_r2_probes.py -q
python -m pytest tests/test_owner_readiness_summary_r2_probes.py -q
python -m ruff check .
python -m turtle_value_engine config validate --input config/project.example.toml
python -m pytest -q
```

Run remaining checks from the **unchanged** `.github/workflows/ci.yml`: systemd unit verification, OpenAPI export check, Dashboard frozen pnpm install, api/types/lint/typecheck/test/build/client bundle secret scan (with CI sentinels), Wrangler strict dry-run and cross-stack smoke. Treat missing tooling as an explicit CI gate or precisely documented environment limitation, not silently “passed”. The previous CI baseline was 7,530 Python passed / 2 opt-in live-AKShare skipped and 55 Dashboard passed; report the new actual totals. Confirm protected Git blob SHAs remain `e34f4ca0` / `0e75b02e` / `ded56064` / `a9cff0de`, and validate unchanged schema and no accidental contract drift.

## 5. Deliverables and acceptance

One scoped implementation PR with tests-first red/green commit evidence, the smallest hint code adjustment, corrected Chinese handoff manual and `docs/status/phase-7-c4-c-r2-YYYY-MM-DD.md`. Record actual base/PR SHA, red assertions, isolated stub argv outcomes, deterministic before/after snapshots, full CI commands and results, excluded tests and protected blob parity. Inspect the **final PR-head SHA's GitHub Actions run** and confirm `success` before merge; then check the merged-main SHA and CI run. No empty “evidence incomplete” claim: show the exact missing command, observation, reason and whether it blocks acceptance.

**No human steps are required for engineering completion.** It is forbidden to generate owner approval/signatures, request private keys, change CDC policy thresholds or activate strict-v2 during this phase. Future real ACCEPT/REJECT, signing, `--apply` or rollback require separate explicit owner authorization, independently described as an optional manual workflow (fresh read-only plan and exact diff/hashes first). Do not count those discretionary real-world actions as failed engineering validation.
