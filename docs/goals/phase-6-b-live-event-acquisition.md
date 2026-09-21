# Phase 6-B — Opt-in Live Event Acquisition and Canonicalization

Status: **SELECTED / NOT YET IMPLEMENTED**
Date: 2026-09-21
Selected after: Phase 6-A CLOSED
Selection audit: `docs/status/phase-6-b-selection-2026-09-21.md`

Parent context:

- `AGENTS.md`
- `docs/goals/phase-6-a-watchlist-event-foundation.md`
- `docs/status/phase-6-a-2026-09-21.md`
- `docs/architecture/runtime-and-automation.md`
- `docs/architecture/provider-and-cache.md`
- `src/turtle_value_engine/providers/filings.py`
- `src/turtle_value_engine/monitoring/`
- `docs/roadmap.md`

## 1. Objective

Connect real, opt-in network acquisition to the frozen Phase 6-A monitoring
boundary without changing investment semantics.

Phase 6-B must:

1. acquire bounded source-native event/disclosure metadata only after explicit
   network authorization;
2. retain auditable raw/source provenance;
3. deterministically map accepted source records into
   `MonitoringEventV1`;
4. build canonical `MonitoringEventBatchV1` values;
5. allow those batches to be replayed through the existing Phase 6-A
   `run_monitoring` / `MonitoringWorkspace` path;
6. preserve the rule that acquisition does **not** advance a committed cursor;
   cursor movement happens only through an atomically committed monitoring run.

This package is acquisition and canonicalization, not unattended automation.

## 2. Non-negotiable boundaries

Phase 6-B must not:

- modify `strict-v1`, deterministic investment formulas or hard gates;
- execute research, accepted-adjustment materialization or CompanyAnalysis;
- automatically approve an adjustment;
- start a scheduler, daemon, webhook consumer or notification provider;
- mutate Cloudflare, Tunnel, Access or FQGate lifecycle state;
- introduce a generic URL/path proxy;
- expose brokerage/trading/order/funds operations;
- silently access the network from `tve analyze`, `tve surface`,
  `tve watch validate|replay|status` or ordinary tests;
- advance event cursors on fetch success, normalization success or batch write
  alone;
- claim a Bridge market-history/event capability that does not exist.

## 3. Provider-neutral acquisition contract

Implement a small monitoring-source boundary under
`src/turtle_value_engine/monitoring/` (or another architecture-consistent
location) with these properties:

- explicit source identity and adapter version;
- explicit listing scope, source scope and bounded acquisition window;
- explicit `as_of` / availability boundary;
- hard request/response count and byte limits;
- injected transport/source client for deterministic tests;
- source-specific normalization separated from transport;
- no provider-specific fields leak into `MonitoringEventV1`;
- acquisition result records enough non-secret provenance to replay and audit
  which raw response/source record produced each canonical event.

If a new persisted acquisition receipt is introduced, it must be typed,
versioned, hash-verified, schema-backed and drift-tested. Do not add a receipt
merely for prose bookkeeping if the existing raw-provider/cache artifact already
provides the needed immutable provenance.

## 4. First source slice: official filing/disclosure metadata

Prefer the existing official filing-discovery boundary as the first source
family instead of inventing a parallel event scraper.

The repository already has:

- `OfficialFilingDiscoveryProvider`;
- `FilingDiscoveryQuery`;
- official A/H source identities such as CNINFO/SSE/SZSE/BSE/HKEXNEWS;
- official-host validation;
- deterministic filing IDs;
- replayable raw-provider records.

Phase 6-B should add an explicit deterministic **filing-to-monitoring-event
mapping** layer. It must not infer a high-impact event type from vague titles.

Mapping rules:

- annual/interim reports may map only when document type/metadata establishes
  that classification;
- earnings warnings/preannouncements, dividend declarations, buybacks, share
  issuance, penalties, litigation, audit-opinion changes and similar events
  require explicit source metadata/rules proving the category;
- ambiguous disclosures map to `INFORMATIONAL_DISCLOSURE`, or remain
  unmapped with an explicit reason; never guess;
- `published_at` may be populated only when the source actually provides
  timestamp precision; a date-only source must not fabricate a timestamp;
- `available_at` must reflect the earliest source availability the adapter can
  actually establish. If only date-level evidence exists, define and document
  a conservative deterministic date-to-availability policy rather than using
  the local fetch clock;
- `source_event_id` / `source_artifact_id` must preserve the official filing
  identity/provenance.

### Live-source checkpoint

Do not guess an upstream endpoint. Before adding a concrete network source
client, inspect the current official/public contract and implement **one**
narrow source only.

Priority is an official A-share disclosure source already represented by the
existing filing boundary; CNINFO is the first candidate, but selection must be
based on current evidence, not the name in this document.

If no official source can be accessed with a stable bounded contract, keep the
provider-neutral and deterministic mapping work complete but leave Phase 6-B
OPEN with the exact source blocker. Do not substitute an undocumented scraper
and do not declare live acquisition proven.

## 5. CLI / network permission

Add an acquisition command under the existing watch namespace, for example:

`tve watch acquire-events ... --network=allow`

Exact spelling may follow current CLI conventions, but all of these rules are
mandatory:

- network is denied by default;
- explicit allow is required for a live source;
- offline fixture/replay mode needs no network flag;
- source, listing scope, time window, limits and output/workspace are explicit;
- a live command prints/stores bounded non-secret diagnostics only;
- credentials, cookies, Access assertions and raw secrets never enter Git,
  stdout, command history guidance or committed fixtures.

## 6. Cursor and idempotency semantics

Acquisition and processing are separate transactions.

Required sequence:

```text
committed WatchlistStateV1
  -> derive bounded source/listing acquisition window
  -> acquire raw source records
  -> deterministically canonicalize
  -> MonitoringEventBatchV1
  -> Phase 6-A run_monitoring(...)
  -> inspect/validate planned next state
  -> atomic MonitoringWorkspace commit
  -> cursor advances only here
```

A failed fetch, partial response, normalization failure, batch write failure or
crash before the final monitoring commit must leave the committed cursor
unchanged.

Repeated acquisition of the same source records must produce byte-identical
canonical events/batches or fail on a real content conflict.

## 7. FQGate remote bridge integration policy

`blooddrunk/fqgate-remote-bridge` is a future optional provider candidate.

Current verified state:

- its Phase 5 remote-machine boundary is closed;
- it has real Access/Tunnel machine acceptance;
- it exposes a registry-derived filtered machine OpenAPI;
- it currently exposes one bounded instrument lookup;
- it does **not** expose quote/history/event/disclosure operations.

Therefore Phase 6-B must **not** depend on the Bridge.

A later Turtle Bridge adapter may be added when the companion repository
publishes a stable Bridge-owned operation that satisfies all of these gates:

1. explicitly read-only semantics;
2. typed and bounded request/response;
3. fixed Bridge operation ID/path, no generic proxy;
4. `remote_machine` authorization and filtered machine OpenAPI;
5. operation-scoped compatibility/drift evidence;
6. permanent-Windows and real remote acceptance;
7. source timestamps/provenance sufficient for Turtle PIT semantics.

If those gates are met, Turtle should consume that operation through the same
provider-neutral Phase 6-B interface. It may then become a preferred source for
the capabilities it actually proves. Turtle must not duplicate Bridge
Cloudflare/FQGate lifecycle code.

## 8. Required implementation tests — automatic

Codex must automate every machine-verifiable case.

At minimum add deterministic tests for:

- network deny-by-default;
- explicit allow path using injected/fake transport;
- request window/count/byte bounds;
- source error, timeout, malformed response and oversized response;
- exact source/listing scope validation;
- deterministic source-record identity/provenance;
- exact filing/event classification rules;
- ambiguous disclosure no-fabrication behavior;
- PIT boundary: future-unavailable events do not enter the batch;
- stable canonical ordering;
- duplicate same-content idempotency;
- duplicate conflicting-content hard failure;
- acquisition does not mutate committed state;
- failed acquisition does not move cursor;
- successful acquisition + Phase 6-A commit moves only the expected
  source/listing cursor;
- restart/replay from persisted raw/canonical artifacts is deterministic;
- schemas/drift tests for any new persisted contract;
- all existing Phase 6-A tests remain unchanged and green;
- complete repository regression suite remains green.

Mandatory repository gates before closure:

```bash
python -m ruff check .
python -m pytest
```

Also run every existing generated-contract/Dashboard gate that GitHub Actions
currently enforces. Do not report only focused tests.

## 9. Live verification policy

### Automatically perform when possible

For the selected first live source, use a bounded non-mutating probe with:

- one or two public listing IDs only;
- a short fixed date window;
- a small explicit result limit;
- fixed timeout and response-byte bound;
- no credential printed or persisted;
- raw payload retained only in the repository's existing private/raw cache
  boundary, never committed to Git.

Then automatically:

1. acquire;
2. canonicalize;
3. validate hashes/schemas;
4. replay offline from the persisted raw artifact;
5. compare canonical bytes/hashes;
6. feed the batch into Phase 6-A planning;
7. verify the committed cursor moves only after successful workspace commit.

### Human-only boundary

Human intervention is permitted only when the upstream source genuinely
requires an action automation cannot safely perform, such as CAPTCHA,
interactive browser login or consent.

If that occurs, the handoff must name a marker such as
`MANUAL_SOURCE_ACCESS_REQUIRED` and include:

1. exact command to run before the human step;
2. exact browser/login/CAPTCHA action required;
3. what secret must stay outside logs/Git;
4. exact command to resume automation;
5. exact expected machine-verifiable success output;
6. what remains unverified if the operator stops there.

Do not write “manual verification recommended”, “live evidence incomplete” or
similar vague closure language.

## 10. Baseline and closure discipline

Before editing:

1. fast-forward `main` only; never reset/delete owner changes;
2. record `git status --short`, HEAD and remotes;
3. discover the owner's real checkout under `D:\\code\\research` or
   `/mnt/d/code/research` when available;
4. verify GitHub Actions is green for the exact baseline commit;
5. run baseline repository tests.

After implementation:

1. run focused Phase 6-B tests;
2. run the complete local gates;
3. run the bounded live-source probe when technically possible;
4. push;
5. verify GitHub Actions is green for the **exact pushed closing commit**;
6. only then mark Phase 6-B CLOSED and record exact run/commit IDs.

If a mandatory automated gate fails, Phase 6-B stays OPEN. Record the exact
command, observed error, and next required action.

## 11. Expected file scope

Likely additions/changes include:

- `src/turtle_value_engine/monitoring/` acquisition/source modules;
- narrow source client(s) under the existing provider boundary when justified;
- `src/turtle_value_engine/cli.py`;
- `src/turtle_value_engine/config/project.py` only for non-secret monitoring
  acquisition defaults;
- `config/project.example.toml`;
- tests for acquisition, normalization, CLI and Phase 6-A integration;
- optional new schema only if a new persisted contract is necessary;
- `docs/architecture/runtime-and-automation.md`;
- `docs/architecture/provider-and-cache.md` when the provider boundary changes;
- this goal and a dated closure/status document;
- `AGENTS.md` / `docs/roadmap.md` only to synchronize final state.

Do not modify Dashboard code, Cloudflare deployment code, `strict-v1` or
deterministic calculation/gate modules in this package unless an actual
contract defect is discovered and separately justified.

## 12. Exit criteria

Phase 6-B may close only when all are true:

1. explicit opt-in acquisition exists and ordinary paths remain offline;
2. at least one source family deterministically produces valid
   `MonitoringEventV1` values;
3. ambiguous source metadata fails closed or becomes explicitly informational;
4. raw/source provenance remains auditable;
5. canonical replay is deterministic;
6. acquisition alone never advances committed cursors;
7. Phase 6-A planning/commit integration is proven automatically;
8. focused and full repository gates pass;
9. exact closing commit has green GitHub Actions;
10. if a live source is part of the claimed closure, its bounded live probe and
    offline replay evidence are recorded;
11. no Phase 6-C/D/E work is mixed in;
12. FQGate Bridge remains optional unless/until it publishes a compatible
    event-capable machine operation.
