# Codex Goal — Phase 5R-A M2-E H-share Source Selection Record

Work in repository `blooddrunk/turtle-value-engine` on current `main`.

## Current execution state — 2026-09-17

M2-C is complete with outcome **`FUTU_SELECTED`**. Futu OpenD earned the bounded H-share
unadjusted daily `MARKET_BAR` role for private research. M2-D AKShare/Eastmoney is gated
and must not be implemented as provider proliferation.

The genuine owner runtime evidence is:

- OpenD Ready on `127.0.0.1:11111`; owner completed the required login/questionnaire flow.
- `futu-api==10.10.7008` connected successfully.
- The runtime returned 3,790 Hong Kong stock rows and the exact accepted/returned H identity
  used for the probes was `HK.00001`.
- History quota preflight was `used=0`, `remaining=100`.
- `2026-09-15..2026-09-17` returned 3 rows with daily `K_DAY` and explicit unadjusted
  `AuType.NONE`.
- `2025-09-15..2025-09-17` returned 3 rows with the same identity and explicit request
  semantics.
- Only after both probes passed, bounded acquire froze the private
  `futu-opend-sdk-export-v1` envelope; offline compile with `--verify-replay` succeeded
  and produced 3 canonical `MARKET_BAR` rows.

The private evidence remains under `.tve-private` and is not committed. The bounded
selection does not establish historical membership, lifecycle, delisting/terminal
economics, corporate actions, benchmark/FX, filings, complete coverage or redistributable
source terms. Broader `H_SOURCE_UNQUALIFIED` and readiness blockers remain fail-closed for
those claims.

## Objective

Close the repository-defined **M2-E selection record** without changing investment math or
turning a bounded price-source selection into a complete historical-corpus claim.

Use the existing source-selection contract in
`docs/goals/phase-5r-a-m2-h-share-history-source-selection.md`. Record Futu as:

```text
H_PRICE_SOURCE_SELECTED_FUTU
role = primary bounded personal-research H daily unadjusted MARKET_BAR source
```

## Required work

1. Read the source-of-truth documents in `AGENTS.md`, `docs/spec/`,
   `rules/strict-v1.yaml`, `schemas/`, `docs/architecture/`, the M2 parent goal and the
   M2-C goal before changing behavior.
2. Make the selection record machine/auditor-readable using the existing status and
   historical provenance contracts. Preserve the exact observed identity, two windows,
   quota/permission result, provider representation, private batch/manifest identities and
   limitations.
3. If an independent H source is later genuinely available, use the existing historical
   reconciliation contract for an overlapping-session comparison. Do not add a new
   provider merely to create a comparison and do not silently change rows on discrepancy.
4. Keep `.tve-private` artifacts local and keep ordinary imports, CI and deterministic
   analysis offline. Run the full repository verification after any code change.

## Acceptance

- The dated status and M2 parent/child goal records contain exactly one bounded source
  selection state: `H_PRICE_SOURCE_SELECTED_FUTU`.
- The record distinguishes the selected bounded price role from unresolved membership,
  lifecycle, terminal, corporate-action, complete-coverage and licensing claims.
- No change is made to `strict-v1`, A6, PIT, historical coverage semantics, deterministic
  investment math or existing provider compatibility.
- M2-D, lifecycle/membership reconstruction, corporate actions, Phase 6, Tunnel/Access,
  Web UI and trading/state-changing operations remain unimplemented.

## Verification guardrails

```bash
python -m ruff check .
python -m pytest
```

This is the next handoff after M2-C. Do not reopen M2-C or treat the earlier blocked probe
state as current; the owner-runtime evidence and replay result above are now recorded.
