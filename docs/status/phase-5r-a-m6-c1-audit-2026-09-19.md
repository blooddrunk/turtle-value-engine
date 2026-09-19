# Phase 5R-A M6-C1 audit — 2026-09-19

Status: **M6-C1 NOT PRESENT ON GITHUB / RECOVERY REQUIRED**

Audited GitHub branch: `main`
Audited head: `2edc30a01bfc685275f3d3767963534e915cd124`
Head message: `docs: plan M6-C1 personal dashboard foundation`

## 1. Audit conclusion

The owner reported M6-C1 as completed, but the completed implementation is not
present in the GitHub repository that can be audited.

At the audited head:

- the latest commit is the M6-C1 **planning** commit, not an implementation commit;
- the repository root has no `apps/` directory, therefore no
  `apps/dashboard/` application is present on `main`;
- the M6-C1 goal remains `ACTIVE / NEXT`;
- `docs/status/phase-5r-a-next-codex-goal.md` still instructs Codex to implement
  M6-C1;
- GitHub exposes no M6-C1 branch or pull request;
- the only repository branches visible in addition to `main` are older Phase
  2/5 branches and the already-merged M2-E branch;
- the audited head has no combined commit-status checks attached.

Commit `2edc30a` changes planning/status documentation for M6-C1. It does not
contain the Dashboard implementation required by
`docs/goals/phase-5r-a-m6-c1-personal-dashboard-foundation.md`.

Therefore M6-C1 cannot be accepted as complete and M6-C2 must not be opened yet.

## 2. Immediate next package: M6-C1 recovery and closure

The next Codex run must first recover any completed-but-unpushed work before
making destructive Git changes.

### 2.1 Recovery-first rule

Before `git reset`, `git clean`, checkout of another branch, or any operation
that could discard work, run and record:

```bash
git status --short --branch
git log --oneline --decorate --graph -n 30 --all
git reflog --date=iso -n 80
git diff --stat
git diff --cached --stat
git fsck --no-reflogs --unreachable
```

Also inspect whether the expected implementation exists in the working tree:

```bash
test -d apps/dashboard && find apps/dashboard -maxdepth 3 -type f | sort
test -f schemas/research-surface-api-v1.openapi.json
test -f scripts/export_surface_openapi.py
```

If completed work exists as uncommitted files, a local commit, a detached HEAD,
or another local branch, recover it into a normal branch/commit and preserve its
history. Do not reimplement first and accidentally overwrite recoverable work.

If no implementation can be recovered, implement M6-C1 from the frozen goal.

## 3. Mandatory automated acceptance

M6-C1 may be closed only after all automatable checks in the goal are actually
executed successfully. At minimum record exact commands, exit codes, versions
and test counts for:

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

The required real cross-stack smoke must also pass. It must start the actual
M6-B server and actual local Dashboard/Worker preview, verify root HTML,
same-origin health/list/detail, unknown-ID 404 and mutation rejection, then shut
both processes down cleanly. Mock-only coverage is not acceptance.

Do not replace any of these checks with prose such as "looks good", "manual
verification recommended" or "evidence incomplete".

## 4. Publication verification is part of closure

After committing the recovered or reimplemented work, Codex must push it and
prove that the remote repository contains the implementation.

Record:

```bash
git status --short --branch
git rev-parse HEAD
git log -1 --oneline
git ls-remote origin refs/heads/main
```

If development occurs on a branch, record the remote branch SHA and merge it to
`main` only after its required checks pass. Then verify the remote `main` SHA
again.

Finally prove that the checked-in tree contains the expected M6-C1 artifacts,
for example:

```bash
git ls-tree -r --name-only HEAD -- apps/dashboard
git ls-tree -r --name-only HEAD -- schemas/research-surface-api-v1.openapi.json
git ls-tree -r --name-only HEAD -- scripts/export_surface_openapi.py
```

A local green workspace that is not pushed is not repository closure.

## 5. Manual-intervention boundary

No owner/cloud action is required for normal M6-C1 acceptance.

Owner intervention is justified only if Codex cannot access the workspace or
credentials needed to publish its already-created Git commit. In that case it
must state:

1. the exact command that failed;
2. the exact error;
3. the local commit SHA containing the completed work, if one exists;
4. the exact branch/ref that needs to be pushed;
5. the smallest owner command required to publish it.

Do not ask the owner to rerun ordinary tests, open a browser, configure
Cloudflare, or manually inspect the UI.

## 6. Boundary after successful recovery

Only after the implementation is present on GitHub `main` and every M6-C1
acceptance gate has passed may the project select and plan M6-C2.

M6-C2 remains the later deployment/security package: owner-authorized
Cloudflare deployment, authenticated ingress, secure non-loopback origin
connectivity, secret/service-token handling and a concrete decision on whether
M5-C/R2 is needed. Phase 6 monitoring, M4-D/M4-E and M2-D remain outside the
M6-C1 recovery run.
