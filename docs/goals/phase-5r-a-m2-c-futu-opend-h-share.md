# Phase 5R-A M2-C — Futu OpenD Bounded H-share `MARKET_BAR` Candidate

Status: **COMPLETE / FUTU_SELECTED**
Date: 2026-09-17  
Parent goal: `docs/goals/phase-5r-a-m2-h-share-history-source-selection.md`  
Trigger: M2-B closed with evidence-supported FQGate selection failure at
`ccd3c7f85034506cfe1520df486faab3e32bdd65`.

## 1. Decision

FQGate did not earn the bounded H-share `MARKET_BAR` source role in M2-B. The next
candidate is Futu OpenD.

M2-C is deliberately split into two gates:

```text
M2-C1  provider adapter + provenance + deterministic offline compiler/replay integration
M2-C2  owner-runtime live dual-window evidence + source-selection decision
```

The split is mandatory. A Codex/cloud runner that cannot reach the owner's OpenD may
complete M2-C1, but that execution-environment limitation is not evidence that Futu failed
M2-C2 and must not automatically advance the project to M2-D.

## 2. Goal

Determine whether Futu OpenD can earn the smallest useful bounded H-share source role:
**daily, unadjusted `MARKET_BAR` history for personal research**, with auditable provider
provenance and deterministic offline replay.

M2-C does not attempt to prove full historical membership, delisted retention, corporate
actions, terminal economics or market-wide completeness.

## 3. Existing boundaries to preserve

Do not change the semantics of:

- `strict-v1`;
- CDC, Net Cash, Through Return, hard gates or valuation;
- A6 acceptance;
- PIT validation;
- `HistoricalDatasetManifest` / `HistoricalArtifactStore` coverage semantics;
- existing FQGate/Hithink receipts, hashes, replay or adapter compatibility;
- the rule that ordinary CI and deterministic analysis remain offline.

Network acquisition remains explicitly opt-in through `--network=allow`.

## 4. Current provider facts to verify at implementation time

The current official Futu OpenD interface documents a historical K-line API with:

- explicit stock identity;
- start/end date bounds;
- daily K-line type;
- an adjustment-mode parameter;
- provider page keys for pagination;
- a separate historical K-line quota query.

The API default adjustment mode must not be trusted for Turtle semantics. M2-C must
explicitly request the provider's documented **unadjusted** mode (`AuType.NONE` or the
runtime-documented equivalent).

Documentation describes interface capability only. It is not evidence that this owner's
OpenD installation/account has H-share history permission, quota or coverage for a
particular listing/date range.

## 5. M2-C1 — provider implementation

### 5.1 Expected implementation surface

Expected files normally include:

- new `src/turtle_value_engine/historical/futu_opend.py` (or repository-consistent name);
- `src/turtle_value_engine/historical/__init__.py` where registration requires it;
- acquisition/CLI registration only at the existing networked boundary;
- `pyproject.toml` only if an optional provider dependency is needed;
- new `tests/test_futu_opend_historical.py`;
- operations/status documentation.

Do not make Futu a dependency of ordinary deterministic engine use.

### 5.2 SDK boundary

Prefer an injected client/factory boundary and lazy SDK import.

Requirements:

- ordinary deterministic imports/tests must still work when the Futu Python SDK is absent;
- live OpenD access occurs only after explicit network opt-in;
- provider contexts/connections are closed deterministically;
- do not request or store brokerage passwords or login secrets in Turtle plans;
- use a listing identity actually accepted or returned by the owner's OpenD runtime;
- never derive a Futu identity from FQGate `market`/`code` fields.

### 5.3 Request semantics

For canonical H daily price history:

- explicitly request daily K-lines;
- explicitly request unadjusted prices;
- inspect historical quota before consuming a new symbol quota when practical;
- bound start/end dates;
- use deterministic pagination through the provider page token/key;
- preserve page order;
- do not issue an accidental unlimited or market-wide pull.

### 5.4 Provider evidence representation

The Python SDK returns a decoded SDK/DataFrame representation; it is not necessarily raw
OpenD wire bytes. Freeze a complete deterministic pre-normalization provider envelope in
private CAS before canonical projection, with an explicit representation id such as:

```text
futu-opend-sdk-export-v1
```

Record, where observable and non-secret:

- provider + representation id/version;
- Futu SDK version;
- OpenD version;
- requested listing identity;
- start/end date;
- daily K-line type;
- explicit unadjusted mode;
- requested fields;
- deterministic page ordinal;
- page-token identity/representation only when needed and safe for provenance;
- returned columns/schema;
- every provider row before canonical projection;
- quota/permission outcome as bounded diagnostics.

Do not call this representation raw OpenD wire bytes.

Resolved secrets, brokerage credentials, login material and arbitrary private error text
must not enter plans, logs, reports, receipts, CAS metadata, fixtures or Git.

### 5.5 Canonical `MARKET_BAR` compilation

Validate field meaning before mapping. At minimum validate:

- listing identity;
- trading date/time and timezone/date normalization;
- open;
- high;
- low;
- close;
- volume;
- turnover where supported/required by the canonical contract.

Fail closed on missing required fields, duplicate or ambiguous dates, mismatched listing,
malformed numbers, unsafe coercion or schema drift affecting required semantics.

Successful rows do not establish corporate actions, delistings, membership/lifecycle or
terminal economics.

### 5.6 Diagnostics

Use evidence-supported diagnostics and keep provider-specific details at the acquisition
boundary. Distinguish at least where safely observable:

- OpenD process/transport unavailable;
- SDK unavailable/incompatible;
- history quota exhausted;
- H quote/history permission or entitlement denial;
- provider history request failure with unknown cause;
- valid success with no usable rows;
- incomplete requested coverage;
- unsupported schema.

Do not infer strong semantic causes from free-form provider messages alone. Unknown causes
remain explicitly unclassified unless a stable provider code/contract establishes the
meaning.

## 6. M2-C1 offline acceptance

Use an injected fake OpenD client. Ordinary tests must not contact OpenD or the Internet.

Cover at least:

1. explicit daily + unadjusted request construction;
2. Futu identity is not inferred from FQGate fields;
3. deterministic single-page mapping;
4. deterministic multi-page ordering and complete pre-normalization export;
5. quota exhausted vs entitlement denied vs OpenD unavailable;
6. unknown provider failure remains conservative/unclassified;
7. malformed or changed required schema fails closed;
8. bounded date/listing validation;
9. optional SDK absence does not break ordinary deterministic imports;
10. repeated offline compile/replay produces identical manifest/shard identities for the
    same frozen provider representation;
11. no secrets enter persisted artifacts or fixtures.

Run at minimum:

```bash
python -m pytest tests/test_futu_opend_historical.py -q
python -m pytest tests/test_phase_5r_acquisition.py -q
python -m ruff check .
python -m pytest
```

The latest recorded full-suite code baseline before M2-C is `6212 passed, 2 skipped` from
M2-T. M2-B changed live evidence/docs only. Do not regress existing tests except for an
intentional, documented replacement.

## 7. M2-C2 — owner-runtime source-selection evidence

M2-C2 requires a genuine owner OpenD runtime. Fake clients, official documentation, SDK
installation or a runner-local mock cannot satisfy it.

Use an H listing identity actually returned or accepted by that runtime. Do not assume a
symbol merely from documentation examples and do not reuse `UHKM/HK0700` as a Futu
identity without runtime evidence.

When practical, inspect quota/permission before consuming a new historical-symbol quota.
Then run two non-overlapping bounded **daily + unadjusted** windows:

- one recent window;
- one older historical window at least one year earlier.

Private plans, reports, SDK exports, batches, CAS and manifests remain under
`.tve-private` and must not be committed.

Only if both windows succeed with a supported schema and usable rows, run one bounded:

```text
acquire -> private CAS/provider envelope -> compile -> --verify-replay
```

and verify deterministic offline replay.

## 8. Completion outcomes

Exactly preserve the distinction below.

### 8.1 `FUTU_SELECTED`

Required evidence:

- M2-C1 implementation/tests pass;
- owner OpenD is actually reachable;
- exact H listing identity is observed/accepted;
- required quota/permission is available;
- both recent and older unadjusted daily windows succeed;
- bounded acquisition freezes auditable provider evidence;
- offline compilation/replay is deterministic.

Then select Futu for the bounded H `MARKET_BAR` role. Stop provider proliferation: do not
implement M2-D in the same package. Advance to M2-E selection record / the next
repository-defined historical milestone.

### 8.2 `FUTU_EVIDENCE_SUPPORTED_FAILURE`

This outcome requires a functioning evidence path, not merely missing owner access. Valid
examples include:

- the owner's real OpenD returns an established quota or permission blocker;
- actual bounded history probes fail with evidence-supported provider/schema/coverage
  blockers;
- both windows cannot satisfy the bounded contract despite a functioning owner runtime;
- the complete provider representation cannot be frozen/replayed without weakening the
  existing acquisition/provenance boundary.

Record the exact blocker and advance the next handoff to M2-D. Do not implement M2-D in
this goal.

### 8.3 `BLOCKED_ON_OWNER_LIVE_PROBE`

Use this when Codex/cloud execution cannot produce genuine M2-C2 evidence because, for
example:

- it cannot reach the owner's localhost/OpenD;
- OpenD is not installed, running, logged in or configured on the owner machine;
- owner-runtime identity/quota/permission evidence is unavailable;
- another execution-environment limitation prevents the live probe.

This is not Futu provider failure.

In this outcome:

- complete M2-C1 implementation/offline tests if possible;
- record M2-C1 complete and M2-C2 pending;
- provide exact owner-side setup/private-plan/probe commands;
- keep Futu selection unresolved;
- keep M2-D gated.

Do not use fake-client success, docs, successful SDK import or runner localhost failure as
source-selection evidence.

## 9. Documentation closure

Before stopping, update:

- this goal with the actual M2-C execution record/outcome;
- `docs/status/phase-5r-a-2026-09-17.md` or a newer dated status page;
- `docs/operations/phase-5r-a-acquisition.md` for the implemented Futu boundary/workflow;
- `docs/status/phase-5r-a-next-codex-goal.md` to the true next package.

Update `AGENTS.md` only for stable repository-wide behavior, not implementation history.

## 10. Non-goals

M2-C must not:

- implement M2-D AKShare/Eastmoney in the same goal;
- reconstruct H historical membership/lifecycle/delistings/actions;
- claim a complete/authoritative H corpus from bounded K-line success;
- change `strict-v1`, A6, PIT or coverage semantics;
- change deterministic investment math;
- add Cloudflare storage, Web UI or Phase 6 event monitoring;
- implement Tunnel/Access inside Turtle;
- add trading, order, cancellation, transfer or other state-changing financial operations;
- make Futu a mandatory deterministic-engine dependency.

Stop after the actual M2-C outcome is recorded and the next handoff is prepared.

## 11. M2-C execution record — 2026-09-17

Outcome: **`FUTU_SELECTED`**.

M2-C1 is complete. The implementation adds the optional/lazy Futu SDK boundary in
`src/turtle_value_engine/historical/futu_opend.py`, registers the adapter and decoder at
the networked acquisition boundary, explicitly sends daily `K_DAY` plus unadjusted
`AuType.NONE`, checks history quota when the client exposes it, bounds pagination and
date ranges, closes the OpenD context, and freezes the decoded SDK result as the
non-wire `futu-opend-sdk-export-v1` provider envelope before offline `MARKET_BAR`
compilation. Required listing identity, date/time, OHLC, volume, turnover, duplicate-date,
schema and secret-boundary checks fail closed. The fake-client suite covers the required
diagnostics and deterministic replay paths.

M2-C2 used the genuine owner OpenD runtime at `127.0.0.1:11111`. OpenD reached Ready
after the owner completed the API questionnaire/agreement flow. The installed SDK was
`futu-api 10.10.7008`; the runtime returned 3,790 Hong Kong stock rows from
`get_stock_basicinfo`, including the exact accepted/returned H identity `HK.00001`.
The quota check returned `used=0`, `remaining=100` before the bounded probe. The two
non-overlapping live windows both returned three usable daily rows with matching identity,
explicit `K_DAY` and explicit unadjusted `AuType.NONE`:

```text
recent: 2026-09-15..2026-09-17 -> PASS, HK.00001, 3 rows
older:  2025-09-15..2025-09-17 -> PASS, HK.00001, 3 rows
```

The private evidence is intentionally outside Git:

```text
.tve-private/live/futu-h-recent-20260915-17.json
  response_sha256=ee75f454b86aaf98e71b1bedff4443e743a97d7d67b1ca52d2da817e33d94be2
.tve-private/live/futu-h-older-20250915-17.json
  response_sha256=02d2aff0e038a4344fdf87249707a9c8635f79408bb5390fec492078b1f1549d
.tve-private/batches/futu-h-recent-20260915-17.json
  batch_id=batch-d1ef177190b7cd1f25870315fb15af7b
.tve-private/raw/futu-h-recent-20260915-17/
  provider envelope sha256=ee75f454b86aaf98e71b1bedff4443e743a97d7d67b1ca52d2da817e33d94be2
  representation=futu-opend-sdk-export-v1, rows=3, quota_remaining=99
.tve-private/manifests/futu-h-recent-20260915-17.json
  dataset_id=dataset-b27e7ffc96bf7de78055d5bd3774b897
  manifest_sha256=e1aac2fd22350d0898bb718a68febb558a4ba35638cf504a1e038f15787a341b
  MARKET_BAR shard_sha256=6b4708a74530f5de9bba0fc2dcfe98337976c92a6565cb9feaa5b537e2bc3a62
```

The bounded acquire froze the complete decoded SDK export in private raw CAS; offline
compile with `--verify-replay` exited successfully and produced three canonical
`MARKET_BAR` rows. The resulting readiness report remains `NOT_READY` for the broader
dataset because this goal does not provide membership, lifecycle, terminal, corporate
action, benchmark/FX, filing or source-terms completeness. That fail-closed result is
expected and does not negate the bounded price-source selection.

Futu is selected only for the bounded H daily unadjusted `MARKET_BAR` personal-research
role. The broader `H_SOURCE_UNQUALIFIED`/coverage blockers remain for claims outside this
role. M2-D is not implemented or started. The next handoff is **M3 A-share
lifecycle/calendar automation**.
