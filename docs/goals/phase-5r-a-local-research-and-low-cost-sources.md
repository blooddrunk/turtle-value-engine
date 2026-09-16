# Phase 5R-A Next — Personal Research Data Acquisition and Deployment-Neutral Access

Status: **PROPOSED / NEXT**  
Date: 2026-09-16

## 1. Objective

`turtle-value-engine` is a **personal research project**. The next Phase 5R-A
work should optimize for reliable, reproducible, inexpensive or free data that
the project owner can actually obtain and use. It must not make institutional
market-data procurement, redistribution rights, or a public data-service claim
a prerequisite for useful research.

The system is also **deployment-neutral**. The engine may be invoked by a local
CLI, Codex, ChatGPT, Hermes or another agent; derived research results may later
be exposed through an API or a Web UI hosted on Cloudflare Workers or another
platform. None of those deployment choices should downgrade or invalidate a
research dataset.

The existing A6 audit and `--require-production` remain available as an
optional strict claim/audit layer. They must not become the default gate for
personal research, agent execution, or a private Web UI.

The following remain unchanged:

- `rules/strict-v1.yaml`;
- deterministic CDC, Net Cash and Through Return math;
- deterministic hard gates and valuation;
- point-in-time rules;
- ordinary CI remains offline and model-independent;
- no hidden network calls from deterministic analysis.

## 2. Correct interpretation of `LOCAL_ONLY` and `PRODUCTION_ELIGIBLE`

The repository currently contains terms such as `StoragePolicy.LOCAL_ONLY` and
`PRODUCTION_ELIGIBLE`. They must not be interpreted as product deployment
modes.

`LOCAL_ONLY` means only that a raw/source artifact is currently stored in a
local/private store and is not automatically mirrored elsewhere. It does **not**
mean:

- the engine can only run on one computer;
- Hermes cannot use the data;
- a Skill cannot use the engine;
- the results cannot be served by an API;
- a private Web UI cannot be deployed to Cloudflare Workers;
- normalized/derived artifacts cannot later be mirrored to R2, a VPS, S3-like
  storage or another private backend.

Likewise, `PRODUCTION_ELIGIBLE` is a strict Phase 5R historical-corpus claim. It
is useful when the owner explicitly asks for that audit, but it is not the
project's definition of "usable".

A dataset may therefore be technically useful and reproducible for personal
research while:

```text
research_usable = true
production_eligible = false
```

That is a normal state, not an error.

## 3. Deployment model

Keep four concerns separate:

```text
DATA ACQUISITION
public API / local gateway / authenticated personal session /
open-source wrapper / exchange or issuer download / other reliable adapter
        |
        v
RAW + NORMALIZED ARTIFACTS
content-addressed bytes + manifests + provenance
        |
        v
DETERMINISTIC ENGINE
replay / analysis / backtest / calibration
        |
        +--------------------+
        |                    |
        v                    v
AGENT / SKILL            WEB / API
Hermes/Codex/etc.        Cloudflare Worker or other UI
```

Acquisition may run on the machine or VPS that can reach the source. The
artifact store may initially be local and later gain a remote backend/mirror.
The deterministic engine must consume the same frozen artifacts regardless of
where they are stored.

A future Cloudflare deployment should normally serve **derived/frozen data and
analysis results**, or call a backend API. It does not require every upstream
market-data source to be callable directly from a Worker. For example, a local
FQGate acquisition process can persist/freeze data first and a later sync step
can publish eligible normalized artifacts/results to a remote store.

## 4. Data-source policy for this personal project

Source selection is driven primarily by:

1. can the owner actually access it;
2. observed historical coverage;
3. data quality and stability;
4. deterministic repeatability/caching;
5. ability to identify source/provenance and detect changes;
6. cost and operational complexity.

Do not reject a useful personal-research source merely because it cannot satisfy
a public redistribution or institutional procurement standard.

Acquisition implementations may use any technically sound method that is
available to the owner, including documented APIs, local gateways, public
endpoints, open-source wrappers, authenticated personal sessions, exchange or
issuer downloads, and deterministic HTML/JSON extraction when necessary. Do
not bypass authentication or technical access controls. Preserve exact/raw
responses or equivalent source evidence whenever practical so changed upstream
behavior can be detected.

The owner must not be required to manually assemble price, filing, lifecycle or
corporate-action CSV files.

## 5. Current baseline

The repository already has a useful acquisition/replay foundation:

- owner-authorized A-only Hithink probe/acquire completed;
- `SH600000`, 2020-01-01 through 2022-01-02 target;
- one `MARKET_BAR` shard containing 486 daily rows for 2020-01-02 through
  2021-12-31;
- exact raw bytes persisted in a private content-addressed store;
- repeated offline compilation produces stable identities;
- ordinary CI remains offline/model-free.

The A6 `historical accept` blockers describe the larger full A/H acceptance
claim. They do not make the existing A-share historical data unusable.

## 6. Recommended source stack

### 6.1 Hithink — keep as the current A-share bulk source

The successful owner probe already proved that the current adapter can acquire
and compile the A-share daily-k dump. Keep it as the primary bulk A-price path
unless another source proves materially better.

Do not require this one provider to solve every category.

### 6.2 FQGate / `tonghuasun-agent` — next implementation priority

FQGate is especially attractive for this project because its useful integration
surface is a **local HTTP market-data gateway**, not the AI plugin itself.

The public Python SDK exposes:

```text
POST /v1/market/history/klines
```

with parameters including:

```text
market
code
count
start_date
end_date
adjust
interval
```

The public client also exposes an `hk` market group, and the UI implementation
contains explicit K-line field mappings for time/open/high/low/close/volume and
amount.

Integrate FQGate through its HTTP boundary rather than importing the whole
`tonghuasun-agent` project:

```text
FQGate
  -> local HTTP response
  -> HistoricalSourceAdapter
  -> RawBlobStore / receipt
  -> offline decoder
  -> MARKET_BAR shard
```

Probe A and H independently. Do not invent H history, delisted coverage or
action coverage that has not been observed.

### 6.3 AKShare / Eastmoney-backed paths — zero-key research and reconciliation

AKShare already exposes A- and H-share historical interfaces and the repository
already uses AKShare elsewhere. For Phase 5R, route it through the historical
acquisition/CAS boundary rather than bypassing provenance.

Good uses:

- zero-key fallback historical prices;
- sampled cross-source reconciliation;
- filling a bounded research slice when a primary gateway is unavailable.

Do not require it to prove the full Phase 5R production claim before it can be
used for personal research.

### 6.4 BaoStock — A-share calendar/lifecycle supplement

BaoStock is a useful free complement for:

- trading calendars;
- listing/basic information such as IPO/out dates and status;
- sampled unadjusted daily bars for comparison.

Its first role should be closing practical A-share research gaps rather than
replacing the working Hithink price path.

### 6.5 Futu OpenD — H-share fallback

If FQGate's observed H historical capability is insufficient, evaluate Futu
OpenD next. It has an explicit H-share historical K-line API and a local gateway
model. Account-specific entitlements/quotas are runtime facts to probe, not a
reason to block the project in advance.

## 7. Revised milestone order

The previous version of this plan put a separate `LOCAL_ONLY_EXPERIMENTAL`
status milestone first. That is no longer the recommended priority.

The highest-value next merge is **data acquisition**, not a new label.

### M1 — FQGate historical MARKET_BAR adapter and capability probe

Goal: integrate the smallest useful FQGate historical source path into the
existing raw-CAS/offline-compiler architecture.

Scope:

- support the local FQGate HTTP endpoint;
- add POST request support to the acquisition transport if the current
  abstraction only supports GET;
- preserve exact response bytes in `RawBlobStore` before decoding;
- first support unadjusted daily bars only (`adjust=""`, day interval);
- decode only verified fields;
- use fake/local transport fixtures in ordinary CI;
- keep live access opt-in and outside ordinary CI;
- provide probe plans/examples for one A listing and one H listing without
  inventing unobserved market identifiers or coverage;
- persist observed date span/schema/capability/limitations.

M1 does **not** need to make A6 or `--require-production` pass.

Expected implementation surface:

- `src/turtle_value_engine/historical/acquisition.py` or a small adapter module;
- optional dedicated `src/turtle_value_engine/historical/fqgate.py` if that
  keeps provider logic cleaner;
- `src/turtle_value_engine/cli.py` only where needed for existing probe/acquire
  plumbing;
- acquisition schema only if POST/local-adapter metadata cannot be represented
  additively today;
- focused tests with fake FQGate JSON responses;
- one redacted/example acquisition plan if useful;
- Phase 5R-A operations/status docs after implementation.

Acceptance:

1. ordinary CI is fully offline;
2. a frozen fake FQGate response compiles deterministically into `MARKET_BAR`;
3. repeated compile produces the same identities;
4. unadjusted daily OHLCV mapping is covered by tests;
5. unsupported/malformed field shapes fail closed;
6. no H-share capability is claimed unless actually observed;
7. A6 and `--require-production` semantics are unchanged;
8. `strict-v1` and deterministic investment math are unchanged.

### M2 — Real source probe and H-share source selection

Run/record real owner-side probes using the implemented adapter.

Decision tree:

```text
FQGate H history sufficient?
  YES -> use FQGate for the bounded H research path
  NO  -> probe Futu OpenD
            |
            +-- sufficient -> use Futu
            +-- insufficient -> use AKShare/Eastmoney as research fallback
```

A failed source probe narrows that source's role; it does not block unrelated
research.

### M3 — A-share lifecycle/calendar automation

Implement the smallest BaoStock or equivalent automated adapter for trade dates
and listing lifecycle/basic fields. Do not ask the owner to prepare tables.

### M4 — Cross-source reconciliation

Compare selected canonical observations against an independent available source
on deterministic samples. Reconciliation improves confidence but is not a
prerequisite for every local/agent research run.

### M5 — Deployment-neutral artifact backend

After the data pipeline is useful, introduce an artifact-store abstraction or
mirror strategy so the same normalized/frozen data can live in:

- local filesystem/CAS;
- private VPS/object storage;
- S3-compatible storage such as Cloudflare R2.

Do not change content identities when moving an artifact between backends.

This milestone enables clean agent/API/Web usage without coupling the engine to
a specific cloud provider.

### M6 — Agent/API/Web surface

Expose stable research/analysis interfaces suitable for Hermes/Skill/API use and
then a Web UI. A Cloudflare Worker UI may read prepared data/results from R2/D1
or call an engine/backend service. UI deployment must not change investment
math or historical replay semantics.

## 8. What is no longer a prerequisite

The following are **not** prerequisites for continuing useful personal research
or for building an agent/Web UI:

- full A/H `PRODUCTION_ELIGIBLE` status;
- redistribution rights for every source;
- institutional/commercial data contracts;
- complete survivorship-free market-wide history;
- complete H-share lifecycle reconstruction;
- every corporate action across both markets;
- full historical Business Quality archive.

Those may be added when they become useful to a specific research/backtest
claim. Missing data must remain explicit, but incompleteness should narrow the
claim rather than disable the entire system.

## 9. Storage and Cloudflare direction

Remote storage is a deployment choice, not a data-quality classification.

A practical future shape is:

```text
acquisition node (PC/VPS)
  -> immutable raw/normalized artifacts
  -> optional R2/VPS mirror
  -> engine/API/Hermes
  -> Worker Web UI + D1/R2 metadata/results
```

For the initial source milestones, local CAS remains the simplest authoritative
store. Add remote mirroring only after acquisition is stable; do not make it a
prerequisite for M1.

## 10. Recommended next Codex goal

Implement **M1 — FQGate historical MARKET_BAR adapter and capability probe**.
Do not spend the next implementation cycle creating a new product-level
`LOCAL_ONLY` readiness gate. Preserve existing strict audit modes, but optimize
the implementation for reliable personal research data first.
