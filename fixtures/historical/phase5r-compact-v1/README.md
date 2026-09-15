# Phase 5R compact historical replay corpus

This Git fixture is a small, deterministic contract and adversarial replay
corpus. It contains both A/H listing identities for one economic company, a
historical code change, a later/terminal H listing, a suspended price session,
dividend and split actions, listing-specific FX, an explicit price-return
benchmark, a frozen research-archive reference, and an independent-reference
reconciliation sample.

The rows are acceptance fixtures assembled from repository snapshots. They are
not asserted to be authoritative market history, are not a claim of complete
A/H coverage, and carry `FIXTURE`/`UNKNOWN` authority and licensing metadata.
Use a separately acquired, licensed source artifact to make a production
claim. The manifest is intentionally `FIXED_RESEARCH_UNIVERSE` with `PARTIAL`
coverage so `--require-production` fails closed.

Replay from the repository root:

```bash
tve dataset validate \
  --manifest fixtures/historical/phase5r-compact-v1/manifest.json \
  --store fixtures/historical/phase5r-compact-v1/store
tve dataset freeze \
  --manifest fixtures/historical/phase5r-compact-v1/manifest.json \
  --store fixtures/historical/phase5r-compact-v1/store \
  --output /tmp/phase5r-backtest-manifest.json
```

The store is content-addressed JSONL. Missing or modified shard bytes are
errors; no network fallback is permitted.
