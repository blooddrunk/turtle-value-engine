# Phase 5R-A M2-E — H-share Source Selection Record

Status: **COMPLETE / `H_PRICE_SOURCE_SELECTED_FUTU`**  
Date: 2026-09-17  
Baseline: `78f3f5801f269f4757e3f1fb7c8a29139641bbd3`  
Parent goal: `docs/goals/phase-5r-a-m2-h-share-history-source-selection.md`  
Machine-readable record: `docs/status/phase-5r-a-m2-e-h-share-source-selection.json`

## 1. Decision

M2 closes with exactly one bounded H-share price-source selection state:

```text
H_PRICE_SOURCE_SELECTED_FUTU
```

Futu OpenD is selected as the **primary bounded personal-research H daily unadjusted
`MARKET_BAR` source**. This is a planning/source-acquisition status only. It is not an
investment-engine state and does not change `strict-v1`, A6, point-in-time semantics,
historical coverage semantics, deterministic calculations, gates, valuation, or existing
provider compatibility.

M2-D AKShare/Eastmoney remains gated and was not implemented. No new provider was added
merely to manufacture an independent comparison.

## 2. Evidence retained by the selection record

The selection record projects only non-secret facts already earned by M2-C owner-runtime
evidence. The underlying plans, probe reports, provider envelopes, raw CAS, batches and
manifests remain under `.tve-private/` and are not committed.

Observed runtime and source identity:

```text
OpenD version:       10.11.7108
OpenD endpoint:      127.0.0.1:11111
futu-api version:    10.10.7008
H runtime identity:  HK.00001
representation:      futu-opend-sdk-export-v1
```

The provider representation is a deterministic decoded SDK export, not raw OpenD wire
bytes.

Quota/permission evidence before the bounded probes:

```text
history quota used:       0
history quota remaining:  100
```

Both owner-runtime history requests succeeded. That proves usable permission for these
bounded requests; it is deliberately not generalized into an account-wide entitlement or
market-wide coverage claim.

## 3. Verified windows

Both probes explicitly used daily `K_DAY` and unadjusted `AuType.NONE` semantics with the
same runtime identity:

```text
2026-09-15..2026-09-17 -> PASS, HK.00001, 3 rows
2025-09-15..2025-09-17 -> PASS, HK.00001, 3 rows
```

The recent probe/provider envelope SHA-256 is
`ee75f454b86aaf98e71b1bedff4443e743a97d7d67b1ca52d2da817e33d94be2`; the older
probe response SHA-256 is
`02d2aff0e038a4344fdf87249707a9c8635f79408bb5390fec492078b1f1549d`.

## 4. Bounded acquire and replay identity

Only after both windows passed, the recent bounded plan completed:

```text
acquire
  -> private CAS / futu-opend-sdk-export-v1 provider envelope
  -> offline compile
  -> --verify-replay
```

Recorded identities:

```text
batch_id:                batch-d1ef177190b7cd1f25870315fb15af7b
dataset_id:              dataset-b27e7ffc96bf7de78055d5bd3774b897
manifest_sha256:         e1aac2fd22350d0898bb718a68febb558a4ba35638cf504a1e038f15787a341b
MARKET_BAR shard_sha256: 6b4708a74530f5de9bba0fc2dcfe98337976c92a6565cb9feaa5b537e2bc3a62
canonical MARKET_BAR:    3 rows
verify replay:           PASS / identity-equivalent
quota remaining:         99
```

These identifiers make the selection decision auditable without committing the private
provider bytes or live artifacts themselves.

## 5. Reconciliation decision

No second independent H source has a successful, replayable bounded result in the current
repository evidence. Therefore M2-E performs **no cross-source reconciliation**. The
existing historical reconciliation contract remains the required mechanism if a genuine
independent source is available later; discrepancies must remain explicit and must never
silently rewrite canonical price rows.

FQGate's earlier bounded H probes failed with evidence-supported but cause-unclassified
HTTP 504/provider-code results, so they are not a second successful source. M2-D is not
started merely to create a comparison.

## 6. Explicit limitations

`H_PRICE_SOURCE_SELECTED_FUTU` proves only the bounded role stated above. It does **not**
establish or imply:

- a complete or market-wide H historical corpus;
- historical universe membership or survivorship-free coverage;
- listing lifecycle, code changes, delisting retention, prolonged suspension handling, or
  terminal economics;
- corporate-action completeness;
- benchmark or FX completeness;
- filing or historical research archive completeness;
- complete source-category/date/listing coverage;
- authoritative redistribution rights, complete source terms, or production eligibility.

Those broader claims remain fail-closed under the existing Phase 5R/A6 contracts. The
bounded price-source success narrows one acquisition gap; it does not satisfy the broader
historical acceptance claim.

## 7. Scope confirmation

M2-E introduces no changes to provider implementation, historical schemas, acquisition
semantics, canonical `MARKET_BAR`, coverage evaluation, PIT validation, A6 acceptance,
`strict-v1`, deterministic investment math, or provider compatibility.

This package does not implement M2-D, AKShare/Eastmoney, H/A lifecycle reconstruction,
corporate actions, Phase 6, Cloudflare/R2, Tunnel/Access, Web UI, trading, orders, transfers
or any state-changing financial operation.

## 8. Verification

Required repository verification for this documentation/status package:

```bash
python -m ruff check .
python -m pytest
```

The CI result is recorded in the dated status after the branch verification completes.

## 9. Next handoff

M2 is closed. The next repository-defined milestone is **M3 — A-share lifecycle/calendar
automation** from `docs/goals/phase-5r-a-local-research-and-low-cost-sources.md`, to be
executed as a separate package. M3 is not implemented as part of M2-E.
