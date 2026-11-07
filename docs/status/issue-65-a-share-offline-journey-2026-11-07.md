# Issue #65 — A 股离线个人研究全流程可用性收口（2026-11-07）

Status: implemented; awaiting the one natural exact-head PR CI run.

## Baseline

- Baseline `main` SHA: `73b4be10e434ee5a17de4ac9fc59b7ef772fefa8`
  (fast-forward synchronized; working tree clean).
- Phase 7 remains engineering-complete through C4-D; nothing in Phase 7 was
  reopened and no owner approval was manufactured.

## Gate A — journey reproduction and gap selection (no edit first)

The existing A-only offline path was exercised end-to-end on pristine main
from the repository root with the frozen synthetic A-share fixture
`fixtures/healthy_cash_cow.json` (`SH600001`):

| Step | Command (baseline) | Result |
| --- | --- | --- |
| analyze | `tve analyze --input fixtures/healthy_cash_cow.json --profile strict-v1 > analysis.json` | exit 0; `SPECIAL_REVIEW`; `business_quality=NOT_EVALUATED` (expected fail-closed states) |
| surface build | `tve surface build --analysis analysis.json --output snapshot.json` | exit 0; `decision_trace_reference=null`, `research_report_reference=null` |
| surface validate | `tve surface validate --input snapshot.json` | exit 0 |
| surface serve | `tve surface serve --snapshot snapshot.json --port 8791` + `/healthz`, `/v1/surfaces`, `/v1/surfaces/{id}`, POST→405 | all pass |

Inventory comparison against existing coverage
(`scripts/dashboard_cross_stack_smoke.py`, `tests/test_research_surface.py`,
`tests/test_surface_api.py`, `tests/test_cli.py`, `tests/test_analyze.py`)
isolated **exactly one** material operator gap:

- `tve surface build --trace/--report` consumes `decision_trace_v1` and
  `research_report_v1` JSON files, and the Dashboard renders both references,
  but **no CLI command could produce those files** — `build_decision_trace`
  and `compose_report` were library-only. Every operator-built snapshot
  therefore carried null trace/report references (reproduced above), and the
  README quick start ended at shell redirection with no path to the product
  surface. The only full chain (analyze→trace→report→snapshot) existed
  inside the monitoring executor library, not as an operator journey.

This is a bounded usability gap, not an investment-semantics change.

## Gate B — smallest coherent fix

1. `tve analyze` (existing command, no new command) gained three additive
   optional flags: `--output` (CompanyAnalysis), `--trace-output`
   (`decision_trace_v1`), `--report-output` (`research_report_v1`). They are
   pure deterministic projections of the already-computed analysis
   (`build_decision_trace` / `compose_report` frozen boundaries); no new
   investment math, no network, no defaults — nothing is written unless a
   path is explicitly supplied and stdout behavior is unchanged. Colliding
   output paths fail closed before any write.
2. Serialization preserves model-construction key order (the `tve prepare
   --output` convention) because `tve surface build`'s trace-equality check
   is list-order sensitive; sorted canonical serialization would make the
   reparsed analysis produce a mismatched trace (verified during
   implementation). Cross-process ordering stability was proven under
   varying `PYTHONHASHSEED` (1/2/3/101/102/103).
3. New Chinese-first operator runbook
   `docs/operations/a-share-offline-research-journey.md` chains the verified
   journey (analyze → surface build → validate → serve/Dashboard) with
   result interpretation (`SPECIAL_REVIEW`/`NOT_EVALUATED`), fail-closed
   notes and explicit non-claims; README quick start and
   `docs/architecture/agent-api-web-surface.md` link it; AGENTS.md records
   the additive boundary.
4. `tests/test_offline_journey_cli.py` proves the full CLI chain
   (analyze with three artifacts → surface build with `--trace/--report` →
   validate → byte-identical replay) plus the colliding-path fail-closed
   rejection, socket-guarded. **Both tests were executed against pristine
   baseline `73b4be1` first and failed** (argparse: unrecognized arguments),
   then passed after the fix.

## Verification

- Baseline-red proof: 2/2 new tests fail on `73b4be1`; pass on the branch.
- `python -m ruff check .` — clean.
- Targeted: `tests/test_offline_journey_cli.py tests/test_cli.py
  tests/test_analyze.py tests/test_research_surface.py tests/test_surface_api.py`
  — 33 passed.
- Full suite: 7797 passed / 2 skipped (this branch; includes the 2 new tests).
- `python -m turtle_value_engine config validate --input
  config/project.example.toml` — valid, `default_profile: strict-v1`.
- `scripts/dashboard_cross_stack_smoke.py` on the branch tree — passed.
- Dashboard suite (`apps/dashboard`, vitest) — 55/55 passed.
- Protected artifacts byte-identical to baseline (sha256, first 16 hex):
  `rules/strict-v1.yaml` `e3618f78b2f8e4d1`, `rules/strict-v2.yaml`
  `adba44b799fdb42a` (equals the published release manifest
  `release_profile_sha256`), `docs/releases/strict-v2/release-candidate.json`
  `604226f405fe0330`, `config/project.example.toml` `9c621217285ade01`,
  `config/monitoring-runner.example.json` `c81008c9886326ae`.
- Exact-head PR CI: recorded in the PR description (single natural run).

## Changed files

- `src/turtle_value_engine/cli.py` — additive analyze output flags + helper.
- `tests/test_offline_journey_cli.py` — new journey regression (red-first).
- `docs/operations/a-share-offline-research-journey.md` — new runbook.
- `README.md`, `docs/architecture/agent-api-web-surface.md`, `AGENTS.md` —
  links/boundary notes.

## Residual risks / non-claims

- The snapshot's `historical_status.claim_state` remains `NOT_AVAILABLE`;
  this is a personal-usability milestone, not a Phase 5R/A6
  `production_eligible` claim.
- `strict-v2` remains published but not default and not applied; no owner
  decision, signature or activation was created or simulated.
- Trace/report artifacts are deterministic projections bound to their exact
  analysis run; hand-edited or re-serialized (e.g. sorted-key) analysis files
  are rejected by `tve surface build` by design.
- No H-share expansion, provider endpoint sweep, brokerage/trading,
  Cloudflare deployment change, or live credential access occurred.

## Human-only boundary

None required for this milestone. Real `tve prepare` network acquisition,
strict-v2 policy acceptance (owner key/signature/activation) and any
production deployment remain outside Issue #65.
