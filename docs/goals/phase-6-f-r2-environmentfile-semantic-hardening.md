# Phase 6-F-R2 — Canonical EnvironmentFile Semantics and Render Gating

Status: **CLOSED** (2026-09-29; implementation
`c064cda68a0e31b0dc1b47ed451bd59977e7c931`, exact-head Actions run
`36533726274` `success`; closure record
`docs/status/phase-6-f-r2-2026-09-29.md`)  
Date: 2026-09-29  
Selected after: Phase 6-F-R1 post-closure review

Selection audit:
`docs/status/phase-6-f-r1-post-closure-review-2026-09-29.md`

Predecessor:
`docs/goals/phase-6-f-r1-production-credential-boundary-hardening.md`

Predecessor closure:
`docs/status/phase-6-f-r1-2026-09-29.md`

Coding-agent handoff:
`docs/status/phase-6-f-r2-next-coding-agent-goal.md`

## 1. Objective

Close the remaining credential-source correctness gap without reopening or
expanding the accepted monitoring architecture.

R2 has one responsibility:

> for every EnvironmentFile syntax that the production harness accepts, the
> harness must derive exactly the same referenced secret bytes that systemd
> will inject into the service, and render must fail closed before producing a
> delivery-enabled unit unless the private credential file is readable and
> complete.

The preferred design is **not** a home-grown full systemd parser. Define and
machine-enforce a strict canonical subset whose interpretation is identity
under both the harness and systemd.

## 2. Frozen boundaries

Do not change or reinterpret:

- Phase 6-A/6-B/6-C monitoring/event/re-analysis semantics;
- D1 cycle/outbox identity;
- D2A/R1 lease/recovery semantics;
- D2B/R1/R2 delivery ledger, dispatch-claim or retry-budget semantics;
- D3/R1 read-only observation;
- Phase 6-F cadence, activation, convergence, persistence or accepted WSL
  deployment claim;
- R1 manual-resume command behavior;
- `strict-v1`, valuation, hard gates, accepted adjustments or investment
  rules.

Do not add Phase 7, Bridge/FQGate integration, a provider, notification vendor,
remote secret manager, brokerage/trading behavior, M4-D/M4-E/M2-D or Windows
autostart implementation.

## 3. Canonical private EnvironmentFile contract

Replace the permissive/simple parser with one canonical parser/validator used
by **all** production-operations credential paths.

When delivery is enabled, accept only a deliberately unambiguous subset:

1. UTF-8 text; blank lines and whole-line `#` / `;` comments may be
   ignored.
2. Every assignment is exactly one physical line in `NAME=VALUE` form.
3. `NAME` must be one of the currently referenced secret names returned by
   `_production_secret_reference_names(config)`.
4. Every required referenced name appears **exactly once**.
5. Reject duplicate assignments, unknown/unrelated environment keys and
   `export NAME=...` forms.
6. `VALUE` is non-empty and is used byte-for-byte after UTF-8 decoding and
   line-ending removal. Reject syntax that would make systemd transform the
   value: quoting, backslash escaping, backslash-newline continuation,
   embedded/leading/trailing whitespace or control characters.
7. `=`, URL punctuation, `#` and `;` inside the value are allowed; they
   are data, not inline comments.
8. Never print, persist, return through reports/APIs, put on argv or commit a
   resolved value.

If a future requirement genuinely needs richer systemd EnvironmentFile syntax,
that must be a separate explicitly tested package; do not silently broaden the
parser in R2.

## 4. Path and metadata boundary

Keep the R1 path/type/mode checks and strengthen only what is necessary for
unambiguous unit serialization and actual auditability:

- configured path remains absolute and lexically inside the production private
  root;
- resolved file remains inside that root and must be a regular file;
- group/world permission bits remain rejected;
- reject control characters/newlines in the configured EnvironmentFile path;
- do not auto-chmod, rewrite or normalize the owner's credential file;
- the canonical reader must successfully open/read the file in the harness
  context; an unreadable file is a fail-closed
  `MANUAL_SECRET_REFERENCE_REQUIRED` boundary.

Do not claim service-effective values if the harness cannot read and validate
the exact file content it is scanning.

## 5. Render gating must become truthful

Before writing a delivery-enabled unit, `cmd_render()` must run the same
canonical credential validation used by preflight/scanning and prove:

- metadata/path boundary is valid;
- file is readable;
- every required referenced name exists exactly once;
- every accepted value satisfies the canonical syntax;
- no unknown assignment can alter the service process environment.

Any failure stops at `MANUAL_SECRET_REFERENCE_REQUIRED` with all six
disclosure items and the existing exact `_resume_command(..., "render")`.
Do not write secret values into the marker.

Prefer failing before unit/config artifacts are written. Add a deterministic
assertion that an invalid credential file does not leave a newly rendered
delivery-enabled unit behind.

## 6. One source of truth for effective secret values

After canonical validation, the same in-memory parsed values must feed:

- preflight tracked-file secret scanning;
- verify and live-proof journal redaction;
- D3 payload secret scanning;
- live-proof/recover-proof/report artifact scans;
- serialized-report guards;
- delivery completeness checks.

Do not maintain separate parsing logic for render, scans and delivery.

Process-environment values remain part of the R1 effective scan set exactly as
before; when process and file values differ, both remain scanned/redacted.

## 7. Required deterministic regressions

Add tests that fail on current main and pass only after R2:

1. **Unquoted backslash escape mismatch** — a file value containing a systemd
   escape is rejected before it can be treated as a service-effective secret.
2. **Backslash-newline continuation** — rejected deterministically.
3. **Quoted/multiline syntax** — single/double quoted or multiline values are
   rejected rather than approximately parsed.
4. **Missing required reference** — render stops at
   `MANUAL_SECRET_REFERENCE_REQUIRED`.
5. **Duplicate required reference** — rejected.
6. **Unknown environment key** — rejected so the credential file cannot inject
   unrelated process environment.
7. **Unreadable credential file** — render/preflight use the precise manual
   boundary and do not claim success.
8. **Canonical positive case** — URL/token punctuation including additional
   `=`, `#`, `;`, `?`, `&`, `%` is preserved byte-for-byte and all
   scan/redaction paths see the exact value.
9. **Dual-source mismatch remains covered** — R1 behavior stays intact.
10. **Delivery-disabled compatibility** — existing production monitoring-only
    behavior stays unchanged.
11. **No render artifact on rejected credential syntax** — prove the failure
    occurs before a new delivery-enabled unit is emitted.
12. A fail-on-main proof: demonstrate at least the semantic-mismatch and
    render-completeness regressions fail against pre-R2 main.

Tests must be offline, deterministic and host-mutation-free. No real secret or
notification destination is required.

## 8. Automatic verification

Run all machine-verifiable checks yourself. At minimum:

```text
python -m ruff check .
python -m turtle_value_engine config validate --input config/project.example.toml
python -m pytest tests/test_monitoring_production_ops.py
python -m pytest tests/test_monitoring_live_acceptance.py
python -m pytest tests/test_monitoring*.py
python -m pytest
systemd-analyze verify deploy/monitoring/turtle-value-monitor.service deploy/monitoring/turtle-value-monitor.timer
python scripts/export_surface_openapi.py --check
pnpm --dir apps/dashboard install --frozen-lockfile
pnpm --dir apps/dashboard api:check
pnpm --dir apps/dashboard types:check
pnpm --dir apps/dashboard lint
pnpm --dir apps/dashboard typecheck
pnpm --dir apps/dashboard test --run
pnpm --dir apps/dashboard build
pnpm --dir apps/dashboard security:client-bundle
pnpm --dir apps/dashboard exec wrangler deploy --dry-run --config wrangler.jsonc --strict
python scripts/dashboard_cross_stack_smoke.py
```

Use the repository gate helper when it already covers the same checks. Record
real commands/results; do not replace execution evidence with prose.

If the existing private production config is available, automatically rerun
only these non-destructive current-head checks after the code change:

```text
python scripts/monitoring_production_ops.py --production-config <real-config> gate
python scripts/monitoring_production_ops.py --production-config <real-config> preflight --require-clean-tree
python scripts/monitoring_production_ops.py --production-config <real-config> verify --expect-active
python scripts/monitoring_production_ops.py --production-config <real-config> report
```

Do **not** enable delivery, send Telegram/webhook traffic, rerun bounded live
provider firing, reboot Windows or perform a recovery drill merely as ceremony.
R2 changes only dormant delivery-credential parsing/gating.

If the private config is unavailable to the coding environment, do not ask the
owner to reconstruct it. Deterministic/CI closure is sufficient because the
accepted production deployment has delivery disabled.

## 9. CI closure rule

Push the exact implementation SHA and query GitHub Actions.

R2 is CLOSED only when:

- the required workflow run has `head_sha` exactly equal to the implementation
  SHA and `conclusion=success`;
- focused R2 regressions and the R1 production-ops tests pass;
- the full Python/Dashboard/systemd/cross-stack gate passes;
- fail-on-main evidence is recorded for the new regressions;
- no resolved secret value appears in tracked/generated/test-output artifacts;
- a dated closure record contains the exact SHA, Actions run ID/result and
  concrete test counts/results.

Do not close from local tests alone.

## 10. Manual boundary

**No planned manual verification.**

Do not ask the owner to paste credentials, create a Telegram bot/webhook, edit a
private file for test purposes, reboot Windows, run sudo, inspect logs or
manually compare hashes.

If an unexpected authority limitation blocks an automatic step, record all of:

1. exact command attempted;
2. exact human action required;
3. exact secret/data boundary;
4. exact parser-valid resume command;
5. machine-verifiable success condition;
6. exact remainder that is still unverified.

Do not use vague language such as "evidence not fully recorded".

## 11. Stop boundary

Stop when canonical EnvironmentFile syntax, render completeness/readability
gating, effective-value reuse, deterministic regressions, full automatic gate
and exact-head CI closure are complete.

Do not start Phase 7, FQGate/Bridge integration, provider expansion, new
notification vendors, trading/brokerage work, investment-rule changes or
Windows-autostart implementation.
