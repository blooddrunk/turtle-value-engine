# Phase 6-D2B post-closure review / R1 selection — 2026-09-22

Status: **REVIEWED / R1 SELECTED**

Audited main head:
`eba7336b62d70f99ec9c3c8bd19f407714ad054b`

D2B implementation SHA:
`1abb2973e3f26d2db373f60b63da8c62a2bc530c`

Exact implementation Actions run:
`35694475358` — **success**, exact head SHA match

Canonical original goal:
`docs/goals/phase-6-d2b-notification-delivery-ledger.md`

Selected corrective goal:
`docs/goals/phase-6-d2b-r1-dispatch-hardening.md`

Coding-agent handoff:
`docs/status/phase-6-d2b-r1-next-coding-agent-goal.md`

## 1. What remains accepted

The review independently confirmed that the original D2B implementation is real
and CI-closed at its documented integration boundary:

- Actions run `35694475358` is a completed successful push run whose
  `head_sha` is exactly
  `1abb2973e3f26d2db373f60b63da8c62a2bc530c`;
- the single CI job passed Ruff, project-config validation, the complete Python
  suite, systemd verification, generated API checks, Dashboard checks/build,
  client-bundle secret scan, Wrangler validation and cross-stack smoke;
- D2B consumes only validated terminal D2A/D1 artifacts and does not rerun D1,
  acquisition, providers, models or re-analysis;
- network remains deny-by-default and live endpoint/auth values are resolved
  only in process memory;
- immutable intent/attempt artifacts, canonical payload hashing, bounded
  response persistence, retry classification, zero-I/O NOOP and sequential
  DELIVERED replay are all implemented and covered by deterministic tests;
- the existing tests correctly prove repair when an attempt artifact is already
  durable and only the latest-state pointer publication is missing.

Those boundaries are not being redesigned.

## 2. Required correctness findings

### F1 — post-dispatch process death can be mistaken for "never sent"

`MonitoringDeliveryService._perform_attempt()` calls
`transport.send(...)` first and persists `MonitoringDeliveryAttemptV1` only
after the transport returns.

Therefore there is an uncovered crash window:

1. the immutable delivery intent exists;
2. request bytes may have been dispatched and the receiver may have acted;
3. the process dies before `save_attempt()`;
4. the next invocation sees zero attempts and automatically sends attempt 1
   again.

For the default `receiver_idempotency_declared=false` case, that is not
consistent with D2B's conservative post-dispatch ambiguity rule. A process
crash after possible dispatch is operationally ambiguous just like a timeout
or connection loss after dispatch; it must not be treated as proven-unsent.

The existing test named
`test_crash_after_response_before_pointer_publish_repairs_deterministically`
does not cover this window: it injects failure only on the second **pointer**
write, after the successful immutable attempt has already been saved.

### F2 — concurrent deliver invocations can both perform the outbound side effect

The D2B ledger has no per-delivery single-flight exclusion around state
inspection and transport dispatch.

Two processes can load/create the same intent, both observe no terminal attempt,
and both enter `_perform_attempt(... attempt_number=1)`. Immutable attempt
conflict detection happens only after the outbound requests, so it can detect a
race too late to prevent duplicate webhook effects.

A deterministic `Idempotency-Key` helps receivers that honor it, but D2B
explicitly does not assume arbitrary receivers enforce idempotency. Local
single-flight must therefore prevent duplicate dispatches before relying on
the receiver.

### F3 — `timeout_seconds` is not an actual end-to-end deadline

The real transport constructs `http.client.HTTP(S)Connection` with a socket
timeout and then performs request/response reads. That bounds individual
blocking socket operations, but it does not enforce the goal's stated
connect/read/write/**overall** deadline.

A peer that keeps making progress inside each socket timeout can make the total
exchange exceed `timeout_seconds` substantially. The transport needs one
monotonic overall deadline, with each blocking phase bounded by the remaining
budget.

### F4 — `delivery-status` does not validate the published state pointer

`delivery_status_projection()` derives state from immutable artifacts, but for
the published state it reports only
`pointer_published = ledger.state_path(...).exists()`.

A corrupt, non-canonical, foreign or contradictory published pointer can
therefore be hidden by the read-only status command even though a subsequent
`deliver()` correctly fails closed. Status must validate the pointer and
report a truthful consistency classification (or fail closed); it must not
silently treat mere path existence as evidence of a valid published state.

## 3. Decision

Do **not** start Phase 6-D3 yet.

Select one bounded corrective package:

**Phase 6-D2B-R1 — Dispatch Durability, Single-Flight and Timeout Truthfulness
Hardening**

R1 is a local deterministic hardening slice. It does not change Phase 6-A,
6-B, 6-C, D1, D2A/R1 source semantics, investment rules, notification payload
meaning, owner deployment, Dashboard monitoring projection, Cloudflare,
FQGate Bridge, brokerage or source taxonomy.

After R1 passes focused tests, the complete repository gate and exact closing
SHA GitHub Actions success, Phase 6-D3 becomes the next candidate package.

## 4. Automatic verification requirement

R1 has **no planned manual verification**. The coding agent must automatically
prove at least:

- an orphaned durable dispatch-start record (no completion artifact) is
  classified `AMBIGUOUS` on restart and produces zero automatic resend when
  receiver idempotency is not declared;
- the same orphaned dispatch can be retried only under the existing explicit
  receiver-idempotency policy, with monotonic attempt identity;
- a crash before any dispatch claim remains safely retryable without changing
  D1/provider/model state;
- two real concurrent processes targeting the same `delivery_id` cannot both
  enter the transport; the loser receives a precise busy/fail-closed result and
  performs zero outbound requests;
- unrelated lock/open OS errors are not misclassified as contention;
- the real transport obeys one monotonic overall deadline, including bounded
  connect/request/read behavior, without sleep-based/flaky public-network tests;
- status validates the published pointer and distinguishes current,
  missing/stale-repairable and corrupt/conflicting state truthfully;
- all existing 43 D2B tests and the full repository CI matrix remain green;
- the exact pushed R1 closing SHA has a successful Actions run whose id/result
  are recorded.

No owner webhook, VPS, credentials, browser screenshot or public Internet
request is required for R1.
