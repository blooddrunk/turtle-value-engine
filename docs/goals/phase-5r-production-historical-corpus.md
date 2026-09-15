# Phase 5R — Production Historical Dataset and Research Archive Readiness

Status: **ACTIVE**

## Objective

Turn the completed Phase 5 frozen synthetic/integration boundary into a
defensible, replayable historical-data and historical-research boundary. The
work is scoped to a named A/H target universe and date range; it must not claim
that the whole A/H market is production-ready without source and coverage
evidence for that exact scope.

Phase 5 remains complete at its documented integration boundary. Phase 5R is
additive: it introduces source, coverage, shard, compiler and research-archive
contracts without changing `strict-v1`, deterministic investment semantics,
or the Phase 5 signal/portfolio/calibration rules.

## Declared target and conservative claim policy

The implementation must carry a declared target scope containing:

- a stable target-universe identifier and human-readable name;
- A-share and H-share listing identity scope;
- inclusive start and end dates;
- the intended historical membership claim and required source categories.

The initial repository corpus is a compact, offline contract/acceptance corpus.
It is not a production A/H-market claim unless authoritative source identity,
licensing/redistribution conditions, membership intervals and measurable
coverage are persisted. Unknown, partial, date-only and otherwise incomplete
coverage remains explicit and fails closed for production claims.

## Work packages and measurable deliverables

### A. Source registry and production coverage contract

- Add typed, persisted source descriptors for universe membership, listing
  lifecycle/delistings, prices, corporate actions, benchmarks, FX, filings and
  archived research.
- Persist provider/source identity, authority, query parameters, retrieval
  time, source version where available, coverage dates, content hashes and
  licensing/redistribution constraints.
- Add named target scope, per-listing/per-period coverage reports and a
  validator that requires source-backed membership evidence for any historical
  or survivorship-bias-free claim.

### B. Scalable frozen dataset layout

- Add a backward-compatible content-addressed artifact/shard boundary. Each
  shard reference includes format, schema version, content hash, row count,
  date range, listing scope and source artifact identity.
- Provide deterministic offline readers and validators that fail on missing or
  mismatched shards and never fetch data implicitly.
- Keep Git fixtures compact and document the storage/format decision.

### C. Historical A/H universe and listing lifecycle

- Implement a bounded vertical slice with A/H listing identities, economic
  company mapping, listing dates, terminal dates/statuses, calendars,
  currencies, membership intervals and symbol/code changes.
- Preserve delisted and terminal listings. Distinguish delisting,
  acquisition/cancellation, transfer, prolonged suspension and unresolved
  terminal outcomes.
- Never synthesize a terminal value; unresolved terminal economics are invalid
  or manual-review outcomes, with per-listing and per-period coverage reports.

### D. Market/action/benchmark/FX reconciliation

- Compile cached bars, explicit corporate actions, listing calendars, FX and
  benchmark observations into Phase 5-compatible replay inputs.
- Preserve the unadjusted-price-plus-actions versus adjusted-price semantics;
  reject double counting, fabricated fills and silent repairs.
- Persist an independent-reference reconciliation report with tolerances,
  comparison rows and discrepancies.

### E. Frozen historical research archive

- Add a typed archive manifest for Phase 4 evidence packets, research tasks,
  analyst runs, Business Quality results, research reports, filings and
  adjustment/document artifacts.
- Preserve point-in-time availability, source/document hashes, filing identity,
  page/section locators and review status. Validate every decision-to-research
  reference at its decision time.
- Historical backtests must use frozen validated Business Quality artifacts;
  no live model reconstruction is permitted. Missing archives retain
  `NOT_EVALUATED`, WATCH or manual-review semantics.

### F. Compiler, workspace and thin CLI

- Add offline compiler/validator APIs and thin CLI commands for freezing from
  acquired cache, validating references and PIT availability, reporting
  coverage/reconciliation, projecting decision snapshots, running the existing
  offline backtest and calibrating only against an explicit frozen manifest and
  search space.
- Reject dangling IDs, unrelated availability records, missing hashes and
  cross-artifact mismatches. Keep networked acquisition separate.

### G. Frozen real-data and adversarial acceptance

- Add compact fixtures/tests for membership changes, later listings, A/H
  economic-company mapping, code changes, terminal listings, suspensions,
  actions, missing shards/hashes, incomplete coverage, availability failures,
  archived BQ, hindsight rejection, reconciliation and byte-equivalent replay.
- Prove `strict-v1` byte identity and ordinary CI's lack of live provider/model
  dependencies.

### H. Documentation and closure

- Keep the README concise and Chinese-first, with a workflow only after it is
  executable. Update agent and architecture documentation and add the next
  Phase 6 goal only after Phase 5R closure.
- Mark this goal COMPLETE only when the declared target scope satisfies every
  exit criterion. Otherwise keep it ACTIVE/PARTIAL and record the precise
  source, access-right or redistribution blocker and the smallest decision
  required to proceed.

## Exit criteria

1. A named, bounded A/H target universe and date range are declared.
2. Membership and listing lifecycle data have provenance and measurable
   coverage.
3. Delisted/terminal listings are retained and unknown terminal economics fail
   closed.
4. Bars, actions, FX and benchmarks are replayable and cross-referenced.
5. Real-data returns are reconciled to an independent reference sample.
6. Historical research artifacts are frozen, point-in-time-valid and never
   reconstructed by a live model during backtest.
7. Large data uses verified content-addressed artifacts/shards rather than a
   single embedded JSON payload.
8. The compiler rejects missing, mismatched and dangling artifacts.
9. Frozen inputs reproduce identical structured outputs and hashes offline.
10. Coverage and missingness are reported, never silently repaired.
11. `strict-v1` remains byte-identical and calibration emits proposals only.
12. `python -m ruff check .` and the full offline test suite pass (or the
    available equivalent is recorded if the `python` executable is absent).

## Current known limitation

At activation, the repository has Phase 5 synthetic/provider-snapshot
fixtures but no verified, redistributable authoritative A/H historical corpus
covering a market-wide target. Implementation may therefore close the replay
and validation boundary while retaining a clearly documented partial/blocked
production claim until source access and coverage evidence are established.

## Current implementation review — ACTIVE / PARTIAL

The source-aware contracts, content-addressed JSONL store, offline compiler,
coverage/reconciliation reports, frozen research-archive PIT validator, CLI and
adversarial acceptance tests are implemented. The declared checked-in target is
`fixture-ah-2020` in universe `fixture-ah`, listings `A1` and `H1`, with date
range `2020-01-01` through `2020-01-03`. It is explicitly
`FIXED_RESEARCH_UNIVERSE` and `PARTIAL`.

The compact corpus currently declares target `fixture-ah-2020` in universe
`fixture-ah`, with A1 and H1 listings over 2020-01-01 through 2020-01-03. It
proves 2 listing lifecycles, 2 membership intervals, 6 market rows, 2
corporate actions, 1 suspended session, 1 delisted terminal listing with no
fabricated terminal value, 1 frozen archive reference, and a 2-row
independent-reference reconciliation that passes its fixture tolerance. These
are replay/contract metrics, not market-wide coverage metrics.

The remaining production blocker is precise: this repository does not contain
an authoritative, licensed and redistributable A/H historical source corpus
with complete membership, lifecycle, price/action, benchmark, FX and filing
coverage for a declared market-wide target. The compiler therefore reports
`production_eligible=false` and `--require-production` fails closed. The
smallest decision needed for closure is a bounded source/access/licensing
choice (or an explicitly narrower target for which those artifacts and
coverage reports can be supplied). Phase 5R remains ACTIVE until that choice
and evidence exist; the Phase 6 goal file is intentionally not created yet.

### Source-access review — 2026-09-15

The official source pages reviewed during this goal establish authority and
availability, but do not by themselves establish repository redistribution
rights:

- [HKEX historical data marketplace](https://www.hkex.com.hk/Services/Market-Data-Services/Historical-Data-Services/HKEX-Data-Marketplace?sc_lang=en)
  and [HKEX market-data FAQ](https://www.hkex.com.hk/Global/Exchange/FAQ/Market-Data/Getting-Market-Data?sc_lang=en)
  describe subscription products and separate licensing/redistribution
  arrangements.
- [SSE service guidance](https://www.sse.com.cn/transparency/services/)
  directs market institutions to product authorization, licensing and fee
  materials; public availability is not treated as open redistribution.
- [HKEXnews archive disclaimer](https://www.hkexnews.hk/listedco/listconews/mainindex/sehk_dw_datetime_today_c.htm)
  states that copyright may belong to HKEX, the issuer or another party.

Accordingly no downloaded market, index or filing content was promoted into a
production fixture, and no source was marked `OPEN_REDISTRIBUTABLE` from these
pages alone. The smallest closure decision is either (a) supply a bounded
licensed cache plus its permission/redistribution evidence, or (b) explicitly
narrow the target and accept an internal-only source scope. Until then the
checked-in corpus remains an acceptance fixture.
