# Phase 6-F-R4 post-closure review / Phase 7-A selection — 2026-09-30

Status: **R4 ACCEPTED; NO R5 BLOCKER FOUND; PHASE 7-A SELECTED**

Reviewed repository head: `0ea000a7c9aba74821b7206f899321429112489a`

Reviewed R4 implementation: `a09b9c101b6f7c7d0800fd844450652fbcfd19dc`

Canonical R4 closure:
`docs/status/phase-6-f-r4-2026-09-29.md`

Selected next goal:
`docs/goals/phase-7-a-controlled-evolution-evaluation-foundation.md`

Coding-agent handoff:
`docs/status/phase-7-a-next-coding-agent-goal.md`

## 1. R4 acceptance result

The post-closure audit found no blocking implementation defect that justifies a
Phase 6-F-R5.

The R4 implementation centralizes systemd Exec serialization, path/text
specifier escaping and TOML basic-string encoding; render performs an internal
round-trip parity check before bytes leave the renderer. Production verification
no longer treats a textual command substring as proof: it reads manager-effective
`ExecStart`, `ExecStartPre` and `EnvironmentFiles` structures through D-Bus
and compares argv/path values element by element against the typed intent.

The hostile-character regression matrix also preserves the R3 credential gate:
the real transient user-manager proof executes the exact rendered argv and a
drifted credential file blocks the main notification command.

## 2. Independent CI evidence

GitHub Actions run `36555555882` is a completed successful push run whose
`head_sha` is exactly
`a09b9c101b6f7c7d0800fd844450652fbcfd19dc`.

Its `test` job completed every required step successfully, including Ruff,
project-runtime validation, the deterministic Python suite, reference systemd
verification, generated OpenAPI/type checks, Dashboard lint/typecheck/test/build,
client-bundle secret scanning, Wrangler deployment-config validation and the
cross-stack smoke.

The job log records:

- `6861 passed, 2 skipped` for the Python suite;
- `55 passed` for Dashboard tests;
- successful reference systemd verification;
- successful M6-C1/6-D3 cross-stack smoke.

The earlier R4 push `466bdfb` failed CI because the transient proof helper used
an `env python3` shebang and therefore lost repository dependencies under the
Actions user manager. Commit `a09b9c1` pins that proof helper to the test
interpreter; the exact-head run above then closes the gate. This is useful
evidence that the real-manager proof was exercised by CI rather than being only
a local claim.

## 3. Documentation drift found and corrected by this selection commit

R4's implementation/closure evidence was already coherent, but two historical
pointers remained active-looking:

1. the canonical R4 goal still said `SELECTED / NOT IMPLEMENTED`;
2. the old R4 coding-agent handoff still said `READY`.

The current-milestone paragraph in `docs/roadmap.md` also still described R4 as
the selected next slice. This review corrects those pointers while preserving
the historical R4 instructions as the contract that was satisfied.

## 4. Why Phase 7-A is next

The roadmap already defines Phase 7 as controlled evolution:

`proposal -> evaluation -> tests -> point-in-time validation/backtest -> PR -> human approval`.

Phase 5 already supplies important lower-level primitives:

- `CandidateProfileProposal` is proposal-only and cannot authorize automatic
  application;
- `CalibrationExperiment` binds the selected candidate to chronological
  train/validation search;
- `CalibrationHoldoutResult` evaluates the selected proposal separately after
  search;
- ordinary calibration/backtest execution is offline once frozen inputs exist.

What is still missing is the first-class **evaluation/admission artifact** that
binds those pieces together and proves, reproducibly, that a particular proposal,
base-profile identity, frozen dataset and holdout result belong to the same
evidence chain. Without that boundary, starting profile materialization or PR
automation would jump over the "evaluation" stage named by the roadmap.

Phase 7-A therefore builds that boundary first.

## 5. Automatic-verification policy for Phase 7-A

Phase 7-A is intentionally designed so that **no owner/manual action is required
for closure**.

The coding agent must automatically:

1. add focused adversarial tests and demonstrate the meaningful new failures
   against the pre-7-A baseline where feasible;
2. run the complete offline repository gate locally;
3. push the implementation;
4. query GitHub Actions and close only after a successful required run whose
   `head_sha` exactly equals the implementation commit;
5. record exact commands, counts, SHA, run id and conclusion.

Human approval is **not** part of Phase 7-A because this package must not create
or apply a new rule profile. Human approval belongs to a later explicitly
selected package that actually proposes materializing a versioned profile.

If an unexpected authority/environment boundary blocks an otherwise automatic
step, the agent must record all of the following rather than writing vague
"evidence unavailable" text:

- the exact command/action attempted immediately before the stop;
- the exact external authority or capability that is missing;
- the exact human action required, if any;
- the exact data/secret boundary involved;
- the exact resume command;
- the machine-checkable success criterion after resume;
- the precise remaining unverified scope.

## 6. Stop boundary

Do not start profile materialization, `strict-v2`, PR creation/merge, human
approval recording, provider/source expansion, Bridge/FQGate integration,
notification-vendor expansion, Windows bootstrap work, brokerage/trading, or
changes to `strict-v1` investment semantics in Phase 7-A.
