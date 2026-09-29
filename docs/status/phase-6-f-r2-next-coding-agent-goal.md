# Phase 6-F-R2 coding-agent handoff — Canonical EnvironmentFile Semantics and Render Gating

Status: **COMPLETED 2026-09-29**

Implementation:
`c064cda68a0e31b0dc1b47ed451bd59977e7c931`

Exact-head CI:
GitHub Actions run `36533726274` (`success`).

Closure:
`docs/status/phase-6-f-r2-2026-09-29.md`

Canonical goal:
`docs/goals/phase-6-f-r2-environmentfile-semantic-hardening.md`

Selection audit:
`docs/status/phase-6-f-r1-post-closure-review-2026-09-29.md`

Predecessor closure:
`docs/status/phase-6-f-r1-2026-09-29.md`

## Mission

Implement only Phase 6-F-R2.

Current main already has R1's EnvironmentFile-aware scan/redaction and
private-file metadata boundary, but the file reader is only an approximate
`KEY=VALUE` parser rather than systemd EnvironmentFile semantics, and render
does not prove readability or required-reference completeness.

Do not implement the full systemd grammar. Enforce the canonical credential
subset specified by the goal so every accepted value is interpreted
byte-identically by the harness and systemd.

## Execution rules

- Read the canonical goal and post-R1 review before editing.
- First add focused regressions that fail on current main.
- Use one canonical parser/validator for render, preflight, scans and delivery.
- Reject quoting, backslash escapes/continuations, multiline values,
  whitespace-bearing values, duplicates and unknown keys.
- Render must fail closed on unreadable/incomplete/unsupported credential files
  before a new delivery-enabled unit is emitted.
- Never request, print or persist a real secret.
- Keep tests offline and host-mutation-free.
- Run the entire automatic gate yourself; do not delegate machine-verifiable
  checks to the owner.
- If the existing private production config is locally available, rerun only
  the non-destructive gate/preflight/verify/report checks in the goal.
- Do not enable delivery merely to prove R2.
- Push the exact implementation SHA and close only after matching exact-head
  GitHub Actions succeeds.
- Record fail-on-main evidence, commands/results and exact test counts in a
  dated R2 closure document.
- Stop at R2; do not start Phase 7, FQGate/Bridge, provider/vendor expansion,
  trading or investment-rule work.

## Required deliverables

- canonical EnvironmentFile parser/validator in
  `scripts/monitoring_production_ops.py`;
- focused deterministic regressions in
  `tests/test_monitoring_production_ops.py`;
- complete call-site reuse of the canonical parsed values;
- truthful render fail-closed behavior for unreadable/incomplete/unsupported
  credential files;
- dated R2 closure record with exact-head CI evidence;
- source-of-truth docs updated only as narrowly required.
