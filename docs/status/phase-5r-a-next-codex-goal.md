# Codex Goal — Phase 5R-A M4-C Artifact-backed Reconciliation Closure

Work in repository `blooddrunk/turtle-value-engine` on current `main`.

## Baseline and audited state

Use the current `main` descended from baseline `a0469f4`.

Read and follow `AGENTS.md` and the source-of-truth order before editing. Also read:

- `docs/goals/phase-5r-a-m4-cross-source-reconciliation.md`
- `docs/status/phase-5r-a-2026-09-18.md`
- `docs/architecture/production-historical-data-and-research-archive.md`
- `docs/operations/phase-5r-a-acquisition.md`
- `docs/goals/phase-5r-a-local-research-and-low-cost-sources.md`
- `docs/goals/phase-5r-a-production-source-acquisition.md`

Audited state:

- M4-A source/upstream qualification and persisted sample-spec contract are implemented.
- M4-B BaoStock sampled A-share daily unadjusted price-reference acquisition/decoder is implemented.
- M4-C comparator core is implemented, including PASS/FAIL/PARTIAL/MISSING, union missingness,
  basis/CNY/scope/independence checks and deterministic report hashing.
- M4-C is **not yet fully closed** because there is no dedicated artifact-backed execution path
  that loads the two frozen MARKET_BAR sources from manifest/store artifacts under the persisted
  sample spec and writes the reconciliation report.
- The legacy generic `tve dataset reconcile` JSON-value path must not be treated as M4 closure
  because it does not enforce the M4 sample/provider/upstream/provenance boundary.

## Current mandatory goal — smallest executable package

Close only the missing M4-C artifact-backed path.

1. Add the smallest library boundary that:
   - accepts a persisted `HistoricalReconciliationSampleSpec`;
   - reads canonical and independent `MARKET_BAR` rows from frozen
     `HistoricalDatasetManifest` + `HistoricalArtifactStore` inputs (or an equally explicit
     pair of frozen manifest/store references);
   - selects only the sample's listing/date scope;
   - verifies that source IDs and provider/upstream identities match the declared sample;
   - requires A-share / CNY / UNADJUSTED semantics;
   - calls the existing sampled reconciliation core without mutating either source artifact;
   - returns/persists the existing `HistoricalReconciliationReport`.

2. Add the thinnest CLI wrapper only if it materially improves reproducible owner execution.
   Prefer an additive M4-specific command/arguments over weakening the legacy generic
   `dataset reconcile` contract. Do not silently change old CLI semantics.

3. Add deterministic tests proving:
   - two frozen artifact stores/manifests -> M4 report end to end;
   - source/provider/upstream mismatch fails closed;
   - sample listing/date scope is enforced;
   - adjusted or non-CNY rows fail closed;
   - extra/missing sessions remain explicit MISSING/PARTIAL;
   - exact tolerance-boundary equality passes and just-outside fails;
   - repeated execution over identical frozen inputs produces identical report content hash;
   - old Phase 5R/M2/M3 fixtures and CLI behavior remain compatible.

4. Update only documentation whose factual state changes:
   - M4 goal;
   - architecture if a public library/CLI boundary is added;
   - acquisition runbook with exact offline reconciliation command if one exists;
   - dated status and this handoff.

## Owner-live rule

Do **not** require live network access for ordinary tests or for this code package to merge.

After the deterministic artifact-backed path is green, perform the smallest owner-authorized
live M4 BaoStock price sequence **only if the current runtime has access to the owner's private
environment and corresponding frozen Hithink sample**:

1. use the existing SH600000 Hithink sample window where possible (2020-01-01..2022-01-02;
   preferably the smallest overlapping subset);
2. create a private BaoStock M4 price plan using `baostock-a-share-price-reference`;
3. `historical source probe --network=allow`;
4. bounded `historical acquire --network=allow` into private raw CAS;
5. `historical compile --verify-replay`;
6. run the new offline artifact-backed reconciliation against the frozen Hithink source;
7. record only non-secret hashes, listing/date/count/status/tolerance/source identities and blockers.

If the runtime does not have the private Hithink artifact, owner BaoStock SDK environment, or
private CAS, stop at deterministic closure and record that **live evidence is pending**, not a
code blocker and not a failed source.

## Explicitly not current work

### Later optional M4-D
Corporate-action/reference-event audit. Do not start it in this goal.

### Later optional M4-E
Official-exchange lifecycle cross-check. Do not start it in this goal.

### Explicitly forbidden M2-D
Do not implement the AKShare/Eastmoney H fallback. Do not reopen H source selection, expand
H-share coverage, or modify `H_PRICE_SOURCE_SELECTED_FUTU`.

Also do not change `strict-v1`, deterministic investment math, PIT/A6 semantics,
`--require-production`, Phase 6 monitoring, R2/object-store work, Web UI/API, Tunnel/Access,
or any trading/financial-state functionality.

## Verification

Run at minimum:

```bash
python -m ruff check .
python -m pytest tests/test_m4_reconciliation.py -q
python -m pytest
```

Add focused commands for any new M4 artifact-backed test module/CLI test.

## Acceptance

This goal is complete when:

- M4-A and M4-B remain backward-compatible;
- the M4-C report can be generated solely from persisted sample spec + frozen artifact inputs;
- provider/upstream independence and price semantics cannot be bypassed by the execution path;
- missing sessions are preserved;
- reconciliation is deterministic and persisted/replayable;
- ordinary CI remains offline;
- no M4-D/M4-E/M2-D scope is pulled in;
- docs distinguish deterministic closure from owner-live evidence.

Do not claim `M4_FIXED_A_RECONCILIATION_PASS` until an owner-live independent BaoStock
price sample has actually been acquired/replayed and reconciled against the corresponding
frozen Hithink sample. Until then, use a precise state such as deterministic M4-C closed /
owner-live M4 evidence pending.
