# Coding-agent handoff — Phase 7-A Controlled Evolution Evaluation Foundation

Status: **CONSUMED** (implementation delivered; see
`docs/status/phase-7-a-2026-09-30.md`)

Date: 2026-09-30

Canonical goal:
`docs/goals/phase-7-a-controlled-evolution-evaluation-foundation.md`

Selection audit:
`docs/status/phase-6-f-r4-post-closure-review-2026-09-30.md`

## Mission

Implement Phase 7-A exactly as the canonical goal defines it: create a
deterministic, offline, non-mutating controlled-evolution evaluation/admission
dossier that binds an existing `PROPOSAL_ONLY` `CandidateProfileProposal`,
its `CalibrationExperiment`, a separate `CalibrationHoldoutResult`, frozen
calibration observations, the frozen dataset identity and the exact base-profile
bytes.

The package ends at evidence admission. It must not create or apply a rule
profile and must not ask the owner for an investment-rule approval.

## Required preflight

Read before editing:

- `AGENTS.md`;
- `docs/goals/phase-7-a-controlled-evolution-evaluation-foundation.md`;
- `docs/status/phase-6-f-r4-post-closure-review-2026-09-30.md`;
- `docs/goals/phase-5-backtesting-calibration.md`;
- `docs/architecture/backtesting-and-calibration.md`;
- `docs/architecture/runtime-and-automation.md`;
- `src/turtle_value_engine/backtest/contracts.py`;
- `src/turtle_value_engine/backtest/calibration.py`;
- current CLI/schema-generation tests and `.github/workflows/ci.yml`.

Confirm the starting `main` SHA and keep unrelated working-tree changes out of
the implementation.

## Implementation requirements

1. Add a versioned immutable evaluation contract (suggested
   `ControlledEvolutionEvaluationV1`) and checked-in JSON Schema.
2. Canonically hash the proposal payload without retroactively mutating the
   existing `CandidateProfileProposal` contract.
3. Recompute the exact base-profile SHA-256 from the supplied profile bytes and
   require it to match the experiment/proposal.
4. Bind manifest, experiment, proposal, selected trial, holdout result and frozen
   observations with explicit identity/content checks.
5. Re-run canonical built-in calibration from the frozen observations and
   require deterministic equality with the admitted experiment/proposal; then
   recompute holdout and require equality with the supplied holdout artifact.
   An experiment produced by an unrecorded custom scorer is not reproducible and
   must be `BLOCKED`, not guessed compatible.
6. Emit stable machine-readable checks plus only
   `READY_FOR_HUMAN_REVIEW` or `BLOCKED` at the admission layer.
7. Keep `requires_human_approval=true` and
   `automatic_application_allowed=false`.
8. Add an offline CLI boundary such as `tve evolution evaluate ...`.
9. Make repeated execution from identical inputs deterministic; avoid wall-clock
   fields.
10. Prove the command cannot modify `strict-v1` or any supplied evidence
    artifact and does not construct network/provider/model/transport clients.

Do not invent a minimum holdout score, performance winner or economic approval
rule. The machine gate checks evidence integrity/reproducibility only.

## Test-first / adversarial proof

Before implementation, add focused tests for the currently missing admission
boundary and record which meaningful tests fail on the pre-7-A baseline.
Coverage must include all adversarial cases listed in the canonical goal:
profile/manifest/proposal/experiment/holdout/observation substitution,
chronology/holdout leakage, non-`PROPOSAL_ONLY` input, canonical-scorer
reproduction, custom-scorer non-reproducibility, deterministic hashing,
schema parity, no network and rule-file byte identity.

Do not manufacture a fail-on-main result for a test that only asserts the
existence of a brand-new contract; distinguish "new surface absent" from a
regression that demonstrates an existing unsafe gap.

## Automatic verification — mandatory

Run the focused suite first, then the entire current CI-equivalent gate. At
minimum:

```bash
python -m pip install ".[api,dev]"
python -m ruff check .
python -m turtle_value_engine config validate --input config/project.example.toml
python -m pytest
systemd-analyze verify deploy/monitoring/turtle-value-monitor.service deploy/monitoring/turtle-value-monitor.timer
pnpm --dir apps/dashboard install --frozen-lockfile
python scripts/export_surface_openapi.py --check
pnpm --dir apps/dashboard api:check
pnpm --dir apps/dashboard types:check
pnpm --dir apps/dashboard lint
pnpm --dir apps/dashboard typecheck
pnpm --dir apps/dashboard test --run
export CLOUDFLARE_API_TOKEN=ci-client-bundle-api-token-sentinel
export SURFACE_API_ACCESS_CLIENT_ID=ci-client-bundle-origin-id-sentinel
export SURFACE_API_ACCESS_CLIENT_SECRET=ci-client-bundle-origin-secret-sentinel
export TVE_DASHBOARD_ACCESS_CLIENT_ID=ci-client-bundle-dashboard-id-sentinel
export TVE_DASHBOARD_ACCESS_CLIENT_SECRET=ci-client-bundle-dashboard-secret-sentinel
pnpm --dir apps/dashboard build
pnpm --dir apps/dashboard security:client-bundle
pnpm --dir apps/dashboard exec wrangler deploy --dry-run --config wrangler.jsonc --strict
python scripts/dashboard_cross_stack_smoke.py
```

If the repository's current CI uses a renamed command, run that exact current
equivalent and document why the spelling differs.

Push the implementation, then query GitHub Actions yourself. Do not ask the
owner to inspect the Actions page. Do not mark Phase 7-A closed until the
required successful run has `head_sha == implementation_sha`.

The closure record must contain:

- exact implementation SHA;
- exact Actions run id, URL-equivalent reference and conclusion;
- focused test count and fail-on-main evidence;
- complete Python pass/skip count;
- Dashboard test count;
- explicit result of systemd/OpenAPI/types/lint/typecheck/build/security/
  Wrangler/cross-stack gates;
- proof that `rules/strict-v1.yaml` remained byte-identical;
- exact list of any skipped live-provider tests and why they are intentionally
  outside ordinary offline CI.

## Manual boundary

No manual work is expected in Phase 7-A.

If an unexpected external authority/environment boundary makes one required
automatic step impossible, stop only that step and document all seven items:
exact attempted command, exact blocker, exact human action, exact data/secret
boundary, exact resume command, machine-checkable success criterion and exact
unverified scope. Then continue every other automatic check that is still
possible.

Never write "evidence unavailable" or "manual verification required" without
that full boundary.

## Stop

Stop after Phase 7-A closure. Do not create `strict-v2`, mutate
`strict-v1`, open/merge a profile PR, record human approval, add provider or
Bridge/FQGate scope, add notification vendors, implement Windows bootstrap, or
add brokerage/trading behavior.
