# Codex Goal — Phase 5R-A M4 Cross-source Reconciliation

Work in repository `blooddrunk/turtle-value-engine` on current `main`.

## Current execution state — 2026-09-18

M3 BaoStock A-share lifecycle/calendar acquisition is complete at the bounded
personal-research slice:

- owner-authorized live probe passed;
- decoded SDK exports were frozen into private raw CAS;
- offline compile/replay produced typed `LISTING_LIFECYCLE` and
  `TRADING_SESSION` shards;
- ordinary CI and deterministic analysis remain offline.

M2-E remains frozen exactly as:

```text
H_PRICE_SOURCE_SELECTED_FUTU
```

Futu remains only the selected bounded personal-research H daily unadjusted
`MARKET_BAR` source. M2-D remains gated and must not be implemented merely to
manufacture a comparison. M4 must not enlarge H-share coverage.

The executable M4 plan is:

- `docs/goals/phase-5r-a-m4-cross-source-reconciliation.md`

The M3 live/replay record and remaining broader blockers are:

- `docs/status/phase-5r-a-2026-09-18.md`

## Objective

Implement the smallest coherent M4 vertical slice for a **fixed private
A-share research set**, preserving source independence, deterministic replay and
explicit missingness.

Start with M4-A/B/C from the dedicated goal:

1. source/upstream independence guard plus deterministic sample specification;
2. an additive BaoStock sampled A-share unadjusted daily price-reference
   adapter/decoder, without changing the existing M3 lifecycle adapter identity;
3. sampled close-price reconciliation using the existing
   `HistoricalReconciliationReport` / `reconcile_observations` contract.

Do not start by broadening the H-share path or by replacing Hithink as the
canonical bounded A-share price source.

## Mandatory source-of-truth reading

Before changing behavior, read and follow `AGENTS.md` and its source-of-truth
order, especially:

- `docs/spec/`
- `rules/strict-v1.yaml`
- `schemas/`
- `docs/architecture/production-historical-data-and-research-archive.md`
- `docs/goals/phase-5r-production-historical-corpus.md`
- `docs/goals/phase-5r-a-production-source-acquisition.md`
- `docs/goals/phase-5r-a-local-research-and-low-cost-sources.md`
- `docs/goals/phase-5r-a-m4-cross-source-reconciliation.md`
- `docs/operations/phase-5r-a-acquisition.md`
- `docs/status/phase-5r-a-2026-09-18.md`

If a lower-priority document conflicts with a frozen contract, preserve the
higher-priority contract and prefer an additive/versioned design.

## Frozen boundaries

- keep `H_PRICE_SOURCE_SELECTED_FUTU` byte-for-byte/conceptually unchanged;
- do not implement M2-D;
- do not expand any H-share coverage claim;
- do not change `strict-v1`, deterministic investment calculations, PIT rules,
  A6 semantics or `--require-production`;
- keep ordinary CI offline/model-free;
- keep private provider bytes, credentials and restricted artifacts outside Git;
- do not silently repair missing data or overwrite canonical observations from
  reconciliation results.

## First implementation acceptance

The first M4 merge should, at minimum, prove:

1. different source IDs are insufficient for independence when provider/upstream
   identity is the same or unresolved;
2. a frozen fake BaoStock A-share daily unadjusted price response can travel
   through acquire -> private-CAS-compatible envelope -> offline compile/replay
   deterministically;
3. malformed schemas, adjusted mode, H identities, duplicate/conflicting natural
   keys and out-of-scope rows fail closed;
4. deterministic sampled close-price reconciliation can produce PASS, FAIL and
   PARTIAL/MISSING outcomes;
5. missing or extra sessions are retained as explicit missing counterparts and
   are not removed by intersecting source dates;
6. repeated reconciliation over identical frozen inputs produces the same
   content identity;
7. existing Phase 5R fixtures, M2-E state and M3 lifecycle/calendar tests remain
   compatible.

Only after this bounded price path is proven should M4-D/E add corporate-action
reference auditing and official-exchange lifecycle cross-checking as described
in the dedicated M4 goal. Do not force event/lifecycle semantics through the
scalar price-reconciliation contract; use an additive typed/versioned sidecar
when required to preserve old hashed v1 artifacts.

## Live evidence rule

Live work is optional and owner-authorized only. If the runtime can access the
candidate independent source after deterministic tests pass, run the smallest
bounded A-share probe/acquire/replay and then reconcile offline. If live access
is unavailable or source independence cannot be proven, retain an explicit M4
blocker instead of fabricating a PASS or selecting a correlated source.

## Verification

Before declaring a code package complete:

```bash
python -m ruff check .
python -m pytest
```

Update architecture/operations/status documentation only after the corresponding
behavior is executable and observed. Do not add implementation history to
`AGENTS.md` or the root README.
