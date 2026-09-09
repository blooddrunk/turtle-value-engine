# Provider and Cache Architecture

> Status: Phase 2 foundation, read-only AKShare statement slices, dividend events and share-capital raw slice

This document freezes the boundary between structured-data acquisition and the
deterministic Turtle Value Engine. It does not authorize a live provider or
change any `strict-v1` formula, threshold, schema meaning or gate semantic.

## 1. Invariant and flow

The deterministic engine remains the source of truth:

```text
external provider
    -> raw provider records
    -> normalization / mapping
    -> Evidence + Fact + DataQuality
    -> existing NormalizedCompanyInput
    -> existing deterministic pipeline
```

There is one analysis model: `NormalizedCompanyInput` on the input side and
the existing `CompanyAnalysis` on the output side. A provider must not create
a parallel analysis object, calculate an investment metric, or decide a gate.

Phase 2 adds acquisition and replay infrastructure only. Phase 3 is the
boundary for official filing retrieval and filing-derived evidence.

## 2. Responsibilities and boundaries

### Structured provider adapter

A provider adapter is responsible for:

- accepting a provider-neutral request for one data category and entity;
- calling its upstream service when a live implementation exists;
- returning an opaque `RawProviderRecord`;
- advertising the categories it actually supports;
- preserving provider/source version metadata and the retrieval timestamp;
- translating provider failures into a typed `ProviderError` without
  fabricating a successful response.

An adapter may understand upstream column names, pagination, authentication,
rate limits and response quirks. Those details end at the raw-record boundary.
An adapter must not calculate CDC, net cash, Through Return, valuation,
business-quality scores or hard gates.

### Cache

The cache stores successful raw responses and their acquisition metadata. It
does not store normalized facts as a substitute for the input contract, and
it does not decide whether a response is financially trustworthy. A cache
read is either a validated record, an explicit miss, a stale record when the
caller opted into stale replay, or a typed corruption error.

### Normalization / mapping

The normalizer is the only boundary that knows how an upstream field maps to a
canonical normalized field. It is responsible for:

- mapping provider-specific payloads to the existing `Fact` model;
- creating `Evidence` items that point back to the raw source and request;
- creating conservative `DataQuality` metadata;
- preserving explicit `null` values and listing critical missing fields;
- rejecting ambiguous duplicate field/period mappings;
- returning the existing `NormalizedCompanyInput`.

The provider foundation exposes a normalizer protocol but does not implement
AKShare, Tushare, or any other mapping. The normalizer must not silently apply
an accounting judgment that belongs to a filing review or an accepted
`Adjustment`.

### Deterministic engine

`calculations/`, `gates/`, valuation code and investment-rule profiles consume
canonical normalized inputs and deterministic stage results only. They never
import a provider module or inspect an upstream payload. Their current
nullable and evidence-lineage behavior remains unchanged.

## 3. Provider-neutral categories and capability discovery

The foundation defines independent categories so a later adapter can support
only what it can acquire reliably:

```text
COMPANY_METADATA
LISTING_METADATA
MARKET_QUOTE
MARKET_HISTORY
INCOME_STATEMENT
BALANCE_SHEET
CASH_FLOW_STATEMENT
DIVIDENDS
SHARE_CAPITAL
CORPORATE_ACTIONS
```

Each request has:

- `category`;
- stable `entity_id` (for example a canonical listing or issuer identity);
- JSON parameters such as period, frequency or date range.

`ProviderCapabilities` is an explicit set, not an optimistic registry. A
request for an unsupported category raises `ProviderCapabilityError` before
the adapter is called. Capability discovery therefore does not require a
network call and can be used to plan a fetch before execution.

The foundation's `StructuredDataProvider` interface has one raw fetch method
plus a convenience category request. Later adapters may dispatch internally
to their quote, history, income, balance-sheet, cash-flow, dividend or
share/corporate-action endpoint. The interface does not require every provider
to implement every category.

## 4. Raw provider representation

`RawProviderRecord` is intentionally provider-neutral while its payload is
intentionally provider-specific. It contains:

```text
provider:       provider_id, provider_version, source_name
request:        category, entity_id, canonical parameters
retrieved_at:   timezone-aware UTC timestamp
raw_payload:    opaque JSON object/array/scalar/null
source_uri:     optional endpoint or source URL
response_metadata: small JSON metadata such as status or upstream request ID
```

The payload is copied and validated as JSON, but no column names or nested
structure are interpreted. Raw records may contain an explicit `null`; a
provider or normalizer must distinguish that from a real numeric zero.

The provider version is part of the cache identity. A mapping or upstream
contract change can therefore create a new cache namespace instead of replaying
bytes under an incompatible adapter version.

## 5. Normalization and provenance

For every normalized fact, the normalizer must establish:

1. canonical `Fact.field` and period;
2. value and unit/currency without an implicit unit conversion;
3. `source_evidence_ids` pointing to evidence in the same input;
4. confidence and estimated status appropriate to the source;
5. a `DataQuality` update when a critical value is absent or unresolved.

For structured data, evidence should use the existing
`STRUCTURED_DATA_VENDOR` source type and retain enough metadata to find the
raw record again. The recommended source mapping is:

- `Source.title`: source name plus provider identifier/version;
- `Source.url`: `source_uri` when available;
- `Source.document_id`: deterministic cache-key digest or upstream response
  identifier;
- `Source.locator`: category, entity identity and request parameters;
- evidence `notes`: retrieval timestamp and any non-sensitive response
  metadata needed for replay.

The raw cache remains the authoritative byte-level provenance. Evidence is the
normalized contract's auditable pointer to it. A re-fetch must not erase the
earlier evidence from an already persisted analysis.

Fact and evidence IDs should be deterministic when their semantic identity is
stable. Use the provider, request identity, canonical field, period and
mapping version as components; do not use list position or wall-clock retrieval
time for a fact ID. The foundation's `deterministic_id` helper exists for this
purpose. IDs for genuinely distinct snapshots may include an explicit snapshot
identity.

## 6. Structured facts versus filing-derived facts

Structured data is suitable for fast, repeatable observations such as a
reported price, reported CFO, reported profit, total cash, reported debt,
dividend amount, or a share count when the provider's period and entity are
unambiguous.

The financial-statement slices are deliberately narrow. The AKShare adapter
may acquire `CASH_FLOW_STATEMENT`, `INCOME_STATEMENT` and `BALANCE_SHEET`
records for A/H listings. Its normalizer maps only report-period rows whose
labels unambiguously represent `reported_cfo`, `acquisition_cash`,
`parent_net_profit`, `consolidated_net_profit`, `book_cash`,
`parent_equity`, `total_equity` or an explicit aggregate
`reported_interest_bearing_debt`. A-share wide records and H-share long-form
item records are handled separately. The documented A-share aggregate
balance endpoint is date-based and returns a universe; the provider selects
the requested listing and carries the exact requested quarter-end date into
the normalized period. That aggregate shape maps only its explicit cash and
total-equity fields. The mapper preserves the reported sign, currency and
null value; it does not scale amounts, split aggregate capex into
PPE/intangible purchases, sum borrowing sub-items into debt, calculate
CDC/financing metrics, or import revenue and provider ratios as canonical
facts.

Statement currency is accepted only from explicit, valid three-letter
metadata. The normalizer does not infer a statement currency from the listing
market; missing currency remains `null`, and conflicting explicit currencies
within one report period are a normalization error. Reported amount scaling
and unit conversion remain unresolved and are not performed.

Missing report dates, year-only periods, duplicate periods or duplicate
long-form items are normalization errors. This keeps a provider convenience
table from silently becoming a normalized annual history with ambiguous
semantics.

The first share-capital slice is deliberately acquisition-only. The current
[AKShare documentation](https://akshare.akfamily.xyz/data/stock/stock.html)
describes `stock_zh_a_gbjg_em` as an A-share endpoint that accepts `symbol` and
returns all historical records with `变更日期`, `总股本`, circulation fields and
`变动原因`. The documentation types `总股本` as `int64`, but does not declare a
unit or define a fully diluted economic scope for the count. The provider
therefore passes the six-digit A-share code, retains the complete tabular
payload and row count, and does not select a “latest” row. The normalizer keeps
the raw record's evidence, marks
`normalized_diluted_economic_shares` as critically missing and emits the
`AKSHARE_SHARE_CAPITAL_RAW_ONLY` flag without creating a canonical share fact.
It does not treat `变更日期` as a financial-statement period or `总股本` as
fully diluted shares. H-share share capital and all dividend/capital-action
facts remain outside this slice.

When a statement row includes an explicit security code, the normalizer also
checks it against the requested listing and rejects a mismatch. Statement
endpoints that omit a row-level code remain bound to their listing-scoped
request; the normalizer does not invent an entity code for them.

The adapter version and mapping version are part of the cache/fact identity,
so an endpoint or mapping contract change cannot replay a prior snapshot under
an incompatible mapping. The explicit statement-row entity guard is a
normalizer-only mapping change; it bumps the mapping version while leaving the
raw adapter/cache version unchanged.

It is not permission to infer economic classifications that are absent from
the provider response. Examples that remain outside automatic Phase 2
normalization include:

- restricted or pledged cash and cash upstreamability;
- supplier finance, recourse factoring, lease-principal classification and
  other debt equivalents;
- one-off operating inflows and core/non-core profit classification;
- formal payout-policy interpretation and genuine recurring net share
  reduction;
- accounting opinions, illegal guarantees and governance risk;
- customer/channel/supplier dependency and structural disruption;
- the eight Business Quality dimension judgments.

The field matrix in `docs/data/provider-field-matrix.md` is the controlling
allowlist for this distinction. A structured provider may supply a raw hint
for a filing-required item, but the Phase 2 normalizer must keep the canonical
fact `null` or mark it unresolved until the required source and review exist.
It must never promote a headline field into a strict-v1 economic fact merely
because the provider uses a confident label.

If structured sources disagree, retain both source records/evidence and emit
an explicit data-quality issue. Do not silently choose the most favorable
value and do not overwrite a deterministic metric from the provider layer.

## 7. Missing and null values

The following states are distinct:

| State | Meaning | Normalized treatment |
| --- | --- | --- |
| field absent from response | provider did not return the field | no invented value; record the field as unavailable when it is critical |
| field present with `null` | provider explicitly has no value | preserve `Fact.value = null` and its evidence |
| numeric `0` | source reported an actual zero | preserve zero and its evidence |
| unresolved classification | raw amount exists but economic meaning is unknown | keep the canonical classified fact `null`; add a data-quality note/evidence |
| ambiguous duplicate | more than one value maps to the same field/period | fail normalization for that mapping; never use “last row wins” |

No adapter, cache reader or normalizer may use zero as a missing-data default.
The existing calculation and gate modules then apply their established
nullable behavior and may return `SPECIAL_REVIEW` or an unavailable metric.

## 8. Failure and isolation behavior

Provider requests are isolated by category and entity. A quote failure must
not invalidate an already acquired balance-sheet raw record; conversely, a
cached quote must not make a failed balance-sheet request look successful. The
orchestration layer should carry per-request errors and only assemble a
normalized input from records it can account for.

Failure rules are:

- unsupported category -> `ProviderCapabilityError`;
- transport, authentication, quota or upstream request failure -> typed
  `ProviderError` with retryability classified by the adapter;
- invalid response type or request/provider identity mismatch ->
  `ProviderResponseError`;
- ambiguous or invalid raw-to-fact mapping -> `ProviderNormalizationError`;
- no provider error is converted to an empty payload, zero or a successful
  `Fact`;
- a live provider failure does not write to the cache;
- cache corruption is an explicit `CacheCorruptionError`, not a cache miss;
- an offline cache miss is an explicit `CacheMissError`;
- a cache write failure is an explicit `CacheWriteError`.

The cache-aware helper defaults to re-raising live provider errors. Replaying
a stale cached record after a provider failure requires an explicit caller
option and returns a replay mode so a report can disclose that it is not live.
Offline mode never calls a provider.

## 9. Cache semantics and filesystem layout

The Phase 2 cache is a filesystem of JSON envelopes, not a database. A cache
key is a canonical JSON digest of:

```text
provider
provider_version
category
entity_id
request parameters
```

The readable path is:

```text
<cache-root>/<provider>/<category>/<sha256>.json
```

The envelope separately stores:

```json
{
  "cache_format_version": 1,
  "provider": {"id": "...", "version": "...", "source_name": "..."},
  "request": {"category": "...", "entity_id": "...", "parameters": {}},
  "retrieved_at": "2026-09-09T00:00:00Z",
  "raw_payload": {},
  "source_uri": null,
  "response_metadata": {}
}
```

Parameter object order does not change a key. Provider version does. The
retrieval timestamp is metadata, not an accidental request identity.

Writes serialize and validate the complete envelope, write a temporary file in
the destination directory, flush and fsync it, then use an atomic replace. If
serialization, provider acquisition or replacement fails, the previous valid
file is left in place. Temporary files are not treated as cache entries. A
corrupted or incomplete existing file is never silently repaired, deleted or
interpreted as valid data by a read.

The current implementation stores the latest valid snapshot for an exact
provider/request-version key. If historical snapshots are needed, a future
version must add an explicit immutable snapshot index; it must not overload the
normalized input or silently change replay semantics.

## 10. Freshness, replay and rate-limit protection

The cache has no automatic network behavior. A caller may supply a maximum age:

- a fresh entry can be replayed when it matches the key;
- a stale entry is treated as unavailable unless stale replay is explicitly
  allowed;
- `offline=True` never falls through to a provider;
- provider-failure fallback is opt-in and reported as cache replay.

This supports reproducible tests and development, protects upstream rate
limits, and makes offline analysis possible without making a stale value look
like a live observation. Cache freshness does not prove financial correctness
or filing-level reliability.

## 11. Retry boundaries

Only a concrete provider adapter may retry its own idempotent read operation.
Retries must be bounded and respect the provider's rate-limit/authentication
rules. The adapter should not retry authentication failures, unsupported
categories, malformed requests or deterministic response-validation errors.

The cache performs no network retries. The normalizer performs no provider
retries. The deterministic pipeline performs no provider retries and should
not be rerun as a substitute for resolving missing facts.

## 12. Phase 2.2–2.8 AKShare adapter

The first concrete adapter is intentionally limited to read-only metadata,
market observations, three documented financial-statement slices, a raw-only
dividend event category and one A-share share-capital raw slice. It
advertises exactly these capabilities:

| Category | A-share endpoint | H-share endpoint | Normalized output |
| --- | --- | --- | --- |
| `COMPANY_METADATA` | `stock_info_a_code_name` | `stock_hk_company_profile_em` (with conservative metadata-list fallbacks) | company metadata extension facts; nullable `Company` context enrichment only |
| `LISTING_METADATA` | `stock_info_a_code_name` | `stock_hk_security_profile_em` (with conservative listing-list fallbacks) | listing code/name/date/exchange and other explicit metadata facts |
| `MARKET_QUOTE` | `stock_zh_a_spot_em` | `stock_hk_spot_em` | selected-listing `current_price` plus quote timestamp |
| `MARKET_HISTORY` | `stock_zh_a_hist` | `stock_hk_daily` | dated OHLCV/turnover extension facts |
| `CASH_FLOW_STATEMENT` | `stock_cash_flow_sheet_by_report_em` (Sina fallback) | `stock_financial_hk_report_em` | explicit `reported_cfo` and `acquisition_cash` lines |
| `INCOME_STATEMENT` | `stock_profit_sheet_by_report_em` (Sina fallback) | `stock_financial_hk_report_em` | explicit `parent_net_profit` and `consolidated_net_profit` lines |
| `BALANCE_SHEET` | `stock_zcfz_em` / `stock_zcfz_bj_em` (detailed report-period and Sina fallbacks) | `stock_financial_hk_report_em` | explicit `book_cash`, equity totals and aggregate interest-bearing debt when labeled |
| `DIVIDENDS` | `stock_dividend_cninfo` | `stock_hk_dividend_payout_em` | raw structured evidence only; no canonical dividend cash or payout ratio |
| `SHARE_CAPITAL` | `stock_zh_a_gbjg_em` | — | raw historical response and provenance only; no canonical share/dilution fact |

The adapter accepts common stable A/H identifiers such as `SH600000`,
`000001.SZ`, `A:600000`, `HK00700`, `700.HK` and `H:00700`. A-share history
passes the supported period, date-range and adjustment parameters to AKShare.
The current H-share daily endpoint returns a full history, so the normalizer
applies an explicitly requested date range deterministically after replay;
the raw record remains the upstream response.

The `akshare` package is optional and loaded only at the first live fetch.
Tests inject a client object and use frozen JSON fixtures. The existing
`fetch_with_cache` helper remains the only cache boundary: `offline=True`
never calls AKShare, and a failed live request is never written as a snapshot.

The normalizer emits `Fact` and `Evidence` objects inside the existing
`NormalizedCompanyInput`. For the dividend and share-capital raw slices it
emits raw-record evidence only and explicit unresolved flags where needed; it
does not emit canonical dividend or share facts. It never maps provider
headline market cap,
listing-years inferred from history length, unlisted financial-statement lines,
total liabilities as interest-bearing debt, filing classifications, or any
CDC/net-cash/Through Return/valuation/gate result. The statement slices
preserve exact periods and explicit nulls and reject ambiguous duplicate
periods/items.

Open mapping questions intentionally left for later review are: an explicit
A-share first-trading date and listing-status source, point-in-time treatment
of delayed/closed quote timestamps, FX and A/H cross-listing share equivalence,
whether the H-share full-history endpoint can be replaced by a bounded range
endpoint without changing replay semantics, field-name coverage across all
A/H balance-sheet variants, consolidated-versus-standalone statement basis,
currency/unit scaling, the absence of parent-equity and interest-bearing-debt
aggregates in the documented A-share quarterly balance shape, and
point-in-time publication semantics. For the share-capital raw slice, the
remaining questions are the unit represented by `总股本`, whether each
`变更日期` is an effective legal change date or a point-in-time observation
date, the treatment of options/convertibles and other dilution, the economic
relationship between A/H classes, and whether the change-reason text can be
used to classify buybacks, issuance or splits. None of those classifications
is admitted automatically.
The period/total-cash/ordinary-versus-special classification needed to
normalize dividend event rows also remains open. Missing or conflicting
statement currency metadata is handled conservatively as described above, but
a null currency still requires later source review before cross-currency
calculations.

## 13. Deliberate non-goals

This foundation plus the Phase 2.2–2.8 slices does not include:

- Tushare, BaoStock or any other additional provider;
- automatic network scheduling, credentials or retry orchestration outside an adapter;
- official filing retrieval or PDF parsing;
- LLM evidence extraction or Business Quality scoring;
- a normalized-data database, web service, scheduler or event monitor;
- additional financial-statement categories beyond the documented slices or
  economic classifications inside the adapter;
- financial calculations inside provider classes.

Future provider categories must be added one at a time behind these
interfaces and validated against frozen normalized fixtures before being used
in screening.
