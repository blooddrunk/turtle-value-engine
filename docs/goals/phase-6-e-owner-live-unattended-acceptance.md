# Phase 6-E — Owner Live Unattended Acceptance

Status: **ACTIVE** (harness implemented; exact-SHA CI and the bounded live
acceptance run recorded in `docs/status/phase-6-e-2026-09-24.md`)
Date: 2026-09-24
Selected after: Phase 6-D3-R1 closure

Predecessor closure:
`docs/status/phase-6-d3-r1-2026-09-24.md`

Selection record:
`docs/status/phase-6-e-selection-2026-09-24.md`

Coding-agent handoff:
`docs/status/phase-6-e-next-coding-agent-goal.md`

## 1. Objective

Prove the already-implemented Phase 6 monitoring chain on one real,
owner-authorized persistent Linux host without turning live acceptance into a
manual checklist.

The acceptance target is the existing chain, not new product scope:

```text
bounded real watchlist
  -> Phase 6-B bounded CNINFO acquisition
  -> Phase 6-A planning/cursor commit
  -> Phase 6-C re-analysis boundary
  -> D1 cycle + alert outbox
  -> D2A unattended runner / durable activation + receipt
  -> D2B/R1/R2 generic webhook delivery ledger
  -> D3/R1 read-only operations projection
  -> existing private API / Worker / Dashboard
```

Phase 6-E must prove, with machine-verifiable evidence wherever technically
possible:

1. real bounded event acquisition on the owner-authorized host;
2. unattended systemd execution at an explicit cadence;
3. restart/replay/idempotency behavior against the durable runner artifacts;
4. real generic webhook delivery and durable delivery accounting;
5. read-only monitoring status through the real surface;
6. no secret leakage, no unexpected mutation and no duplicate work caused by
   status observation;
7. the exact host topology satisfies the D3-R1 passive-lock observation
   assumptions.

This phase does not authorize trading, investment-rule mutation, source
expansion or vendor-specific notification adapters.

## 2. Automation-first acceptance rule

Phase 6-E is not a request for the owner to collect screenshots, inspect logs
by hand, edit unit files manually or translate internal state names into
"evidence".

The coding agent must automate every machine-verifiable step, including host
preflight, configuration validation, unit rendering/validation, bounded live
probe, replay comparison, service/timer verification, runner/delivery status,
monitoring API checks, evidence collection and secret scanning.

A human action is permitted only when the current execution identity genuinely
lacks authority or information that cannot be derived safely, for example:

- supplying an owner-selected non-secret host/cadence fact;
- making a secret reference available in an approved secret manager or
  environment without revealing its value;
- executing a privileged systemd installation command when non-interactive
  sudo is unavailable;
- confirming receipt in a destination that exposes no machine-readable receipt
  API;
- completing a genuinely interactive external login/consent/CAPTCHA boundary.

Every such boundary must use a named marker and include all six items:

1. exact command the agent ran immediately before stopping;
2. exact human action required;
3. exact secret/data handling boundary;
4. exact command the agent will run to resume;
5. exact machine-verifiable success condition;
6. exact remainder that would stay unverified if the operator stops there.

Do not use phrases such as "manual verification recommended", "evidence not
fully recorded", "please inspect the service" or equivalent vague closure
language.

If owner inputs are absent, the software/harness work may be completed, but
Phase 6-E itself remains explicitly
`READY_FOR_OWNER_AUTHORIZED_PHASE_6E`; it must not be marked CLOSED.

## 3. Frozen boundaries

Preserve all previously closed semantics:

- Phase 6-A watchlist/event contracts and cursor commit semantics;
- Phase 6-B source scope, PIT/provenance and network-deny-by-default behavior;
- Phase 6-C execution/review boundaries;
- D1 cycle/outbox identity and replay semantics;
- D2A/R1 authoritative single-host `flock` lease and fail-closed behavior;
- D2B/R1/R2 dispatch-claim, retry-budget, deadline, pointer and no-duplicate
  semantics;
- D3/R1 read-only projection, non-interfering lease observation, secret hygiene
  and zero mutation controls;
- `strict-v1`, valuation, hard gates, adjustment approval and all investment
  decision semantics.

Do not add Slack/Telegram/email-specific transports, scheduled GitHub Actions
monitoring, Bridge/FQGate source expansion, M4-D/M4-E/M2-D, brokerage/order/
funds behavior or autonomous rule mutation.

## 4. Required automation surface

Before live owner acceptance, inspect the existing deployment helpers and add
the smallest coherent automation needed so the phase can be run and audited
without hand-editing systemd files or manually assembling evidence.

A dedicated helper such as
`scripts/monitoring_live_acceptance.py` is appropriate if no existing helper
cleanly owns this workflow. Exact naming is not prescribed, but the resulting
surface must have equivalent machine-readable modes:

### 4.1 preflight

A non-mutating preflight must automatically verify at minimum:

- Linux host and supported Python/runtime;
- systemd availability and checked-in unit validity;
- repository checkout identity and clean/expected revision;
- explicit owner working directory, Python executable, service user and
  cadence inputs;
- runner/project/watchlist configuration parses against the typed contracts;
- live acquisition is explicitly enabled only for the acceptance config;
- delivery configuration is enabled only when an endpoint secret reference can
  be resolved at runtime; secret values are never printed;
- all runtime roots are owner-selected private paths and writable by the
  intended service identity;
- no checked-in file contains resolved owner credentials;
- the existing full deterministic repository gate is green before any live
  mutation;
- the actual deployment topology can observe the same kernel lease truth from
  the runner and D3/status contexts.

The last item is mandatory because D3-R1 uses passive `/proc/locks`
observation. On the actual host, use a private acceptance lease file and real
`flock` holder to prove that the intended runner execution context and the
status/API observation context see the same holder. Release it and prove the
slot becomes non-live without the observer ever acquiring the authoritative
lock.

The current supported claim is **single-host Linux/systemd**. Do not infer
container/PID-namespace support. If the supplied topology isolates lock-table
visibility, fail preflight with a precise marker such as
`DEPLOYMENT_LOCK_VISIBILITY_UNPROVEN`; either move both contexts to a proven
shared host/kernel view or explicitly scope a separate future portability
task.

### 4.2 render / dry-run

Generate finalized owner-specific service/timer material from explicit
non-secret inputs; do not ask the owner to open a unit file and replace
placeholders manually.

Automatically:

- render deterministic unit/drop-in content;
- keep all credential values out of unit files;
- run `systemd-analyze verify`;
- show a redacted diff/plan of exactly what would be installed;
- make dry-run idempotent and mutation-free.

### 4.3 apply

If the agent has sufficient privilege, install/reload/enable the units itself
and continue automatically.

If privileged installation genuinely requires the owner, stop only at
`MANUAL_SUDO_INSTALL_REQUIRED` and provide the exact generated source paths,
destination paths and exact `sudo install` / `systemctl` commands. After the
owner executes them, automation must resume and independently verify the files,
unit hashes, service/timer state and effective command line. A successful
human command is not itself acceptance evidence.

### 4.4 verify

Automatically inspect the actual installed deployment:

- `systemctl show` effective properties rather than trusting templates;
- timer enabled/active state and next/last trigger;
- service exit/result and bounded journal slice with secret redaction;
- exact runner config identity used by the service;
- runner status and immutable receipt/artifact identities;
- no unintended overlapping runner work;
- monitoring surface/API can read the same configured roots read-only.

Persist a bounded secret-free acceptance report under the ignored private
runtime tree, not in Git. A committed closure record may contain only
non-sensitive identities, hashes, classifications, counts and redacted facts.

## 5. Bounded real live acceptance

Do not wait for a random future disclosure merely to obtain evidence.

Use an isolated Phase 6-E acceptance workspace and a deliberately bounded
watchlist of one or two public listings. Select a short explicit historical
window containing a known recent public CNINFO disclosure, using the existing
Phase 6-B source contract only.

Automatically prove:

1. the live acquisition uses the explicit network-allow path and the bounded
   request/time/byte limits;
2. raw source payload stays only in the private cache boundary;
3. canonical event/batch hashes and provenance validate;
4. replaying the captured raw input with network blocked yields byte-identical
   canonical output;
5. the watchlist cursor advances only after the successful monitoring commit;
6. the resulting D1/runner artifacts are internally consistent and
   hash/identity linked;
7. a repeated read-only D3/status observation does not cause
   `LEASE_BUSY` or any mutation.

The acceptance workspace must be separate from any long-lived production
watchlist unless the owner explicitly selects the production workspace.

## 6. Restart, replay and idempotency proof

Prefer automated controlled proofs over arbitrary process killing.

First inspect the existing durable runner boundaries and test hooks. Use an
isolated acceptance root and the narrowest deterministic mechanism that proves
the real host can restart/resume from durable state without manufacturing a
second activation, changing the frozen PIT or repeating work already proven
terminal.

At minimum the live acceptance report must establish the contract-supported
restart/replay facts through persisted activation/receipt/cycle identities and
hashes. If a safe controlled interruption can be injected at an existing
durable boundary, automate it and resume with the real CLI/service.

Do not add a broad production "crash here" feature merely for acceptance. If a
new test-only/acceptance-only hook is necessary, it must be impossible to
activate accidentally in ordinary runtime and must have deterministic tests.

A completed activation replay/restart must never be counted as proof merely
because two commands both exited zero; compare the durable identities and
prove the expected no-duplicate invariant.

## 7. Real notification acceptance

Use only the existing generic HTTPS webhook boundary.

The owner secret inputs are references such as
`TVE_MONITORING_WEBHOOK_URL` and optional
`TVE_MONITORING_WEBHOOK_TOKEN`; values must stay outside Git, committed
status documents and command output.

Automatically:

1. deliver the selected terminal activation with
   `tve watch deliver ... --network allow`;
2. capture the secret-free `delivery_id`, ledger state, attempt count,
   dispatch-claim count, unresolved claims and pointer status;
3. repeat the already-delivered identity and prove zero additional authorized
   outbound dispatch slots/requests according to the D2B contract;
4. expose the same delivery state through the D3 operations projection;
5. fail closed on ambiguous/corrupt evidence rather than normalizing it to
   success.

If the receiver exposes a machine-readable receipt/query API, use it
automatically to match the exact delivery identity.

If the receiver has no machine-readable receipt surface and the only possible
proof is a human-visible destination, use
`MANUAL_NOTIFICATION_RECEIPT_REQUIRED`. Show the exact non-secret delivery
identity/timestamp the human must match, what screen/log entry counts as a
match, what must not be copied back (tokens/raw secret headers), and the exact
resume command that records only the confirmation marker. This human check
must not replace ledger/idempotency verification.

## 8. Monitoring API / Dashboard live proof

Use the existing D3 route and existing private deployment; do not add mutation
controls.

Automatically verify the real configured surface returns the expected
activation/cycle/job/delivery projection and:

- the lease state is truthful for the actual host topology;
- `UNKNOWN` remains conservative and is not rendered as LIVE/FREE;
- attempt count and dispatch-claim count remain distinct;
- unresolved dispatch slots and pointer status remain exact;
- local roots, endpoint URLs, auth tokens, holder tokens and raw response bodies
  are absent from API/browser payloads;
- POST/PUT/PATCH/DELETE remain rejected;
- repeated polling changes no file bytes and cannot interfere with a runner.

Reuse existing Cloudflare/private Dashboard verification helpers where
possible instead of duplicating deployment code.

If a browser-only identity-provider interaction is genuinely required after
all machine checks pass, use an explicit human marker with exact URL,
incognito/session conditions, expected page/state and resume verification.
Do not ask for screenshots containing account data unless no safer evidence is
possible.

## 9. Mandatory deterministic gate

Before live mutation and again after any code change, run all repository CI
checks. At minimum:

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

Use `python3` or an explicit venv interpreter only when required by the host
and record the substitution.

Any new live-acceptance/deployment helper needs deterministic tests covering
dry-run/no-mutation, redaction, malformed inputs, missing secrets,
insufficient privilege, idempotent rerun and evidence/report generation.

## 10. CI and closure discipline

For any software/documentation implementation commit that changes executable
behavior, push it and query GitHub Actions for the exact implementation SHA.
Fix failures yourself. Do not close the software slice from local tests alone.

Phase 6-E is CLOSED only when both are true:

1. the implementation SHA has a required Actions run whose `head_sha`
   exactly matches and whose conclusion is `success`; and
2. the owner-authorized live acceptance report proves the bounded real-host
   chain above.

The closure record must state, with exact machine-readable evidence where
available:

- implementation SHA and Actions run id/conclusion;
- host OS/systemd/runtime facts at a non-sensitive level;
- the proven lock-visibility topology result;
- bounded watchlist/source/date-window facts;
- live acquisition identity/hash and offline replay equality;
- activation/cycle/receipt identities and restart/replay result;
- service/timer effective-state evidence;
- delivery identity/state/attempt/dispatch counts and idempotency result;
- D3/API projection result and secret/path scan;
- every manual marker that was actually crossed, the exact human action and
  the subsequent automated verification.

If owner inputs are missing, record the exact missing input names and use
`READY_FOR_OWNER_AUTHORIZED_PHASE_6E`. Do not substitute a green CI run for
live acceptance.

## 11. Stop boundary

Stop after Phase 6-E owner live unattended acceptance.

Do not start vendor-specific notification adapters, scheduled GitHub Actions
monitoring, Bridge/FQGate provider expansion, M4-D/M4-E/M2-D, new financial
data licensing work, brokerage/trading operations or investment-rule changes.
