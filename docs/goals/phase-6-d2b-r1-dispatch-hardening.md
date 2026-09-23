# Phase 6-D2B-R1 — Dispatch Durability, Single-Flight and Timeout Truthfulness Hardening

Status: **CLOSED / IMPLEMENTED**
Date: 2026-09-22
Selected after: Phase 6-D2B post-closure review

> Closed at implementation `6c039266083de015535f3f05dce0cf9aba2f0042`
> (Actions run 35805665083, `success`, exact head SHA match); see the
> implementation record for the full evidence.

Selection audit:
`docs/status/phase-6-d2b-r1-review-2026-09-22.md`

Coding-agent handoff:
`docs/status/phase-6-d2b-r1-next-coding-agent-goal.md`

Implementation record:
`docs/status/phase-6-d2b-r1-2026-09-23.md`

## 1. Objective

Close the narrow external-side-effect correctness gaps found after D2B without
reopening its validated D2A/D1 source binding, payload semantics, retry policy,
secret boundary or investment/monitoring semantics.

R1 answers four concrete questions:

1. can a process die after the receiver may have seen request bytes without the
   next invocation falsely treating that delivery as proven-unsent?
2. can two local processes ever dispatch the same delivery concurrently?
3. does the configured timeout bound the **whole** HTTP exchange rather than
   only one socket operation?
4. does the read-only status path tell the truth about the persisted latest
   pointer instead of checking only whether a path exists?

R1 must be completed before Phase 6-D3 starts.

## 2. Required behavior

### 2.1 Durable dispatch-start evidence before possible network side effects

Add an additive durable attempt/dispatch-start boundary before request bytes may
be sent.

The exact contract name is implementation-defined, but the persisted model must
make these states distinguishable:

- no dispatch claim exists -> request is proven not yet attempted and may run;
- dispatch claim exists + terminal attempt outcome exists -> derive from the
  immutable terminal outcome as today;
- dispatch claim exists + no terminal outcome -> prior process may have
  dispatched and died; derive `AMBIGUOUS`.

For an orphaned dispatch claim:

- with `receiver_idempotency_declared=false`: terminal/fail-closed
  `AMBIGUOUS`, zero automatic resend;
- with `receiver_idempotency_declared=true`: a bounded retry may be scheduled
  using the existing deterministic delivery key and retry budget.

Persist the dispatch-start evidence **before** the transport can write request
bytes. Crash after the durable claim but before actual network dispatch may
therefore conservatively become `AMBIGUOUS`; that is acceptable and must be
documented explicitly. Do not manufacture proof that an external side effect
did or did not happen when the process cannot know.

Keep artifacts immutable/canonical/hash-validated and keep resolved endpoint or
auth material out of all persisted records.

### 2.2 Per-delivery single-flight exclusion before transport entry

Add an OS-level non-blocking exclusion keyed by `delivery_id`, held across:

- immutable state inspection/repair;
- dispatch-start publication;
- transport call;
- terminal attempt publication;
- latest-state publication.

Use the hardened truthfulness discipline already established by D2A-R1:

- only genuine lock contention may map to a precise delivery-busy result;
- unrelated open/flock/filesystem errors fail closed;
- the losing invocation performs zero transport calls;
- no mutable JSON holder record is allowed to become the liveness authority.

Do not rely on the receiver's `Idempotency-Key` to paper over local
concurrency.

### 2.3 One monotonic end-to-end HTTP deadline

Treat the existing bounded timeout policy as an overall transport deadline.

Use an injectable monotonic clock/deadline abstraction so deterministic tests
can prove behavior without long sleeps. Each potentially blocking phase must
use no more than the remaining budget, including at least:

- connect/TLS establishment;
- request write / response-header wait;
- bounded response-body reads.

If the deadline expires after dispatch may have started, classify the result as
`AMBIGUOUS`, not retryable-proven-unsent.

Do not contact the public Internet in tests.

### 2.4 Truthful read-only latest-pointer status

`delivery-status` remains read-only and secret-free, but it must validate a
published latest-state artifact rather than reporting only path existence.

At minimum distinguish:

- no pointer published;
- pointer is canonical and exactly current;
- pointer is valid but behind immutable artifacts and therefore repairable by
  the mutating delivery path;
- pointer is corrupt, foreign or contradictory -> fail closed.

Do not silently repair state from the status command.

## 3. Expected file scope

Expected implementation scope:

- `src/turtle_value_engine/monitoring_delivery/contracts.py`
- `src/turtle_value_engine/monitoring_delivery/store.py`
- `src/turtle_value_engine/monitoring_delivery/service.py`
- `src/turtle_value_engine/monitoring_delivery/transport.py`
- `src/turtle_value_engine/cli.py` only if a precise busy/status projection
  requires an additive CLI result
- additive checked-in schema(s) if a durable dispatch-start contract is added
- `tests/test_monitoring_delivery.py`
- closure/status docs after successful implementation

Do not change `strict-v1`, D1/D2A identities, monitoring cursor/re-analysis
semantics, provider/source behavior or the webhook payload meaning.

## 4. Mandatory deterministic tests

Add focused regression coverage that automatically proves:

1. **crash after durable dispatch claim, before send** -> conservative
   `AMBIGUOUS`; default policy performs zero resend on restart;
2. **crash after request may have been dispatched, before outcome save** ->
   restart remains `AMBIGUOUS` and performs zero resend by default;
3. **idempotent-receiver opt-in** -> an orphaned dispatch can retry only when
   `receiver_idempotency_declared=true`, with deterministic key and bounded
   monotonic attempt numbering;
4. **concurrent two-process delivery** -> deterministic barrier/subprocess test
   proves exactly one process can enter the transport for one `delivery_id`;
5. **non-contention lock failure** -> precise fail-closed error, never
   delivery-busy;
6. **overall deadline** -> injected monotonic/fake connection tests prove the
   same deadline bounds connect, request/header and repeated response reads;
7. **post-dispatch deadline expiry** -> `AMBIGUOUS`;
8. **status pointer truthfulness** -> current, missing, stale-repairable,
   corrupt, non-canonical and foreign pointer cases are classified precisely;
9. existing D2B deny/NOOP/success/retry/permanent/timeout/secret/crash-repair
   tests remain green;
10. existing D2A runner/cycle and full repository regression gates remain green.

Prefer deterministic barriers, injected clocks and fake/local transports over
timing sleeps. No acceptance criterion may be delegated to the owner if it can
be tested automatically.

## 5. Full automatic gate

Before editing:

- fast-forward-only sync with `main`;
- prove a clean tree and record the exact baseline SHA;
- verify the baseline CI state.

After focused tests, automatically run the complete repository gate:

```text
python3 -m ruff check .
python3 -m turtle_value_engine config validate --input config/project.example.toml
python3 -m pytest tests/test_monitoring_delivery.py
python3 -m pytest tests/test_monitoring_runner.py tests/test_monitoring_cycle.py tests/test_monitoring_cli.py
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

Use the available `python`/ `python3` executable equivalently; executable
naming is not a reason to skip validation.

After push, query GitHub Actions for the **exact R1 implementation SHA**. R1 is
not CLOSED from local tests alone. Record exact SHA, run id, URL, conclusion,
focused test counts and full-suite pass/skip counts.

## 6. Manual intervention boundary

**None planned.**

Do not ask the owner to:

- reproduce a race manually;
- provide a webhook/token;
- deploy a VPS/systemd unit;
- run a public endpoint;
- inspect screenshots or logs by hand.

If an environment limitation blocks an automatic check, record the exact
command, exact failure, exact missing capability, the automatic substitute if
one exists, and the precise unproved boundary. Do not write vague phrases such
as "evidence incomplete".

## 7. Stop boundary

Do **not** start Phase 6-D3 or Phase 6-E in R1.

No Dashboard monitoring views, owner live unattended acceptance,
Slack/Telegram/email-specific adapter, scheduled monitoring workflow, FQGate
Bridge adapter, CNINFO taxonomy expansion, Cloudflare mutation,
brokerage/trading behavior, or investment-rule change.

## 8. Acceptance criteria

R1 is closed only when:

1. an unresolved durable dispatch is never automatically re-sent for a
   non-idempotent receiver;
2. receiver-idempotent retry remains explicit and bounded;
3. one `delivery_id` has at most one local process in the transport boundary;
4. lock error classification is truthful;
5. one monotonic deadline bounds the whole HTTP exchange;
6. post-dispatch deadline uncertainty is `AMBIGUOUS`;
7. read-only status truthfully validates published state;
8. focused regression tests and all existing D2B/D2A tests pass;
9. the complete repository gate passes;
10. exact closing-SHA Actions success is recorded;
11. no D3/6-E or unrelated scope is mixed in.
