# Phase 6-D3 post-closure review — 2026-09-24

Status: **D3 ACCEPTED / R1 REQUIRED BEFORE 6-E**

Reviewed implementation:
`eb5f199437cba1d9747f87da7a6591943cbbacab`

D3 closing CI:
Actions run `35860274042`, `success`, exact `head_sha` match.

## Review result

The D3 implementation remains accepted for its delivered read model, API,
Worker, Dashboard, secret boundary, R2 accounting projection and exact-SHA CI
closure. One post-closure operational-correctness defect was found in the
runner lease observation path. It is narrow, reproducible and should be fixed
before Phase 6-E live unattended acceptance.

## F1 — a D3 read can transiently make the real runner report LEASE_BUSY

Current call chain:

```text
GET /v1/monitoring/operations
  -> MonitoringOperationsReadService.operations_projection()
  -> build_monitoring_operations_projection()
  -> RunnerLease.probe()
  -> flock(fd, LOCK_EX | LOCK_NB)

MonitoringRunnerService.run()
  -> RunnerLease.held()
  -> flock(fd, LOCK_EX | LOCK_NB)
  -> contention => RunnerLeaseBusyError / LEASE_BUSY / zero D1 work
```

`RunnerLease.probe()` is byte-preserving, but it is not concurrency-neutral:
when no real runner currently owns the lease, the observer itself can acquire
the same exclusive OS lock. A runner starting during that interval sees real
kernel contention and truthfully follows the existing D2A-R1 busy path, so an
API/Dashboard read can suppress one scheduled invocation.

The existing D3 store-inventory test cannot detect this because advisory lock
state is transient kernel state, not a file-byte mutation.

### Independent deterministic reproduction

A local two-process reproduction using the same Linux operations was executed:

1. observer opens the lease file `O_RDONLY`;
2. observer acquires `LOCK_EX | LOCK_NB`;
3. while that lock is held, a runner-shaped process opens the same file
   `O_RDWR` and attempts `LOCK_EX | LOCK_NB`;
4. the runner receives `BlockingIOError` (`runner-busy`).

This proves the interference mechanism independently of the repository tests.

## Required correction

Select **Phase 6-D3-R1 — Non-interfering Lease Observation Hardening** before
Phase 6-E.

The fix must be structural, not a timing workaround:

- D3/status observation must not acquire a lock that conflicts with the
  authoritative runner lease;
- a read request must never be able to create `RunnerLeaseBusyError` for an
  otherwise uncontended runner;
- D2A-R1 single-flight semantics and true-holder `LEASE_BUSY` behavior must
  remain unchanged;
- if exact LIVE/FREE/ABANDONED classification cannot be proven passively on a
  supported platform, expose an explicit conservative/unknown state rather
  than acquiring authority or fabricating liveness;
- no sleep/retry loop may be used merely to reduce the probability of the race.

## Verification gap to close

R1 must add deterministic concurrent tests with barriers/processes proving both:

1. with no real holder, concurrent D3 observation cannot cause the runner to
   return busy and the runner enters D1 exactly once;
2. with a real holder, a second runner still returns busy while the D3
   observer remains non-interfering and reports only truth it can prove.

Also retain the existing no-write, no-secret, API/Worker/Dashboard, generated
contract, cross-stack and exact-closing-SHA gates.

## Manual boundary

**NONE.** This is a local concurrency/protocol defect. It can and must be
closed entirely with deterministic automated tests and CI. No VPS, Cloudflare
mutation, owner webhook, real provider/model call or human visual inspection is
required.

Phase 6-E remains queued behind R1.
