# Phase 7-C4-B — Read-Only Activation Status and Disposable Operator Rehearsal

Status: **SELECTED / NOT IMPLEMENTED**. Selected by docs/status/phase-7-c4-a-r4-post-closure-review-2026-10-24.md. C4-A/R1/R2/R3/R4 remain CLOSED. This is not R5 and does not authorize real strict-v2 activation.

## 0. Mandatory sync before acting
- Inspect git status --short; git fetch origin --prune; git log -5 --oneline origin/main; inspect latest PRs, issues, main SHA and CI. Protect local changes. Create clean feature worktree at the freshly verified origin/main. Never git reset --hard.
- Read AGENTS.md, docs/spec, rules/strict-v1.yaml, schemas, current activation status/goal, docs/operations/profile-activation-executor.md, CLI and activation_execution implementation and all C4-A–R4 test suites. Record baseline SHA.
- Avoid duplicating a later merged PR or changing frozen investment math or user authorization.

## 1. Goal
Implement one bounded, offline, **strictly read-only** command to inspect the local persisted activation/rollback state. Preferred CLI: python -m turtle_value_engine evolution activation-status --activation-root PATH --project-config PATH. Optionally allow --receipt PATH for exact-record inspection, only with unambiguous semantics. If scanning multiple histories cannot be done safely within reasonable scope, document a smaller receipt-focused approach first.

The command must help a non-expert operator answer: Has anything activated? Did the activation finish? Has it been rolled back? Is recovery pending? Are the stored artifacts consistent? What explicit action, if any, can the operator consider next?

It must NEVER apply, rollback, sign, re-authorize, repair a journal, publish a receipt, finalize rollback, create a lock, write an audit record, query a provider, activate strict-v2, or trade.

## 2. Required observed-state classification
Use existing validated V1 receipt, intent, rollback-intent, rollback-outcome models and SHA-256 helpers. Return a small versioned JSON projection with stable status/code, relevant verified activation/rollback identifiers, current config SHA/default if readable, problems, and Chinese plain-language guidance. Distinguish facts observed, identities validated, and unknown owner authority. Do not leak keys, secrets or unnecessarily absolute private paths.

Implement deterministic fixture coverage for:
1. NO_HISTORY: no store/artifacts; no directories created.
2. ACTIVATED_VERIFIED: persisted receipt, journal and before-image valid and selected config equals the activated hash.
3. ROLLED_BACK_VERIFIED: valid rollback intent/outcome, original bytes restored.
4. RECEIPT_FINALIZATION_PENDING: config activated, valid journal, receipt missing; observer NEVER repairs.
5. APPLY_RESUMABLE: valid unfinished journal and config still prior; fresh authority and successful retry NOT guaranteed.
6. ROLLBACK_FINALIZATION_PENDING: restored config, bound rollback intent exists but outcome missing.
7. CONFIG_DIVERGED and AMBIGUOUS_HISTORY: current config mismatch or multiple unfinished relevant intents; never infer success.
8. CORRUPT_OR_UNVERIFIABLE: missing/invalid/symlinked/nonregular/out-of-root artifact, modified receipt/hash/before-image, incorrect association or unexpected entries. No false verified-green state.

Distinguish stale historical receipts from current activation; scope all evidence to the requested config; unrelated histories must not be labeled current. Use existing CLI conventions for exit codes (suggested 0 verified informational, 1 unresolved/diverged/unverifiable, 2 invalid path/input). If a classification is not provable from bytes, report NOT_VERIFIED explicitly rather than guess.

## 3. Pure-read boundary
- Inspection must perform zero mkdir, lock creation, exclusive flock, auto-repair, json rewrite, config write, side-effectful probing or provider calls.
- Existing guards may be reused only if read-only. Check symlink and path traversal boundaries for store children and persisted artifact paths; suspicious files fail closed.
- Assert complete directory-tree entries, hashes and config bytes unchanged before/after every success and failure path. Missing store remains missing.
- Concurrency: report observation limits honestly. Do not claim a global atomic snapshot. A bounded read/recheck is optional only if useful, tested and compatible.
- Preserve public persisted schema/receipt/rollback formats, CLI apply/rollback behavior and current error contracts.

## 4. Fully automated rehearsal
Use real CLI with throwaway Ed25519 keys, registry/evidence, decision, private config, and temp activation root built from tests/test_activation_execution.py::_Env, or an equivalent fixture. Exercise:
- fresh READY preview with zero tree changes;
- explicit expected-plan-id / expected-config-sha256 apply -> ACTIVATED, hashes of config/receipt/before-image proven;
- new status -> ACTIVATED_VERIFIED, second status byte-identical and zero writes;
- explicit receipt-bound rollback -> ROLLED_BACK, new status -> ROLLED_BACK_VERIFIED, second status stable and zero writes;
- deterministic injected faults at journal-persisted, config-replaced-before-receipt and restored-before-rollback-outcome, ensuring inspection reports pending conditions without recovery;
- missing file, tamper, forged association, symlink/nonregular file, path with spaces, divergence, multiple histories, unrelated store entries and refusal cases; assert named status/code, exit code, original hashes and zero writes.

No sleeps, uncontrolled concurrency, actual keys, external private config, live market data, network, Cloudflare or human steps.

## 5. Documentation and UX
Update docs/operations/profile-activation-executor.md with a brief Chinese 'current state / next action' quick start, literal runnable commands, status and error table, and scope of read-only verification. Explain that historical receipts do not prove present owner consent and status does not re-validate fresh signature authority. Keep changes narrowly scoped: no UI, daemon, database, new signing process, automatic recovery or policy switch.

## 6. Automated gate and recorded evidence
- Focused: pytest tests/test_activation_execution.py tests/test_activation_execution_r1_regressions.py tests/test_activation_execution_r2_regressions.py tests/test_activation_execution_r3_probes.py tests/test_activation_execution_r4_probes.py plus new tests, twice for new tests.
- Full: python -m ruff check .; python -m turtle_value_engine config validate --input config/project.example.toml; python -m pytest -q; systemd-analyze verify deploy/monitoring/turtle-value-monitor.service deploy/monitoring/turtle-value-monitor.timer; python scripts/export_surface_openapi.py --check; pnpm --dir apps/dashboard install --frozen-lockfile; pnpm --dir apps/dashboard api:check; pnpm --dir apps/dashboard types:check; pnpm --dir apps/dashboard lint; pnpm --dir apps/dashboard typecheck; pnpm --dir apps/dashboard test --run; pnpm --dir apps/dashboard build with CI sentinel environment; pnpm --dir apps/dashboard security:client-bundle; pnpm --dir apps/dashboard exec wrangler deploy --dry-run --config wrangler.jsonc --strict; python scripts/dashboard_cross_stack_smoke.py.
- Compare exact Git blob SHAs vs pinned baseline for rules/strict-v1.yaml, rules/strict-v2.yaml, docs/releases/strict-v2/release-candidate.json and config/project.example.toml: all MUST remain identical. Default strict-v1 unchanged.
- Open one scoped PR, verify exact PR-head CI and (after authorized merge) merge-head and current main CI. Create docs/status/phase-7-c4-b-YYYY-MM-DD.md with actual commands, counts, hashes, fault matrix and CI run links. Never claim a local test was run when it was not.

## 7. Human intervention boundaries
Normal engineering verification requires ZERO manual input or real credentials. If an OS/CI limit prevents execution, write exact attempted command, error, affected assertion, automatic Linux CI alternative and precise unverified remainder; require a human only when no automatic equivalent can test it. When genuinely necessary provide exact prerequisites, numbered commands, expected outputs and stop criteria. Do not ask owner for signing keys.
Separate future optional human-owned action: review the CDC 14% gate versus S-band 12% exception, independently accept or reject, privately sign the actual decision, examine a fresh preview and deliberately apply against a real private config. This is NOT part of C4-B acceptance.
