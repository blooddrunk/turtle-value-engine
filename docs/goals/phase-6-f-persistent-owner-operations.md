# Phase 6-F — Persistent Owner Operations Hardening

Status: **CLOSED / OWNER_ACCEPTED**
(final implementation `065b53a17bcb4f009a57ef918ffa3d59de135107`, exact-head
Actions run `36515225218` `success`; the owner-authorized real production
deployment on the accepted WSL2 host passed automated preflight, plan,
render, apply/converge (idempotent), explicit activation, bounded firing,
replay/no-duplicate, D3 read-only observation, restart/recovery and verify,
with the production timer intentionally left enabled and the persistence
claim narrowed to the running distro/user manager — see
`docs/status/phase-6-f-2026-09-29.md`)
Selected: 2026-09-28  
Closed: 2026-09-29  
Predecessor: Phase 6-E `CLOSED / OWNER_ACCEPTED`  
Predecessor implementation: `8565621777762c601172aee562b2523a37ce02a6`  
Predecessor CI: Actions run `36375649575` (`success`, exact `head_sha`)  
PR #3 merge baseline: `b0eca4c2f518a7562b6209833f85bf3de553842f`

Selection record:
`docs/status/phase-6-f-selection-2026-09-28.md`

Coding-agent handoff:
`docs/status/phase-6-f-next-coding-agent-goal.md`

## 1. Objective

Turn the already-proven Phase 6-E single-host chain into an intentionally
owner-authorized, restart-resilient long-lived monitoring operation.

Phase 6-E proved the real chain and then deliberately disabled its acceptance
timer. Its real host was WSL2 with systemd PID 1 and user-level units; the
record also observed `Linger=no`. Phase 6-F must close the operational gap
between "the bounded acceptance can run" and "the owner's selected monitoring
runtime can remain enabled and auditable without an interactive terminal."

This is **operational hardening, not feature expansion**. Reuse the closed
chain:

```text
Phase 6-B bounded acquisition
  -> Phase 6-A planning/cursor commit
  -> Phase 6-C controlled re-analysis
  -> D1 cycle/outbox
  -> D2A/R1 unattended runner + authoritative lease
  -> optional D2B/R1/R2 delivery
  -> D3/R1 read-only operations projection
```

## 2. Automation-first rule

Automate every machine-verifiable action. Do not turn Phase 6-F into a runbook
that asks the owner to inspect services, compare files, read logs or infer
internal states.

The implementation must provide one coherent operator surface (extend the
Phase 6-E helper when that is the smallest safe design, otherwise add a
dedicated production-operations helper) with equivalent capabilities for:

- non-mutating `preflight` / `plan`;
- deterministic render;
- apply/converge;
- explicit production activation;
- verification/reporting;
- safe deactivation/rollback.

A human action is allowed only when the current execution identity genuinely
lacks authority or information that cannot be derived safely. Every manual
boundary must be named and must contain **all six** items:

1. exact command the agent ran immediately before stopping;
2. exact human action required;
3. exact secret/data handling boundary;
4. exact command the agent will run to resume;
5. exact machine-verifiable success condition;
6. exact remainder that stays unverified if the operator stops there.

Forbidden closure language includes "manual verification recommended",
"please inspect the service", "evidence not fully recorded" and equivalent
vague statements.

## 3. Frozen boundaries

Do not change or reinterpret:

- Phase 6-A cursor/PIT/event semantics;
- Phase 6-B provider scope or network-deny-by-default behavior;
- Phase 6-C execution/review boundaries;
- D1 cycle/outbox identities;
- D2A/R1 lease/single-flight/recovery semantics;
- D2B/R1/R2 delivery identity, dispatch-claim and retry-budget semantics;
- D3/R1 read-only/non-interfering projection semantics;
- `strict-v1`, valuation, hard gates, adjustment approval or investment
  decision semantics.

Do **not** add Bridge/FQGate provider expansion, M4-D/M4-E/M2-D, Slack/email
transports, brokerage/order/funds operations, new market-data licensing work,
or autonomous rule/profile mutation.

## 4. Production configuration boundary

Acceptance and production must be distinct.

The helper must refuse to silently promote the Phase 6-E isolated acceptance
workspace into a production workspace. A production deployment must use
explicit typed non-secret inputs for at least:

- production runner id and watchlist/config paths;
- production workspace / runner / cycle / delivery roots;
- systemd scope and unit name;
- cadence and jitter;
- Python executable / working directory / service identity;
- network policy;
- notification enabled/disabled state and only secret **references**, never
  resolved values.

`plan` must be deterministic, redacted and mutation-free. It must show the
effective target paths/unit names/config identities/hashes and whether the
operation would install, modify, enable, disable or leave each resource
unchanged.

Re-running apply/converge against the same desired state must be idempotent.

## 5. Host-lifecycle persistence proof

The deployment must not infer persistence from a template.

Automatically inspect and record the real host/runtime topology. At minimum:

- Linux/systemd availability and PID 1 facts;
- native Linux vs WSL2 detection;
- effective unit/timer hashes and `systemctl show` properties;
- timer `Persistent=true`, enabled/active state and next/last trigger;
- effective `ExecStart`, working directory and service identity;
- the same D3-R1 kernel-lock visibility proof used by the real runner/status
  contexts.

For **user-scope** deployment, persistence outside an interactive login must be
proven from the real user manager. Check `loginctl show-user <user> -p Linger`.
If `Linger=no` and non-interactive privilege can enable it safely, automate
that action and verify the effective property afterwards. Otherwise stop at a
named `MANUAL_ENABLE_LINGER_REQUIRED` boundary with the six required items.

For **system-scope** deployment, install/reload/enable automatically when
privilege exists; otherwise use `MANUAL_SUDO_INSTALL_REQUIRED` with exact
generated paths and commands, then independently verify effective state after
resume.

Because the accepted host is WSL2, do not claim Windows-reboot persistence
from Linux systemd evidence alone. Probe what can be proven from the current
execution environment. If Windows-side boot/distro-start authority is
available, automate a bounded bootstrap proof using generated, reviewable
material. If it is not available, record a precise
`WINDOWS_HOST_BOOTSTRAP_UNPROVEN` capability boundary; this boundary may
limit the claim to "persistent while the WSL distro/user manager is running"
but must not be disguised as full machine-reboot persistence.

A physical host reboot is **not** required merely to make CI green.

## 6. Notification/service credential boundary

Notifications remain optional. A production monitoring-only deployment may
close Phase 6-F with delivery disabled.

If the owner selects Telegram or a custom webhook for the production service,
the service identity must be able to resolve the existing typed
`SecretReference` after a service/user-manager restart without embedding
secret values in:

- Git;
- generated unit text or command-line arguments;
- project/runner config;
- delivery ledger artifacts;
- reports/logs;
- Dashboard/API/browser payloads.

Do not treat an interactive-shell `export` as restart-persistent production
credential configuration. Implement the smallest typed local credential
source/injection path needed for the selected host while preserving the
current environment-reference CLI behavior.

If a secret is genuinely absent, stop at
`MANUAL_SECRET_REFERENCE_REQUIRED` with the exact six-item boundary. Never
ask the owner to paste a token into chat or commit it.

## 7. Activation and bounded live proof

Production activation must be explicit; rendering/applying configuration must
not silently start recurring work.

Once owner authorization is present, automate the activation and prove:

1. the intended timer is enabled and active;
2. one bounded immediate or scheduled firing executes the real production
   runner config;
3. the terminal runner receipt is valid and linked to the expected
   activation/cycle;
4. a second/repeated wake cannot manufacture duplicate D1 work;
5. read-only D3 polling changes no file bytes and cannot induce
   `LEASE_BUSY`;
6. if notification is enabled, its delivery ledger reaches the appropriate
   truthful state and a delivered identity replays with zero extra outbound
   dispatch;
7. no acceptance-root state is mutated by the production run;
8. no secret/path leak appears in persisted/public projections.

Leave the owner-authorized production timer **enabled** only when closure is
being claimed for the production deployment. The safe deactivation command
must remain available and idempotent.

## 8. Restart/recovery proof

Do not use a host reboot as a substitute for deterministic recovery tests.

Automate the strongest non-destructive proof supported by the host, including:

- daemon reload/re-exec or equivalent manager refresh;
- service/timer stop/start where safe;
- runner restart from existing durable state;
- unchanged production configuration identity;
- no duplicate activation/cycle/delivery;
- timer remains enabled/active after the manager operation;
- credential resolvability survives the selected service restart when
  notification is enabled.

Reuse existing crash/replay hooks and Phase 6-E evidence; do not invent a
general-purpose unsafe crash switch.

## 9. Secret-free production operations report

Persist a machine-readable report under an ignored private operations root.
It must bind evidence to the exact code/config/unit identities and contain no
secret values.

At minimum record:

- implementation SHA and deterministic gate result;
- host/runtime topology and support classification;
- desired/effective unit hashes;
- scope, cadence, linger/persistence facts;
- production runner/watchlist/config identities;
- activation/cycle/receipt identities from the bounded live proof;
- timer enabled/active/last/next trigger facts;
- delivery state/counts only when delivery is enabled;
- D3 read-only projection result;
- secret scan result;
- every manual/capability marker actually crossed.

## 10. Mandatory automatic verification

Before host mutation and again after any executable change, run the complete
repository gate. At minimum:

```text
python -m ruff check .
python -m turtle_value_engine config validate --input config/project.example.toml
python -m pytest tests/test_monitoring*.py
python -m pytest
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
systemd-analyze verify deploy/monitoring/turtle-value-monitor.service deploy/monitoring/turtle-value-monitor.timer
```

Add deterministic tests for every new production-operations behavior:
no-mutation plan, convergence/idempotency, effective-state verification,
user/system privilege simulation, linger classification, WSL capability
classification, redaction, secret absence, activation/deactivation, restart
proof and report validation.

Ordinary CI must remain network-free/model-free except existing explicitly
opt-in live tests.

## 11. CI and closure discipline

For every executable implementation candidate, push the exact SHA and query
GitHub Actions. Fix failures yourself. Do not close from local tests alone.

Phase 6-F is `CLOSED / OWNER_ACCEPTED` only when:

1. the implementation SHA has a required Actions run with exactly matching
   `head_sha` and `conclusion=success`;
2. the owner-authorized production configuration passed automated preflight,
   apply/converge, activation and verify on the selected real host;
3. the timer is intentionally left enabled/active;
4. one bounded production firing and recovery proof are machine-verified;
5. any enabled notification passed its own durable delivery verification;
6. the secret-free production operations report has zero unexplained
   failures/markers.

If software is complete but owner production activation is not authorized or a
required human boundary has not been crossed, use
`READY_FOR_OWNER_AUTHORIZED_PHASE_6F`, not CLOSED.

A WSL deployment may close with a narrower host claim only if the report
explicitly says what was and was not proven. It must not claim Windows reboot
autostart without machine-verifiable Windows-side evidence.

## 12. Stop boundary

Stop after long-lived owner-runtime convergence and its bounded production
proof.

Do not start Phase 7 controlled-evolution implementation, provider expansion,
Bridge/FQGate integration, M4-D/M4-E/M2-D, new notification vendors,
brokerage/trading behavior or investment-rule changes.

## 13. Implementation and closure record

Implemented as `scripts/monitoring_production_ops.py` (typed
`ProductionConfigV1` with hard acceptance/production separation, modes
`gate`/`preflight`/`plan`/`render`/`apply`(`converge`)/`activate`/`verify`/
`live-proof`/`recover-proof`/`deactivate`/`report`), checked-in template
`config/monitoring-production.example.json`, a `deploy/monitoring/README.md`
lifecycle section and 39 deterministic tests in
`tests/test_monitoring_production_ops.py`; the Phase 6-E harness helpers
were generalized to structural Protocols and reused rather than duplicated.
Superseded exact-head-green pushes `bb074de3`, `4e68090e` and `0ee74e21`
each closed a defect the live deployment itself exposed (D3 path-type
crash, frozen-PIT proof assumptions, activate-after-deactivate leaving the
timer active-but-disabled).

The real-host production deployment (user-scope units
`tve-production-monitor.{service,timer}`, runner `production-owner`,
watchlist `SH600519`+`SZ000858`, rolling 7-day window, daily cadence,
monitoring-only with delivery disabled) closed at the final SHA with
`phase_state: PRODUCTION_DEPLOYED` in the secret-free report
`.tve-private/monitoring/production/production-report.json`: linger was
enabled automatically (`Linger=yes`), apply converged idempotently without
ever starting recurring work, the bounded firing and replay proved
`CYCLE_TERMINAL`/`NO_CHANGE` with no duplicate D1 work, D3 stayed read-only
and non-interfering, daemon-reload/reexec plus timer stop/start proved
durable recovery with unchanged configuration identity, the acceptance tree
stayed byte-unchanged, and the production timer is intentionally left
enabled and active. The single recorded marker is the non-blocking
`WINDOWS_HOST_BOOTSTRAP_UNPROVEN` capability boundary narrowing the
persistence claim to the running WSL distro/user manager. Full evidence:
`docs/status/phase-6-f-2026-09-29.md`.
