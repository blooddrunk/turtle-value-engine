# Phase 5R-A next Codex goal — M6-C2

Status: **M6-C2 IMPLEMENTED; READY_FOR_OWNER_AUTHORIZED_LIVE_ACCEPTANCE**

Current `main` contains the M6-C1 implementation, CI hardening, M6-C2
Worker/deployment code, templates and tests. The pre-edit baseline was
`a54f86b60f111e7dca9c5bb6a3cbcb903bfeaabf`; GitHub Actions run `35482336396`
for that SHA was green. The implementation commit is
`41da846ecb3e7b2835933c0c9d9a8bd463eba7f4`, and post-push GitHub Actions run
`35484472809` for that SHA is also green: the single `test` job and all required
execution steps succeeded. The exact post-implementation checks and current
live blockers are recorded in
`docs/status/phase-5r-a-2026-09-20.md`.

The final deployment-helper correction is commit
`43bfa8f7e5191266dcec2635fd602d5fd82d9808`; GitHub Actions run `35484921932`
for that commit is green, including the full `test` job and all required
steps.

The code-bearing final hardening commit is
`3c8e188ac58f05b11a41389d1041181190ca24a1`. Before that hardening,
`ece4610eb61f1c5340ceb0ad3d6b727ad9fd53d1` had green run `35485017083`.
Run `35485721496` for the hardening commit is green: the `test` job completed
all 18 execution steps, including source Wrangler deployment-config dry-run.
The documentation closure commit
`aed18ee54795406dfbe77b022f8c706c39d18d8d` also has green run
`35486022150`, with all 18 execution steps passed. The final local
deterministic suite is `6301 passed, 2 skipped`;
Dashboard Vitest is `14 passed`, and deployment-helper regression tests are
`7 passed`.

The implementation provides:

- loopback HTTP preview only and remote HTTPS-only Worker origin validation;
- paired server-side Access service-token injection with browser-header spoof
  rejection and secret-safe responses;
- explicit `workers_dev: false` / `preview_urls: false`, custom-domain
  production generation and generated Wrangler type checking;
- deterministic Worker security tests, deployment preflight/dry-run/resource
  verifier and repeatable live smoke;
- loopback-only Tunnel ingress and explicit snapshot-path origin commands.
- source Wrangler asset-directory validation in CI;
- exact-hostname/Access-policy/service-token verification and invalid-origin-
  credential live-smoke coverage.

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

The final hardening follow-up is pushed as
`3c8e188ac58f05b11a41389d1041181190ca24a1`; its CI run is
`35485721496`. It fixes the source Wrangler dry-run configuration, tightens
deployment verification against hostname/policy/token drift, rejects invalid
origin credentials in live smoke, and records the current cloudflared ingress
validation command. Owner-specific Cloudflare/account/identity/origin inputs
remain the only reason live acceptance is not claimed.
