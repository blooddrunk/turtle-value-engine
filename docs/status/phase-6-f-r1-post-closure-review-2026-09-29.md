# Phase 6-F-R1 post-closure review — 2026-09-29

Status: **R1 IMPLEMENTATION ACCEPTED WITH A NARROW POST-CLOSURE DEFECT; PHASE 6-F-R2 SELECTED**

Reviewed head before this selection:
`797ea623bf975fc2a9c1df9cf6a4e093e0fa23eb`

R1 implementation:
`42304cf86db6fb2d8b177f3d7d13a4b89531103b`

R1 implementation CI:
GitHub Actions run `36519413717`, `conclusion=success`, exact
`head_sha=42304cf86db6fb2d8b177f3d7d13a4b89531103b`.

R1 closure-doc head CI:
GitHub Actions run `36519811015`, `conclusion=success`, exact
`head_sha=797ea623bf975fc2a9c1df9cf6a4e093e0fa23eb`.

The current full CI at the reviewed head reports **6787 passed / 2 skipped** for
Python and **55 passed** for Dashboard tests, with Ruff, systemd reference-unit
verification, generated API/type checks, Dashboard build/client-bundle secret
scan, strict Wrangler dry-run and cross-stack smoke all green.

## 1. What remains accepted

The Phase 6-F production deployment remains `CLOSED / OWNER_ACCEPTED`. Its
accepted runtime has `delivery_enabled=false`, so the findings below do not
change the already accepted monitoring cadence, persistence, D1/D2/D3 behavior
or investment semantics and do not expose a live production credential.

R1 correctly added:

- EnvironmentFile-only values to the effective secret scan/redaction set;
- dual-source (process + file) scan coverage;
- in-private-root, symlink-escape, regular-file and owner-only mode checks;
- canonical parser-valid manual resume commands;
- deterministic regressions and exact-head CI evidence.

No reason was found to reopen Phase 6-F itself.

## 2. Finding F1 — the harness parser is not systemd EnvironmentFile semantics

`environment_file_values()` currently parses each physical line as a simple
`KEY=VALUE` pair and then applies:

`value.strip().strip('"').strip("'")`.

That is not equivalent to the documented systemd `EnvironmentFile=` grammar.
systemd supports unquoted backslash escaping, backslash-newline continuation,
single-quoted and double-quoted multi-line values, and quote-specific escape
rules.

Therefore the harness can derive a different value from the one the service
manager actually injects. For example, a value containing an unquoted
backslash escape or a continued line can be transformed by systemd while the
current scanner keeps the backslash/physical-line shape. In that case the
"effective" secret scan/redaction set can miss the actual service value.

This violates the R1 objective that the private EnvironmentFile be a genuinely
auditable **service-effective** secret source.

## 3. Finding F2 — render does not prove readability or referenced-value presence

`cmd_render()` calls `validate_delivery_environment_file()`, which checks
path/type/mode metadata, but it does not call the file-value reader and does
not prove that every referenced secret name is present and non-empty.

Consequences:

- a regular owner-only file that is unreadable to the harness can pass the
  render metadata gate;
- a syntactically valid private file that omits a required referenced name can
  still render the unit;
- the render boundary's own machine-verifiable-success text claims that every
  referenced name is defined, but the render path does not currently prove it.

R1 §3.1 explicitly required missing/unreadable EnvironmentFile conditions to
retain fail-closed/manual-boundary semantics, so this is a real acceptance gap.

## 4. Selected correction: Phase 6-F-R2

Select the narrow follow-on:

**Phase 6-F-R2 — Canonical EnvironmentFile Semantics and Render Gating**

Canonical goal:
`docs/goals/phase-6-f-r2-environmentfile-semantic-hardening.md`

Coding-agent handoff:
`docs/status/phase-6-f-r2-next-coding-agent-goal.md`

R2 must not implement a second hand-written approximation of the full systemd
grammar. Instead, make the accepted credential-file format deliberately
canonical and unambiguous: one physical `NAME=VALUE` assignment per required
reference, no quoting/escaping/continuations or whitespace-bearing values,
no duplicates and no unrelated environment keys. Unsupported syntax fails
closed before the unit is rendered.

This makes the harness interpretation byte-identical to the systemd
interpretation for every accepted credential value while also preventing an
"EnvironmentFile as arbitrary process-environment injection" side channel.

## 5. Production/owner boundary

No owner action is needed for this review or for R2 implementation/CI closure.
Do not request a real Telegram token, webhook URL, reboot, sudo action or
manual log inspection.

The current production deployment is monitoring-only, so do not enable
delivery merely to test R2. If the existing private production config is
available to the coding environment, only the goal-specified non-destructive
gate/preflight/verify/report checks should be rerun automatically.

Until R2 closes, production notification delivery should remain disabled. This
is a narrow dormant-path correctness boundary, not a Phase 6-F production
closure reversal.
