# Codex Goal — Phase 5R-A M6-B Read-only API Adapter

Work in repository `blooddrunk/turtle-value-engine` on current `main`.

Status: **M6-A COMPLETE; M6-B COMPLETE; M5-A/B COMPLETE; A6 PENDING**

Read and follow `AGENTS.md` and the source-of-truth order. Read at least:

- `docs/goals/phase-5r-a-m6-b-read-only-api-adapter.md`
- `docs/goals/phase-5r-a-m6-a-read-only-research-surface.md`
- `docs/architecture/agent-api-web-surface.md`
- `docs/architecture/runtime-and-automation.md`
- `docs/goals/phase-5r-a-local-research-and-low-cost-sources.md`
- `docs/status/phase-5r-a-2026-09-19.md`
- `docs/roadmap.md`

The completed M6-B package implemented exactly this boundary: a
framework-neutral registry/service over explicit, validated
`ResearchSurfaceSnapshotV1` inputs, a thin optional ASGI/FastAPI adapter and
the `tve surface serve` entry point. It does not read raw stores, recursively
discover workspace files, call providers or models, recompute investment
semantics, or add mutation endpoints.

The default server must bind to `127.0.0.1`. If non-loopback binding is
supported, require an explicit opt-in; do not silently expose `0.0.0.0`.
M5-C, Worker/D1/UI, authentication-provider integration, Phase 6 monitoring,
M4-D/M4-E and M2-D are out of scope.

## Verification is a completion gate

Before editing, automatically run:

```bash
python3 -m ruff check .
python3 -m pytest
```

After implementation, automatically run at minimum:

```bash
python3 -m ruff check .
python3 -m pytest tests/test_research_surface.py -q
python3 -m pytest tests/test_surface_api.py -q
python3 -m pytest
```

Add an automated **real loopback socket smoke test** that starts the actual
server, waits for `/healthz`, fetches one known surface, verifies its
`surface_id`/hash, verifies an unknown ID is 404, verifies a mutation request
is rejected, and shuts the server down cleanly. Run it yourself; do not ask the
owner to perform browser/curl checks that can be automated.

If dependencies are missing, use the repository-declared extras and install
them automatically when the environment permits. If the environment prevents a
required command, package install, process spawn or loopback bind, record the
exact command/error and the exact unverified acceptance item. In that case do
not claim M6-B fully closed; mark verification
`BLOCKED_BY_EXECUTION_ENVIRONMENT` and provide the exact manual fallback
commands. Never summarize this as merely “evidence incomplete”.

Update the dated status document with exact commands, exit results and
pass/skip counts, and update roadmap/goal status only after the automated
acceptance gates pass. Stop after M6-B; do not automatically start M5-C, M6-C
or Phase 6.

## Closure — 2026-09-19

The requested M6-B implementation and all automated acceptance gates passed.
The exact commands, exit codes, pass/skip counts, optional dependency setup and
loopback smoke evidence are recorded in
`docs/status/phase-5r-a-2026-09-19.md`.

No M5-C, M6-C Worker/Dashboard, authentication/deployment integration or Phase
6 work was started.
