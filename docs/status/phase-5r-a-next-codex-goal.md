# Phase 5R-A Next Codex Goal — M6-C1 Recovery and Closure

Status: **M6-C1 REPORTED COMPLETE BUT NOT PRESENT ON GITHUB; RECOVERY/CLOSURE REQUIRED**
Date: 2026-09-19
Audited GitHub baseline: `36da491` (audit record on top of M6-C1 planning head `2edc30a`)

Work in repository `blooddrunk/turtle-value-engine`.

Read and follow `AGENTS.md` and the repository source-of-truth order. Read at
least:

- `docs/status/phase-5r-a-m6-c1-audit-2026-09-19.md`
- `docs/goals/phase-5r-a-m6-c1-personal-dashboard-foundation.md`
- `docs/goals/phase-5r-a-m6-b-read-only-api-adapter.md`
- `docs/goals/phase-5r-a-m6-a-read-only-research-surface.md`
- `docs/architecture/agent-api-web-surface.md`
- `docs/status/phase-5r-a-2026-09-19.md`

The owner reports M6-C1 as completed, but the auditable GitHub `main` tree did
not contain `apps/dashboard/` or the M6-C1 implementation. Do **not** assume the
work is lost and do **not** start M6-C2.

## Goal

Recover, verify, publish and close **M6-C1 only**.

First inspect the local workspace, branches, reflog, uncommitted changes and
unreachable commits without running destructive Git commands. If the completed
implementation exists locally, preserve and use it. If it cannot be recovered,
implement the frozen M6-C1 goal.

The implementation must still satisfy the original boundary: React 19 +
TypeScript + Vite, Cloudflare Vite/Workers Static Assets path, TanStack Router
and Query, generated types from deterministic M6-B OpenAPI, a bounded
same-origin GET/HEAD-only Worker proxy, responsive read-only list/detail UI,
preservation of blocked/partial/unavailable/not-evaluated states, and no
investment recomputation or mutation capability.

## Recovery commands — run before destructive Git operations

Record exact output for:

```bash
git status --short --branch
git log --oneline --decorate --graph -n 30 --all
git reflog --date=iso -n 80
git diff --stat
git diff --cached --stat
git fsck --no-reflogs --unreachable
test -d apps/dashboard && find apps/dashboard -maxdepth 3 -type f | sort
test -f schemas/research-surface-api-v1.openapi.json
test -f scripts/export_surface_openapi.py
```

Do not run `git reset --hard`, `git clean -fd`, delete branches, or overwrite
uncommitted files before this recovery inspection is complete.

## Automated acceptance — Codex owns it

Install/bootstrap declared dependencies automatically when the execution
environment permits it. Do not delegate ordinary verification to the owner.

Run and record exact exit codes, versions and pass/skip counts for at least:

```bash
python3 -m ruff check .
python3 -m pytest tests/test_research_surface.py -q
python3 -m pytest tests/test_surface_api.py -q
python3 -m pytest

pnpm --dir apps/dashboard lint
pnpm --dir apps/dashboard typecheck
pnpm --dir apps/dashboard test --run
pnpm --dir apps/dashboard build

python3 scripts/export_surface_openapi.py --check
```

Run the required real cross-stack smoke from the M6-C1 goal against the actual
M6-B process and actual local Worker/Vite preview. It must automatically verify
Dashboard HTML, same-origin health/list/known-detail, unknown-ID 404, mutation
rejection and clean process shutdown. Mock-only tests do not close M6-C1.

If a check fails, diagnose/fix/re-run it. Do not merely record a failure and
declare the milestone complete.

## Remote publication gate

After all acceptance checks pass, commit and push the work. Then record:

```bash
git status --short --branch
git rev-parse HEAD
git log -1 --oneline
git ls-remote origin refs/heads/main
git ls-tree -r --name-only HEAD -- apps/dashboard
git ls-tree -r --name-only HEAD -- schemas/research-surface-api-v1.openapi.json
git ls-tree -r --name-only HEAD -- scripts/export_surface_openapi.py
```

If working on a feature branch, prove its remote SHA, merge it after checks pass,
then prove the final remote `main` SHA. A local-only commit is not completion.

Update the M6-C1 goal/status/architecture/roadmap and this handoff only after the
implementation is both green and present on GitHub. Record exact verification
evidence, not phrases such as "tests look good" or "evidence incomplete".

## Manual-intervention boundary

M6-C1 requires no Cloudflare account, public domain, browser clicking, D1/R2,
Access/OIDC or other owner cloud work.

If and only if the environment prevents publication of an already-created
commit, report the exact failed push command/error, local commit SHA, branch/ref
and the smallest exact owner push command. If the environment prevents a
required automated test, use `BLOCKED_BY_EXECUTION_ENVIRONMENT`, identify the
single unverified acceptance item and give the exact fallback command sequence.
Do not close M6-C1 while that gate is unverified.

Stop after M6-C1 is genuinely closed on remote `main`. Do not implement M6-C2,
M5-C, Phase 6, M4-D/M4-E or M2-D in this goal.
