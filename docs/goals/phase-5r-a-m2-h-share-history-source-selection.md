# Phase 5R-A M2 — H-share Historical Source Selection and FQGate Failure Diagnosis

Status: **PROPOSED / NEXT**  
Date: 2026-09-16  
Baseline: `41fa843cce854f70ae6fb02c3d0e0012814f3a47`

## 1. Decision and recommended order

M2 should not start by adding several H-share providers in parallel. The smallest useful
next merge is to make the existing FQGate H-share failure diagnosable without inventing
an H market identifier or capability claim, and then select the first source that earns a
bounded H-share `MARKET_BAR` role.

Recommended order:

1. **FQGate diagnosis first** — retain the current `fqgate-local-market-history`
   integration and distinguish local gateway failure, unverified/rejected H routing,
   explicitly observed upstream timeout, account/entitlement denial, schema failure,
   no-data, and insufficient historical coverage. The current `HTTP 504` alone is not
   enough to classify the cause.
2. **FQGate bounded H probe second** — if an H `market`/`code` pair is actually observed
   from the running FQGate environment and historical K-lines succeed, use FQGate as the
   first H price source for the bounded personal-research slice. Do not infer that the
   same route proves delisted retention, lifecycle, corporate actions, or market-wide
   history.
3. **Futu OpenD next if FQGate remains unqualified** — Futu documents an H-share
   historical candlestick API, unadjusted mode, paging, quota inspection, and a
   market-specific permission model. Those are documented interface capabilities, not
   proof of this owner's entitlement or of any particular listing/date coverage; select
   it only after a live local OpenD probe.
4. **AKShare/Eastmoney last as a low-cost fallback and reconciliation source** — AKShare
   exposes an Eastmoney-backed H-share historical interface, but the wrapper/upstream
   stability and source-provenance boundary are weaker than the first two paths. It may
   be used for bounded personal research or independent reconciliation after a live
   probe, but must not be promoted to complete/authoritative history from row count alone.
5. **Stop once one H price path is selected and replayable.** Do not pull M3 lifecycle,
   historical membership, delistings, corporate actions, filings, benchmark/FX, remote
   storage, API or Web UI work into M2.

This ordering keeps M2 aligned with the existing acquisition architecture and avoids
provider proliferation before the observed FQGate failure is understood.

## 2. Current baseline and facts that are already earned

At baseline `41fa843`:

- FQGate acquisition is a local HTTP adapter over
  `POST /v1/market/history/klines`;
- A-share probes succeeded for `USHA/600000` and `USZA/000001` over
  2026-09-01 through 2026-09-15;
- the owner-observed H candidate `UHKM/HK0700` returned HTTP 504 over that same
  period;
- the H result therefore remains `historical_capable=false` and
  `H_SOURCE_UNQUALIFIED`;
- FQGate raw response bytes, receipts/provenance, deterministic `MARKET_BAR`
  compilation and offline replay are already implemented;
- `strict-v1`, A6 acceptance semantics, CDC, Net Cash, Through Return, hard gates,
  valuation, Phase 5 signal/portfolio math and ordinary offline CI are unchanged.

The observed `UHKM/HK0700` pair is evidence that the local catalog/runtime exposed that
identity. It is **not** proof that the historical endpoint accepts that identity, and it
must not be generalized into an H-share market-identifier rule.

## 3. Goal

Select and integrate the smallest reliable low-cost H-share historical **unadjusted daily
price** path for personal research, while making every failed source probe explainable
without over-claiming what the evidence proves.

M2 is complete when either:

- **Path A:** FQGate earns a bounded H `MARKET_BAR` role and can acquire -> CAS -> compile
  -> replay deterministically; or
- **Path B:** FQGate is left precisely unqualified, Futu OpenD earns that bounded role and
  can acquire -> CAS/equivalent source envelope -> compile -> replay deterministically;
  or
- **Path C:** both remain unqualified and AKShare/Eastmoney is explicitly retained only
  as the bounded fallback/reconciliation path with its limitations recorded.

A source-selection failure is a valid M2 outcome when the evidence is insufficient. The
implementation must leave an exact blocker instead of fabricating capability.

## 4. Non-goals

M2 must **not**:

- make the full A6 private A/H acceptance pass;
- weaken `historical accept`, `--require-production`, coverage or PIT validation;
- change `rules/strict-v1.yaml` or any investment calculation/gate/valuation semantics;
- prove or reconstruct H historical membership, lifecycle, code changes, delistings,
  terminal economics or prolonged suspension treatment;
- claim corporate-action completeness or silently use adjusted prices in place of
  unadjusted prices plus explicit actions;
- add an institutional/commercial market-data requirement;
- require manually assembled CSV/Parquet input;
- introduce HTML scraping or an undocumented scraping workaround;
- move acquisition into deterministic calculation code;
- make ordinary CI contact FQGate, OpenD, AKShare/Eastmoney, a model or any remote
  provider;
- add Cloudflare/R2/Supabase/VPS storage, agent/Web UI or Phase 6 event monitoring;
- ask for, print, persist, commit or echo API keys, passwords, session secrets or other
  private credentials.

## 5. Architecture boundary to preserve

Keep the existing separation:

```text
NETWORKED / EXPLICITLY OPT-IN
source probe / acquisition adapter
    -> raw bytes or explicitly identified provider-SDK source envelope
    -> receipt / provenance / private CAS

OFFLINE / DETERMINISTIC
verified acquisition batch
    -> provider decoder
    -> canonical MARKET_BAR
    -> HistoricalArtifactStore / HistoricalDatasetManifest
    -> replay / coverage / optional reconciliation

SEPARATE EVIDENCE / RESEARCH
filings / evidence / Phase 4 research artifacts

SEPARATE DETERMINISTIC INVESTMENT ENGINE
NormalizedCompanyInput
    -> CDC / Net Cash / Through Return / hard gates / valuation
```

Provider-specific identifiers and failure codes may exist at the acquisition/provenance
boundary. They must not leak into deterministic calculation modules.

## 6. Public contracts

### 6.1 Contracts that must remain unchanged in M2

Do not change the semantics of:

- `HistoricalDatasetManifest` and existing historical shard contracts;
- `MarketBar` / `market-bar-v1`;
- `HistoricalCoverageRecord` semantics;
- `HistoricalAcquisitionPlanV1` request identity/hash semantics;
- A6 `PrivateAcceptanceReportV1` behavior;
- `strict-v1` and all investment math.

### 6.2 Preferred diagnostic representation

For the first merge, **do not revise `SourceProbeReportV1` structurally** merely to add
provider diagnostics. Existing reports and hashes must remain readable and stable.
Use the existing machine-readable fields (`http_status`, `account_entitlement`,
`observed_start`, `observed_end`, `historical_capable`, `blockers`, `warnings`, response
hash/metadata) and introduce stable blocker/warning prefixes.

Recommended stable diagnostic prefixes:

```text
FQGATE_LOCAL_GATEWAY_UNREACHABLE
FQGATE_H_ROUTE_UNVERIFIED
FQGATE_H_ROUTE_REJECTED
FQGATE_HTTP_504_UNCLASSIFIED
FQGATE_UPSTREAM_TIMEOUT_CONFIRMED
FQGATE_ENTITLEMENT_DENIED
FQGATE_PROVIDER_ERROR_CODE
HISTORICAL_NO_ROWS
HISTORICAL_COVERAGE_INSUFFICIENT
SOURCE_SCHEMA_UNSUPPORTED

FUTU_OPEND_UNAVAILABLE
FUTU_HISTORY_QUOTA_EXHAUSTED
FUTU_ENTITLEMENT_DENIED
FUTU_HISTORY_REQUEST_FAILED

AKSHARE_UPSTREAM_UNAVAILABLE
AKSHARE_SCHEMA_UNSUPPORTED
AKSHARE_COVERAGE_INSUFFICIENT
```

A new structural diagnostic contract is allowed only if implementation proves the
existing report cannot represent the evidence safely. If needed, add a **new additive
version/sidecar**, rather than silently changing v1 hash or replay semantics.

## 7. Failure-classification rules

The core M2 rule is: **classify only what is explicitly observed**.

| Observation | Classification | What it proves | What it does not prove |
| --- | --- | --- | --- |
| local FQGate health/connection cannot be reached | `FQGATE_LOCAL_GATEWAY_UNREACHABLE` | the local gateway path is unavailable | nothing about H routing, entitlement or H history |
| catalog/runtime cannot provide an exact H identity for the requested security | `FQGATE_H_ROUTE_UNVERIFIED` | no verified history route is available | that FQGate has no H support globally |
| a structured provider response explicitly rejects the supplied market/code | `FQGATE_H_ROUTE_REJECTED` | that observed pair is not accepted for that request | the correct alternative identifier |
| HTTP 504 with no structured reason proving the upstream cause | `FQGATE_HTTP_504_UNCLASSIFIED` | a gateway timeout occurred | route error, provider outage, entitlement, or lack of H support |
| a structured FQGate/provider error code explicitly identifies upstream timeout | `FQGATE_UPSTREAM_TIMEOUT_CONFIRMED` | the request reached a path that reported upstream timeout | future availability or historical coverage |
| HTTP 401/403, or a provider error code explicitly identified by captured evidence as permission/entitlement denial | `FQGATE_ENTITLEMENT_DENIED` | current runtime/account is not permitted for that request | that another account/source cannot access H history |
| valid success envelope and rows, but requested dates/sessions are missing | `HISTORICAL_COVERAGE_INSUFFICIENT` | source works but does not cover the declared target | delisted/action/lifecycle completeness |
| valid success envelope with zero usable rows | `HISTORICAL_NO_ROWS` | no bars were observed for that exact request | whether the cause is invalid route, suspension, no coverage or provider outage unless separately evidenced |
| response shape differs from the supported contract | `SOURCE_SCHEMA_UNSUPPORTED` | decoder cannot safely interpret it | that values should be guessed or defaulted |

### 7.1 Important FQGate 504 rule

Do **not** relabel the existing H 504 as an upstream timeout simply because HTTP status is
504. The current adapter may retry 504 as a transient server status, but retryability is
not cause classification.

If FQGate returns a structured non-2xx error body, M2 may parse and retain a bounded,
non-secret provider error code. Do not persist arbitrary error messages or infer semantics
from free-form text. A provider code may map to a stable blocker only after that code's
meaning is established from official/public implementation evidence or an owner-observed
fixture. Unknown codes remain unknown.

### 7.2 Routing evidence rule

The public FQGate SDK exposes health, catalog search and historical K-line endpoints. Use
those only as diagnostics. A market/code pair observed in catalog or another endpoint may
be recorded as evidence, but the historical adapter must not silently substitute it into
a plan. The plan must still carry the exact pair actually probed against the history
endpoint.

## 8. Source-candidate evaluation

### 8.1 FQGate — first candidate

Strengths for M2:

- already integrated into the repository;
- exact local HTTP responses are preserved in raw CAS;
- existing `MARKET_BAR` compiler/replay path is deterministic;
- no API key belongs in the acquisition plan;
- smallest incremental implementation.

Open questions that M2 must answer by observation:

- whether the owner-observed H identity is accepted by history;
- whether 504 is route-related, entitlement-related, provider-upstream timeout, or remains
  unclassified;
- whether at least a bounded recent and older H date window returns unadjusted daily bars;
- whether the returned schema remains compatible.

Do not use FQGate to claim actions, terminal handling, delisted retention or historical
membership in M2.

### 8.2 Futu OpenD — second candidate

Official Futu API documentation currently describes:

- `request_history_kline(...)` for historical candlesticks;
- daily history with a documented maximum lookback policy of 20 years;
- paging via `page_req_key` and a recommendation to page larger requests;
- `AuType.NONE` / `RehabType_None` as unadjusted/actual prices;
- market-specific quote rights and a separate rolling historical-candlestick quota;
- `get_history_kl_quota(...)` for inspecting quota use.

These are **interface constraints**, not evidence that a particular H listing, terminal
listing, action history or date range is available to this owner. Live selection must
check the actual local OpenD result and preserve the returned limitations.

If implemented, prefer a provider-client-backed acquisition adapter with an injected fake
client in tests. Before normalization, freeze the complete returned page data and request
metadata into a deterministic source envelope and record at least:

```text
provider = Futu OpenD
SDK/OpenD version when observable
requested code and dates
K-line type = day
adjustment = NONE
page order / page keys or stable page identities
returned columns
all returned rows before MARKET_BAR projection
quota/permission outcome as non-secret diagnostics
```

Mark the representation explicitly, e.g. `futu-opend-sdk-export-v1`; do not call it raw
OpenD wire bytes if the SDK does not expose those bytes. This is acceptable for the
personal-research source path only if provenance remains explicit; it must not weaken A6
or turn an SDK export into an authoritative/redistributable claim.

### 8.3 AKShare / Eastmoney — third candidate

The current AKShare codebase exposes `stock_hk_hist`; documentation identifies it as an
Eastmoney-backed H-share historical interface with daily/weekly/monthly modes and
unadjusted/QFQ/HFQ choices.

M2 policy:

- force unadjusted mode for canonical `MARKET_BAR`;
- preserve both wrapper identity (`AKShare`, package version, function/arguments) and
  upstream identity (`Eastmoney`) where documented;
- freeze a deterministic pre-normalization wrapper export before decoding;
- never label row-count success as `COMPLETE` coverage;
- by default use this path as **fallback or reconciliation**, not as an authority claim;
- do not bypass the wrapper by reverse-engineering an undocumented Eastmoney endpoint in
  this milestone;
- do not add HTML scraping or anti-bot bypasses.

If a live probe shows stale rows, upstream failure, schema drift, or incomplete target
coverage, retain the exact blocker and do not silently switch to another AKShare function.

## 9. Minimal mergeable work packages

The packages below are intentionally decision-gated. Do not implement later provider
packages when an earlier source has already earned the required bounded H price role.

### M2-A — FQGate diagnostic hardening

**Objective**

Make FQGate H failures precise enough to support a source-selection decision without
changing public historical/replay semantics.

**Expected files**

- `src/turtle_value_engine/historical/fqgate.py`
- `tests/test_fqgate_historical.py`
- optionally `tests/test_phase_5r_acquisition.py` only if generic transport behavior is
  exercised;
- `docs/operations/phase-5r-a-acquisition.md`;
- `docs/status/phase-5r-a-2026-09-16.md` or a new dated status page.

Avoid modifying `acquisition.py` unless the behavior is genuinely provider-neutral.

**Implementation**

- preserve the current successful A behavior byte-for-byte where possible;
- distinguish connection/local-gateway failure from returned HTTP errors;
- conservatively inspect structured FQGate error envelopes before falling back to generic
  HTTP classification;
- retain a safe scalar provider error code only; do not persist arbitrary response
  messages;
- keep HTTP 504 unclassified unless an observed structured code proves upstream timeout;
- keep 401/403 as entitlement denial;
- preserve successful-but-partial history as coverage insufficiency, not a route failure;
- do not infer an H market identifier;
- do not change retry policy just to make a live probe pass.

**Offline tests**

```bash
python -m pytest tests/test_fqgate_historical.py -q
python -m pytest tests/test_phase_5r_acquisition.py -q
python -m ruff check .
python -m pytest
```

Frozen fake responses must cover at least:

1. A-share 200 success regression;
2. 401/403 -> entitlement denied;
3. opaque 504 -> `FQGATE_HTTP_504_UNCLASSIFIED`;
4. a structured provider error fixture whose code has independently established timeout
   semantics -> `FQGATE_UPSTREAM_TIMEOUT_CONFIRMED`;
5. explicit route-rejection fixture -> `FQGATE_H_ROUTE_REJECTED`;
6. 200 + valid rows with incomplete requested range/sessions ->
   `HISTORICAL_COVERAGE_INSUFFICIENT`;
7. 200 + unsupported schema -> `SOURCE_SCHEMA_UNSUPPORTED`;
8. no test/network path logs credentials or arbitrary error bodies.

If no real/official fixture establishes a timeout or route-rejection provider code, omit
those positive mappings and test that the unknown code remains unclassified. Do not
invent provider codes for test convenience.

**Optional live probe**

Use a private local plan containing only values actually observed from the running FQGate
environment:

```bash
tve historical source probe \
  --plan .tve-private/plans/fqgate-h-smoke.json \
  --network=allow \
  --output .tve-private/live/fqgate-h-smoke.json
```

For local gateway/catalog diagnosis, operator-side calls may use the public local FQGate
health/catalog endpoints, but the returned H market/code must be recorded as observed
evidence and then explicitly placed in the private history plan. Do not auto-promote a
catalog identity into a history identity.

**Acceptance**

- all ordinary tests remain offline;
- current A FQGate success remains valid;
- the old H 504 can no longer be accidentally described as a confirmed upstream timeout;
- every failed probe lands in an evidence-supported class or explicit `*_UNCLASSIFIED`;
- no H capability is claimed from diagnostics alone;
- full test baseline is at least the existing `6180 passed, 2 skipped` unless deliberate
  new tests increase the count;
- `strict-v1`, A6 and deterministic investment math are untouched.

**Blockers**

- FQGate error body contains no stable machine-readable cause;
- H route cannot be independently observed;
- current FQGate runtime is unreachable.

Any of these is a valid reason to retain `H_SOURCE_UNQUALIFIED` and continue to M2-C.

### M2-B — FQGate bounded H selection probe

**Objective**

Determine whether FQGate can be the bounded H `MARKET_BAR` source after M2-A diagnostics.
This package may be documentation/live-evidence only if no code change is needed.

**Implementation / evidence**

Probe the exact H identity actually observed in the owner's FQGate environment in two
non-overlapping bounded windows:

- one recent window;
- one older historical window at least one year earlier.

Do not hard-code an unverified H market identifier into a committed plan. Exact live
plans/reports remain under `.tve-private`; only redacted capability conclusions belong in
Git.

If both windows succeed, perform one bounded acquisition and offline compile/replay:

```bash
tve historical acquire \
  --plan .tve-private/plans/fqgate-h-selected.json \
  --network=allow \
  --raw-store .tve-private/raw \
  --batch-output .tve-private/batches/fqgate-h.json \
  --report-output .tve-private/live/fqgate-h-readiness.json

tve historical compile \
  --batch .tve-private/batches/fqgate-h.json \
  --raw-store .tve-private/raw \
  --store .tve-private/artifacts \
  --output .tve-private/manifests/fqgate-h.json \
  --verify-replay
```

**Offline tests**

No new network tests. Reuse M2-A plus existing compiler/replay tests.

**Acceptance to select FQGate**

- exact H market/code was observed, not inferred;
- history endpoint returns a supported success envelope and unadjusted daily rows;
- recent and older bounded probes succeed;
- bounded acquisition preserves raw response CAS/receipts/provenance;
- offline `--verify-replay` produces stable identities;
- observed coverage is recorded honestly as `COMPLETE`, `PARTIAL` or `UNKNOWN` only when
  the existing evidence basis permits it;
- actions, lifecycle, delistings and historical membership remain unqualified.

If these criteria are not met, record the exact failure and proceed to M2-C without
weakening any gate.

### M2-C — Futu OpenD H MARKET_BAR candidate

**Trigger**

Implement this package only when FQGate remains unqualified for the bounded H price path.

**Expected files**

- new `src/turtle_value_engine/historical/futu_opend.py` (name may follow repository style);
- `src/turtle_value_engine/historical/__init__.py`;
- adapter registration only where needed for the existing acquisition CLI;
- `pyproject.toml` only for an optional historical/provider dependency if required;
- new `tests/test_futu_opend_historical.py`;
- operations/status docs.

Do not make Futu a dependency of ordinary deterministic analysis.

**Implementation**

- use local OpenD only through the explicit acquisition path;
- require `--network=allow` for live calls;
- force daily + unadjusted (`AuType.NONE`/equivalent documented value);
- inspect historical quota before a live probe when practical;
- distinguish OpenD unavailable, quota exhaustion, entitlement denial and history request
  failure;
- page deterministically and preserve page order;
- freeze the complete pre-normalization SDK response envelope into private CAS with
  explicit provider/SDK representation metadata;
- compile only verified OHLCV/turnover fields into canonical `MARKET_BAR`;
- fail closed on unknown columns/schema changes that affect required fields;
- do not claim delisted retention, actions or lifecycle from the existence of the API.

**Offline tests**

Use an injected fake OpenD client. No OpenD process or internet access is allowed in CI.

```bash
python -m pytest tests/test_futu_opend_historical.py -q
python -m pytest tests/test_phase_5r_acquisition.py -q
python -m ruff check .
python -m pytest
```

Cover at least:

- unadjusted daily mapping;
- deterministic multi-page ordering/export;
- quota exhausted vs entitlement denied vs transport/OpenD unavailable;
- malformed/changed schema fail closed;
- bounded date filtering;
- repeated offline compilation produces identical manifest/shard hashes;
- no credentials/session secrets enter plan, log, receipt or fixture.

**Optional live probe**

After local OpenD is already configured by the owner, create a private plan using a stock
identifier returned/accepted by that OpenD runtime and run:

```bash
tve historical source probe \
  --plan .tve-private/plans/futu-h-smoke.json \
  --network=allow \
  --output .tve-private/live/futu-h-smoke.json
```

No brokerage password, login secret or API token is requested by the repository plan.

**Acceptance to select Futu**

- local OpenD is reachable;
- historical quota is available for the probe;
- the runtime/account is entitled to the requested H history;
- recent + older bounded daily unadjusted windows succeed;
- acquisition freezes source evidence before normalization;
- compile/replay is deterministic offline;
- limitations and source representation are explicit;
- no delisting/action/lifecycle completeness is claimed.

**Blockers**

- OpenD unavailable;
- no history quota;
- H quote/history permission denied;
- requested listing/date range is incomplete;
- source-envelope provenance cannot be represented without weakening the existing
  acquisition audit boundary.

A blocker narrows Futu's role; it does not justify changing A6 or strict-v1.

### M2-D — AKShare/Eastmoney bounded fallback/reconciliation adapter

**Trigger**

Implement only if FQGate and Futu cannot provide the bounded H price path, or if an
independent low-cost source is needed for reconciliation.

**Expected files**

- new provider module under `src/turtle_value_engine/historical/`;
- optional dependency declaration only if necessary;
- focused fake-wrapper tests;
- operations/status docs.

**Implementation**

- use the documented `stock_hk_hist` behavior rather than an HTML scraping workaround;
- force `adjust=""`;
- record AKShare package version, function, exact non-secret arguments and Eastmoney
  upstream identity;
- freeze a deterministic complete wrapper export before `MARKET_BAR` projection;
- never infer complete history from first/last row or row count;
- fail closed on schema drift, stale/short range or upstream errors;
- do not silently switch to Sina/another AKShare function;
- by default describe the source role as fallback/reconciliation.

**Offline tests**

```bash
python -m pytest tests/test_akshare_historical.py -q
python -m pytest tests/test_phase_5r_acquisition.py -q
python -m ruff check .
python -m pytest
```

Use a fake wrapper result; ordinary CI must not import a networked provider client unless
it is an optional dependency available in the test environment.

**Optional live probe**

```bash
tve historical source probe \
  --plan .tve-private/plans/akshare-h-smoke.json \
  --network=allow \
  --output .tve-private/live/akshare-h-smoke.json
```

**Acceptance**

- bounded H unadjusted rows are actually observed;
- wrapper and upstream provenance are explicit;
- deterministic export -> compile -> replay works;
- missing/stale range remains a blocker;
- source is not labeled authoritative/complete without separate evidence.

**Blockers**

- upstream interface instability or stale data;
- wrapper schema drift;
- inability to preserve a sufficiently auditable source envelope;
- terms/access evidence incompatible with the intended private research use.

### M2-E — Selection record and optional cross-source reconciliation

**Objective**

Close M2 with a machine/auditor-readable record of which source was selected and why,
without converting source selection into investment logic.

**Implementation**

- update the dated Phase 5R-A status document with:
  - selected H price source or `H_SOURCE_UNQUALIFIED`;
  - exact role (`primary bounded research`, `fallback`, `reconciliation-only`);
  - observed windows and limitations;
  - account/quota/route result in non-secret terms;
  - whether offline replay succeeded;
- if two independent sources both succeed on overlapping sessions, use the existing
  historical reconciliation contract rather than inventing a new scoring system;
- discrepancies may block a stronger coverage claim, but must not alter price rows
  silently.

**Offline tests**

Use existing reconciliation tests plus the selected adapter's tests.

**Acceptance**

M2 ends with exactly one of these explicit states:

```text
H_PRICE_SOURCE_SELECTED_FQGATE
H_PRICE_SOURCE_SELECTED_FUTU
H_PRICE_SOURCE_SELECTED_AKSHARE_RESEARCH_ONLY
H_SOURCE_UNQUALIFIED
```

These are planning/status labels, not new investment-engine states and do not belong in
`strict-v1`.

## 10. Source-selection decision tree

```text
M2-A: Diagnose FQGate
  |
  +-- exact observed H route + history works in bounded recent/older windows
  |      -> M2-B select FQGate
  |
  +-- route/timeout/permission remains failed or unclassified
         -> M2-C probe Futu OpenD
               |
               +-- bounded unadjusted H history + replay succeeds
               |      -> select Futu
               |
               +-- unavailable / denied / quota / coverage failure
                      -> M2-D evaluate AKShare/Eastmoney
                             |
                             +-- usable bounded research path
                             |      -> research-only fallback selection
                             |
                             +-- not auditable/reliable enough
                                    -> H_SOURCE_UNQUALIFIED
```

Do not implement a later branch merely because it exists in this document.

## 11. Verification and regression guardrails

Every mergeable package must run:

```bash
python -m ruff check .
python -m pytest
```

Additional invariants:

- no ordinary test performs a live network call;
- no secret value appears in snapshots, logs, exceptions or Git fixtures;
- existing M1 A-share FQGate tests continue to pass;
- acquisition remains the only networked layer;
- compiler/replay remains offline;
- old manifests/batches/probe reports remain readable;
- no adjusted price is silently normalized as the canonical unadjusted price;
- no missing row is converted to zero or assumed suspension;
- no current universe is substituted for historical membership;
- no provider failure changes deterministic investment results or rules.

## 12. External implementation references to verify at implementation time

FQGate public client:

- https://github.com/zhuyifang/tonghuasun-agent/blob/main/sdk/python/src/fqgate_client/client.py

Futu official API docs:

- historical candlesticks:
  https://openapi.futunn.com/futu-api-doc/en/quote/request-history-kline.html
- quote rights and historical quota:
  https://openapi.futunn.com/futu-api-doc/en/intro/authority.html
- historical quota detail:
  https://openapi.futunn.com/futu-api-doc/en/quote/get-history-kl-quota.html
- candlestick adjustment definitions:
  https://openapi.futunn.com/futu-api-doc/en/quote/quote.html

AKShare implementation/reference:

- https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_em.py

All external capabilities must be rechecked when the package is implemented. Documentation
proves interface semantics only; it does not replace owner-side capability probes.

## 13. Codex execution rule

Codex should treat this document as a **decision-gated goal**, not a request to implement
FQGate + Futu + AKShare all at once.

Start at M2-A, keep each merge independently reviewable, and stop provider expansion as
soon as one H `MARKET_BAR` path earns the bounded personal-research role. If live access
is unavailable in the Codex runtime, complete the deterministic/fake-client implementation
and leave the live capability state explicitly unqualified; never invent a live success.
