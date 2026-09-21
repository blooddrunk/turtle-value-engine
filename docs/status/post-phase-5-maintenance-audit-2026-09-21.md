# Post-Phase-5 maintenance audit — 2026-09-21

Status: **ENGINEERING READINESS ACCEPTED FOR PERSONAL RESEARCH / STRICT PHASE 5R A6 STILL ACTIVE-PARTIAL**

Audited baseline: `main@502c5c60f9ee501d04c944698d24873e6d77037b`

Baseline GitHub Actions: run `35558610338` — `success`.

## 1. What this audit means

The original post-Phase-5 maintenance package became Phase 5R / Phase 5R-A.
Its purpose was to move Phase 5 beyond a synthetic integration corpus toward
real, replayable, source-aware historical data and frozen historical research.

Two claims must now be kept separate:

1. **Personal-research engineering readiness** — the repository has the
   acquisition/replay/compiler/storage/reconciliation/read-surface machinery
   needed to continue useful private research and monitoring work.
2. **Strict Phase 5R `PRODUCTION_ELIGIBLE` / A6 closure** — a real declared
   A/H corpus satisfies every Phase 5R exit criterion across historical
   membership/lifecycle, terminal economics, market/actions, benchmark/FX,
   frozen research and independent acceptance evidence.

The first claim is accepted. The second claim is not.

Do not describe the whole Phase 5R goal as COMPLETE, and do not use the pending
A6 claim as a blanket blocker for Phase 6 personal-research monitoring.

## 2. Evidence accepted

The repository now has, with deterministic/offline coverage where applicable:

- Phase 5 frozen PIT backtesting/calibration closed on main;
- Phase 5R source-aware manifests, verified content-addressed JSONL shards,
  compiler/validator, coverage/missingness/reconciliation reports and
  point-in-time historical research-archive validation;
- Phase 5R-A acquisition contracts, explicit network authorization,
  credential isolation, immutable raw CAS, batch receipts, deterministic
  compile/replay and fail-closed A6 audit;
- owner-authorized bounded A-share Hithink acquisition/replay;
- bounded BaoStock lifecycle/calendar acquisition/replay;
- deployment-neutral FQGate transport and a selected bounded Futu H-share
  history source path, without making either source authoritative beyond the
  evidence actually recorded;
- sampled cross-source price reconciliation at the documented M4 partial
  boundary;
- local and S3-compatible artifact-mirror layers;
- the read-only research surface/API, private authenticated Dashboard and
  Chinese-first presentation layer;
- Phase 6-A offline watchlist/event/state/cursor/reanalysis-planning foundation,
  with automated duplicate/PIT/cursor/atomicity/replay checks;
- green current-main CI for the Phase 6-B planning baseline.

These items establish that the project no longer needs another generic
"historical infrastructure" maintenance package before continuing bounded
personal research.

## 3. What is still not closed

Strict Phase 5R/A6 remains `ACTIVE / PARTIAL` because the repository still
does not have one real declared private A/H corpus that proves the complete
Phase 5R acceptance surface.

The remaining strict claim must continue to fail closed where evidence is
missing, including as applicable:

- complete point-in-time historical A/H membership and lifecycle coverage;
- terminal/delisting economics for affected listings;
- complete corporate-action coverage needed by the claimed return model;
- target-spanning benchmark and FX evidence;
- frozen historical filing/research coverage sufficient for the claimed
  Business Quality decisions;
- independent real-data reconciliation for the declared target;
- one final A6 acceptance over the actual declared corpus.

These are corpus/evidence blockers, not missing generic framework code. Do not
answer them by weakening `--require-production`, inventing current-constituent
history, reconstructing historical Business Quality with a live model, or
requiring the owner to manually assemble CSVs.

## 4. Current next package

The selected next functional package remains:

**Phase 6-B — Opt-in Live Event Acquisition and Canonicalization**

Source of truth:

`docs/goals/phase-6-b-live-event-acquisition.md`

The goal is to connect real, explicitly authorized source acquisition to the
already-frozen Phase 6-A event boundary, beginning with a narrow official
filing/disclosure source when a current bounded contract can be verified.

The companion `blooddrunk/fqgate-remote-bridge` remains an additive future
source candidate. Turtle must not wait for it and must not hard-code Bridge
semantics until the Bridge publishes a typed, bounded, read-only event/history
operation with its own compatibility and live-machine evidence.

## 5. Verification policy for Codex

Codex must perform every machine-verifiable acceptance step itself.

Before edits:

1. fast-forward `main` only and keep owner changes intact;
2. record clean/dirty status, HEAD and remotes;
3. discover the permanent owner test root under
   `D:\\code\\research` / `/mnt/d/code/research` and use it when an
   actual checkout exists;
4. verify green GitHub Actions for the exact baseline SHA;
5. run the baseline repository gates.

During Phase 6-B, automate at minimum network deny-by-default, bounded request
limits, malformed/timeout/oversized-source handling, exact listing/source
scope, deterministic provenance and canonicalization, ambiguous-disclosure
fail-closed behavior, PIT filtering, ordering, duplicate idempotence,
conflicting-duplicate failure, restart/offline replay, and the invariant that
fetch/canonicalization alone never moves a committed cursor.

After implementation:

1. run all focused Phase 6-B tests;
2. run `python -m ruff check .` and the complete `python -m pytest` suite;
3. run every generated-contract/Dashboard gate enforced by current CI;
4. when technically possible, execute the bounded live-source probe,
   canonicalization, offline replay and Phase 6-A commit path automatically;
5. push and verify green GitHub Actions for the exact closing commit.

Human intervention is allowed only for a genuine upstream boundary that
automation cannot safely complete, such as CAPTCHA, interactive login or
consent. In that case the handoff must state the exact pre-step command, exact
human action, secret/logging boundary, exact resume command, expected
machine-verifiable success result and exactly what remains unverified.

Phrases such as "manual verification recommended", "evidence incomplete" or
"needs owner confirmation" are not closure evidence by themselves.
