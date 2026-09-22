# Phase 6-D2A post-closure review / R1 selection — 2026-09-22

Status: **REVIEWED / CLOSED BY R1**

Resolution: all four findings (F1-F4) were re-confirmed to still exist at the
advanced baseline `ec17af0` and were fixed by Phase 6-D2A-R1 at
`2f9aae27afb8cb95c6fed7ee20cdf47d7ad09d1e` (Actions run 35679461520,
success). Closure evidence:
`docs/status/phase-6-d2a-r1-2026-09-22.md`.

Audited main head:
`81b2ac2bb07711eab03fc594aabeab4293c99ec2`

D2A implementation SHA:
`2fb682f991b70f3f6bb4e3cce8cd2fe3b69a50ac`

Exact implementation Actions run:
`35677839752` — **success**

Canonical original goal:
`docs/goals/phase-6-d2a-persistent-runner-foundation.md`

Selected corrective goal:
`docs/goals/phase-6-d2a-r1-lease-hardening.md`

## 1. What was verified and remains accepted

The review independently confirmed the core D2A boundary and its exact-SHA CI
evidence:

- the pushed implementation SHA is exactly the head SHA of Actions run
  `35677839752`, and that run completed successfully;
- the runner keeps Phase 6-D1 unchanged and persists a typed activation intent
  before entering D1;
- unfinished activations freeze and reuse the same PIT/`as_of`;
- existing D1 terminal artifacts repair the runner layer without repeating
  provider/model/re-analysis work;
- terminal runner receipts bind exact D1 result/outbox identities and hashes;
- the runner has a real OS-level `flock` exclusion boundary;
- the test file contains 21 test functions plus one 5-case parametrized matrix,
  matching the closure document's 25 deterministic D2A cases;
- the CI job passed Ruff, project config validation, the full Python suite,
  systemd unit verification, generated API checks, Dashboard checks/build,
  client-bundle secret scan, Wrangler dry-run and cross-stack smoke.

The persistence, PIT freeze, D1 repair and no-duplicate-work architecture is not
being reopened.

## 2. Required correctness findings

### F1 — non-contention `flock` failures are misclassified as LEASE_BUSY

`RunnerLease.held()` currently catches any `OSError` from
`fcntl.flock(... LOCK_EX | LOCK_NB)` and converts it to
`RunnerLeaseBusyError`.

Only real lock contention (normally `EAGAIN`/`EACCES` via
`BlockingIOError`) proves that another live invocation owns the slot. Errors
such as `ENOLCK`, invalid-descriptor/filesystem errors, or other OS failures
must fail closed as `RunnerLeaseError`; reporting them as `LEASE_BUSY`
produces false machine evidence about a live holder.

The same principle applies to `probe()`: an inability to open or lock an
existing lease slot must not be reported as `FREE` or `LIVE` merely because
an unrelated OS operation failed.

### F2 — a lease record is not bound back to its runner slot

Active/latest pointers explicitly verify that the decoded `runner_id` matches
the requested slot. The lease path does not perform the equivalent check after
decoding `RunnerLeaseV1`.

A canonical, hash-valid lease record for runner B placed in runner A's lease
slot is therefore accepted as prior state and can be overwritten. That is a
conflicting persisted runner state and must fail closed before any provider,
model or D1 work.

### F3 — mutable lease metadata is parsed before the authoritative OS lock

`MonitoringRunnerService.run()` calls `lease.validate_record()` before it
attempts the non-blocking `flock`.

The OS lock is the actual liveness authority. The ordering should be:

1. try the lock;
2. if real contention exists, return `LEASE_BUSY` with zero work;
3. only after acquiring the slot, validate any abandoned/stale persisted record
   and fail closed on corruption or slot mismatch.

This removes a pre-lock metadata read from the contention path and makes the
machine classification depend on the kernel lock rather than mutable JSON.

### F4 — lease record writes must prove full-byte persistence

`LeaseHandle.record()` currently issues one `os.write` call without checking
that the complete canonical payload was written. A short write must be retried
or rejected explicitly; a partially persisted lease record must never be
treated as a successful holder-record update.

## 3. Decision

Do **not** start Phase 6-D2B yet.

Select one bounded corrective package:

**Phase 6-D2A-R1 — Lease Classification and Slot-Integrity Hardening**

This is a local deterministic maintenance slice. It does not change Phase 6-A,
6-B, 6-C, D1 semantics, activation identity, alert outbox semantics, systemd
cadence, network policy, credentials, Dashboard behavior, Cloudflare, Bridge,
brokerage or investment math.

After R1 passes the full gate and exact closing-SHA Actions success is recorded,
Phase 6-D2B becomes the next package.

## 4. Automatic verification requirement

R1 has no planned manual verification. The coding agent must automatically
prove at least:

- a true live lock conflict returns `LEASE_BUSY` and performs zero D1/provider
  work even when the holder record is unreadable/torn;
- after that live holder releases, the same corrupt abandoned record fails
  closed before D1;
- injected non-contention `flock` OS errors produce `RunnerLeaseError`, never
  `LEASE_BUSY`;
- a canonical lease record whose `runner_id` differs from the lease slot fails
  closed;
- simulated short writes still produce a complete canonical lease record or a
  deterministic failure, never silent truncation;
- all existing overlap, abandoned recovery, crash resume/repair, status,
  subprocess and no-scheduled-workflow tests remain green;
- the full repository CI matrix passes;
- the exact pushed R1 closing SHA has a successful GitHub Actions run and its
  run id/result are recorded.

No owner VPS, credentials, live CNINFO traffic or notification endpoint is
required for this corrective package.
