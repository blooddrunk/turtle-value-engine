# Phase 7-C4-A-R1 — Activation Artifact Containment & Rollback Audit Recovery

Status: **IMPLEMENTED / CLOSED** (see `docs/status/phase-7-c4-a-r1-2026-10-23.md`). Selected by `docs/status/phase-7-c4-a-post-closure-review-2026-10-23.md`. Phase 7-C4-A remains **CLOSED**.

## 0 — Mandatory synchronization / branch discipline

First run `git status --short`, `git fetch origin --prune`, `git log -5 --oneline origin/main` and check current PRs and exact-head Actions CI. Read `AGENTS.md`, this goal, the selection review, `docs/status/phase-7-c4-a-2026-10-23.md`, `docs/operations/profile-activation-executor.md`, the entire current `activation_execution.py`, `cli.py`, `tests/test_activation_execution.py` and relevant schema contracts. Review worktree modifications before switching; preserve them safely and **never use a destructive hard reset**. Work from a clean feature worktree/branch cut from the **current** origin/main, not the historic SHA in the selection review. If this goal PR is still pending, use the selected goal in it or merge after exact-head CI, without duplicating diverging documents.

## Outcome / strict scope

Finish a small, automated, offline reliability repair for the controlled activation executor: (F1) refuse activation-root descendant symlink/path escapes; (F2) make rollback outcome publication recoverable after config restoration; (F3) make READY-preview apply instructions actually executable and appropriately quoted; and inspect metadata fsync durability without claiming physical-crash proof. Each code correction must have a **baseline failure or a separately documented, defensible contract necessity**. No real owner action is permitted or required for test completion.

## 1 — Independent baseline-red experiments BEFORE fixes

In a pristine clean worktree of current origin/main, author focused regression tests and run them without changing production code. Save exact commit, test commands, observed exit codes/statuses, state of every test trap/config/receipt/journal directory, failure assertions and before/after SHA-256 in the PR/review notes. Do not manufacture red by editing application code or relaxing assertions.

**F1: descendant path guard.** Set up `activation_root/locks`, `journal`, `receipts`, `before-images` and `rollbacks`, separately, as symlinks to unrelated **throwaway temp directories**. Run relevant preview/apply/rollback with real generated test Ed25519 keys and temporary private config; capture actual side effects (including pre-lock writes) and named failures. Also test unexpected file/non-directory ancestors. Fix only real path escapes or an objectively violated store invariant. Avoid asserting preview must fail for unused descendant entries if its byte-exact read-only behavior is not compromised; the apply/rollback mutation boundary is primary.

**F2: rollback after-restore audit gap.** Use actual signed fixture to apply, then inject a failure immediately after the rollback config replacement and before publishing its immutable rollback outcome; verify restored bytes, absent outcome, retry result, and whether the immutable audit is ever finalized. Baseline failure should be the missing durable outcome following retry, not merely a simulated exception. The eventual repair should persist recovery intent before replace and verify receipt/before-image/bound state before safely finalizing any result. If no failure reproduces, record evidence and skip speculative code.

**F3: literal command.** Run one READY preview using real throwaway authority and space-containing paths; show whether `apply_command_hint` is directly usable. Fix via safely shell-quoted full argv or an explicit structured command object with documented copy-and-run behavior; preserve existing preview semantics and do not emit private key material. Test original input flags (policy exceptions, evidence, inventory), structured args and default preview's zero-write contract.

**Durability:** inspect `_write_create_or_identical`: `fsync(file)` alone does not guarantee parent-directory entry durability. Test expected call ordering for intent and before-image publication before configuration swap, receipt and rollback-outcome publication afterward. The acceptance claim is correct fsync order and recoverability under simulated interruption, **not power-loss certification**.

## 2 — Minimal production implementation

- Guard all artifact subdirectories and intermediate ancestors against symlinks/non-directories, prove containment within the resolved activation root, do not follow foreign paths, never delete unrelated files; use appropriately anchored file opens where practical. Fix lock path first so no lock file is created outside the private root. Fail with stable, documented error codes; no silent fallback storage.
- On explicit rollback, validate the receipt/backup, persist an immutable recovery intent **before** restoring config, perform the existing atomic replace, then create-only publish an outcome. On a repeated explicit rollback that observes the exact restored bytes, distinguish (a) genuine completed rollback with a valid outcome, (b) recovered interrupted rollback with a valid bound intent (finalize idempotently without rewriting config), and (c) pre-restored config with no trustworthy proof (report true current state without fabricating a completed operation). Refuse conflicting/altered evidence and foreign mutations. Do not make rollback automatic.
- Restore operator usability: a generated apply command must be complete and shell-safe for the declared supported shell, or clearly present an argv representation plus a tested command-renderer. The example in the Chinese operations doc must not contain ellipsis while being labelled copy-and-run.
- Document metadata durability truthfully. Do not claim one transaction over config, journal, backup and outcome.
- Preserve the offline preview/read-only contract, fresh READY re-attestation, byte-exact edit, CAS and rollback guard, content addresses and existing schema compatibility. Add a field/schema only when needed for a reproduced contract; prefer additive compatibility.

## 3 — Automated acceptance (not optional)

A. Focused `python -m pytest tests/test_activation_execution.py -q` including new baseline-red regression tests now passing on fixed branch; test ordinary success and repeat, exact-byte before/after SHA, active/failing lock contenders, trap symlinks for every directory, invalid ancestors, exception-specific return codes, failure injection before/after restore, rollback retry, tampered/replaced receipt and intent, counterfactual different receipt, divergence and preservation of older independent artifacts.

B. Full `python -m ruff check .` and `python -m pytest`; `python -m turtle_value_engine config validate --input config/project.example.toml`; `systemd-analyze verify deploy/monitoring/turtle-value-monitor.service deploy/monitoring/turtle-value-monitor.timer`; `python scripts/export_surface_openapi.py --check`; `pnpm --dir apps/dashboard install --frozen-lockfile`, `api:check`, `types:check`, `lint`, `typecheck`, `test --run`, `build`, `security:client-bundle` with the five existing CI secret sentinels, `pnpm --dir apps/dashboard exec wrangler deploy --dry-run --config wrangler.jsonc --strict` and `python scripts/dashboard_cross_stack_smoke.py`. Use the exact current `.github/workflows/ci.yml` as authority; if a check cannot run, preserve named status and evidence instead of calling it passed. Remote GitHub CI should cover the complete matrix.

C. Compare SHA-256 against baseline for: `rules/strict-v1.yaml`, `rules/strict-v2.yaml`, `docs/releases/strict-v2/release-candidate.json`, `config/project.example.toml`. Require byte-identical; checked-in default remains `strict-v1`. Ensure no real keys/private paths/secret values in code, logs, PR, issue, or artifacts.

D. Provide a one-command reproducibility helper (e.g. focused pytest) with deterministic temporary test fixtures. Attach machine-readable and human-readable evidence: test name, baseline fail, fixed pass, exact SHA CI links, error/exit/side-effect matrix; leave no unexplained `manual evidence incomplete` state. When claiming crash safety, explicitly separate process-interruption simulation from filesystem power-loss reliability.

E. Open scoped PR, verify CI **exact PR head SHA** success, and ask for review; do not merge prematurely. After merge check actual main/merge-head CI and write concise completion status. Do not silently rewrite past C4-A closure.

## 4 — Human action boundary

**None for this phase.** All keys are freshly generated disposable Ed25519 test keys and all configs/roots are private temporary test fixtures. There is no reason to solicit a real owner signature, true policy acceptance, or network/production deployment to prove R1 engineering quality.

**Only if the user later independently elects to activate strict-v2**: present the CDC yield discrepancy (strict-v2 PASS 14% versus S tier at 12%; 13% behaves differently), obtain the owner's explicit signed decision and matching exception, generate a preview against their actual private configuration, have them inspect the one-line diff and explicit expected hashes, and require their own deliberate apply action. This is a separate policy/operations choice and must never block or be counted as R1 engineering acceptance.

## Definition of done

All reproduced high-priority defects repaired; focused and full CI-equivalent tests green; no off-root writes in hostile descendant-layout tests; recovery after simulated rollback interruption produces coherent durable audit or a deterministic explicit refusal; operator apply instructions are truly runnable; no unauthorized changes or defaults; exact-head and post-merge CI evidence recorded. If a candidate fails to reproduce, close it as **UNPROVEN** with the actual test evidence and no invented fix. Do not expand this bounded task into a general security review or unrelated future release.
