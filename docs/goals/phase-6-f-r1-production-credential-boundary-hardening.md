# Phase 6-F-R1 — Production Credential Boundary and Manual-Resume Hardening

Status: **SELECTED / NOT IMPLEMENTED**  
Date: 2026-09-29  
Selected after: Phase 6-F post-closure review

Selection audit:
`docs/status/phase-6-f-r1-selection-2026-09-29.md`

Predecessor:
`docs/goals/phase-6-f-persistent-owner-operations.md`

Predecessor closure:
`docs/status/phase-6-f-2026-09-29.md`

Coding-agent handoff:
`docs/status/phase-6-f-r1-next-coding-agent-goal.md`

## 1. Objective

Close the narrow post-Phase-6-F audit findings in
`scripts/monitoring_production_ops.py` without reopening or expanding the
closed monitoring architecture.

R1 has two responsibilities:

1. make the typed production `EnvironmentFile` a genuinely auditable,
   private, service-effective secret source for leak scanning/redaction; and
2. make every Phase 6-F manual/capability boundary emit an exact, parser-valid,
   directly runnable resume command using the real production-config path.

Phase 6-F itself remains `CLOSED / OWNER_ACCEPTED`; the accepted deployment
has delivery disabled, so R1 is a hardening follow-on for dormant notification
and manual-boundary paths.

## 2. Frozen boundaries

Do not change or reinterpret:

- Phase 6-A cursor/PIT/event semantics;
- Phase 6-B acquisition/network-deny-by-default semantics;
- Phase 6-C re-analysis semantics;
- D1 cycle/outbox identities;
- D2A/R1 lease/single-flight/recovery semantics;
- D2B/R1/R2 delivery identity, dispatch-claim or retry-budget semantics;
- D3/R1 read-only/non-interfering observation;
- Phase 6-F activation, convergence, timer cadence or accepted WSL persistence
  claim;
- `strict-v1`, valuation, hard gates, accepted-adjustment or investment-rule
  semantics.

Do not add a provider, Bridge/FQGate integration, a notification vendor,
brokerage/trading behavior, Phase 7 controlled evolution, M4-D/M4-E/M2-D, or
a new remote secret manager.

## 3. Effective secret-source hardening

### 3.1 Scan/redaction values must include the service-effective EnvironmentFile

Refactor the scan/redaction helper so that, when delivery is enabled:

- only the **referenced** secret names are considered;
- values resolvable from the current process environment are included;
- values resolvable from the configured private `EnvironmentFile` are also
  included in memory;
- if both sources contain different values for the same reference, **both**
  values are scanned/redacted rather than silently dropping one;
- no resolved value is printed, persisted, returned through a report/API, put
  on argv, or written to Git;
- a missing/unreadable EnvironmentFile continues to use the existing precise
  fail-closed/manual-boundary semantics rather than fabricating a value.

Use this effective value set everywhere Phase 6-F claims secret scanning or
redaction, including at minimum:

- tracked-repository file scanning in preflight;
- bounded journal redaction in verify;
- production artifact scanning in live-proof/report;
- any other production-operations scan path found by a complete call-site
  audit.

Do not weaken the existing test that unit/config/report output contains only
secret references/paths, never values.

### 3.2 Enforce the private EnvironmentFile contract

When delivery is enabled, the configured file must be machine-checked as a
private local credential source.

At minimum:

- require its configured path to be inside the production private root;
- when the file exists, reject symlink/path resolution that escapes that root;
- require a regular file;
- reject group/world-readable or group/world-writable permissions (owner-only
  access; `0600` is the documented normal form);
- never chmod or rewrite the owner's secret file automatically merely to make a
  test pass;
- report only path/permission metadata, never content.

If the file is missing or insecure, stop at the existing
`MANUAL_SECRET_REFERENCE_REQUIRED` boundary with all six disclosure items.

## 4. Exact resume-command hardening

Audit every `ManualBoundary`/capability marker in
`scripts/monitoring_production_ops.py`.

At minimum fix these current defects:

- `windows_bootstrap_marker_payload` must receive/use the actual
  production-config path instead of `<config>`;
- `ensure_linger` must receive/use the actual production-config path instead
  of `<config>`;
- the missing-EnvironmentFile render boundary must use the same canonical
  `_resume_command(..., "render")` shape as other modes, not the invalid
  `render --production-config ...` ordering.

Prefer one canonical resume-command builder. Avoid hand-built CLI strings when
the helper can express the command.

For every manual/capability boundary, add a deterministic assertion that the
emitted command contains the exact resolved config path and that its argument
tail is accepted by `_build_parser()` for the intended mode. A placeholder
such as `<config>` is not acceptable in an emitted machine/action record.

The Windows bootstrap marker may remain non-blocking and may still narrow the
claim; R1 changes only the accuracy of its resume instructions.

## 5. Deterministic regression tests

Add focused tests that fail on the current main branch and pass only after the
fix.

Required cases include:

1. **EnvironmentFile-only leak detection** — put a referenced sentinel only in
   the EnvironmentFile (do not `setenv` it), place the sentinel in a
   production artifact, and prove report/live scan fails closed.
2. **EnvironmentFile-only journal redaction** — feed the sentinel through a
   fake journal result and prove the persisted/printed verify record contains
   no sentinel value.
3. **Dual-source mismatch** — process env and EnvironmentFile provide
   different values for the same reference; prove both are included in the
   scan/redaction set without either value being exposed by the test output.
4. **Private-root containment** — outside-root credential path is rejected.
5. **Symlink escape** — an in-root symlink resolving outside the private root
   is rejected.
6. **Permissions** — group/world-accessible file is rejected with the precise
   secret boundary; owner-private file is accepted.
7. **Resume parser round-trip** — Windows bootstrap, linger and render-secret
   boundaries all emit the exact real config path and parser-valid mode/args.
8. Existing delivery-disabled behavior remains byte/semantics compatible.

Keep tests deterministic, offline and host-mutation-free. Do not require a real
Telegram bot, webhook receiver, Windows reboot, sudo action, browser action or
owner secret.

## 6. Automatic verification

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

Use the repository's existing gate helper when it already runs the same checks;
do not replace real output with prose.

If the existing private production config is available in the execution
environment, also automatically rerun the **non-destructive** current-head
production checks after the code change:

```text
python scripts/monitoring_production_ops.py --production-config <real-config> gate
python scripts/monitoring_production_ops.py --production-config <real-config> preflight --require-clean-tree
python scripts/monitoring_production_ops.py --production-config <real-config> verify --expect-active
python scripts/monitoring_production_ops.py --production-config <real-config> report
```

Do not rerun bounded live provider firing, restart/recovery or delivery merely
as ceremony: R1 does not change those semantics. If the private config is not
available to the coding environment, do not ask the owner to reconstruct it;
record that the deterministic R1 closure does not claim a fresh real-host
deployment proof.

## 7. CI closure rule

Push the exact implementation SHA and query GitHub Actions.

R1 is CLOSED only when:

- the required workflow run has `head_sha` exactly equal to the implementation
  SHA and `conclusion=success`;
- all required focused regressions pass;
- the full Python suite and existing Dashboard/systemd/cross-stack gates pass;
- no resolved secret value is present in tracked/generated/test-output
  artifacts;
- the closure document records exact SHA, Actions run ID/result and test
  counts/results.

Do not close from local tests alone.

## 8. Manual boundary

**No planned manual verification.**

Do not ask the owner to paste a token, create a real Telegram bot, send a real
webhook, reboot Windows, inspect a log, compare hashes or infer service state
for R1 closure.

If an unexpected authority limitation genuinely blocks an automatic step,
record the exact command attempted, exact human action, secret/data boundary,
exact resume command, machine-verifiable success condition and exact
unverified remainder. Do not write "evidence not fully recorded" or equivalent
vague language.

## 9. Stop boundary

Stop after the credential-source and resume-command defects are fixed,
regression-tested, fully gated and exact-head CI-green.

Do not start Phase 7, Bridge/FQGate integration, provider expansion,
M4-D/M4-E/M2-D, additional notification vendors, brokerage/trading behavior,
Windows-autostart implementation or investment-rule/profile changes.
