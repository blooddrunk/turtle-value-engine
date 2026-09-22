# Phase 6-D2B selection audit — 2026-09-22

Status: **SELECTED / ACTIVE**

Baseline: `168cd628ae749bd1a10b458625fdd733f22cf11b`
R1 implementation: `2f9aae27afb8cb95c6fed7ee20cdf47d7ad09d1e`
R1 CI: Actions run `35679461520`, conclusion `success`

Canonical goal:
`docs/goals/phase-6-d2b-notification-delivery-ledger.md`

Coding-agent handoff:
`docs/status/phase-6-d2b-next-coding-agent-goal.md`

## 1. R1 audit conclusion

Phase 6-D2A-R1 is genuinely closed, not documentation-only.

The implementation delta from `ec17af0` to `2f9aae2` is one commit touching
only:

- `src/turtle_value_engine/monitoring_runner/lease.py`;
- `src/turtle_value_engine/monitoring_runner/service.py`;
- `tests/test_monitoring_runner.py`.

The code makes the kernel `flock` the first/only liveness authority, separates
real contention from unrelated OS failures, binds canonical lease records to
their runner slot, removes pre-lock mutable-record validation, verifies
full-byte holder-record writes, and applies the same truthful classification to
status/probe paths. Nine deterministic R1 regression tests were added.

Actions run `35679461520` is a push run whose exact `head_sha` is
`2f9aae27afb8cb95c6fed7ee20cdf47d7ad09d1e`. Its single CI job completed
successfully. The logs record:

- Ruff: passed;
- Python: **6593 passed, 2 skipped**;
- reference monitoring systemd units: `systemd-analyze verify` passed;
- Dashboard tests: **44 passed**;
- Dashboard build, client secret scan and cross-stack smoke: passed.

No manual R1 acceptance remains.

## 2. Why D2B is next

D1 already emits a deterministic immutable alert outbox. D2A already runs that
cycle durably and records the exact alert-batch identity/hash. What is still
missing from the monitoring path is an external side-effect boundary that can
send those alerts without re-running analysis and without losing auditability
across retry/crash scenarios.

Therefore select:

**Phase 6-D2B — External Notification Delivery and Delivery/Receipt Ledger.**

The minimal first transport is a generic HTTP webhook. This is intentionally
smaller and more testable than adding multiple vendor integrations.

## 3. Verification philosophy

D2B must be automatically closable.

The implementation agent is expected to use a loopback HTTP test server,
failure injection, fake clocks, socket blocking and the existing full CI gate
to prove delivery, retry, ambiguity, deduplication, crash repair and secret
hygiene. The owner is **not** required to provision a real webhook or inspect a
manual delivery in D2B.

A real owner endpoint, real host/cadence and live unattended end-to-end
acceptance remain Phase 6-E.

## 4. Explicitly not selected

Do not mix in:

- Phase 6-D3 Dashboard monitoring projection;
- Phase 6-E live owner deployment/acceptance;
- Slack/Telegram/email-specific adapters;
- scheduled GitHub Actions monitoring;
- FQGate Bridge integration;
- CNINFO taxonomy/source expansion;
- Cloudflare mutation;
- trading/brokerage mutation;
- `strict-v1`, valuation, hard-gate or adjustment-approval changes.
