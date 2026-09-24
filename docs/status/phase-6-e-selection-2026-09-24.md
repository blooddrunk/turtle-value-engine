# Phase 6-E selection — owner live unattended acceptance — 2026-09-24

Status: **SELECTED**

Baseline main:
`5451eb8254cae7f1c3f120a6d1e745a58c53d6ef`

Predecessor implementation:
`40a75d89c2863b74a3e44ecfbad4fe432959fc5b`

Predecessor closing CI:
Actions run `35948785496`, `success`, exact implementation `head_sha`.

Canonical goal:
`docs/goals/phase-6-e-owner-live-unattended-acceptance.md`

Coding-agent handoff:
`docs/status/phase-6-e-next-coding-agent-goal.md`

## Review conclusion

Phase 6-D3-R1 is accepted within the repository's declared single-host
Linux/systemd boundary.

The implementation removes the observer/runner authority race structurally:
`RunnerLease.probe()` takes no OS lock, passively classifies a granted
`FLOCK` from `/proc/locks`, uses an explicit conservative `UNKNOWN` when
passive proof is unavailable, and leaves the authoritative D2A-R1
`RunnerLease.held()` path unchanged.

The exact implementation SHA has a successful push CI run. The recorded gate
contains Ruff, config validation, full Python regression
(`6695 passed, 2 skipped`), monitoring tests (`344 passed`), Dashboard
tests (`55 passed`), generated-contract checks, Dashboard build/type/lint,
client-bundle secret scan, strict Wrangler dry-run, systemd verification and
the real cross-stack smoke. The R1 closure also contains deterministic
observer-vs-runner process/barrier proofs and a repeated coordinated
concurrency matrix. No owner action was used for R1.

No finding in this review requires reopening R1.

## One live-deployment boundary to prove, not assume

The passive observation implementation intentionally depends on Linux
`/proc/locks`. The current runner contract is explicitly single-host and the
checked-in deployment model is systemd on that host, so this is not an R1
defect.

Phase 6-E must nevertheless prove the actual owner deployment places the real
runner and the D3/status/API observer in execution contexts that see the same
authoritative flock truth. Container/PID-namespace portability is not an
accepted claim unless that topology is separately proven.

## Why Phase 6-E is next

The repository already has the software pieces for bounded live acquisition,
durable unattended execution, generic webhook delivery and read-only
monitoring. What remains is the bounded owner-authorized real-host acceptance
that the roadmap has intentionally deferred.

The current monitoring deployment README still expects owner-side hand editing
of systemd paths/cadence and manual installation. That is not a sufficient
automation boundary for this project. Phase 6-E therefore includes the
smallest deployment/live-acceptance helper needed to automate host preflight,
unit rendering/validation, apply/verify, bounded live smoke and evidence
collection.

Human intervention is allowed only for genuine authority/secret/UI boundaries,
with exact stop/resume commands and machine-verifiable postconditions. Missing
owner inputs leave the phase at
`READY_FOR_OWNER_AUTHORIZED_PHASE_6E`, never a vague "evidence incomplete"
state.

## Explicitly not selected

- vendor-specific Slack/Telegram/email notification adapters;
- scheduled GitHub Actions monitoring;
- FQGate/Bridge provider expansion;
- new CNINFO/source taxonomy work;
- M4-D/M4-E/M2-D;
- brokerage/order/funds operations;
- investment-rule or `strict-v1` changes.
