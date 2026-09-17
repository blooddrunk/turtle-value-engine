# Codex Goal — Phase 5R-A M3 A-share Lifecycle and Calendar Automation

Work in repository `blooddrunk/turtle-value-engine` on current `main` after the M2-E
closure is merged.

## Current execution state — 2026-09-17

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
economics, corporate actions, benchmark/FX, filings, complete coverage or redistributable
source terms. Those wider claims remain fail-closed.

## Next objective

Execute the repository-defined **M3 — A-share lifecycle/calendar automation** from
`docs/goals/phase-5r-a-local-research-and-low-cost-sources.md` as a separate package.

The purpose is to close practical A-share historical interpretation gaps with the smallest
reliable automated source path for trading dates and listing lifecycle/basic fields. Use
BaoStock if its current documented/runtime evidence is sufficient; an equivalent reliable
source is acceptable if it better preserves provenance and point-in-time semantics. Do
not require the owner to hand-prepare lifecycle or calendar tables.

## Required first steps

Before changing code, read and follow:

- `AGENTS.md`
- `docs/spec/`
- `rules/strict-v1.yaml`
- `schemas/`
- `docs/architecture/`
- `docs/goals/phase-5r-a-local-research-and-low-cost-sources.md`
- `docs/goals/phase-5r-a-production-source-acquisition.md`
- `docs/goals/phase-5r-production-historical-corpus.md`
- `docs/status/phase-5r-a-2026-09-17.md`
- `docs/operations/phase-5r-a-acquisition.md`
- the M2-E closure record named above.

Inspect the actual repository contracts before deciding whether M3 needs a new adapter,
an additive schema/contract, or can reuse existing historical acquisition and lifecycle
contracts. Prefer the smallest coherent implementation and keep ordinary CI offline.

## M3 boundaries

M3 should focus on **A-share** calendar/lifecycle automation only. Preserve all existing
investment and historical semantics.

At minimum, investigate and, only when evidenced, automate the facts needed to interpret a
bounded A-share historical slice, such as:

- exchange trading dates/calendar identity;
- listing/IPO effective date;
- terminal/out date and listing status when the selected source actually provides them;
- stable listing/code identity needed by existing lifecycle contracts.

Do not infer historical membership from a current security master. Do not invent code
changes, delisting outcomes, suspension semantics or terminal economics when the source
does not prove them. A source that provides only part of the lifecycle must narrow the
claim and leave exact blockers for the rest.

## Explicit non-goals

Do not reopen or rerun M2-C, and do not implement M2-D merely for comparison. Do not in
this package implement H-share lifecycle reconstruction, corporate actions, full
historical membership, terminal-economics reconstruction, Phase 6, Cloudflare/R2,
Tunnel/Access, Web UI, trading, orders, transfers or any other state-changing financial
operation.

Do not change:

- `rules/strict-v1.yaml` or investment calculations/gates/valuation;
- A6 acceptance semantics;
- point-in-time semantics;
- existing historical coverage semantics;
- selected Futu bounded H price role;
- existing provider compatibility.

## Evidence and tests

Live/provider capability claims require actual documented/runtime evidence. Ordinary tests
must use frozen/fake inputs and remain network-free. Persist provenance before canonical
projection, keep missing facts explicit, and preserve deterministic replay identities.

Run at minimum:

```bash
python -m ruff check .
python -m pytest
```

Update the M3 goal/status/operations documentation with the actual implementation result,
exact remaining lifecycle/calendar limitations, and the next repository-defined handoff.
