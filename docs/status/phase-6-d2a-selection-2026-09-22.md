# Phase 6-D2A selection audit — 2026-09-22

Status: **SELECTED / NOT IMPLEMENTED**

Audited main head:
`976ee2ded6ec677fcea131af86c8a02bf71466b3`

## 1. Phase 6-D1 audit result

Phase 6-D1 is accepted as **CLOSED** at the synchronous cycle/outbox boundary.

Repository evidence independently checked through GitHub:

- implementation commit:
  `e452eadc866035a7a784d7862956a3f24e3985b8`;
- closure documentation commit:
  `976ee2ded6ec677fcea131af86c8a02bf71466b3`;
- implementation Actions run:
  `35602785093`;
- run event / branch:
  `push` / `main`;
- run conclusion:
  `success`;
- the single CI job completed Ruff, project config validation, the full Python
  suite, generated OpenAPI/API/Wrangler checks, Dashboard lint/typecheck/tests/
  build, client-bundle secret scan, Wrangler strict dry-run and the real
  Dashboard cross-stack smoke successfully.

The D1 implementation also matches its stop boundary in code:

- `MonitoringCycleRunner` composes Phase 6-B acquisition -> Phase 6-A commit
  -> Phase 6-C execution;
- `MonitoringCycleSpecV1` freezes explicit PIT/as_of and execution bindings;
- `MonitoringCycleStore` persists immutable artifacts plus a repairable atomic
  latest pointer;
- `MonitoringAlertBatchV1` is deterministic and delivery-neutral;
- unresolved current `BLOCKED`/`FAILED` execution dispositions stop the next
  pointer advance before acquisition;
- the automated D1 suite covers cache replay with sockets blocked, all impact
  classes, no-event zero-call behavior, failure atomicity, schema drift,
  conflict/tamper rejection, crash/pointer repair, retry reuse and
  duplicate-alert suppression;
- no scheduler, delivery transport, Dashboard write path, Cloudflare mutation,
  live LLM integration or brokerage action was added.

No D1 defect was found that requires reopening Phase 6-D1.

## 2. Documentation correction made during this audit

`docs/roadmap.md` still described Phase 6-B as "not started" even though
6-B, 6-C and 6-D1 are closed. That stale milestone text is corrected together
with this selection so future agents do not plan from an obsolete Phase 6
state.

## 3. Why D2 is split again

The previous D1 selection grouped the later work as "D2 scheduling +
notification delivery/receipt semantics". After D1, those are now clearly two
separate failure domains:

1. durable wakeup / overlap / crash / restart behavior;
2. external message transport, credentials, rate limits, retries and delivery
   receipts.

Combining them would make a failed webhook or channel credential look like a
scheduler correctness problem. Therefore D2 is split:

- **6-D2A — active:** persistent unattended runner foundation;
- **6-D2B — later:** external notification delivery and receipt ledger;
- **6-D3 — later:** read-only monitoring/cycle/job projection in the existing
  API/Cloudflare/Dashboard stack;
- **6-E — later:** bounded real owner unattended acceptance.

## 4. Selected runner model

Select a persistent Linux host with a host-native **systemd timer/service** as
the first reference monitoring runner.

This is a storage-driven choice:

- current monitoring state is local and durable;
- current re-analysis job state is local and durable;
- current cycle/outbox state is local and durable;
- systemd can wake the exact non-interactive CLI without introducing another
  application runtime;
- host restart recovery can be tested against the same filesystem state.

Do not select GitHub Actions as the Phase 6 monitoring scheduler merely because
the repository already uses Actions. Its workspace is ephemeral. Making it the
runtime now would require a remote persistence design unrelated to proving the
unattended runner.

Hermes remains a future compatible wakeup/orchestration option because it can
invoke the same CLI on a persistent host; D2A does not require an agent runtime.

## 5. Key D2A contract decision

The runner must persist an activation intent **before** entering D1. That intent
freezes the resolved PIT/as_of. If the process crashes, the next invocation
must resume the unfinished activation rather than derive a new cycle from a
later wall clock.

A separate single-host lease prevents overlap. A terminal runner receipt binds
the activation to exact D1 result/outbox identities. If D1 terminal artifacts
exist but the runner receipt/pointer was not published, recovery repairs the
runner layer without repeating provider/model work.

This is the minimum durable boundary needed before any external notification
transport is trustworthy.

## 6. Verification policy

D2A is a software/operations-contract closure, not a live deployment
acceptance. It has no planned manual functional step.

The coding agent must automatically prove baseline sync/CI, focused
activation/lease/restart tests, subprocess CLI behavior, schema drift,
network-deny/default and secret-free output, systemd unit validity, the entire
existing repository CI gate and the exact closing-SHA GitHub Actions result.

Real VPS installation, real cadence, real credentials and live unattended
event detection are Phase 6-E inputs and must not be pulled forward merely to
produce "evidence".
