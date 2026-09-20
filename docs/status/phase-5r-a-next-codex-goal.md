# Phase 5R-A next Codex goal — M6-C2

Status: **M6-C2 IMPLEMENTED; READY_FOR_OWNER_AUTHORIZED_LIVE_ACCEPTANCE**

Latest code verification commit is
`cdca47f291d3cbc3bac8f51933c62f7cd0e13408`; GitHub Actions run
`35491132677` is green with all 19 execution steps passed. It adds a
production-build client-bundle scanner that rejects runtime secret sentinels,
while retaining fail-closed malformed-credential handling, the
production-config secret guard, pre-mutation Cloudflare list and
alternate-ingress checks, POST/PUT/PATCH/DELETE mutation rejection, M6-B
loopback tests, local cross-stack smoke and repeatable live smoke.

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
deterministic suite is `6303 passed, 2 skipped`;
Dashboard Vitest is `14 passed`, and deployment-helper regression tests are
`9 passed`.

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
- subprocess output redaction covering the API token and both service-token
  pairs before Wrangler deployment.
- Dashboard zone-level Worker route isolation with fail-closed pagination
  handling before apply/verify.
- apply-time workers.dev/preview, extra-domain and overlapping Access-target
  checks now fail closed before any Cloudflare mutation; live credential pairs
  reject whitespace-only and surrounding-whitespace values.
- Worker tests explicitly cover both client-only and secret-only half-paired
  origin credentials.
- Standalone live smoke rejects Dashboard/origin hostname collisions before
  any network request.

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

The route-isolation follow-up is
`a68fa3196f496d08782d01cc2ea9bf5823245f25`; run `35487136705` is green with
all 18 CI execution steps passed. It requires `TVE_DASHBOARD_ZONE_ID` and
rejects legacy zone routes still attached to the Dashboard Worker.

The route-pagination regression-test follow-up is
`65f413c4a62ecd9adc8c531a42f372f7504c62b5`; run `35487290954` is green with
all 18 CI execution steps passed. The deployment runbook now records the
additional Workers Routes Read permission.

The complete-list fail-closed follow-up is
`4c6523c2d8f21e4f44c4aee4304501311a7ab44c`; run `35487651724` is green with
all 18 CI execution steps passed. All relevant Cloudflare list responses now
require matching pagination metadata before apply/verify proceeds.

The read-only method-coverage follow-up is
`7859d7021726e1ea09e80126e3f30e844f735015`; run `35488158752` is green with
all 18 execution steps passed. All four HTTP mutation methods are rejected
before upstream fetch in the Worker and are exercised by local and live smoke
paths.

The current fail-closed deployment follow-up is
`8b930dff8ab289b67a9c02fc7e92de7564462d1f`; run `35489083702` is green with
all 18 execution steps passed. The latest local Python suite is
`6306 passed, 2 skipped`, and the deployment/live-smoke regression tests are
`12 passed`.

The service-token symmetry follow-up is
`3fb2bf7e9706ac9e8e054160a45259d234c1ba7d`; run `35489453533` is green with
all 18 execution steps passed.

The live-smoke hostname-isolation follow-up is
`0ae71121138601b61694f2f2e1b1039a9620fda1`; run `35489756086` is green with
all 18 execution steps passed.

The production-config secret-safety follow-up is
`c93814b3de6c034da77ea526cef1a3bfb1300026`; run `35490033160` is green with
all 18 execution steps passed. Its focused deployment regression test asserts
that the generated production config contains only the non-secret origin
variable and no API-token or Access service-token values. The current focused
deployment tests passed (`12 passed`) and standalone live-smoke validation
tests passed (`2 passed`); the full local deterministic suite passed
(`6308 passed, 2 skipped`).

The malformed-origin-credential hardening follow-up is
`ce3956e1ceb04aff462228bc7747d5b686236a80`; run `35490794888` is green with
all 18 execution steps passed. Worker security tests now reject empty,
whitespace-only and surrounding-whitespace credential values before upstream
fetch for both loopback and remote HTTPS origins. Dashboard Vitest passed
(`15 passed`), and the focused M6-A/M6-B/M6-C2 Python tests passed (`32
passed`).

The client-bundle secret-safety follow-up is
`cdca47f291d3cbc3bac8f51933c62f7cd0e13408`; run `35491132677` is green with
all 19 execution steps passed. The build runs with test-only runtime secret
sentinels and `security:client-bundle` scans all generated client files
without printing values; the local scan passed over 4 files.

The subsequent secret-redaction follow-up is
`297d7cf1232823fc3dab1b5758dae8d6907275d2`; run `35486605298` is green with
all 18 CI execution steps passed.
