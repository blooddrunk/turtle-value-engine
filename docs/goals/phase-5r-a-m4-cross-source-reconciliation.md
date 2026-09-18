# Phase 5R-A M4 — Cross-source Reconciliation for Fixed A-share Private Research

Status: **CLOSED / PARTIAL**
Date: 2026-09-18
Baseline: `a0469f4`
Parent goals:
- `docs/goals/phase-5r-a-local-research-and-low-cost-sources.md`
- `docs/goals/phase-5r-a-production-source-acquisition.md`
- `docs/goals/phase-5r-production-historical-corpus.md`

Implementation state: M4-A and M4-B are implemented and M4-C is closed,
including the artifact-backed deterministic path and a minimum owner-authorized
BaoStock/Hithink fixed-A price sample with a 2/2 PASS. The new library/CLI path
reads frozen canonical and independent `MARKET_BAR` shards under the persisted
sample specification, verifies source/adapter/provider/upstream identity and
A/CNY/UNADJUSTED semantics, preserves union missingness, and persists the
existing `HistoricalReconciliationReport`. The legacy generic
`tve dataset reconcile` JSON-value path remains unchanged and is not M4
closure evidence. M4-D/M4-E were deliberately deferred as optional future
research-quality extensions. Therefore, under the closure definitions in
section 9, the **price reconciliation report is PASS while overall M4 closes as
`M4_FIXED_A_RECONCILIATION_PARTIAL`**. M2-D remains out of scope.

## 1. Objective

Close the next bounded Phase 5R-A milestone by adding **real, replayable cross-source
reconciliation for a fixed private A-share research set**.

M4 must answer a narrower question than full Phase 5R/A6 production acceptance:

> For explicitly named A-share listings and dates, do independently sourced price,
> corporate-action/reference-event and listing-lifecycle observations agree closely enough
> to make the private research corpus more trustworthy and auditable?

M4 does **not** make a survivorship-free market-wide claim. It does not require a complete
A/H corpus before useful private research can continue.

## 2. Frozen boundaries

The following decisions are not reopened by M4:

1. M2-E remains exactly `H_PRICE_SOURCE_SELECTED_FUTU`.
2. Futu remains the primary bounded personal-research H daily unadjusted `MARKET_BAR`
   source selected by M2-E.
3. M2-D AKShare/Eastmoney H fallback is not implemented merely to manufacture a comparison.
4. M4 does not enlarge any H-share price, lifecycle, action, filing, membership, terminal
   or coverage claim.
5. M3 BaoStock A-share lifecycle/calendar acquisition, private raw CAS and offline replay
   remain the baseline and remain backward compatible.
6. `rules/strict-v1.yaml`, deterministic investment math, PIT rules, A6 semantics and
   `--require-production` semantics remain unchanged.
7. Ordinary CI remains offline/model-free. Live probes remain explicit, owner-authorized
   and outside ordinary CI.
8. Private provider bytes, credentials and restricted artifacts stay outside Git.

## 3. Current baseline

The repository already proves:

- Hithink A-share unadjusted daily history acquisition into private CAS and deterministic
  offline replay for the bounded `SH600000` research slice;
- BaoStock `query_stock_basic` plus `query_trade_dates` acquisition into private CAS,
  with typed `LISTING_LIFECYCLE` and `TRADING_SESSION` replay;
- the existing scalar `HistoricalReconciliationReport` / `reconcile_observations`
  contract for deterministic numeric comparison;
- an offline `historical accept` boundary that remains fail-closed when broader A/H
  evidence is absent.

The M3 run does not prove historical membership, complete delisted retention, terminal
economics or a broad market-wide lifecycle claim.

## 4. Source-selection decision for M4

M4 must evaluate independence by **data-provider/upstream identity**, not by adapter name.
Two different adapters are not independent when they ultimately expose the same upstream
dataset.

The existing acquisition contract already separates `adapter_id` from `provider_id`.
Use that separation deliberately:

- `adapter_id` describes the technical transport/SDK wrapper;
- `provider_id` must identify the actual data provider/upstream that the evidence came
  from;
- an aggregator/wrapper such as AKShare must not be recorded as an independent authority
  if the actual upstream is SSE, SZSE, Eastmoney, Sina or another named source.

Do not count Hithink and an unproven FQGate/Tonghuashun-derived path as independent merely
because their adapters differ. If upstream independence is unresolved, keep an explicit
`RECONCILIATION_SOURCE_INDEPENDENCE_UNPROVEN` blocker.

### 4.1 Price reference — preferred first path

Keep the existing Hithink unadjusted A-share daily `MARKET_BAR` slice as the canonical
price path for M4.

The preferred second source is an additive BaoStock sampled-market reference using the
already proven lazy SDK/private-CAS boundary, but with a **new additive adapter identity**
rather than changing the meaning of the M3 lifecycle adapter. Probe
`query_history_k_data_plus` for daily, unadjusted A-share bars and freeze the complete
decoded SDK export before offline decoding.

This is intentionally a sampled reconciliation role. It does not replace Hithink as the
bulk A-price path and does not create a market-wide BaoStock coverage claim.

If the BaoStock price path is not live/replayable for the declared sample, a fallback may
use another genuinely independent A-share provider through the same acquisition/CAS
boundary. Futu A-share history is only a fallback candidate and must first pass the owner
runtime's A-share entitlement/capability probe; do not alter the frozen M2-E H-share role
to make that possible.

### 4.2 Corporate-action/reference-event comparison

Treat Hithink adjustment-factor data and BaoStock dividend/adjustment data as **reference
evidence first**, not automatically as canonical `CorporateAction` rows.

M4 should probe/freeze the minimum provider responses needed to compare, where semantics
are explicit on both sides:

- event/effective/ex-date;
- cash dividend per share;
- bonus/split factor;
- rights/allotment ratio;
- rights/allotment price;
- adjustment-factor dates/values as reconciliation signals.

An adjustment factor is not itself a corporate action. Do not derive a cash dividend,
split or rights issue from a factor unless the source semantics and mapping are explicitly
proven. The existing Hithink decoder's default reconciliation-only guard remains in force.

If action semantics cannot be normalized safely, persist the raw reference evidence and
an explicit blocker instead of coercing it into `CorporateAction`.

### 4.3 Lifecycle reference — official exchange path

Keep BaoStock `query_stock_basic` as the existing bounded M3 lifecycle/basic evidence.

For lifecycle reconciliation, prefer an independent official exchange source for the
declared fixed A-share listings:

- SSE for Shanghai listings;
- SZSE for Shenzhen listings;
- BSE for Beijing listings when/if the fixed research set actually contains them.

A thin direct adapter is acceptable. An existing AKShare function may be used as a
technical wrapper only when the persisted `provider_id` and source provenance identify
the actual exchange/upstream and the acquisition still goes through raw CAS/offline replay.

Compare only facts the second source actually proves, such as listing date, terminal date,
status or code/name change. Absence of a delisting row is not proof of ACTIVE status unless
the source scope is demonstrably complete for that claim.

## 5. Reconciliation semantics

### 5.1 Deterministic sample specification

Do not choose live samples randomly.

Persist a bounded sample specification containing at least:

- target ID;
- explicit listing IDs;
- explicit inclusive date range;
- canonical source ID;
- independent source ID;
- price basis;
- compared field/semantic;
- deterministic tolerance or exact-match rule;
- sample-selection rationale;
- source/provider identities.

For the first M4 vertical slice, re-use `SH600000` where practical so M3 evidence and the
existing Hithink slice remain directly comparable. Expansion to additional A listings must
be explicit and justified by the fixed research set, not by a desire to simulate
market-wide coverage.

### 5.2 Price reconciliation

Use the existing `HistoricalReconciliationReport` for the first numeric price check
rather than inventing a parallel numeric contract.

The first required comparison is unadjusted daily **close** on the intersection/union of
the declared sampled sessions:

- same canonical listing identity;
- same calendar date;
- same CNY unit;
- both sources explicitly unadjusted;
- missing on either side remains `MISSING` and makes the report `PARTIAL`;
- a discrepancy beyond the declared tolerance remains `FAIL`;
- no reconciliation result may rewrite either source's canonical rows.

Tolerance must be justified by documented/observed source precision before the live run.
Do not loosen tolerance after seeing a mismatch merely to make a report pass.

Optional OHLC/volume/turnover diagnostics may be added after close-price reconciliation
works, but they must not overload the meaning of a `PRICE_RETURN` report without an
explicit documented contract.

### 5.3 Corporate-action/reference-event reconciliation

Use a deterministic category-specific comparator rather than forcing event payloads
through the scalar price report.

Match events by explicit normalized keys, preferably:

`(listing_id, action_type/reference_kind, effective_or_ex_date)`.

For fields present on both sides:

- exact-match dates and event type;
- numeric tolerance only for explicitly comparable numeric terms;
- missing counterpart -> `MISSING/PARTIAL`;
- incompatible event semantics -> fail closed;
- contradictory numeric terms -> `FAIL`.

For M4, this comparator may be a typed sidecar/audit artifact rather than changing the
hashed v1 historical manifest contract. Do not add a default field to an existing hashed
v1 model if doing so would invalidate old persisted hashes. If persistence needs a new
wire contract, add a versioned sidecar contract/schema and keep old fixtures readable.

### 5.4 Lifecycle reconciliation

Use exact deterministic comparison after explicit provider-to-canonical normalization:

- listing identity/exchange;
- listing date;
- terminal/out date when supplied;
- active/terminal status when supplied;
- code/name-change facts only when effective dates are explicit.

No fuzzy name matching is allowed for identity. Missing official scope remains
`UNKNOWN/MISSING`, not a pass.

Like action reconciliation, lifecycle comparison may initially be a typed sidecar audit
artifact so M4 does not destabilize the existing content-addressed manifest identities.

## 6. Implementation work packages

### M4-A — Source qualification and independence guard

1. Add a deterministic helper/check that refuses a reconciliation claim when canonical
   and independent evidence do not have demonstrably distinct provider/upstream identity.
2. Keep `adapter_id` and `provider_id` semantics explicit in tests and docs.
3. Add stable diagnostics for unresolved independence.
4. Add/freeze a deterministic M4 sample specification.

Acceptance:
- different source IDs backed by the same provider/upstream cannot earn an independent
  PASS;
- an AKShare wrapper cannot hide its upstream identity;
- old M2/M3 acquisition plans and manifests remain readable.

### M4-B — BaoStock sampled unadjusted price reference

1. Add the smallest additive BaoStock market-reference adapter/decoder for daily
   `query_history_k_data_plus`.
2. Require explicit daily frequency and unadjusted mode.
3. Freeze the complete decoded SDK response in private CAS before decoding.
4. Emit canonical `MARKET_BAR` rows only for verified fields and exact A-share identity.
5. Keep the M3 `baostock-a-share-lifecycle` request identity/semantics unchanged.

Acceptance:
- fake acquire -> CAS -> offline compile/replay is identity-stable;
- malformed fields, adjusted mode, H identities, out-of-range rows and duplicate semantic
  rows fail closed;
- a bounded owner-authorized price probe can be recorded without broadening coverage.

### M4-C — Price reconciliation

1. Reuse `reconcile_observations` / `HistoricalReconciliationReport` for sampled close
   prices.
2. Load canonical and independent rows from frozen artifacts only.
3. Persist the reconciliation report and exact discrepancy/missing rows.
4. Add deterministic CLI/library tests for PASS, FAIL, PARTIAL/MISSING, tolerance boundary,
   source independence and replay identity.

The artifact-backed entry point is
`reconcile_sampled_market_bars_from_artifacts`. It accepts two explicit
`HistoricalDatasetManifest`/`HistoricalArtifactStore` pairs and an existing
`HistoricalReconciliationSampleSpec`; an optional report store freezes the
unchanged v1 report as a content-addressed JSON artifact. M4-qualified compiled
source descriptors persist additive adapter/upstream identities; legacy
manifests and plans without those fields remain readable but fail closed for
this M4 path.

Acceptance:
- repeated reconciliation over identical frozen inputs produces the same content hash;
- missing rows cannot be silently dropped by intersecting the sources;
- report outcome never mutates Hithink or BaoStock rows;
- the persisted sample's listing/date, source/provider/upstream and A/CNY/UNADJUSTED
  boundaries cannot be bypassed.

### M4-D — Corporate-action/reference-event audit

1. Add the minimum BaoStock dividend/adjust-factor acquisition needed for the fixed sample,
   retaining source semantics.
2. Compare against Hithink adjustment-factor/reference evidence only where both sides have
   equivalent meaning.
3. Keep ambiguous factors reconciliation-only.
4. Persist a typed/versioned deterministic sidecar report if the existing scalar contract
   is insufficient.

Acceptance:
- event presence/date and safely comparable terms are reproducible;
- factor-only evidence cannot silently become a cash dividend/split/rights action;
- unresolved semantic mapping remains an explicit blocker.

### M4-E — Lifecycle cross-check

1. Add the smallest official-exchange acquisition path needed by the fixed A-share sample.
2. Freeze exact source response/document bytes or a complete deterministic provider export
   in private CAS, with source URI/provider identity.
3. Compare BaoStock lifecycle/basic fields to official exchange evidence.
4. Do not infer historical membership or a terminal outcome from a current listing row.

Acceptance:
- listing-date/status/terminal comparisons are deterministic where evidence exists;
- absence is not treated as proof unless source scope is explicit;
- no H-share or market-wide membership claim is added.

### M4-F — Closure, docs and remaining blockers

Update only documentation that changed in fact:

- this goal;
- `docs/architecture/production-historical-data-and-research-archive.md` when new public
  adapter/report contracts exist;
- `docs/operations/phase-5r-a-acquisition.md` with exact live/replay commands after they
  exist;
- `docs/status/phase-5r-a-2026-09-18.md` or a dated successor with non-secret run hashes;
- `docs/status/phase-5r-a-next-codex-goal.md` to the next actual milestone after M4;
- parent roadmap/goal summaries only when milestone status genuinely changes.

Do not rewrite README/AGENTS for implementation history.

## 7. Deterministic test matrix

At minimum cover:

1. source IDs differ but provider/upstream identity is the same -> rejected as independent;
2. price PASS inside an explicitly declared tolerance;
3. price FAIL outside tolerance;
4. one source missing a session -> report PARTIAL/MISSING, never PASS;
5. source has an extra session -> explicit MISSING counterpart, not silently discarded;
6. adjusted-vs-unadjusted basis mismatch -> rejected;
7. BaoStock response schema drift -> fail closed;
8. duplicate price natural key with different values -> fail closed;
9. action event exact match;
10. action event missing counterpart;
11. action numeric discrepancy;
12. adjustment-factor-only evidence cannot be promoted to a canonical action;
13. lifecycle listing-date exact match;
14. lifecycle listing-date/status/terminal mismatch;
15. current/basic row cannot satisfy historical-membership semantics;
16. replay of the same raw CAS produces identical canonical rows and reconciliation hashes;
17. all old Phase 5R fixtures, M2-E selection state and M3 lifecycle/calendar tests continue
    to pass.

Ordinary CI uses only frozen fakes/fixtures. Live provider tests are opt-in.

## 8. Live evidence sequence

After code/tests pass, run only the minimum owner-authorized live sequence:

1. probe the independent BaoStock price-reference request;
2. acquire the bounded price sample into private CAS;
3. offline compile with `--verify-replay`;
4. run deterministic price reconciliation against the already frozen/corresponding
   Hithink sample;
5. probe/acquire action reference data only after price reconciliation works;
6. probe/acquire the relevant official exchange lifecycle reference;
7. run action/lifecycle audit reports offline;
8. record only non-secret hashes, source identities, dates, counts, statuses and blockers
   in Git.

A failed independent source probe narrows M4. It does not justify implementing M2-D,
expanding H-share coverage, weakening A6 or substituting a correlated source.

## 9. M4 closure states

M4 may close as one of:

- `M4_FIXED_A_RECONCILIATION_PASS`: the declared fixed A-share sample has independent,
  replayable price reconciliation plus the implemented action/lifecycle checks required by
  the declared M4 sample, with limitations recorded;
- `M4_FIXED_A_RECONCILIATION_PARTIAL`: price reconciliation is independently replayable
  but action or lifecycle evidence remains unavailable/semantically unresolved;
- `M4_INDEPENDENT_SOURCE_BLOCKED`: no genuinely independent second source can be
  replayed for the required sample.

These are engineering/research-readiness states only. None makes the full Phase 5R/A6
production claim pass by itself.

Current closure at `f17ce3c0`:

- M4-C fixed-A sampled price report: **PASS** (owner-authorized, replayable, 2/2);
- overall M4: **`M4_FIXED_A_RECONCILIATION_PARTIAL`**, because M4-D corporate-action
  and M4-E lifecycle cross-checks are intentionally deferred rather than implemented;
- this partial closure is sufficient to continue to M5. M4-D/M4-E are not current
  blockers and may be reopened later only for a research/backtest claim that needs them.

## 10. Expected remaining blockers after M4

Even a successful fixed-A M4 is expected to leave broader blockers, including some or all
of:

- historical/survivorship-free universe membership;
- code-change history across the full requested scope;
- complete delisted/terminal listing retention and terminal economics;
- complete corporate-action coverage rather than sampled reconciliation;
- benchmark and FX coverage;
- official filing coverage/research archive coverage;
- full H lifecycle/actions/membership/terminal evidence;
- complete A/H category/date/listing coverage;
- source-scope/terms evidence required for broader production/redistribution claims.

Those blockers narrow claims; they do not invalidate the bounded fixed-A private research
workflow.

## 11. Verification

Before declaring the implementation complete:

```bash
python -m ruff check .
python -m pytest
```

Also run focused deterministic tests for every new adapter/comparator before any live
owner-side probe.

## 12. Out of scope

M4 does not implement:

- M2-D;
- new H-share provider selection or H-share coverage expansion;
- market-wide historical membership;
- terminal-value policy;
- Phase 6 monitoring;
- R2/object-store migration;
- Web UI/API productization;
- Tunnel/Access changes;
- trading, orders, transfers or other financial state changes.
