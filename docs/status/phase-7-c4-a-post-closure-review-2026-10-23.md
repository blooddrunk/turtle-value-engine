# Phase 7-C4-A independent post-closure review / C4-A-R1 selection — 2026-10-23

Status: **C4-A CLOSED / independent engineering closure evidence ACCEPTED; C4-A-R1 SELECTED, NOT IMPLEMENTED**.

## Baseline and independent verification

- Repository: blooddrunk/turtle-value-engine; reviewed immutable main `5667cf778565725e5595d83f9d7b7abc3d061868`.
- C4-A implementation PR [#18](https://github.com/blooddrunk/turtle-value-engine/pull/18): implementation head `b228103a96d1e17e9670172b72b2853c6e374f05`; merged as `edca593cbc44f6783eeac374a20011f348ce3970`. Source changes: executor/CLI, four schemas, 47-test module, and Chinese operator guide.
- Independently checked GitHub Actions run [39885236666](https://github.com/blooddrunk/turtle-value-engine/actions/runs/39885236666) on exact PR head, [39885768698](https://github.com/blooddrunk/turtle-value-engine/actions/runs/39885768698) on merge head and [39886521818](https://github.com/blooddrunk/turtle-value-engine/actions/runs/39886521818) on current `main`: all `success` and exact `head_sha` matched.
- Read the latest main workflow job steps and raw log for job `120195853821`. Actual log: **7356 passed, 2 skipped, 9 warnings**; Dashboard **55 passed**; Ruff, config validation, systemd unit verification, OpenAPI/types checks, Dashboard lint/typecheck/build/client-bundle scan, Wrangler strict dry-run and cross-stack smoke all completed successfully.
- Read `docs/goals/phase-7-c4-a-controlled-activation-execution.md`, `docs/status/phase-7-c4-a-2026-10-23.md`, `docs/operations/profile-activation-executor.md`, `.github/workflows/ci.yml`, `AGENTS.md`, the full `activation_execution.py` implementation and focused-test inventory. At review time the GitHub API reported **zero open PRs and zero open issues**.
- **Independent execution limitation:** a local `git clone` failed with `Could not resolve host: github.com`. Code and Actions evidence were independently inspected via the GitHub connector. **No reviewer-local pytest execution, synthetic power-cut test or fail-on-baseline reproduction is claimed.** Every finding below is a source-backed test candidate, not an already reproduced exploit. The coding agent must run the specified baseline-red tests before fixing anything.

C4-A correctly separates preview (read-only) / explicit apply / explicit receipt-bound rollback; fresh READY re-derivation is under the lock; the executor requires exact active-record/evidence-record association. The stated original protection invariants remain: checked-in default `strict-v1`; no real owner key or decision, no real `strict-v2` activation; the four protected published/config files have unchanged bytes according to implementation and closure evidence. This review **does not reopen C4-A**.

## Source-backed follow-up candidates (prioritized)

### F1 — Activation store descendant-directory containment (high priority)

In `src/turtle_value_engine/evolution/activation_execution.py`:
- `_guard_activation_root` (approx. lines 559–583) uses `lstat` only for the top-level activation root and checks the root's resolved location.
- `_ConfigLock.__enter__` (approx. 598–608) creates/opens a path below `activation-root/locks`.
- `_write_create_or_identical` (approx. 177–228) calls `path.parent.mkdir(parents=True, exist_ok=True)` and guards the output file itself, but does not establish that the parent is a real directory contained under the activation root.
- Apply and rollback derive `journal/`, `receipts/`, `before-images/` and `rollbacks/` as children without inspecting each ancestor.

A pre-existing symlink such as `activation-root/locks -> <another disposable directory>` can direct lock/file publication outside the intended private store. This contradicts the stated artifact containment boundary even though it does not itself prove unauthorized financial-policy activation.

**Required baseline test:** in a pristine main worktree, create symlinked descendant directories pointing only to a separate disposable `tmp_path` trap directory; exercise preview and actual test-fixture apply/rollback using real throwaway Ed25519 fixtures as necessary. Assert whether off-root bytes/lock files appear and whether a fail-closed named error is raised. NEVER direct the reproduction at real `rules/`, `docs/`, owner storage, or live configuration. Cover each of `locks`, `journal`, `receipts`, `before-images`, `rollbacks`; include a non-directory case. The intended repaired state refuses every unsafe layout before modifying config or writing elsewhere.

### F2 — Rollback audit outcome lost across an interrupted publication (high priority)

`rollback_profile_activation` replaces the config at approx. 1671–1683, then publishes the rollback outcome at approx. 1685–1689. On a repeated call, approx. 1581–1593 returns `ALREADY_RESTORED` as soon as prior bytes/default match, before checking or finalizing an absent immutable rollback outcome.

**Required baseline test:** use a successful disposable signed activation, inject a controlled process failure at rollback-outcome publication **after** observing exact prior configuration bytes restored, assert that no rollback-outcome file was persisted, then retry the same explicit rollback; inspect whether it merely returns `ALREADY_RESTORED` leaving the audit artifact missing. This is an audit-recoverability candidate, not a claim of corrupted financial analysis.

A possible bounded repair is an immutable rollback intent written **before** the config replacement; after interruption the next explicit rollback can validate the receipt/intent/before-image/current bytes and deterministically finalize the outcome without rewriting the config. Do not predeclare a successful outcome before the write or infer real authority from a plain JSON record. Cover genuinely already-restored and divergent states distinctly.

### F3 — Advertised 'literal' apply command is incomplete (operator usability)

`preview_profile_activation` at approx. 1114–1119 emits `apply_command_hint` with the literal `...` instead of the original CLI arguments. `docs/operations/profile-activation-executor.md` `2 likewise presents an abbreviated command despite calling its examples literal. An owner must reconstruct sensitive policy/decision/evidence arguments by hand, increasing error risk.

**Required baseline test:** capture a real READY preview with throwaway evidence; show that using the emitted hint verbatim does not perform the intended apply, then fix to emit a complete safely shell-quoted command, or a precise structured argv plus an unambiguous documented invocation. Include paths with spaces and ensure nothing autostarts. Never put key secrets into rendered command or logs.

### Supporting durability check — directory metadata persistence

`_write_create_or_identical` fsyncs the file body (approx. 215–220) but not its parent directory; `_stage_and_replace` fsyncs the config directory after replacing the config. Audit the required ordering of durable intent and before-image directory entries relative to the config swap, and the rollback recovery metadata. Instrument the publication/fsync order in tests. A simulated crash and fsync-call assertions are automated evidence; they are **not a physical-power-loss proof**. Avoid unbounded filesystem abstraction rewrites.

## Decision and limits

Select **Phase 7-C4-A-R1 — Activation Artifact Containment & Rollback Audit Recovery**, with goal `docs/goals/phase-7-c4-a-r1-artifact-containment-rollback-recovery.md`. This is a **bounded, tests-first follow-up** focused on the concrete new local-executor boundary, not an open-ended security program. Any candidate that does not fail on pristine main is documented as unproven, and its production fix is omitted unless a clear semantic invariant independently warrants it.

- R1 never changes `rules/strict-v1.yaml`, `rules/strict-v2.yaml`, `docs/releases/strict-v2/release-candidate.json`, `config/project.example.toml`, investment math, live trading, monitoring state or historical artifacts.
- All completion checks use generated throwaway Ed25519 keys, disposable configs and an offline CI-equivalent matrix. **No real owner approval, key provisioning or live switch is necessary** for engineering closure.
- A later real `strict-v2` decision remains strictly optional and human-owned, because its 14% CDC pass hurdle lies above the 12% S band. Never manufacture `ACCEPT`, policy-exception consent or real activation.
- Do not select broader C4-B work before this narrowly justified R1 is reproduced and handled (or explicitly falsified) in automated tests.
