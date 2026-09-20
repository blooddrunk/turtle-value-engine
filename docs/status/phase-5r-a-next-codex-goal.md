# Phase 5R-A next Codex goal — M6-C2

Status: **M6-C2 IMPLEMENTED; READY_FOR_OWNER_AUTHORIZED_LIVE_ACCEPTANCE**

Current `main` contains the M6-C1 implementation, CI hardening, M6-C2
Worker/deployment code, templates and tests. The pre-edit baseline was
`a54f86b60f111e7dca9c5bb6a3cbcb903bfeaabf`; GitHub Actions run `35482336396`
for that SHA was green and every required job/step succeeded. The exact
post-implementation checks and current live blockers are recorded in
`docs/status/phase-5r-a-2026-09-20.md`.

The implementation provides:

- loopback HTTP preview only and remote HTTPS-only Worker origin validation;
- paired server-side Access service-token injection with browser-header spoof
  rejection and secret-safe responses;
- explicit `workers_dev: false` / `preview_urls: false`, custom-domain
  production generation and generated Wrangler type checking;
- deterministic Worker security tests, deployment preflight/dry-run/resource
  verifier and repeatable live smoke;
- loopback-only Tunnel ingress and explicit snapshot-path origin commands.

The selected implementation package is:

`docs/goals/phase-5r-a-m6-c2-private-dashboard-deployment.md`

Core objective: deploy the existing read-only Dashboard privately with
authenticated human ingress and authenticated Worker-to-M6-B origin transport,
preferably Cloudflare Access + Worker + Cloudflare Tunnel while keeping
`tve surface serve` loopback-only.

Preserve M6-A/M6-B/C1 semantics. Do not start Phase 6, M5-C/R2, M4-D/M4-E or
M2-D unless the M6-C2 goal explicitly opens a separately justified boundary.

Automation policy is strict:

- Codex runs all local/CI/deployment/API/Tunnel checks it can run itself.
- Codex uses CLI/API instead of asking the owner to click through Cloudflare
  when credentials/permissions allow automation.
- Secrets come only from environment/secret-manager references and are never
  requested in chat, committed or printed.
- If live owner inputs are unavailable after all offline/security work is green,
  stop at `READY_FOR_OWNER_AUTHORIZED_LIVE_ACCEPTANCE` and list each missing
  input plus exact pending commands.
- If the execution environment blocks an otherwise automatable step, use
  `BLOCKED_BY_EXECUTION_ENVIRONMENT` with exact failing command/error,
  successful checks, affected acceptance item and exact fallback commands.
- The only expected manual acceptance is the final owner interactive Access/IdP
  login sequence described in the goal; it cannot substitute for automated
  transport/security smoke tests.

No Phase 6 monitoring, M5-C/R2, M4-D/M4-E or M2-D work was started. M5-C/R2
remains deferred because the persistent authenticated M6-B origin serves the
existing validated snapshot directly.
