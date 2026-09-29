# Phase 6-F-R1 selection review — 2026-09-29

Status: **SELECTED — Phase 6-F-R1 / NOT IMPLEMENTED**

## Review baseline

- Phase 6-F final implementation:
  `065b53a17bcb4f009a57ef918ffa3d59de135107`.
- Required exact-head Actions run: `36515225218`, `success`.
- That run completed Ruff, runtime-config validation, the deterministic Python
  suite (`6775 passed, 2 skipped`), reference systemd verification, generated
  API/type drift checks, Dashboard lint/typecheck/tests/build, client-bundle
  secret scan, strict Wrangler dry-run and the Dashboard cross-stack smoke.
- The Phase 6-F closure commit
  `fe88f3dd8b9a359307ee81b03394faf83f918e70` also has a successful
  main-branch Actions run (`36515781421`).
- Canonical owner-runtime evidence remains
  `docs/status/phase-6-f-2026-09-29.md`.

The review accepts Phase 6-F as **CLOSED / OWNER_ACCEPTED**. Its real WSL2
deployment was monitoring-only (`delivery_enabled=false`), so the findings
below do not invalidate the bounded firing, no-duplicate, D3, recovery,
activation/deactivation or running-distro persistence evidence.

## Post-closure findings

### F1 — EnvironmentFile-only secret values are not part of the effective scan set

`scripts/monitoring_production_ops.py::resolvable_secret_values` currently
collects referenced values from the harness process environment. The production
service credential source, however, is the private systemd
`EnvironmentFile`. `environment_file_values` can read that file in memory,
but those values are not merged into the values used by tracked-file scans,
report artifact scans or journal redaction.

The existing regression
`test_report_secret_scan_flags_resolved_values` proves a leak is caught only
after also exporting the same value with `monkeypatch.setenv`; it does not
prove the service-effective, EnvironmentFile-only case.

Impact: dormant while production delivery remains disabled, but the future
Telegram/webhook secret-boundary claim is weaker than the documentation states.

### F2 — The private EnvironmentFile contract is not fully enforced

The typed configuration requires an absolute `delivery_environment_file`, but
does not require the file to remain inside the production private root, reject
a symlink escape, or verify owner-private permissions before using it.

Impact: dormant while delivery is disabled; must be hardened before a
production notification opt-in is treated as fully audited.

### F3 — some six-item manual boundaries do not emit an exact runnable resume command

Three production-operations paths violate the Phase 6-F rule that a manual
boundary carry the exact resume command:

- `windows_bootstrap_marker_payload` uses `<config>` instead of the actual
  production-config path;
- `ensure_linger` uses `<config>` instead of the actual path;
- the missing-EnvironmentFile `cmd_render` branch emits
  `... render --production-config <path>`, while the parser requires
  `... --production-config <path> render`.

No such manual boundary was crossed in the accepted Phase 6-F deployment, so
this is a post-closure hardening defect rather than a closure reversal.

## Selected package

**Phase 6-F-R1 — Production Credential Boundary and Manual-Resume Hardening**

Canonical goal:
`docs/goals/phase-6-f-r1-production-credential-boundary-hardening.md`

Coding-agent handoff:
`docs/status/phase-6-f-r1-next-coding-agent-goal.md`

R1 is deliberately narrow. It must fix the audited credential/resume
boundaries, add regression tests that fail on the current implementation, run
the full automatic gate and close only on an exact-head successful Actions
run. It must not start Phase 7, add providers or notification vendors, change
monitoring/investment semantics, or require the owner to paste a secret.
