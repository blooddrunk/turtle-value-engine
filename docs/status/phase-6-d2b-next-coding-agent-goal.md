# Phase 6-D2B coding-agent handoff — external notification delivery

Status: **ACTIVE / IMPLEMENT THIS GOAL**

Canonical goal:
`docs/goals/phase-6-d2b-notification-delivery-ledger.md`

Selection audit:
`docs/status/phase-6-d2b-selection-2026-09-22.md`

Baseline at selection:
`168cd628ae749bd1a10b458625fdd733f22cf11b`

## Goal

Implement Phase 6-D2B exactly as defined by the canonical goal: a provider-
neutral durable delivery ledger plus one generic HTTP webhook transport,
consuming only a validated terminal D2A/D1 alert outbox.

This package must be demonstrably safe under retry, crash, duplicate invocation,
HTTP failure and secret handling. Do not substitute prose for executable
evidence.

## Required implementation posture

- Read and obey `AGENTS.md`, the D2B goal, D2A/R1 closure evidence, D1 goal,
  runtime architecture and current roadmap before changing code.
- Preserve every Phase 6-D2A-R1 invariant.
- Keep network deny-by-default and secret values out of persisted/output state.
- Persist delivery intent before outbound I/O.
- Never re-run D1/provider/model work merely because delivery failed.
- Do not claim arbitrary-webhook exactly-once semantics.
- Treat post-dispatch uncertainty as `AMBIGUOUS`; do not silently resend it by
  default.
- Add one generic HTTP webhook transport only.
- No manual owner acceptance is needed or desired in this phase.

## Automated proof required before claiming completion

Create targeted tests for all items in the D2B goal, including:

- source binding and mismatch failure before network;
- socket-blocked deny path;
- empty-outbox NOOP;
- loopback success and exact request body/idempotency key;
- delivered replay with zero duplicate HTTP request;
- bounded 429/5xx retry;
- permanent 4xx;
- post-dispatch timeout -> AMBIGUOUS;
- crash/repair at ledger publication boundaries;
- corrupt/foreign ledger fail-closed behavior;
- secret-canary non-persistence/non-output;
- schema drift.

Then run:

```bash
python -m ruff check .
python -m pytest tests/test_monitoring_delivery.py
python -m pytest tests/test_monitoring_runner.py tests/test_monitoring_cycle.py tests/test_monitoring_cli.py
python -m pytest
```

Run any additional repository-native config/schema generation checks required by
the files you change. Do not weaken or skip failing existing tests.

After committing/pushing the implementation, automatically verify GitHub
Actions for the exact implementation SHA whenever the environment permits it.
Do not close the phase from a green run on another SHA.

The final closure record must contain the exact SHA, exact Actions run id,
conclusion, full pass/skip counts, targeted test count and remaining later-phase
boundaries. If Actions genuinely cannot be queried, mark
`IMPLEMENTED / CI_PENDING` and give the exact remaining lookup/command instead
of writing vague "evidence unavailable" text.

## Stop

Do not start D3, 6-E, vendor-specific notification integrations, Bridge,
Cloudflare mutation or any investment-rule change.
