# Goal: Phase 7-C4-C — Read-only owner readiness summary and handoff

**Selected by:** `docs/status/phase-7-c4-a-r5-post-closure-review-2026-10-25.md` after independent review of R5 merged as `0542cfd29a4419e752d822b8b3c9c7aea682c360`. This is a bounded *operator-facing* improvement. C4-A/R1–R5, C4-B/R1 stay closed. No `strict-v2` adoption, signed owner decision, real private configuration mutation or auto-recovery is authorized.

## 0. Mandatory first action: synchronize the newest code

Run, without destroying uncommitted work:

    git status --short
    git fetch origin --prune
    git switch main
    git pull --ff-only origin main
    git rev-parse HEAD
    git log -5 --oneline

If the worktree is dirty, preserve it in a separate branch/worktree; do not reset or stash blindly. Read `AGENTS.md`, `docs/spec/`, `rules/strict-v1.yaml`, the relevant `schemas/`, `docs/roadmap.md`, `docs/operations/profile-activation-executor.md`, `docs/operations/owner-provenance-walkthrough.md` and the C4-A/C4-B/R5 sources and tests. Compare the latest PRs/goals and stop if this capability was already added. Pin the new `origin/main` SHA and exact main CI before edits.

## 1. User problem and non-duplication rule

The engine already exposes deterministic profile audit and Chinese `decision-dossier`, signed-provenance-aware activation preview and a read-only `activation-status`. An operator must still correlate those separate outputs to understand (a) the **14% CDC pass vs 12% S band** economic question, (b) what is presently machine-verified, (c) why a real activation is blocked and (d) whether any recovery is pending. Build a small **read-only owner-readiness summary** that combines existing facts and links to exact commands, without creating new authority, replaying approvals or modifying anything.

Inspect existing CLI/library output first. If an already supported command is sufficient, prefer a tested documentation-only workflow; document the redundant-command finding and do **not** add a new public CLI just to satisfy a phase label. Otherwise prefer an additive `tve evolution readiness-summary` that reuses existing code, not a second parser/validator.

## 2. Required view, when a CLI is justified

- Require explicit base-profile, target-profile, release-manifest and project-config paths; accept activation-root and the existing optional policy-exception/decision/trust-root/authority-evidence inputs only where backed by current contracts. No directory guessing, implicit owner credential, active-profile change or hidden network.
- Emit one reproducible, secret-free, Chinese-first JSON summary on stdout: observed profile/manifest identity and hashes, policy audit anomalies and 13% contrasting behavior, project config's exact observed hash/default, observed activation-store classification (if explicitly supplied), existing plan/preview blockers where enough inputs exist, and concrete next-step **read-only** command hints.
- Treat absent real owner authority as `OWNER_DECISION_REQUIRED` / `OWNER_AUTHORITY_NOT_PROVEN` **informational blockers**. Never silently generate an exception, signed acceptance, fake owner identity, or READY plan. Keep previously established CLI status/error codes nested as source facts rather than recoding them as a new authorization decision.
- State explicitly `owner_authority_revalidated` only when the actual existing verification path has run; do not mark it true from a historical receipt. The aggregate summary is **not** an authorization bearer, immutable snapshot or permission to apply. Even if an observed preview is READY, it expires conceptually when inputs or trust root change; the existing apply must re-derive under lock and require explicit expected hashes.
- Zero writes: no mkdir, lock/flock, receipt, journal, signing, config rewrite, repairing, provider, LLM or outside network. A missing activation store stays missing. No auto-invocation of `--apply` or rollback. No new database/service/Worker/schema changes unless essential to an explicitly added versioned read-only output contract.
- Preserve current CLI and library behaviors (`decision-dossier`, `activate-profile`, `rollback-activation`, `activation-status`), exact exit classes, deterministic identity and current schemas; protect the investment math and versioned published bytes. The next-step summary is advisory only.

## 3. Tests-first and acceptance matrix (entirely automatic)

Before production changes, write a failing **user-journey** test, not merely a new function-coverage test, demonstrating what the existing separate outputs cannot convey as a *single* actionable read-only summary. If no material gap is demonstrated, stop at accurate docs and closure.

Run real library/CLI paths in `tmp_path` with runtime-generated disposable Ed25519 keys, as in `tests/test_activation_execution.py` and C4-B suites. Minimum cases:

1. No real owner decision or policy exception: display the 14%/12% decision question, hash-bound profile facts, and a plain-language human decision boundary; no false READY or signature claim.
2. Throwaway authenticated ACCEPT with matching exception: report the existing fresh preview's exact identity, diff and blockers, but no automatic application; re-read latest trust-root authority and stop on revocation/rotation/stale evidence.
3. REJECT/ambiguous/conflicting/revoked authority and corrupt/symlinked inputs: retain the existing named blocker and exit-class semantics, no tracebacks or leaked secrets.
4. Empty store, valid ACTIVATED/ROLLED_BACK, apply/rollback interruption, diverged or corrupt store: reflect the actual `activation-status` without turning recovery guidance into a mutation or a claim of global atomic observation.
5. Stable repeated output over unchanged bytes; byte-and-entry snapshots of the entire supplied private state before/after both success and refusals prove **zero writes**, including no lock creation. CLI output contains no private key material, signing token, unexpected absolute private path or synthetic owner permission.
6. Baseline compatibility controls: valid genuine apply → rollback → idempotent still pass, and `strict-v1` remains default.

No live owner keys, live activation, network accounts, brokerage, sleep races, manual fixture assembly or real market data are needed.

## 4. Full automatic gate and evidence

At minimum, twice run new focused tests plus the established C4-A/R1–R5 and C4-B/R1 suites; then execute `python -m ruff check .`, `python -m turtle_value_engine config validate --input config/project.example.toml` and `python -m pytest -q`. Run the **unchanged** `.github/workflows/ci.yml` remainder: systemd unit verification, OpenAPI and generated type checks, Dashboard frozen install/lint/typecheck/tests/build/client-bundle secret check, Wrangler strict dry-run and cross-stack smoke.

Compare Git blob hashes of `rules/strict-v1.yaml`, `rules/strict-v2.yaml`, `docs/releases/strict-v2/release-candidate.json` and `config/project.example.toml` to the independently pinned review SHAs (all must remain identical). Check default remains `strict-v1`; no deterministic investment calculation, gate, profile or public contract drift.

Document actual baseline SHA, probe red or documented lack of a distinct gap, before/after tree equality, precise commands/results, exact CI SHA/run IDs, exclusions and limitations in `docs/status/phase-7-c4-c-YYYY-MM-DD.md`. Submit one scoped PR. Verify the GitHub Actions run's **exact PR head SHA** and `success` before merging; verify merge/latest-main head and CI afterward. Do not call CI green until complete. On a reviewer host without GitHub DNS, use connector/API code and raw Actions logs as the remote evidence, explicitly distinguishing them from unperformed local execution.

## 5. Human intervention: only for optional real owner action, never for engineering closure

Coding agent: **STOP at a read-only handoff.** Do not ask the owner to paste keys, secrets, decisions or signatures into the chat, PR or CI. The engineering phase requires no owner manual verification.

If the owner later separately requests genuine strict-v2 activation, clearly mark this as an independent, optional human decision requiring all of:

1. Read the actual current `decision-dossier` and 13% comparison; explicitly decide ACCEPT-with-exception or REJECT. If REJECT, stop and leave `strict-v1` unchanged. This economic judgment cannot be automated.
2. On the owner's private trusted host, create/operate a private key and trust-root registration per `docs/operations/owner-provenance-walkthrough.md`; sign exact canonical decision bytes locally, record via the repository's existing signed `record-decision` path. Keep private key outside repo/chat/CI.
3. On that same controlled host, execute a **fresh read-only** `activate-profile` preview against the actual private config and current trust root; inspect `config_diff` (exactly the intended `[profiles] default` change), plan ID, original SHA, evidence binding and full literal `apply_command_hint`. On any blocker or mismatch STOP.
4. Only on explicit owner instruction, run the generated `--apply --expected-plan-id ... --expected-config-sha256 ...` command; verify `config validate`, exact config SHA, receipt and before-image hashes and read-only `activation-status`. Keep the complete printed rollback command for a separately authorized recovery.
5. If any real authority, original data or policy input cannot be verified, stop. Do not fabricate acceptance or substitute CI green for a private signed decision.

## 6. Definition of done and stop boundary

Deliver one human-usable, non-duplicative read-only operator journey; machine-proven no writes; precise source truth and authority uncertainty; fresh green tests/CI; an honest closure report. If an existing workflow already fully solves the problem, close as **NO NEW RUNTIME NEEDED** with a tested runbook and do not add a redundant public command. Do not expand to R6 speculative hardening, daemon, dashboard, remote approval, automatic activation, trading, production historical claims or a new profile.
