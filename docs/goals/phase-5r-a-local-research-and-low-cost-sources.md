# Phase 5R-A Next — Local Research Usability and Low-Cost Source Expansion

Status: **PROPOSED / NEXT**  
Baseline: `main@a3533a36fd27935ca1b5a4178b90c3fd0a924fa1`  
Date: 2026-09-16

## 1. Objective

Turn the already acquired private A-share slice into an explicitly supported
**LOCAL_ONLY / EXPERIMENTAL research surface**, without weakening any existing
Phase 5R production or investment contract, then expand the historical source
portfolio using personal/local/free paths in small, probe-driven milestones.

This package is intentionally personal-research-first. It must not require:

- an institutional market-data contract;
- manual CSV/Parquet assembly by the owner;
- a live model for replay, validation, or ordinary CI;
- any API key in Git, prompts, receipts, logs, fixtures, or documentation;
- a scraping workaround when a documented/local API is unavailable.

The existing A6 audit, `--require-production`, `strict-v1`, deterministic CDC,
Net Cash, Through Return, hard-gate and valuation math remain unchanged.

## 2. Current facts and interpretation

The repository has already completed an owner-authorized A-only Hithink
probe/acquire and a deterministic offline replay:

- target: `SH600000`, `FIXED_RESEARCH_UNIVERSE`, 2020-01-01 through 2022-01-02;
- one `MARKET_BAR` shard with 486 daily rows covering 2020-01-02 through
  2021-12-31;
- exact raw bytes live in the private local CAS;
- repeated offline compilation produces stable manifest/shard identities;
- ordinary CI remains offline and model-independent.

The A6 `historical accept` failure records blockers for the **complete A/H
acceptance claim**. It does not revoke the usefulness of the already compiled
A-only price shard for bounded local research.

The current contracts already distinguish acquisition readiness,
`PERSONAL_RESEARCH_READY`, and `PRODUCTION_ELIGIBLE`. Do **not** reinterpret or
weaken those levels. In particular, the current Phase 5R-A goal defines
`PERSONAL_RESEARCH_READY` around a named private A/H corpus, so an A-only price
slice should not be promoted into that state merely to make the UI look green.

Likewise, `StoragePolicy.LOCAL_ONLY` is a storage policy, not a readiness level.
Do not overload it.

## 3. Data-source decision

### 3.1 Recommended source stack

| Priority | Source | Intended role | What is already verified | What must remain probe-driven |
| --- | --- | --- | --- | --- |
| 0 | Existing Hithink adapter | Primary bulk A-share historical bars | The owner's A-only daily-k dump was reachable, decoded as Parquet, and replayed deterministically; the observed dump spans 2016-09-19 through 2026-09-15 | Do not infer H-share, lifecycle, delisted retention, action completeness, or any other category from the successful A-price probe |
| 1 | FQGate / `tonghuasun-agent` | First local candidate for incremental A/H historical prices and independent price checks | Public local API/SDK exposes `/v1/market/history/klines` with `market`, `code`, `start_date`, `end_date`, `adjust`, and `interval`; the same public client exposes an `hk` market group | Actual H historical K-line support, history span, delisted retention, throttling, and corporate-action completeness must be observed by a live local probe |
| 2 | Futu OpenD | Second personal-account H-share price candidate if FQGate H history is insufficient | Official API documents historical K-lines with start/end, paging and HK symbols such as `HK.00700`; OpenD is a local gateway | Actual quote entitlement and historical quota are account-specific; only add an adapter after a local probe is needed |
| 3 | AKShare / Eastmoney-backed interfaces | Zero-key experimental fallback and sampled reconciliation | AKShare exposes A- and H-share historical interfaces, including `stock_zh_a_hist` and `stock_hk_hist` | Endpoint stability, historical terminal coverage and category completeness are not assumed; do not elevate a successful call into a production claim |
| 4 | BaoStock | Free A-share calendar/lifecycle/basic-data supplement and reconciliation | Public APIs expose unadjusted daily K-lines, trade dates, and stock basic fields including IPO/out dates/status | A-only; historical delisted completeness and exact lifecycle semantics still require observed tests before stronger claims |

### 3.2 FQGate integration decision

FQGate is directly useful, but the repository should **not** import or embed the
whole AI-agent/plugin project. The stable integration boundary is its local
HTTP API.

Recommended adapter shape:

```text
FQGate local process / logged-in market session
        -> 127.0.0.1:17281 public HTTP API
        -> tve HistoricalSourceAdapter
        -> exact JSON response bytes in RawBlobStore
        -> offline decoder
        -> MARKET_BAR shard
```

For the first adapter:

- use the documented/public local API only;
- keep `--network=allow` mandatory even though the endpoint is localhost;
- use no credential reference when the local gateway needs none;
- preserve the exact HTTP response bytes in the existing raw CAS;
- support only unadjusted daily bars (`adjust=""`, daily interval) initially;
- map only fields whose meaning is verified by the public FQGate client/UI
  implementation (time/open/high/low/close/volume/amount, plus optional
  turnover when present);
- probe A and H independently;
- obtain the actual H market identifier/shape from the running OpenAPI/search
  surface rather than inventing it in code or a committed plan;
- if H history is unavailable or shorter than requested, persist the observed
  limitation and stop. Do not substitute a current quote, current constituent
  list, or another hidden source.

This reuses FQGate's strongest property for this project: a stable local gateway
with a normal historical K-line endpoint, while preserving turtle-value-engine's
raw-CAS/offline-compiler architecture.

### 3.3 Futu, AKShare and BaoStock roles

Do not implement all candidate sources in one PR.

- **Futu OpenD** is the first fallback to evaluate only if the FQGate H probe is
  insufficient. It is attractive because H-share historical K-lines are
  explicitly documented, but its market-data permissions and historical quota
  are account-dependent.
- **AKShare** is ideal for zero-key local experiments and an independent sampled
  price comparison. It should initially be an experimental/reconciliation
  source rather than a source that silently upgrades A6.
- **BaoStock** is more valuable for the next A-share lifecycle/calendar slice
  than as another primary price source: `query_trade_dates`, `query_stock_basic`
  and unadjusted historical bars can close practical local-research gaps at zero
  manual-data cost.

Existing `AKShareProvider` used by `tve prepare` must not be conflated with the
Phase 5R historical acquisition/CAS boundary. Reuse concepts or library calls
only through an explicit historical adapter.

## 4. Minimal mergeable milestone — M1 Local Research Usability

### 4.1 Why this is first

The current private A-price shard is already deterministic and useful, but the
operator-facing states are dominated by whole-corpus and production semantics.
At the same time, `HistoricalDatasetCompiler.validation_summary()` checks
whole-dataset invariants such as lifecycle presence even when
`require_production=False`. Therefore `HistoricalValidationSummary.valid` must
not be repurposed as a synonym for "can I inspect and research the price shard
I actually have?".

Add a separate, additive local-research contract instead of weakening the
existing compiler or readiness ladder.

### 4.2 Contract

Add `LocalResearchUsabilityReportV1` (exact naming may follow repository style)
with deterministic content identity and at least:

```text
contract
report_id / content_sha256
dataset_id / dataset_content_sha256
usage_class = LOCAL_ONLY_EXPERIMENTAL
usable: bool
markets / listing_ids / start_date / end_date
available_artifact_kinds
row_counts_by_kind
verified_capabilities
limitations
errors
```

`verified_capabilities` must be derived from the artifacts actually present,
not requested aspirational categories. For the current A-only market-bar slice,
a successful report may expose capabilities such as:

```text
SHARD_REPLAY
PRICE_SERIES_RESEARCH
```

It must **not** imply any of:

```text
PRODUCTION_ELIGIBLE
PERSONAL_RESEARCH_READY
SURVIVORSHIP_FREE_BACKTEST
TOTAL_RETURN_BACKTEST
COMPLETE_AH_CORPUS
```

### 4.3 Local usability semantics

The local report is a technical/research usability status over the artifacts
that actually exist. It is orthogonal to A6 source/coverage acceptance.

For each present shard/category it must fail closed on integrity defects such
as:

- missing or corrupt content-addressed shard;
- schema/row decode failure;
- duplicate canonical row identity within a shard;
- row outside declared shard listing/date scope;
- row/source identity or hash mismatch;
- invalid manifest content hash.

Missing *other* categories (for example H share, lifecycle, benchmark, FX,
filings or corporate actions) are limitations on the supported research scope,
not reasons to claim that an intact A-only price shard cannot be replayed or
studied.

This command is not a backdoor Phase 5 compiler. It must not fabricate
lifecycle, sessions, actions, terminal economics, benchmark returns, FX or
Business Quality artifacts.

### 4.4 CLI

Add an offline-only command, preferably:

```bash
tve historical research-status \
  --manifest <historical-manifest.json> \
  --store <artifact-store> \
  [--output <local-research-status.json>]
```

Properties:

- no provider or transport construction;
- no model construction;
- no network fallback;
- deterministic output for the same manifest/store;
- success means only that the declared local research capabilities are intact.

Do not change the meaning or exit behavior of:

```text
tve historical accept
tve dataset validate --require-production
tve dataset freeze --require-production
tve backtest --require-production
tve calibrate --require-production
```

### 4.5 M1 affected files

Expected implementation surface:

- `src/turtle_value_engine/historical/research_status.py` — new local usability
  model + deterministic inspection logic;
- `src/turtle_value_engine/historical/__init__.py` — public export;
- `src/turtle_value_engine/__init__.py` — export only if consistent with current
  package convention;
- `src/turtle_value_engine/cli.py` — add `historical research-status` only;
- `schemas/historical-local-research-status.schema.json` — generated/checked
  additive schema;
- `tests/test_phase_5r_local_research.py` — focused offline acceptance tests;
- `docs/operations/phase-5r-a-acquisition.md` — document the distinction between
  local research status and A6 after implementation;
- `docs/status/phase-5r-a-2026-09-16.md` — append the implemented milestone result
  after verification, not before.

Explicitly **not affected**:

- `rules/strict-v1.yaml`;
- deterministic calculation/gate/valuation modules;
- existing A6 acceptance semantics;
- Phase 5 portfolio policy/calibration math.

### 4.6 M1 tests and acceptance

Add frozen offline tests proving at least:

1. an A-only price shard with intact hashes can report
   `LOCAL_ONLY_EXPERIMENTAL` + `PRICE_SERIES_RESEARCH` even when it is not
   production eligible;
2. the same fixture still fails the existing production requirement when
   `--require-production` is requested;
3. a corrupt/missing shard makes local research status unusable;
4. rows outside listing/date scope or with mismatched source identity/hash fail;
5. missing H/lifecycle/FX/benchmark/filing categories are surfaced as
   limitations, not silently fabricated;
6. repeated status generation is byte/hash deterministic;
7. ordinary tests instantiate no provider, network transport or model.

Minimum verification:

```bash
python -m ruff check .
python -m pytest
```

If a compact synthetic fixture is needed, keep it small and Git-safe. Do not
commit private Hithink bytes or the owner's private reports.

## 5. Follow-on milestones

### M2 — FQGate local historical adapter + probe

Goal: add the smallest source adapter for unadjusted daily `MARKET_BAR` rows.

Implementation constraints:

- direct local HTTP integration; no dependency on the AI plugin runtime;
- exact raw response bytes enter `RawBlobStore` before decoding;
- add POST support to the acquisition transport only if the existing abstraction
  cannot express it, without changing retry/network defaults;
- fake-transport fixtures in ordinary CI;
- a committed redacted plan template may describe A/H probe intent, but must not
  claim the H market code/coverage until observed;
- live probe remains explicit and local/operator-run.

Completion result is one of two valid states:

1. A/H historical K-lines are observed and their actual ranges/shapes are
   recorded; or
2. H remains explicitly unqualified, with a precise observed limitation.

Neither outcome weakens A6.

### M3 — Select one H-share fallback only if M2 needs it

If FQGate cannot provide the required H historical slice, evaluate Futu OpenD
next. If the local account cannot provide the needed history, retain that result
and use AKShare/Eastmoney only for LOCAL_ONLY/EXPERIMENTAL price research and
sample reconciliation.

Do not add multiple H adapters merely because they exist.

### M4 — A-share lifecycle/calendar slice

Add a BaoStock-based experimental adapter for the smallest useful set:

- trade calendar;
- listing basic information including IPO/out date/status;
- optional unadjusted daily bars for sampled reconciliation.

This milestone should improve local A research and terminal-case discovery. It
must not label a current stock list as historical universe membership.

### M5 — Sampled cross-source reconciliation

Use a source independent from the canonical price source for deterministic
sample comparisons. AKShare/Eastmoney, FQGate, Futu or BaoStock may fill this
role depending on the category and the probes that actually pass.

Reconciliation is evidence about sampled values. It is not a substitute for
historical universe/lifecycle coverage.

## 6. Deferred work

Do not pull these into M1/M2 merely to make the complete A/H audit green:

- full H-share lifecycle and delisted universe reconstruction;
- survivorship-free historical membership;
- complete corporate-action semantics and total-return backtests;
- benchmark/FX coverage for all portfolios;
- complete A/H filing archive and frozen historical Business Quality;
- remote object-store mirroring;
- Phase 6 event monitoring.

They remain legitimate later milestones, but are not prerequisites for bounded
local price research.

## 7. External source evidence reviewed for this plan

- FQGate / tonghuasun-agent: `https://github.com/zhuyifang/tonghuasun-agent`
- Futu historical K-lines: `https://openapi.futunn.com/futu-api-doc/quote/request-history-kline.html`
- Futu quote authority/quota: `https://openapi.futunn.com/futu-api-doc/en/intro/authority.html`
- AKShare: `https://akshare.akfamily.xyz/`
- BaoStock: `https://github.com/zxygithub/baostock`

These links identify candidate capabilities only. Runtime capability is accepted
only from actual probe results; this plan deliberately does not invent coverage
that was not observed.

## 8. Recommended next Codex goal

Implement **M1 only** first. Do not implement FQGate or another live source in
the same change. M1 is intentionally small enough to merge independently and
makes the existing private A-only replay a first-class, honest research surface
without changing any production or investment semantics.
