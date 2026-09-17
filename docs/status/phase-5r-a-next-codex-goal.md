# Codex Goal — Phase 5R-A M2-C Futu OpenD H `MARKET_BAR` Candidate

Work in repository `blooddrunk/turtle-value-engine` on current `main`.

## Current handoff

M2-B is closed with an evidence-supported FQGate selection failure. After the owner
started a local FQGate instance, two fresh `LOCAL_DIRECT` probes used the exact
owner-observed candidate `UHKM/HK0700` (`HK00700`):

- recent window `2026-09-08` through `2026-09-11`;
- older window `2025-09-08` through `2025-09-11`.

Both reached `/v1/market/history/klines` and returned HTTP 504 with provider code `4003`,
no usable daily rows, and the conservative diagnostics
`FQGATE_HTTP_504_UNCLASSIFIED`, `FQGATE_PROVIDER_ERROR_CODE` and
`FQGATE_PROVIDER_ERROR_UNCLASSIFIED`. Code `4003` has no established semantics and must
not be reclassified as route rejection, upstream timeout or entitlement denial. The
successful `realtime/hk` response is a different interface and is not historical
`MARKET_BAR` evidence.

FQGate therefore did not earn the bounded H price role. H remains
`H_SOURCE_UNQUALIFIED`; lifecycle, membership, delisting, terminal and corporate-action
coverage remain unqualified. No FQGate acquisition/compile was run because the M2-B
acquisition gate requires both bounded probes to succeed.

Read and follow, in source-of-truth order:

- `AGENTS.md`
- `docs/spec/`
- `rules/strict-v1.yaml`
- `schemas/`
- `docs/architecture/`
- `docs/goals/phase-5r-a-m2-c-futu-opend-h-share.md`
- `docs/goals/phase-5r-a-m2-h-share-history-source-selection.md`
- `docs/goals/phase-5r-a-m2-t-fqgate-endpoint-transport.md`
- `docs/status/phase-5r-a-2026-09-17.md`
- `docs/operations/phase-5r-a-acquisition.md`
- `src/turtle_value_engine/historical/acquisition.py`
- existing provider adapters and compiler/replay paths
- relevant historical CLI and tests

The dedicated M2-C goal is the executable refinement of the parent M2 source-selection
plan. If a lower-priority handoff detail conflicts with it, follow the dedicated goal and
preserve frozen specs/contracts.

## Objective

Implement and evaluate **M2-C only**: Futu OpenD as the next bounded H-share
**unadjusted daily `MARKET_BAR` candidate** through the existing acquisition boundary.

M2-C has two separate gates:

```text
M2-C1  provider adapter + provenance + deterministic offline compiler/replay integration
M2-C2  owner-runtime live dual-window evidence and source-selection decision
```

M2-C1 may be completed without access to the owner's live OpenD. M2-C2 may not be
fabricated from fake clients, documentation, runner limitations, package installation or
an unavailable owner runtime.

Do not change investment math, `strict-v1`, A6, PIT, historical coverage semantics or
existing provider receipts/hashes merely to make Futu fit.

## M2-C1 — implementation boundary

### Provider integration

Add a dedicated Futu OpenD historical provider module following repository style, normally
under `src/turtle_value_engine/historical/`, and register it only at the networked
historical acquisition boundary.

Requirements:

- use local OpenD only through explicit opt-in acquisition;
- every live request still requires `--network=allow`;
- do not make Futu/OpenD part of ordinary deterministic analysis;
- treat the Futu Python SDK as an optional provider dependency; ordinary imports/tests
  must not fail merely because the SDK is not installed;
- prefer lazy SDK import and/or injected client/factory seams;
- use an H stock identity actually accepted or returned by the owner's OpenD runtime;
  never derive it from FQGate `market`/`code` fields;
- explicitly request daily bars and explicitly request **unadjusted** history
  (`AuType.NONE` / runtime-documented equivalent); do not rely on the API default, which
  may be adjusted;
- inspect historical K-line quota when the runtime supports it;
- page using the provider's page token/key and preserve deterministic page order;
- bound requests and prevent an accidental unlimited/market-wide fetch;
- close/release SDK contexts deterministically.

### Source evidence / CAS representation

Futu's Python SDK returns a decoded SDK/DataFrame representation rather than guaranteed
raw OpenD wire bytes. Preserve that distinction.

Freeze a complete deterministic pre-normalization provider envelope before `MARKET_BAR`
projection, using an explicit representation identity such as:

```text
futu-opend-sdk-export-v1
```

The frozen envelope should contain enough non-secret information to audit and replay the
request, including at least when observable:

- provider and representation id/version;
- Futu SDK version and OpenD version where available;
- requested stock identity;
- requested start/end;
- daily K-line type;
- explicit unadjusted mode;
- requested fields;
- deterministic page ordinal;
- page token identity in a deterministic non-secret representation if needed for replay
  provenance;
- returned columns/schema;
- every returned row before canonical projection;
- quota/permission outcome as bounded diagnostics where observed.

Do **not** call this envelope raw OpenD wire bytes.

Do not persist brokerage passwords, login secrets, session secrets, arbitrary error
messages containing private material, or any credential not already allowed by repository
contracts.

### Canonical compilation

Compile only validated required daily market fields into canonical `MARKET_BAR`, following
existing schema semantics. Validate exact field meaning before mapping.

At minimum verify the source representation for:

- listing identity;
- trading date/time semantics and timezone/date normalization;
- open;
- high;
- low;
- close;
- volume;
- turnover when canonical schema expects/supports it.

Fail closed on missing required fields, duplicate/ambiguous dates, unexpected listing
identity, malformed numeric values or schema drift that affects required semantics.

Do not infer corporate actions, delisting retention, historical membership, lifecycle,
terminal economics or market-wide completeness from successful K-line rows.

### Diagnostics

Keep diagnostic classification evidence-based and provider-specific only at the
acquisition boundary. Distinguish at least where safely observable:

- OpenD process/transport unavailable;
- SDK unavailable or incompatible;
- historical quota exhausted;
- H quote/history entitlement/permission denied;
- history request failure with unknown cause;
- no usable rows;
- incomplete requested coverage;
- unsupported schema.

Do not map free-form provider error text into strong semantic blocker classes unless the
meaning is established by stable provider code/contract evidence.

## M2-C1 offline tests

Use an injected fake OpenD client. No OpenD process, broker session or internet access is
allowed in ordinary CI.

Add focused tests, normally `tests/test_futu_opend_historical.py`, covering at least:

- explicit daily + unadjusted request construction;
- provider identity is not inferred from FQGate routing fields;
- deterministic single-page mapping;
- deterministic multi-page ordering and complete pre-normalization export;
- quota exhausted vs entitlement denied vs OpenD unavailable;
- unknown provider failure remains conservatively classified;
- malformed/changed schema fails closed;
- bounded date filtering and listing/date validation;
- optional SDK absence does not break ordinary deterministic imports/tests;
- repeated offline compilation/replay produces identical manifest/shard identities for
  the same frozen provider envelope;
- no secrets enter plans, logs, reports, receipts, CAS metadata or fixtures.

Run at minimum:

```bash
python -m pytest tests/test_futu_opend_historical.py -q
python -m pytest tests/test_phase_5r_acquisition.py -q
python -m ruff check .
python -m pytest
```

The latest recorded full-suite code baseline before M2-C is `6212 passed, 2 skipped` from
M2-T. M2-B was documentation/live-evidence only. Do not regress existing tests except for
an intentional, documented replacement.

## M2-C2 — owner-runtime live evidence

Only after the adapter boundary is implemented and offline-tested, attempt source
selection using an **actual owner OpenD runtime**.

Use an H listing identity actually returned/accepted by that OpenD runtime. Do not assume
a Futu symbol syntax merely from examples or reuse `UHKM/HK0700` as if it were a Futu
identifier without runtime evidence.

Before consuming history quota when practical, inspect historical K-line quota/permission
through the provider's documented runtime API.

Run two non-overlapping bounded daily **unadjusted** history probes:

1. one recent window;
2. one older window at least one year earlier.

Private plans/reports/raw SDK exports/batches/manifests remain under `.tve-private` and
must not be committed.

If and only if both windows succeed with a supported schema and usable rows, run one
bounded:

```text
acquire -> private CAS/provider envelope -> compile -> --verify-replay
```

and verify deterministic offline replay.

## M2-C completion decision — preserve these outcomes exactly

### 1. `FUTU_SELECTED`

Use this outcome only when:

- M2-C1 implementation/tests pass;
- owner OpenD is actually reachable;
- exact H listing identity is observed/accepted by the runtime;
- required quota/permission is available;
- both recent and older daily unadjusted windows succeed;
- bounded acquisition freezes auditable provider evidence;
- offline compile/`--verify-replay` is deterministic.

Then record Futu as the bounded H `MARKET_BAR` source, update M2 status, and make **M2-E
selection record / the next repository-defined historical milestone** the next handoff.
Do not implement M2-D in the same goal merely for provider proliferation.

### 2. `FUTU_EVIDENCE_SUPPORTED_FAILURE`

Use this only when M2-C1 is complete and there is genuine evidence that Futu cannot earn
the bounded role, for example:

- the owner's real OpenD runtime returns an established quota exhaustion or permission
  failure;
- real bounded history requests fail with evidence-supported provider/schema/coverage
  blockers;
- both windows cannot satisfy the required bounded history contract despite an available,
  functioning owner runtime;
- the complete provider representation cannot be frozen/replayed without weakening the
  repository's acquisition/provenance boundary.

Record the exact evidence without weakening gates and make **M2-D AKShare/Eastmoney** the
next handoff. Stop before implementing M2-D.

### 3. `BLOCKED_ON_OWNER_LIVE_PROBE`

Use this when:

- Codex/cloud runner cannot reach the owner's localhost/OpenD;
- OpenD is not installed/running/logged in/configured on the owner machine;
- the runner cannot obtain owner-runtime evidence;
- or another execution-environment limitation prevents a genuine M2-C2 probe.

This is **not** Futu provider failure.

In this case:

- finish M2-C1 implementation and offline tests if possible;
- record M2-C1 as complete and M2-C2 as pending;
- provide exact owner-side setup/private-plan/probe commands needed to finish M2-C2;
- keep Futu selection unresolved;
- keep M2-D gated;
- do **not** use fake-client success, documentation, package import success or runner
  localhost failure as selection evidence.

## Documentation before completion

Update at least:

- `docs/goals/phase-5r-a-m2-c-futu-opend-h-share.md` with the actual M2-C execution
  record/outcome;
- `docs/goals/phase-5r-a-m2-h-share-history-source-selection.md` with a concise M2-C
  parent-plan status/result where appropriate;
- `docs/status/phase-5r-a-2026-09-17.md` or a newer dated status page;
- `docs/operations/phase-5r-a-acquisition.md` with the implemented Futu provider boundary
  and owner live workflow where appropriate;
- `docs/status/phase-5r-a-next-codex-goal.md` so it points to the actual next package.

Update `AGENTS.md` only if M2-C introduces stable repository-wide behavior that future
agents need to know; do not use it as an implementation diary.

## Non-goals

Do not in M2-C:

- implement AKShare/Eastmoney unless a later separate M2-D goal explicitly starts;
- reconstruct H historical membership/lifecycle/delistings/actions;
- change `strict-v1`, CDC, Net Cash, Through Return, hard gates or valuation;
- weaken A6/PIT/coverage acceptance;
- add Cloudflare storage, Web UI or Phase 6 event monitoring;
- implement Tunnel/Access in Turtle;
- add trading, order, cancellation, transfer or other financial state-changing operations;
- turn Futu into a mandatory dependency for deterministic engine use;
- claim a complete/authoritative H historical corpus from bounded K-line success.

Stop after M2-C's actual outcome has been recorded and the next handoff has been prepared.
