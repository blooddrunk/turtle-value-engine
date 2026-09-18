# Codex Goal — Phase 5R-A M3 A-share Lifecycle/Calendar Automation

Work in repository `blooddrunk/turtle-value-engine` on current `main` after the M2-E
closure is merged.

## Current execution state — 2026-09-18

Phase 5R-A M2 is closed with the machine/auditor-readable source-selection state:

```text
H_PRICE_SOURCE_SELECTED_FUTU
```

Futu OpenD is selected only as the **primary bounded personal-research H daily unadjusted
`MARKET_BAR` source**. The closure record is:

- `docs/goals/phase-5r-a-m2-e-h-share-source-selection-record.md`
- `docs/status/phase-5r-a-m2-e-h-share-source-selection.json`

M2-D AKShare/Eastmoney was not implemented. The bounded Futu result does not establish a
complete H historical corpus, historical membership, lifecycle, delisting/terminal
economics, corporate actions, benchmark/FX, filings, complete coverage or a public
redistribution claim. Those wider claims remain fail-closed.

M3's owner-authorized bounded live slice is complete: BaoStock `0.9.3` / SDK runtime
`00.9.30` passed lifecycle and SSE calendar probes for `SH600000`, acquired two private
raw-CAS envelopes, and compiled/replayed typed lifecycle and trading-session shards offline.
The private run records source provenance and the owner's non-public-use scope; a free/open
license is not a prerequisite for this private research path. This does not establish
historical membership, complete terminal economics or any H-share coverage.

The private evidence remains under `.tve-private` and is not committed. The detailed M3
run, hashes and remaining blockers are recorded in
`docs/status/phase-5r-a-2026-09-18.md`.

## Frozen M2-E decision

The previous M2-E record remains unchanged and is not reopened:

```text
H_PRICE_SOURCE_SELECTED_FUTU
role = primary bounded personal-research H daily unadjusted MARKET_BAR source
```

## Objective

Implement the repository-defined **M3 A-share lifecycle/calendar automation** without
changing investment math, weakening A6/PIT semantics, or turning a bounded A-share source
into a complete historical-corpus claim.

The implementation must use the existing opt-in acquisition -> raw CAS -> offline compiler
boundary. It must not implement M2-D or enlarge any H-share coverage declaration.

## Required work

1. Read the source-of-truth documents in `AGENTS.md`, `docs/spec/`,
   `rules/strict-v1.yaml`, `schemas/`, `docs/architecture/`, the M2 parent goal and the
   M2-C goal before changing behavior.
2. Add the smallest lazy/injected BaoStock (or equivalent) adapter for:
   - `query_trade_dates` -> explicit `TRADING_SESSION` rows;
   - `query_stock_basic` -> typed A-share listing lifecycle/basic fields.
3. Freeze the decoded SDK result as a complete, redacted, hashable provider envelope before
   offline decoding. Reject unsupported fields, dates, listing identity, status and terminal
   shapes rather than silently coercing them.
4. Let explicit trading-session rows supply expected price sessions when a price request did
   not manually provide them. Preserve missing bars as missing; do not infer suspension.
5. Add deterministic fake-client coverage for acquire -> CAS -> compile/replay, lifecycle
   and calendar validation, malformed responses, and H-share rejection.
6. Keep `.tve-private` artifacts local and keep ordinary imports, CI and deterministic
   analysis offline. Run the full repository verification after any code change.

## Acceptance

- The prior bounded selection state remains exactly `H_PRICE_SOURCE_SELECTED_FUTU`; no
  M2-D adapter or H-share coverage expansion is added.
- A canonical A-share request can acquire and freeze BaoStock lifecycle and trade-date
  responses through the existing raw CAS boundary, with no SDK import during ordinary
  offline use.
- Offline replay emits typed `LISTING_LIFECYCLE` and `TRADING_SESSION` shards with source
  hashes, deterministic IDs, bounded dates and explicit calendar identity.
- A price coverage report can derive expected trading sessions from frozen calendar rows;
  missing price rows remain `PARTIAL`/missing and are never changed into zeros or inferred
  suspension.
- Unsupported provider schema, H-share IDs, inconsistent status/outDate, missing terminal
  fields, and calendar/listing mismatches fail closed.
- Existing old manifests/batches, `strict-v1`, A6/PIT validation, deterministic investment
  math and existing provider compatibility remain intact. BaoStock does not prove historical
  membership, complete delisted retention, terminal economics, a broad source-authority or
  redistribution claim, or H-share data.
- M4 reconciliation, Phase 6, Tunnel/Access, Web UI and trading/state-changing operations
  remain unimplemented.

## Verification guardrails

```bash
python -m ruff check .
python -m pytest
```

This document defined the M3 implementation boundary after M2-E. The code and bounded
live/replay slice are now complete; the next implementation handoff is M4 reconciliation.
Do not reopen M2-C/M2-E, implement M2-D, or treat a BaoStock current/basic response as
historical membership or complete lifecycle coverage.
