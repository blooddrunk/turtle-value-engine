# Phase 6-F coding-agent handoff — Persistent Owner Operations Hardening

Status: **READY FOR IMPLEMENTATION**

Canonical goal:
`docs/goals/phase-6-f-persistent-owner-operations.md`

Selection record:
`docs/status/phase-6-f-selection-2026-09-28.md`

Baseline:
`b0eca4c2f518a7562b6209833f85bf3de553842f` (PR #3 merged; Phase 6-E
closed under the owner-revised acceptance rule).

## Goal

Implement only **Phase 6-F — Persistent Owner Operations Hardening**.

Start from a fast-forward-only synchronized `main`; record the exact baseline
SHA and working-tree state. Read `AGENTS.md`, the Phase 6-F goal, the Phase
6-E goal/status, D2A/R1 deployment/lease contracts, D2B/R1/R2 delivery
contracts, D3/R1 read-only projection contracts and the existing deployment
helper before editing.

The package turns the already accepted single-host chain into an explicit,
restart-resilient long-lived owner deployment. Do not reopen closed Phase 6
semantics and do not expand providers or investment rules.

## Required execution discipline

1. **Audit first.** Determine the smallest safe extension of the Phase 6-E
   helper/deployment surface; do not create a second parallel deployment
   framework without evidence that reuse is unsafe.
2. **Automate first.** Implement non-mutating plan/preflight, deterministic
   render, idempotent apply/converge, explicit activation, verify/report and
   safe deactivation. Automatically verify every machine-checkable condition.
3. **Separate acceptance and production.** Never silently reuse/promote the
   Phase 6-E acceptance root. Bind production evidence to explicit typed
   production paths/config/unit identities.
4. **Prove real persistence.** Inspect native-Linux vs WSL2 topology, effective
   systemd state and D3-R1 lock visibility. For user units, prove
   `Linger=yes`; enable and verify it automatically when authorized, otherwise
   stop only at `MANUAL_ENABLE_LINGER_REQUIRED` with the exact six-item
   boundary. For system units, do the equivalent privilege handling.
5. **Do not overclaim WSL2.** Linux/systemd evidence alone is not Windows
   reboot-autostart evidence. Automate a Windows-side bootstrap proof only if
   the environment exposes the necessary authority; otherwise report the
   exact narrower persistence claim and
   `WINDOWS_HOST_BOOTSTRAP_UNPROVEN`.
6. **Keep secrets out.** Notification is optional. If enabled, the service
   must resolve the existing secret reference after restart without putting
   secret values in Git, units/arguments, configs, ledger, reports or public
   API/UI. An interactive `export` is not a production credential mechanism.
7. **Activate only explicitly.** Applying config must not silently start
   recurring work. When owner authorization is available, activate and
   automatically prove one bounded real production firing, replay/no-duplicate
   behavior, read-only D3 observation and optional delivery. Leave the timer
   enabled only for an accepted production closure.
8. **Recovery proof.** Automate daemon/service/timer restart or the strongest
   safe equivalent, prove config identity and durable runner state survive,
   and prove no duplicate activation/cycle/delivery.
9. **Persist a secret-free report.** Include exact implementation/config/unit
   identities, host classification, linger/persistence evidence, timer state,
   activation/cycle/receipt identities, optional delivery accounting, D3
   result, secret scan and every marker actually crossed.
10. **Run all gates yourself.** Run the complete Phase 6-F goal §10 gate plus
    focused tests. Push the implementation, query GitHub Actions for the exact
    implementation SHA, fix failures and record exact closure evidence.
11. **Human intervention is exceptional.** If unavoidable, never write only
    "manual verification" or "evidence incomplete". Record all six required
    items: last command, exact human action, secret/data boundary, exact resume
    command, machine-verifiable success condition, and exact remainder left
    unverified.
12. **Stop boundary.** Do not start Phase 7, Bridge/FQGate integration,
    M4-D/M4-E/M2-D, other notification vendors, trading/brokerage or
    investment-rule/profile changes.

If executable code is complete but the owner-authorized production activation
cannot be executed in the current environment, close only the software slice
and set the phase to `READY_FOR_OWNER_AUTHORIZED_PHASE_6F`; do not call the
phase CLOSED.

Before finishing, update the canonical goal, a dated Phase 6-F implementation
status record, the next coding-agent handoff, `docs/roadmap.md` and
`AGENTS.md` with exact local/CI/host evidence. Prefer automatically
collecting evidence over asking the owner to reproduce it.
