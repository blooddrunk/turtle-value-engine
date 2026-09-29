# Phase 6-F-R3 — Runtime Credential Drift and Service-Effective Gate Hardening

Status: **SELECTED / NOT IMPLEMENTED**  
Date: 2026-09-29  
Selected after: Phase 6-F-R2 post-closure review

Selection audit:
`docs/status/phase-6-f-r2-post-closure-review-2026-09-29.md`

Predecessor:
`docs/goals/phase-6-f-r2-environmentfile-semantic-hardening.md`

Predecessor closure:
`docs/status/phase-6-f-r2-2026-09-29.md`

Coding-agent handoff:
`docs/status/phase-6-f-r3-next-coding-agent-goal.md`

## 1. Objective

Make the R2 canonical credential contract hold at **service execution time**,
not only at render time.

For delivery-enabled production, no scheduled or manually started
`unattended-notify` process may run unless the current private credential file:

1. satisfies the R1 path/type/permission boundary;
2. satisfies the R2 canonical content grammar;
3. contains exactly the referenced names;
4. contains only systemd-valid Unicode scalar values; and
5. produces referenced bytes that exactly equal the environment values systemd
   injected into the pre-start service context.

No secret value, secret-derived digest or secret-bearing environment dump may
be persisted or printed.

The accepted production deployment remains delivery-disabled and Phase 6-F
remains `CLOSED / OWNER_ACCEPTED`.

## 2. Frozen boundaries

Do not change or reinterpret:

- Phase 6-A/6-B/6-C event, acquisition or re-analysis semantics;
- D1 cycle/outbox identity;
- D2A/R1 lease/recovery semantics;
- D2B/R1/R2 delivery identity, claim or retry-budget semantics;
- D3/R1 read-only projection;
- Phase 6-F cadence, timer persistence, convergence or accepted WSL claim;
- R1 effective secret scanning/resume-command behavior except where R3 must
  fail closed on a current invalid credential;
- R2 canonical `NAME=VALUE` subset except for the systemd-valid Unicode
  correction below;
- `strict-v1`, valuation, gates, adjustments and investment rules.

Do not add Phase 7, FQGate/Bridge integration, a provider, a notification
vendor, brokerage/trading behavior, a remote secret manager,
M4-D/M4-E/M2-D or Windows host autostart.

## 3. Close the remaining systemd character-parity gap

The canonical reader must reject systemd-invalid characters **anywhere in the
decoded EnvironmentFile**, including comments and values:

- `U+0000`;
- `U+FEFF`;
- Unicode noncharacters `U+FDD0..U+FDEF`;
- every code point whose low 16 bits are `FFFE` or `FFFF`.

Strict UTF-8 decoding already rejects non-scalar surrogate encodings and must
remain.

Do not broaden the R2 grammar. It is acceptable and intentional for the TVE
canonical subset to be narrower than systemd (for example it may continue to
reject whitespace/control/quoted/escaped values that systemd could accept).
The invariant is: **systemd must accept every file TVE calls canonical**.

Rejection reasons remain category/line based and must never echo credential
content.

## 4. One current-credential validation primitive

Create one internal validation operation that combines:

- R1 metadata/path/type/mode validation;
- R2 canonical parsing and referenced-name completeness;
- R3 whole-file systemd-valid Unicode validation.

It may return parsed referenced values **in process memory only** plus
non-secret public status/metadata. All lifecycle checks below must reuse this
operation rather than implementing separate parsing rules.

Do not persist raw values or a digest/HMAC/fingerprint derived from credential
content.

## 5. Lifecycle drift gates

When `delivery_enabled=true`:

### 5.1 apply / converge

Immediately before any install, daemon-reload or timer-enable mutation,
revalidate the current credential contract.

If the file drifted after render, fail closed before system mutation. The
operator must rerun the existing canonical resume path after fixing the private
file; no secret value appears in the error.

### 5.2 activate

Revalidate before enabling or starting the timer. If invalid, authorize zero
timer-start/enable actions.

### 5.3 verify

Add an explicit current credential-contract check. A delivery-enabled
deployment with a missing/unreadable/non-canonical credential must make verify
non-green even if units, timer state and old records are otherwise healthy.

Verify stays non-mutating.

### 5.4 report

A delivery-enabled report must include a secret-free current credential
contract summary and fail closed instead of returning
`PRODUCTION_DEPLOYED` when the current credential contract is invalid.

Never suppress this failure merely because old apply/activation/verify records
were green.

### 5.5 deactivate

Safe deactivation must remain possible even when the credential file is
missing or invalid. Do not make credential validity a prerequisite for
stopping/disabling the timer.

## 6. Service-execution pre-start gate

A delivery-enabled rendered service must contain an explicit
`ExecStartPre=` (or an equivalently strong systemd ordering mechanism) before
the unchanged `unattended-notify` `ExecStart=`.

The pre-start checker must:

1. use the same current-credential validation primitive;
2. receive only non-secret path/reference/config facts through argv/unit
   metadata;
3. see the environment that systemd would pass to the service;
4. for every referenced name, compare the inherited value byte-for-byte with
   the canonical parser's in-memory value;
5. return success only when metadata, canonicality, completeness and byte
   equality all hold;
6. return nonzero before `unattended-notify` on any missing/mismatch/drift;
7. print only value-free status/reference names/categories.

The unit must preserve the existing `ExecStart=` delivery command and delivery
ledger semantics.

The implementation may either embed the exact production-config path in the
pre-start command or render a separate non-secret gate specification. Whichever
is chosen must be deterministic, parser-valid, and verified against the
installed unit. Do not put secret values or secret-derived fingerprints in the
unit or gate artifact.

## 7. Runtime safety invariant

After R3, this sequence must be safe:

1. render/apply/activate with a valid canonical credential;
2. owner later edits the private credential file;
3. the edited file becomes non-canonical but is still syntactically accepted by
   systemd;
4. the next timer firing reaches the pre-start gate;
5. pre-start fails value-free;
6. `unattended-notify` is not executed and no delivery dispatch slot is
   consumed.

The same must hold for a canonical file whose systemd-inherited referenced
value does not byte-match the current parsed file value.

## 8. Existing restart proof

Upgrade or reuse the recover-proof service-context credential check so it proves
byte equality, not only non-empty presence, while still emitting no value.

Do not depend on recover-proof as the only runtime guard: every delivery
service start must be protected by the rendered pre-start gate.

## 9. Required deterministic regressions

Add focused tests that fail on current R2 main and pass only after R3. At
minimum:

1. `U+FEFF` in a value is rejected.
2. Unicode noncharacters are rejected, covering both `U+FDD0` and a
   plane-ending `U+FFFF`/equivalent.
3. A systemd-invalid character in a comment is also rejected (whole-file
   validation, not value-only validation).
4. Valid canonical render followed by credential drift before `apply`
   causes apply to fail before install/reload/enable mutations.
5. Drift after apply but before `activate` causes zero enable/start actions.
6. `verify` is non-green on current credential drift.
7. `report` cannot emit `PRODUCTION_DEPLOYED` on current credential drift.
8. Safe `deactivate` still works when the credential is invalid/missing.
9. Delivery-enabled unit contains the expected pre-start gate before the
   unchanged `unattended-notify` ExecStart and passes
   `systemd-analyze verify`.
10. Pre-start checker succeeds for canonical file + byte-identical inherited
    referenced values.
11. Pre-start checker fails on missing or byte-mismatched inherited reference
    without printing either value.
12. Pre-start checker rejects a post-render systemd-valid but TVE-noncanonical
    quoted/escaped credential and authorizes no unattended-notify work.
13. R1 dual-source scan/redaction semantics remain intact.
14. Delivery-disabled service bytes/behavior remain compatible (no credential
    pre-start gate).
15. Fail-on-main proof records the runtime-drift and Unicode regressions
    failing against pre-R3 main.

Tests must remain deterministic, offline and host-mutation-free. Use fake
runners/service-context injections where needed; no real Telegram bot, webhook
or owner credential is required.

## 10. Automatic verification

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

Also run the focused pre-start/unit regressions explicitly so their output is
recorded separately from the full suite.

If the execution host has a usable systemd user/system manager and an
ephemeral fake-sentinel test can be performed without owner secrets, network
delivery or persistent host mutation, the coding agent should automatically
run that bounded integration proof as additional evidence. It is not a reason
to ask the owner for manual steps.

If the existing private production config is available, automatically rerun
the existing non-destructive delivery-disabled production checks:

```text
python scripts/monitoring_production_ops.py --production-config <real-config> gate
python scripts/monitoring_production_ops.py --production-config <real-config> preflight --require-clean-tree
python scripts/monitoring_production_ops.py --production-config <real-config> verify --expect-active
python scripts/monitoring_production_ops.py --production-config <real-config> report
```

Do not enable real delivery, send Telegram/webhook traffic, reboot Windows or
rerun live provider/recovery drills merely as ceremony.

## 11. CI closure rule

Push the exact implementation SHA and query GitHub Actions.

R3 is CLOSED only when:

- required CI has exact implementation `head_sha` and
  `conclusion=success`;
- focused runtime-drift/Unicode/pre-start regressions pass;
- fail-on-main evidence is recorded;
- the full Python/Dashboard/systemd/cross-stack gate passes;
- installed/rendered delivery unit semantics preserve the runtime pre-start
  gate;
- no credential value or credential-derived fingerprint appears in tracked,
  generated or test-output artifacts;
- a dated closure record contains exact SHA, run ID/result and concrete test
  counts/results.

Do not close from local tests alone.

## 12. Manual boundary

**No planned manual verification.**

Do not ask the owner to paste credentials, edit a real production secret file,
create a Telegram bot/webhook, inspect logs, compare hashes, reboot Windows or
run sudo for R3 closure.

If an unexpected authority limitation blocks an automatic step, record all six
items explicitly:

1. exact command attempted;
2. exact human action required;
3. exact secret/data boundary;
4. exact parser-valid resume command;
5. machine-verifiable success condition;
6. exact remainder still unverified.

Never replace these with vague language such as "evidence not fully recorded".

## 13. Stop boundary

Stop after runtime credential drift is blocked at lifecycle and per-service
execution boundaries, Unicode parity is closed, deterministic regressions pass,
the full automatic gate is green and exact-head CI closure is recorded.

Do not start Phase 7, Bridge/FQGate integration, provider expansion, new
notification vendors, brokerage/trading, investment-rule changes,
Windows-autostart implementation or a broader secret-management migration.
