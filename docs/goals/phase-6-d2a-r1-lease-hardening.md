# Phase 6-D2A-R1 — Lease Classification and Slot-Integrity Hardening

Status: **CLOSED**
Date: 2026-09-22
Selected after: Phase 6-D2A post-closure review
Closed by: `2f9aae27afb8cb95c6fed7ee20cdf47d7ad09d1e` (Actions run 35679461520, success)

Selection audit:
`docs/status/phase-6-d2a-r1-review-2026-09-22.md`

Closure record:
`docs/status/phase-6-d2a-r1-2026-09-22.md`

Coding-agent handoff:
`docs/status/phase-6-d2a-r1-next-coding-agent-goal.md`

## 1. Objective

Close the narrow lease correctness gap found after the D2A implementation
without reopening or redesigning the already-proven activation/D1/crash-repair
architecture.

R1 answers one question:

> Does the unattended runner classify the lease slot truthfully and
> deterministically under contention, corruption and OS failure before any
> provider/model/D1 work is allowed?

R1 must be completed before Phase 6-D2B starts.

## 2. Required behavior

### 2.1 Kernel lock is the liveness authority

The non-blocking `flock` acquisition must happen before persisted lease JSON is
treated as authoritative.

- real lock contention -> `RunnerLeaseBusyError` / CLI `LEASE_BUSY` / exit 3;
- any other flock/open failure -> fail closed as `RunnerLeaseError` / CLI
  fail-closed path;
- no provider, model, acquisition or D1 work may occur on either path.

Remove or redesign the pre-lock `validate_record()` path so it cannot preempt
a real live-lock classification.

### 2.2 Distinguish contention errno from unrelated OS errors

Do not catch arbitrary `OSError` and call it busy.

Only the platform's actual non-blocking contention error(s), normally
`EAGAIN`/`EACCES` (`BlockingIOError`), may map to
`RunnerLeaseBusyError`.

Unexpected lock/open errors must preserve a precise fail-closed diagnostic.

Apply the same truthfulness rule to the read-only lease status/probe path.

### 2.3 Bind lease records to the slot identity

After the process owns the OS lock and decodes any prior
`RunnerLeaseV1`, require:

`record.runner_id == RunnerLease.runner_id`

A mismatch is a persisted-state conflict and must fail closed before runner
state settlement or D1 entry.

Do not silently overwrite a canonical lease belonging to another runner id.

### 2.4 Full-byte lease record writes

`LeaseHandle.record()` must not assume a single `os.write` persisted the whole
payload.

Implement a complete write loop or an equivalent primitive that either writes
all canonical bytes and fsyncs successfully or raises a typed error.

Do not add a second lease/state mechanism.

## 3. File scope

Expected implementation scope:

- `src/turtle_value_engine/monitoring_runner/lease.py`
- `src/turtle_value_engine/monitoring_runner/service.py`
- `tests/test_monitoring_runner.py`
- closure/status docs after successful implementation

Schema or public contract changes are **not expected**. If implementation proves
one is genuinely required, keep it additive and explain why before changing it.

## 4. Mandatory deterministic tests

Add focused regression tests that automatically prove:

1. **live lock wins over unreadable metadata** — hold the lease lock, make the
   holder record unreadable/torn, invoke a second runner and require
   `RunnerLeaseBusyError` with zero D1/provider calls;
2. **corrupt abandoned state fails closed** — release that holder and require the
   next invocation to fail before D1;
3. **non-contention flock error is not busy** — inject an OS error such as
   `ENOLCK` and require `RunnerLeaseError`, not `RunnerLeaseBusyError`;
4. **slot identity mismatch** — put a canonical lease for runner B in runner A's
   slot and require fail-closed zero-work behavior;
5. **short-write handling** — deterministically simulate partial writes and
   prove the final record is complete/canonical or the operation fails
   explicitly;
6. all existing D2A tests remain green, especially ordinary overlap,
   abandoned-record recovery, crash resume, D1-terminal repair, CLI exit 3 and
   subprocess black-box coverage.

Do not rely on sleep-based race tests when deterministic barriers/injection can
prove the same property.

## 5. Full automatic gate

Before editing:

- fast-forward-only sync with `main`;
- prove clean tree and record baseline SHA;
- verify the baseline Actions run is green.

After focused tests, run the complete existing repository gate:

```text
python3 -m ruff check .
python3 -m turtle_value_engine config validate --input config/project.example.toml
python3 -m pytest
python3 scripts/export_surface_openapi.py --check
pnpm --dir apps/dashboard api:check
pnpm --dir apps/dashboard types:check
pnpm --dir apps/dashboard lint
pnpm --dir apps/dashboard typecheck
pnpm --dir apps/dashboard test --run
pnpm --dir apps/dashboard build
pnpm --dir apps/dashboard security:client-bundle
pnpm --dir apps/dashboard exec wrangler deploy --dry-run --config wrangler.jsonc --strict
python3 scripts/dashboard_cross_stack_smoke.py
systemd-analyze verify deploy/monitoring/turtle-value-monitor.service deploy/monitoring/turtle-value-monitor.timer
```

If the environment exposes `python` instead of `python3`, use the available
interpreter; do not skip an equivalent automatic check because of executable
naming.

After push, verify GitHub Actions for the **exact R1 closing implementation
SHA**. Record the run id, URL and result in a dated R1 closure document.

## 6. Manual intervention boundary

None planned.

Do not ask the owner to reproduce races, inspect a VPS, provide credentials,
trigger CNINFO, configure systemd, or inspect logs manually. Every R1 acceptance
condition is local and automatable.

If an unexpected environment limitation blocks a specific automatic check,
record the exact command, exact error, exact missing capability, an automatic
alternative if one exists, and the precise unproved boundary. Do not use
phrases such as "evidence incomplete" without those details.

## 7. Stop boundary

Do **not** start Phase 6-D2B in this package.

No webhook/email/Slack/Telegram transport, notification receipt ledger,
notification acknowledgement state, Dashboard monitoring projection, owner
live deployment, new CNINFO taxonomy, Bridge adapter, Cloudflare mutation,
brokerage/trading behavior, or `strict-v1`/valuation/hard-gate changes.

## 8. Acceptance criteria

R1 is closed only when:

1. only real lock contention maps to `LEASE_BUSY`;
2. unexpected open/flock failures fail closed truthfully;
3. live lock classification happens before mutable lease-record validation;
4. abandoned corrupt/mismatched lease state fails closed before D1;
5. lease records are slot-bound by `runner_id`;
6. short writes cannot silently publish partial lease JSON;
7. focused regression tests and the entire existing D2A matrix pass;
8. full repository gates pass;
9. exact closing-SHA Actions success is recorded;
10. no D2B or unrelated scope is mixed in.
