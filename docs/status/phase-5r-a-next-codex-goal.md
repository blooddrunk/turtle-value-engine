# Codex Goal — Phase 5R-A M2-C Futu OpenD H `MARKET_BAR` Candidate

Work in repository `blooddrunk/turtle-value-engine` on current `main`.

## Current handoff

M2-B is closed with an evidence-supported FQGate selection failure. After the owner
started a local FQGate instance, two fresh `LOCAL_DIRECT` probes used the exact
owner-observed candidate `UHKM/HK0700` (`HK00700`):

- recent window `2026-09-08` through `2026-09-11`;
- older window `2025-09-08` through `2025-09-11`.

Both reached `/v1/market/history/klines` and returned HTTP 504 with provider code `4003`,
no usable daily rows, and the conservative diagnostics
`FQGATE_HTTP_504_UNCLASSIFIED`, `FQGATE_PROVIDER_ERROR_CODE` and
`FQGATE_PROVIDER_ERROR_UNCLASSIFIED`. Code `4003` has no established semantics and must
not be reclassified as route rejection, upstream timeout or entitlement denial. The
successful `realtime/hk` response is a different interface and is not historical
`MARKET_BAR` evidence.

FQGate therefore did not earn the bounded H price role. H remains
`H_SOURCE_UNQUALIFIED`; lifecycle, membership, delisting, terminal and corporate-action
coverage remain unqualified. No FQGate acquisition/compile was run because the M2-B
acquisition gate requires both bounded probes to succeed.

Read and follow, in source-of-truth order:

- `AGENTS.md`
- `docs/spec/`
- `rules/strict-v1.yaml`
- `schemas/`
- `docs/architecture/`
- `docs/goals/phase-5r-a-m2-h-share-history-source-selection.md`
- `docs/goals/phase-5r-a-m2-t-fqgate-endpoint-transport.md`
- `docs/status/phase-5r-a-2026-09-17.md`
- `docs/operations/phase-5r-a-acquisition.md`
- `src/turtle_value_engine/historical/fqgate.py`
- `src/turtle_value_engine/historical/acquisition.py`
- relevant compiler/replay tests and CLI code

## Objective

Evaluate Futu OpenD as the next bounded H-share unadjusted daily-price candidate through
the existing acquisition boundary. Implement only M2-C. Do not change investment math,
strict-v1, A6, PIT or historical coverage semantics.

## Required boundary

- Use local OpenD only through an explicit opt-in historical acquisition path; ordinary CI
  must remain offline.
- Use a stock identity actually returned or accepted by the owner’s OpenD runtime; do not
  invent H identifiers or reuse FQGate routing fields as a Futu mapping.
- Force daily unadjusted history (`AuType.NONE` / documented equivalent).
- Inspect historical quota and permission outcomes where the runtime supports it.
- Distinguish OpenD unavailable, quota exhausted, entitlement denied, transport failure and
  incomplete history without guessing from free-form messages.
- Page deterministically and preserve page order.
- Freeze the complete pre-normalization SDK response and request metadata into private CAS
  with an explicit representation such as `futu-opend-sdk-export-v1`; do not call an SDK
  export raw OpenD wire bytes.
- Compile only verified required OHLCV/turnover fields into canonical `MARKET_BAR`.
- Do not claim delisted retention, historical membership, lifecycle, actions or terminal
  economics from an API’s existence or a row count.

If Futu obtains both a recent and an at-least-one-year-older bounded window, run one
bounded acquire -> raw/envelope -> compile -> `--verify-replay` flow. If it cannot, record
the exact blocker and hand off M2-D; do not implement M2-D in this goal.

## Offline tests

Use an injected fake OpenD client; no OpenD process or internet access is allowed in CI.
Cover at least:

- unadjusted daily mapping;
- deterministic multi-page ordering and export;
- quota exhausted vs entitlement denied vs OpenD unavailable;
- malformed or changed schema fails closed;
- bounded date filtering;
- repeated offline compilation produces identical manifest/shard hashes;
- no credentials or session secrets enter plans, logs, receipts or fixtures.

Run at minimum:

```bash
python -m pytest tests/test_futu_opend_historical.py -q
python -m pytest tests/test_phase_5r_acquisition.py -q
python -m ruff check .
python -m pytest
```

Do not implement AKShare/Eastmoney, lifecycle or membership reconstruction, corporate
actions, Cloudflare/Tunnel/Access, Web UI, Phase 6 monitoring, or trading operations in
M2-C.
