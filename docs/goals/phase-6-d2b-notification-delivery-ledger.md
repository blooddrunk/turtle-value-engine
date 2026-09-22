# Phase 6-D2B — External Notification Delivery and Delivery/Receipt Ledger

Status: **SELECTED / NOT YET IMPLEMENTED**
Date: 2026-09-22
Selected after: Phase 6-D2A-R1 CLOSED
Selection audit: `docs/status/phase-6-d2b-selection-2026-09-22.md`
Coding-agent handoff: `docs/status/phase-6-d2b-next-coding-agent-goal.md`

## 1. Goal

Phase 6-D1 already produces one deterministic, immutable
`MonitoringAlertBatchV1` for a terminal cycle. Phase 6-D2A/R1 already provides
a durable single-host unattended activation, exact terminal receipt binding,
crash repair and truthful lease semantics.

D2B adds the missing delivery boundary:

> consume only a validated terminal D2A/D1 alert outbox, send it through one
> explicit external notification transport, and persist enough durable evidence
> to make retries, duplicate suppression, failure classification and audit
> machine-verifiable without changing investment semantics.

The first and only transport in this package is a **generic HTTP webhook**.
Slack, Telegram, email, vendor-specific bots and multi-channel routing are not
part of D2B. They may later adapt to the same transport/ledger boundary.

## 2. Non-negotiable boundaries

1. Do not change `strict-v1`, valuation math, hard gates, historical source
   selection, adjustment approval, monitoring impact semantics, Phase 6-A
   cursor semantics, Phase 6-C re-analysis semantics or Phase 6-D1 cycle
   identity.
2. Do not reopen or weaken the D2A/R1 lease/activation/receipt rules.
3. Delivery starts only after a canonical terminal D2A receipt exists and the
   exact D1 `MonitoringCycleResultV1` + `MonitoringAlertBatchV1` pair has
   been reloaded and hash/identity checked.
4. Delivery state is separate from D1 and D2A state. A delivery failure must
   never cause provider/model/re-analysis work to run again.
5. Network stays **deny by default**. A real HTTP request requires an explicit
   `--network allow` (or an equivalent already-established explicit opt-in).
   The deny path must be proven to perform zero socket I/O.
6. Extend typed project runtime configuration; do not invent raw-secret config
   files or a new ad-hoc environment convention.
7. Webhook URL/auth material is a `SecretReference` resolved only in process
   memory. No secret value may enter Git, delivery intents, attempts, receipts,
   status JSON, logs, exception text, test snapshots or safe config summaries.
8. No scheduled GitHub Actions monitoring, Dashboard monitoring projection,
   Cloudflare mutation, brokerage/trading mutation, FQGate Bridge adapter or
   owner live deployment belongs in this package.
9. Phase 6-E remains the place for a real owner webhook/host/cadence acceptance
   run. D2B must be closable without asking the owner to create an endpoint,
   token, account or manual screenshot.

## 3. Source binding

The delivery command/service must start from a terminal D2A activation, not
from arbitrary user-supplied alert JSON.

Recommended CLI shape (names may be adjusted to existing conventions):

```text
tve watch deliver \
  --runner-config <path> \
  --project-config <path> \
  [--activation-id <id>] \
  --network deny|allow

tve watch delivery-status \
  --delivery-root <path> \
  [--delivery-id <id>] \
  [--activation-id <id>]
```

The service must:

1. load the exact terminal `RunnerReceiptV1` (latest terminal activation when
   no activation id is supplied);
2. load the referenced terminal D1 result/outbox from the cycle store;
3. re-check cycle id, result hash, alert batch id and alert-batch hash against
   the runner receipt;
4. fail closed before any transport call if any artifact is missing, corrupt,
   non-canonical, foreign or mismatched;
5. derive one delivery identity from non-secret stable inputs such as:
   `runner_id + activation_id + alert_batch_id + destination_id +
   payload_contract_version`.

A changed endpoint/destination must not silently inherit a prior destination's
DELIVERED state. The typed configuration must give every destination an
explicit stable non-secret `destination_id`; changing logical destination
requires a new id/config version.

## 4. Durable delivery ledger

Implement a dedicated package (for example
`src/turtle_value_engine/monitoring_delivery/`) with checked-in JSON schemas.
Exact class/file names may follow repository conventions, but the persisted
model must cover these facts:

- immutable delivery intent persisted **before** outbound I/O;
- deterministic `delivery_id` and exact source bindings;
- monotonic attempt number;
- attempt start/finish timestamps from an injectable clock;
- transport name/version and non-secret destination id;
- request payload content hash;
- HTTP status when one was received;
- response body **hash only** (or another bounded non-secret digest), never raw
  untrusted response content by default;
- safe machine-readable error classification;
- atomic latest state/pointer;
- immutable successful terminal receipt.

At minimum the latest delivery state must distinguish:

```text
PENDING
DELIVERED
RETRYABLE_FAILURE
AMBIGUOUS
PERMANENT_FAILURE
NOOP
```

`NOOP` is valid for an empty alert batch and must perform zero network I/O.

A second invocation for an already `DELIVERED` delivery id must validate the
existing ledger and perform **zero** outbound requests.

Store writes must use the repository's existing durable patterns: canonical
JSON, hash validation, immutable artifact conflict detection, atomic pointer
publication, fsync where required, and explicit fail-closed behavior for
corrupt/symlink/foreign state. Crash injection tests must prove repair/retry
behavior instead of merely documenting it.

## 5. HTTP webhook transport

The first transport is a generic JSON webhook.

Required behavior:

- canonical bounded JSON body derived only from the validated alert batch plus
  non-secret delivery metadata;
- `Content-Type: application/json`;
- deterministic `Idempotency-Key` / TVE delivery-id header so a receiver that
  supports idempotency can deduplicate;
- no redirects by default (do not risk forwarding webhook secrets);
- bounded connect/read/write/overall timeout;
- bounded response bytes;
- safe user agent;
- no secret URL/header material in persisted artifacts or error text.

Status classification must be explicit and tested. A reasonable default is:

- any accepted 2xx -> `DELIVERED`;
- 429 and 5xx -> `RETRYABLE_FAILURE`;
- ordinary non-retryable 4xx -> `PERMANENT_FAILURE`;
- failures proven to occur before request dispatch may be retryable;
- timeout/connection loss after dispatch may have reached the receiver and must
  be `AMBIGUOUS`, not falsely called unsent or delivered.

D2B must **not claim exactly-once delivery** for arbitrary HTTP receivers.
Automatic retry of `AMBIGUOUS` is forbidden by default unless the configured
transport explicitly declares receiver-enforced idempotency. The deterministic
idempotency key is necessary evidence, not proof that an arbitrary receiver
honors it.

Retry count/backoff must be bounded, persisted and clock-injectable. Do not
sleep for long periods inside unit tests; test the scheduling decision using a
fake clock.

## 6. Configuration

Extend the existing typed ProjectConfig under `[monitoring]`, preferably a
nested `[monitoring.delivery]` object. The checked-in example remains safe and
disabled by default.

The configuration should include only non-secret policy plus references, for
example:

```text
enabled = false
transport = "webhook-v1"
destination_id = "owner-primary"
delivery_root = ".tve-private/monitoring/delivery"
endpoint_ref = { env = "TVE_MONITORING_WEBHOOK_URL" }
max_attempts = <bounded>
timeout_seconds = <bounded>
```

The exact endpoint value is resolved only at call time. Missing secret
reference, disabled delivery, invalid scheme/host, or network deny must fail
before an outbound request. Loopback HTTP may be allowed only through an
explicit test-only injection path; live configuration should require HTTPS.

`tve config validate` / safe summary must show destination id and secret
**reference name** only, never the resolved endpoint.

## 7. Automatic verification matrix

The coding agent must implement and run deterministic tests that prove, not
merely assert in prose, at least all of the following:

1. schema drift for every new persisted contract;
2. source receipt/outbox hash mismatch -> fail before transport;
3. corrupt/non-canonical delivery ledger -> fail closed;
4. deny-by-default -> sockets blocked/monkeypatched and zero request attempts;
5. empty outbox -> `NOOP`, zero request attempts;
6. local loopback webhook success -> exact canonical body + idempotency header,
   terminal `DELIVERED` receipt and safe status projection;
7. rerun after `DELIVERED` -> zero second HTTP request;
8. first 503/429 then success -> durable bounded retry with monotonic attempts;
9. permanent 4xx -> no automatic retry storm;
10. injected timeout after request dispatch -> `AMBIGUOUS`, no false success,
    no default automatic resend;
11. crash after intent / after remote response / before latest-pointer publish
    -> deterministic recovery with no D1/provider/model rerun;
12. secret URL/token canaries absent from all persisted files, CLI output,
    exception text and safe summaries;
13. existing D2A lease/runner tests remain unchanged and green;
14. existing D1/6-A/6-B/6-C semantics and full repository CI remain green.

Prefer a real in-process/loopback HTTP test server for success/status-code
tests and injected transport failure hooks for precise crash/timeout positions.
Tests must not contact the public Internet.

## 8. Required verification commands

At minimum, run all relevant targeted tests plus the complete repository gates:

```bash
python -m ruff check .
python -m pytest tests/test_monitoring_delivery.py
python -m pytest tests/test_monitoring_runner.py tests/test_monitoring_cycle.py tests/test_monitoring_cli.py
python -m pytest
```

If the implementation changes project config/template behavior, include its
existing config validation tests. If it changes generated schemas or other
generated artifacts, run the repository's canonical drift check/update command
and prove a clean diff.

The package is not CLOSED until GitHub Actions succeeds on the **exact
implementation SHA**. The closing status record must include:

- implementation SHA;
- Actions run id + conclusion;
- local full-suite pass/skip counts;
- new targeted delivery test count;
- exact file scope;
- explicit statement that no public live endpoint/manual owner acceptance was
  required;
- any genuinely remaining boundary, assigned to a named later phase.

If Actions cannot be queried automatically in the agent environment, do not
write `CLOSED`. Record `IMPLEMENTED / CI_PENDING` with the exact SHA and the
single concrete remaining verification command/API lookup. Do not replace
missing evidence with vague language.

## 9. Stop boundary

Do not start Phase 6-D3 Dashboard monitoring views or Phase 6-E owner live
unattended acceptance in this package. Do not add Slack/Telegram/email-specific
adapters just because the generic webhook boundary exists. Do not modify
financial decision rules.

When D2B closes, the next candidate package is Phase 6-D3 read-only monitoring
projection, while Phase 6-E remains the bounded real deployment/notification
acceptance step.
