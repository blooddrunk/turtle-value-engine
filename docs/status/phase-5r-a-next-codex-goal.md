# Codex Goal — Phase 5R-A M2-B Bounded H-share FQGate Selection Probe

Work in repository `blooddrunk/turtle-value-engine` on current `main`.

Read and follow, in source-of-truth order:

- `AGENTS.md`
- `docs/spec/`
- `rules/strict-v1.yaml`
- `schemas/`
- `docs/architecture/`
- `docs/goals/phase-5r-a-m2-h-share-history-source-selection.md`
- `docs/goals/phase-5r-a-m2-t-fqgate-endpoint-transport.md`
- `docs/status/phase-5r-a-2026-09-17.md`
- `docs/operations/phase-5r-a-acquisition.md`
- `src/turtle_value_engine/historical/fqgate.py`
- `src/turtle_value_engine/historical/acquisition.py`
- relevant compiler/replay tests and CLI code

Current baseline facts:

- `main` includes M2-T at `2ee554daba24d988de38d348137b7a0a31c56e69`.
- M2-A diagnostic hardening is complete.
- M2-T deployment-neutral FQGate transport is complete at the Turtle-side contract boundary.
- Full-suite M2-T verification recorded: `6212 passed, 2 skipped`; ruff passed.
- FQGate A-share bounded history previously succeeded for `USHA/600000` and `USZA/000001`.
- Owner-observed H candidate `UHKM/HK0700` has not yet produced successful historical rows.
- H source state remains `H_SOURCE_UNQUALIFIED`.
- `blooddrunk/fqgate-remote-bridge` has closed its own Phase 3 local upgrade/OpenAPI milestone, but Tunnel/human Access is planned for its Phase 4 and machine-authenticated read-only remote HTTP API for its Phase 5. Therefore `REMOTE_BRIDGE_LIVE_UNPROVEN` remains correct. Do not wait for remote bridge work; use `LOCAL_DIRECT` for M2-B unless the repository contains newer proven contracts when you run.

Implement **only M2-B**. This goal is primarily an evidence-gathering and source-selection gate, not a provider-expansion task.

## Objective

Determine whether FQGate can earn a bounded H-share `MARKET_BAR` source role using the exact H identity observed from the owner's actual FQGate environment.

Use the existing owner-observed candidate `UHKM/HK0700` only as a candidate to probe. Do not generalize it into a universal H market mapping and do not invent or substitute another identifier unless it is independently observed from the running owner environment and recorded as such.

## Required execution path

1. Inspect the current implementation/docs and confirm no contract drift since M2-T.
2. Keep ordinary CI fully offline.
3. For live evidence, use `LOCAL_DIRECT` against the owner's running FQGate only with explicit `--network=allow` and private plans/artifacts under `.tve-private`.
4. Probe the exact observed H identity in **two non-overlapping bounded windows**:
   - one recent window;
   - one older historical window at least one year earlier.
5. Classify every result conservatively using the completed M2-A/M2-T diagnostics. Do not reinterpret generic timeout/HTTP failures as a more specific provider cause without evidence.
6. If and only if both windows succeed with a supported success envelope and unadjusted daily rows, perform one bounded acquisition followed by offline compile and `--verify-replay`.
7. Persist only redacted capability conclusions/status in Git. Private live plans, raw bytes, receipts and reports stay under `.tve-private` and must not be committed.

Suggested command shapes (adapt exact private file names as needed):

```bash
tve historical source probe \
  --plan .tve-private/plans/fqgate-h-recent.json \
  --network=allow \
  --output .tve-private/live/fqgate-h-recent.json

tve historical source probe \
  --plan .tve-private/plans/fqgate-h-older.json \
  --network=allow \
  --output .tve-private/live/fqgate-h-older.json
```

If both probes succeed:

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

## Decision rules

### A. Select FQGate only when all of these are true

- exact H market/code was observed rather than inferred;
- both recent and older bounded history probes succeed;
- returned data is supported, unadjusted daily history;
- bounded acquisition preserves raw CAS/receipt/provenance;
- offline compile + `--verify-replay` is deterministic;
- any coverage conclusion is limited to what the observed evidence actually proves;
- lifecycle, historical membership, delistings, terminal economics and corporate actions remain separately unqualified.

When these criteria are met:

- mark M2-B complete and FQGate selected for the bounded H `MARKET_BAR` role;
- update the M2 source-selection goal/status with the evidence boundary;
- advance to M2-E selection record / the next historical milestone appropriate to the repository roadmap;
- do **not** implement M2-C or M2-D merely for redundancy in the same goal.

### B. Advance to M2-C only on evidence-supported FQGate failure

If the owner's live FQGate environment is available and the required exact probes are actually executed, but FQGate still fails to earn the bounded H role because of an evidence-supported route/provider/schema/no-row/coverage outcome, then:

- record the exact blocker and observed scope;
- keep H capability fail-closed;
- update the handoff so M2-C (Futu OpenD candidate) becomes next;
- do not weaken acceptance criteria or silently switch providers during M2-B.

### C. Do not treat runner/environment limitations as provider failure

If Codex cannot access the owner's local FQGate, no valid FQGate login/session is available, localhost is outside the execution environment, or another environment limitation prevents a real live probe:

- do **not** mark FQGate unqualified based on that limitation;
- do **not** advance to M2-C solely because the Codex runner lacks owner-local access;
- record M2-B as `BLOCKED_ON_OWNER_LIVE_PROBE` (or equivalent wording in docs, no new public schema required);
- provide exact commands/private-plan guidance for the owner to run locally;
- keep the next source decision pending actual live evidence.

A historical old timeout, fake transport success, remote-bridge roadmap state, runtime API docs, or absence of CI network access is not M2-B source-selection evidence.

## Code-change policy

M2-B may be documentation/live-evidence only. Do not change code unless the live probe exposes a genuine bug in the already-approved acquisition/decoder/replay boundary.

If a code fix is needed:

- keep it minimal and additive;
- preserve legacy adapter/receipt/batch compatibility;
- do not change `strict-v1`, CDC, Net Cash, Through Return, hard gates, valuation, A6, PIT or coverage semantics;
- add offline regression tests for the bug;
- rerun the full suite.

## Verification

At minimum, rerun the relevant offline regression suite after any code or contract-document change:

```bash
python -m pytest tests/test_fqgate_historical.py -q
python -m pytest tests/test_phase_5r_acquisition.py -q
python -m ruff check .
python -m pytest
```

Do not regress below the current `6212 passed, 2 skipped` baseline except for an explicitly documented intentional replacement.

## Documentation requirements

Before completion, update as applicable:

- `docs/status/phase-5r-a-2026-09-17.md` (or a new dated successor if material new live evidence is obtained);
- `docs/goals/phase-5r-a-m2-h-share-history-source-selection.md` with M2-B result and next gate;
- `docs/status/phase-5r-a-next-codex-goal.md` so it points to the true next package rather than this completed one;
- `docs/operations/phase-5r-a-acquisition.md` only if a real operational contract changed.

Do not commit `.tve-private` artifacts, credentials, raw provider responses, session material or secrets.

## Non-goals

Do not in this goal:

- implement Futu OpenD (M2-C) unless M2-B is actually completed with an evidence-supported FQGate failure and the repo's written next-handoff is being prepared; even then, stop before implementation and hand off M2-C separately;
- implement AKShare/Eastmoney (M2-D);
- reconstruct H historical membership/lifecycle/delistings/actions;
- add Cloudflare storage, Web UI, Phase 6 event monitoring, trading or state-changing financial operations;
- implement Tunnel/Access in Turtle;
- claim remote FQGate live support while remote-bridge lacks the frozen machine API contract;
- infer H capability from catalog presence, docs, a single successful recent window, or row count alone.

The correct result of this goal may be one of three outcomes: **FQGate selected**, **FQGate evidence-supported failure -> M2-C next**, or **BLOCKED_ON_OWNER_LIVE_PROBE**. Preserve that distinction exactly.
