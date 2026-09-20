# Phase 5R-A M6-C2 — Private Dashboard Deployment and Authenticated Origin

Status: **IMPLEMENTED / READY_FOR_OWNER_INTERACTIVE_ACCESS_ACCEPTANCE**
Date: 2026-09-20
Selected after: M6-C1 local/preview Dashboard closure and CI hardening

Parent context:
- `AGENTS.md`
- `docs/architecture/agent-api-web-surface.md`
- `docs/architecture/runtime-and-automation.md`
- `docs/goals/phase-5r-a-m6-c1-personal-dashboard-foundation.md`
- `docs/status/phase-5r-a-2026-09-20.md`
- `docs/status/phase-5r-a-next-codex-goal.md`

## 1. Objective

Turn the completed M6-C1 local/preview Dashboard into a small **private,
owner-controlled live deployment** without weakening the M6-A/M6-B read-only
boundary.

The target path is:

```text
owner browser
  -> authenticated Cloudflare Access ingress
  -> M6-C1 Worker + static Dashboard
  -> same-origin /api/*
  -> Worker server-side authenticated origin request
  -> private HTTPS origin
  -> Cloudflare Tunnel (preferred) or equivalent explicit secure channel
  -> loopback-only tve surface serve
  -> explicit validated ResearchSurfaceSnapshotV1 files
```

The preferred deployment keeps `tve surface serve` bound to `127.0.0.1`.
A Cloudflare Tunnel on the same host publishes only the M6-B HTTP surface to an
origin hostname. The Dashboard Worker reaches that origin through HTTPS and
authenticates with a Cloudflare Access service token held only as Worker
secrets. The human-facing Dashboard is separately protected by Cloudflare
Access.

M6-C2 is deployment/security work. It is not Phase 6 monitoring and it is not a
new analysis engine.

## 2. Why this is the next package

M6-C1 already proved, locally and without cloud dependencies:

- the React/Vite application;
- generated OpenAPI client typing;
- the same-origin bounded Worker proxy;
- M6-B list/detail behavior;
- negative/partial state rendering;
- mutation rejection;
- real Python API + Worker preview cross-stack transport.

The next unresolved boundary is therefore not more UI. It is how to expose the
existing read-only surface privately over the Internet while preventing:

- unauthenticated Dashboard access;
- direct unauthenticated origin access;
- `workers.dev` or preview-hostname authentication bypass;
- browser-controlled upstream URLs;
- service-token leakage;
- accidental public non-loopback M6-B binding;
- mutation or arbitrary reverse-proxy expansion.

M5-C remains deferred unless this package proves that the selected deployment
actually requires remote artifact mirroring. With a persistent M6-B origin
behind Tunnel, M5-C/R2 is not required merely to deploy the Dashboard.

## 3. Frozen boundaries

Preserve all of the following:

1. `strict-v1`, deterministic investment math and rule semantics are unchanged.
2. `ResearchSurfaceSnapshotV1` remains the authoritative Dashboard payload.
3. M6-B remains read-only and consumes only explicit validated snapshot inputs.
4. M6-B must not recursively discover a workspace, raw CAS or historical store.
5. No page/API request may trigger acquisition, provider access, model calls,
   analysis, adjustment approval, rule changes, orders, transfers or other
   state-changing financial operations.
6. The Worker remains an allowlist proxy for the existing M6-B read contract.
7. Browser input may never select or override the upstream origin.
8. Credentials, Access service-token values and Cloudflare API tokens must never
   be committed, rendered to the browser, logged in plaintext or accepted from a
   query/body parameter.
9. Ordinary CI remains independent of a live Cloudflare account and external
   network services after dependency installation.
10. A6 production eligibility is not a prerequisite for serving a frozen
    surface. `PARTIAL`, `BLOCKED`, `NOT_AVAILABLE` and
    `NOT_EVALUATED` must remain unchanged.
11. Phase 6 monitoring, M4-D/M4-E and M2-D remain outside this package.
12. `H_PRICE_SOURCE_SELECTED_FUTU`, PIT/A6 semantics and source-selection
    contracts remain unchanged.

## 4. Security architecture

### 4.1 Human Dashboard ingress

Protect the entire live Dashboard entry point with Cloudflare Access.

The deployment must not protect only one friendly custom hostname while leaving
an alternate production/preview/`workers.dev` route publicly reachable. The
implementation/runbook must either:

- apply Access at the Worker level to every enabled route/domain that can serve
  the app; or
- explicitly disable/bind all alternate routes so the documented protected
  hostname is the only live ingress.

The owner chooses the allowed interactive identity/policy. Codex may automate
resource creation when credentials and account identifiers are available, but
it must not invent the owner's email address, identity provider or organization
policy.

### 4.2 M6-B origin

Preferred topology:

```text
cloudflared on the M6-B host
    -> http://127.0.0.1:<surface-port>
```

The public origin hostname is protected by an Access **service-auth** policy.
Only the Dashboard Worker service token should be admitted for normal machine
traffic.

M6-B itself should stay loopback-only. Do not bind `0.0.0.0` just to make the
Tunnel work.

If the environment cannot use Cloudflare Tunnel, an explicit HTTPS origin may
be substituted only if the task records the concrete transport, firewall,
authentication and certificate model and proves equivalent fail-closed
behavior. Do not silently fall back to plain HTTP on a public network.

### 4.3 Worker-to-origin authentication

Extend the Worker environment with secret-only origin-auth inputs, preferably:

- `SURFACE_API_ACCESS_CLIENT_ID`
- `SURFACE_API_ACCESS_CLIENT_SECRET`

Requirements:

- both absent is permitted only for loopback/local preview;
- exactly one configured is a startup/request configuration error;
- both configured are attached server-side as the Access service-token headers;
- browser-supplied versions of those headers are ignored and never forwarded;
- secret values are never returned in errors/responses;
- remote origins require `https:`;
- `http:` remains allowed only for loopback local preview;
- userinfo, path/query fragments and other malformed origin configuration remain
  rejected.

## 5. Implementation package

Keep changes narrowly around deployment/security:

```text
apps/dashboard/worker/**
apps/dashboard/wrangler.jsonc or an equivalent environment-specific deployment config
apps/dashboard/package.json
apps/dashboard/src tests only if deployment behavior needs coverage
scripts/ for deterministic deployment/preflight/live-smoke helpers
deploy/ or docs/operations/ for origin service/Tunnel examples where useful
.github/workflows/ci.yml
docs/architecture/agent-api-web-surface.md
docs/goals/phase-5r-a-m6-c2-private-dashboard-deployment.md
docs/status/phase-5r-a-2026-09-20.md
docs/status/phase-5r-a-next-codex-goal.md
```

Do not refactor analysis, historical acquisition, M4/M5 storage, filing research
or deterministic calculations for deployment convenience.

### 5.1 Required code/config work

At minimum:

1. harden Worker upstream-origin validation for local-vs-remote transport;
2. add fail-closed Access service-token injection for remote origin calls;
3. add deterministic tests proving browser headers cannot spoof/override origin
   credentials;
4. provide non-secret production configuration templates or generators;
5. add a deployment/preflight command that validates required non-secret
   configuration before any live mutation;
6. add an owner-authorized live deployment/smoke command that can use environment
   credential references without printing secrets;
7. document how the M6-B process receives an explicit snapshot set and remains
   loopback-only;
8. document/provide a concrete Tunnel ingress example mapping only the origin
   hostname to the M6-B loopback port;
9. explicitly record whether M5-C is needed. Default decision: **defer M5-C**
   unless a demonstrated operational need requires mirrored surface artifacts.

## 6. Automated verification — mandatory

**Codex must execute every check that its environment can execute. Do not ask the
owner to run routine tests, inspect files, or click through cloud settings that
can be verified by CLI/API.**

### 6.1 Pre-edit baseline

Run and record exit codes/results:

```bash
git status --short --branch
git rev-parse HEAD
python3 -m ruff check .
python3 -m pytest
node --version
pnpm --version
pnpm --dir apps/dashboard install --frozen-lockfile
pnpm --dir apps/dashboard lint
pnpm --dir apps/dashboard typecheck
pnpm --dir apps/dashboard test --run
pnpm --dir apps/dashboard build
python3 scripts/export_surface_openapi.py --check
pnpm --dir apps/dashboard api:check
python3 scripts/dashboard_cross_stack_smoke.py
```

Before editing, also inspect the latest GitHub Actions result for the baseline
commit. A red required CI run is a blocker to claiming a clean baseline; fix or
explain the exact failure before proceeding.

### 6.2 Offline/security tests after implementation

Run at minimum:

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
pnpm --dir apps/dashboard api:check
python3 scripts/dashboard_cross_stack_smoke.py
```

Add deterministic Worker tests proving all of the following:

- local loopback HTTP origin remains valid for C1-style preview;
- remote plain-HTTP origin is rejected;
- remote HTTPS origin is accepted;
- malformed/userinfo/path/query origins are rejected;
- half-configured service-token credentials fail closed;
- server-side service-token headers are attached when configured;
- browser-supplied `CF-Access-Client-Id` /
  `CF-Access-Client-Secret` cannot override configured values;
- neither credential appears in response body/headers;
- unknown API paths remain 404;
- mutation methods remain rejected before upstream fetch;
- ETag/If-None-Match behavior remains intact.

### 6.3 CI acceptance

Update CI only when necessary, but M6-C2 cannot close while required CI is red.
CI must continue to cover the Python suite plus Dashboard lint/typecheck/tests,
production build, generated-contract drift checks and the local real cross-stack
smoke.

Do not replace CI evidence with prose such as “tested locally”.

## 7. Owner-authorized live deployment

Live Cloudflare creation/update is allowed only when the owner has deliberately
provided the required runtime configuration/credentials.

Codex must first implement and pass all non-cloud tests. Then it should detect
whether the required live inputs are present.

### 7.1 Inputs that may genuinely require the owner

The exact names can follow the implementation, but the live step needs the
equivalent of:

- Cloudflare account ID;
- an API token with the minimum permissions needed for the resources Codex will
  create/update;
- owner-selected Dashboard hostname/custom domain, or an explicit decision to
  use a protected Worker hostname;
- owner-selected origin hostname;
- the identity/policy that is allowed to access the Dashboard;
- a host where `tve surface serve` and `cloudflared` can run;
- the explicit frozen snapshot path(s) to serve.

Secrets must be provided through environment variables, a secret manager, or
another declared runtime reference. **Do not ask the owner to paste API tokens
or service-token secrets into chat or commit them to Git.**

### 7.2 What Codex must automate once those inputs exist

Prefer Wrangler/Cloudflare API/CLI and scripts over dashboard clicking. Codex
should automatically:

1. validate account/token access and required permissions;
2. build the Dashboard from the exact repository commit;
3. create/update the Worker deployment;
4. configure the protected Dashboard hostname/route;
5. create/update the Tunnel/public-origin mapping when the execution environment
   has the authority to do so;
6. create/update the Access applications/policies and service token when API
   support/permissions permit;
7. store Worker origin-auth values through the supported secret mechanism;
8. start or validate the loopback M6-B origin with explicit snapshot paths;
9. validate Tunnel ingress configuration;
10. run machine-verifiable live probes;
11. record resource identifiers/hostnames and non-secret evidence, never secret
    values.

If the available token cannot create a specific Cloudflare resource, record the
exact API/CLI command, returned authorization error, missing permission and the
smallest owner action required. Do not replace this with “Cloudflare setup
needed”.

## 8. Required live acceptance

M6-C2 is not complete merely because `wrangler deploy` succeeds.

Automated live checks must prove, without exposing secrets:

1. the deployed Dashboard hostname responds through the expected Access boundary;
2. the live Worker cannot use an unconfigured/invalid origin;
3. the origin hostname rejects a request without machine authentication;
4. the same origin accepts a valid service-token request and returns M6-B
   `/healthz`;
5. the deployed Worker reaches same-origin `/api/healthz`;
6. list and one known detail work through the deployed Worker;
7. the known detail preserves `surface_id` and `content_sha256`;
8. unknown surface remains 404;
9. POST/PUT/PATCH/DELETE remain rejected;
10. no alternate enabled Dashboard route bypasses Access;
11. no alternate enabled origin route bypasses service authentication.

Use a script such as `scripts/dashboard_live_smoke.py` so the same checks are
repeatable. It must read credentials from runtime references and redact them
from command output.

## 9. Exact human-verification boundary

There should be **at most one small interactive browser verification** that
automation cannot honestly replace: proving the owner's real interactive
identity-provider login flow.

After all automated live checks pass, the owner may be asked to perform exactly:

1. open the final documented Dashboard URL in a private/incognito browser;
2. confirm Cloudflare Access appears **before Dashboard content**;
3. sign in using the owner-approved identity;
4. confirm the Dashboard overview renders and one known surface detail opens;
5. sign out or open a fresh private session and confirm Dashboard content is no
   longer visible without authentication.

Expected result: unauthenticated browser access never sees the Dashboard; the
approved identity can read it; no write/trading controls exist.

This manual check does **not** replace API/security tests. If it fails, record
the exact observed URL, HTTP/login behavior and affected acceptance item.

Do not ask the owner to manually verify:

- lint/typecheck/tests/build;
- OpenAPI/type drift;
- mutation rejection;
- origin header injection;
- Tunnel configuration syntax when `cloudflared` can validate it;
- Worker deployment existence when Wrangler/API can inspect it;
- HTTP status codes when the smoke script can test them.

## 10. Blocked-state rules

If owner credentials/account/domain/host access are not available, Codex may
finish the implementation and automated local security validation, but must use:

`READY_FOR_OWNER_AUTHORIZED_LIVE_ACCEPTANCE`

It must list the exact missing inputs and exact live commands still pending.

If a supplied execution environment prevents an otherwise automatable step, use:

`BLOCKED_BY_EXECUTION_ENVIRONMENT`

and record:

1. exact failing command;
2. exact error/output;
3. checks already passed;
4. the specific acceptance item not proven;
5. exact fallback command(s) for the owner's machine.

Never use “evidence incomplete”, “manual verification recommended”, “should
work”, or an unexplained internal term as a substitute for this record.

## 11. Explicitly out of scope

Do not implement in M6-C2:

- Phase 6 watchlist/event polling or scheduled refresh;
- live acquisition from page/API requests;
- rule editing or approval UI;
- analysis/research execution UI;
- trading, orders, cancellations, transfers or brokerage mutation;
- D1 as a new application database;
- R2/M5-C unless a concrete artifact-distribution need is demonstrated and
  separately scoped;
- M4-D/M4-E;
- M2-D;
- changes to `strict-v1`, A6/PIT, source selection or investment semantics.

## 12. Acceptance

M6-C2 is complete only when:

- all M6-C1 regression gates are green locally and in required CI;
- Worker remote-origin handling is HTTPS-only and fail-closed;
- machine origin authentication is server-side and secret-safe;
- Dashboard ingress is authenticated without an alternate-route bypass;
- M6-B remains loopback-only in the preferred Tunnel topology;
- production/live configuration is reproducible and contains no committed
  secrets;
- automated live smoke passes the Dashboard -> Worker -> authenticated origin ->
  M6-B path;
- unauthenticated origin and Dashboard access are proven blocked;
- the single owner interactive-login check, if required, has explicit successful
  evidence;
- exact commands, exit codes, resource identifiers and remaining limitations are
  recorded;
- M5-C remains explicitly deferred unless separately justified.

Stop after M6-C2 closure. Do not automatically start Phase 6 in the same goal.

## 13. Implementation record — 2026-09-20

The offline/deployment implementation is complete. It adds:

- fail-closed Worker origin validation with loopback HTTP preview only,
  remote HTTPS-only transport, paired server-side Access service-token
  headers, browser-header spoof protection, and preserved allowlist/ETag/
  mutation behavior;
- explicit `workers_dev: false`, `preview_urls: false`, generated Wrangler
  production configuration, observability and generated Wrangler types;
- deterministic Worker security tests under `apps/dashboard/worker/index.test.ts`;
- `scripts/dashboard_deploy.py` for preflight, Wrangler dry-run, explicit
  owner-authorized build/deploy, Access/Tunnel/DNS API configuration, secret
  upload and resource verification. Cloudflare's Service Auth policy is sent
  with the API decision value `non_identity`;
- `scripts/dashboard_live_smoke.py` for repeatable authenticated live probes;
- non-secret production/Tunnel/Access templates under `deploy/dashboard/`.

The implementation was pushed as
`41da846ecb3e7b2835933c0c9d9a8bd463eba7f4`; GitHub Actions run `35484472809`
completed successfully for that commit. Its single `test` job passed the
Python suite, Ruff, frozen Dashboard install, OpenAPI/generated-type checks,
Dashboard lint/typecheck/tests/build and the real cross-stack smoke.
The follow-up commit
`43bfa8f7e5191266dcec2635fd602d5fd82d9808` corrected Cloudflare's Service Auth
API decision to `non_identity`; run `35484921932` also completed successfully
with every required CI step green.

Local and CI-independent acceptance is recorded in
`docs/status/phase-5r-a-2026-09-20.md`. Cloudflare account/token, owner
hostname/identity, Tunnel origin host, explicit snapshot path and live service
credentials were not present in this execution environment, so the remaining
state is exactly `READY_FOR_OWNER_AUTHORIZED_LIVE_ACCEPTANCE`. No Phase 6,
M5-C/R2, M4-D/M4-E or M2-D work was started.

## 14. Final hardening and verification — 2026-09-20

The final implementation audit is pushed at
`3c8e188ac58f05b11a41389d1041181190ca24a1`. It adds source Wrangler asset
directory validation to CI, exact-hostname and exact Access policy/service-token
verification, fail-closed rejection of colliding or ambiguous deployment
inputs, invalid-origin-credential coverage in the live smoke, and the current
`cloudflared tunnel --config ... ingress validate` command ordering.

The code-bearing commit's current-main GitHub Actions run `35485721496`
completed successfully. The single `test` job passed all 18 execution steps,
including Python/Ruff/full
pytest, frozen pnpm install, OpenAPI and generated-type drift, Dashboard
lint/typecheck/Vitest/build, source Wrangler dry-run and real local
cross-stack smoke. The final local results were `6303 passed, 2 skipped` for
pytest, `14 passed` for Dashboard Vitest and `9 passed` for deployment-helper
tests. The checked-in Tunnel example also validated with the official
temporary cloudflared `2026.9.1` binary and returned `Validating rules... OK`.

The subsequent documentation closure commit
`aed18ee54795406dfbe77b022f8c706c39d18d8d` was independently verified by
GitHub Actions run `35486022150`, whose `test` job also passed all 18
execution steps.

The secret-redaction follow-up is
`297d7cf1232823fc3dab1b5758dae8d6907275d2`; GitHub Actions run
`35486605298` also passed all 18 execution steps. It ensures the first
Wrangler deploy subprocess receives explicit redaction values for the API
token and both service-token pairs, and adds a stdout/stderr regression test.

The route-isolation follow-up is
`a68fa3196f496d08782d01cc2ea9bf5823245f25`; GitHub Actions run
`35487136705` also passed all 18 execution steps. It requires the Dashboard
zone ID, checks zone-level Worker routes before apply/verify, and fails closed
on incomplete pagination or legacy routes attached to the Dashboard Worker.

The route-pagination regression-test follow-up is
`65f413c4a62ecd9adc8c531a42f372f7504c62b5`; GitHub Actions run
`35487290954` also passed all 18 execution steps. The deployment runbook
records the additional Workers Routes Read permission.

The complete-list fail-closed follow-up is
`4c6523c2d8f21e4f44c4aee4304501311a7ab44c`; GitHub Actions run
`35487651724` also passed all 18 execution steps. Service-token, Access-app,
Worker-domain, DNS-record and Worker-route lists now require matching
pagination metadata before apply/verify proceeds.

The read-only method-coverage follow-up is
`7859d7021726e1ea09e80126e3f30e844f735015`; GitHub Actions run
`35488158752` also passed all 18 execution steps. The Worker security test,
M6-B loopback tests, local cross-stack smoke and repeatable live smoke now
exercise POST, PUT, PATCH and DELETE, and require each to return 405 before
any upstream fetch. Local verification after this commit recorded
`6303 passed, 2 skipped` for the Python suite, `18 passed` for the focused
M6-A/M6-B tests, `14 passed` for Dashboard Vitest, current generated
OpenAPI/API/Wrangler contracts, a successful source Wrangler strict dry-run,
and a successful real local cross-stack smoke.

The current fail-closed deployment follow-up is
`8b930dff8ab289b67a9c02fc7e92de7564462d1f`; GitHub Actions run
`35489083702` also passed all 18 execution steps. Apply-time checks now fail
closed on incomplete Cloudflare list pagination, enabled or ambiguous
workers.dev/preview/custom-domain/zone-route state, path or wildcard Access
applications, duplicate exact apps, and one Access app covering both the
Dashboard and origin hostnames. Post-deploy verification reuses the explicit
subdomain and Access-target checks. Live smoke credential pairs reject
whitespace-only and surrounding-whitespace values. Latest local results were
`6306 passed, 2 skipped` for Python and `12 passed` for deployment/live-smoke
regression tests.

The service-token symmetry follow-up is
`3fb2bf7e9706ac9e8e054160a45259d234c1ba7d`; GitHub Actions run
`35489453533` also passed all 18 execution steps. The Worker security tests
now explicitly cover both client-only and secret-only half-configured origin
credential states, and both fail before upstream fetch.

The live-smoke hostname-isolation follow-up is
`0ae71121138601b61694f2f2e1b1039a9620fda1`; GitHub Actions run
`35489756086` also passed all 18 execution steps. Standalone live smoke now
rejects Dashboard and origin URLs with the same hostname before any network
request, matching deployment preflight's collision guard.

The production-config secret-safety follow-up is
`c93814b3de6c034da77ea526cef1a3bfb1300026`. Its regression test serializes
the generated production Wrangler configuration and proves that the API token
and both Access service-token pairs are absent; only the non-secret HTTPS
origin variable is emitted as a Worker variable, with workers.dev and preview
URLs disabled and the exact custom-domain route retained. GitHub Actions run
`35490033160` also passed all 18 execution steps. The focused deployment tests
passed (`12 passed`) and the standalone live-smoke validation tests passed
(`2 passed`). The full local deterministic suite passed (`6308 passed, 2
skipped`).

The malformed-origin-credential hardening follow-up is
`ce3956e1ceb04aff462228bc7747d5b686236a80`. The Worker now treats empty,
whitespace-only and surrounding-whitespace origin Access credential values as
invalid and rejects them before any upstream fetch for both loopback preview
and remote HTTPS origins. GitHub Actions run `35490794888` also passed all 18
execution steps. The Dashboard Vitest suite passed (`15 passed`), the focused
M6-A/M6-B/M6-C2 Python tests passed (`32 passed`), and the full local
deterministic suite passed (`6308 passed, 2 skipped`).

The client-bundle secret-safety follow-up is
`cdca47f291d3cbc3bac8f51933c62f7cd0e13408`. The production build and CI now
run with test-only runtime secret sentinels, then scan every generated
`dist/client` file without printing sentinel values; the scan passed. The
repeatable command is
`pnpm --dir apps/dashboard security:client-bundle`. GitHub Actions run
`35491132677` also passed all 19 execution steps, including this bundle scan.

At that pre-authorization checkpoint the implementation was
`READY_FOR_OWNER_AUTHORIZED_LIVE_ACCEPTANCE`: no owner Cloudflare account,
token, selected hostnames/zone, origin host and snapshot path, or service
credentials were available, so no live resource mutation or authenticated
origin smoke was attempted. The exact missing inputs and commands are in
`docs/status/phase-5r-a-2026-09-20.md`. No Phase 6 work was started.

## 15. Project-wide configuration follow-up — 2026-09-20

The non-secret runtime/deployment input convention is now project-wide rather
than M6-C2-specific. `config/project.example.toml` is the checked-in template;
`.tve-private/project.toml` is the ignored owner copy and is intended to grow
with later Phase 5R and Phase 6 sections. `tve config init` and
`tve config validate` provide the reproducible creation/validation boundary.

M6-C2 consumes the typed `ProjectConfig`, derives the default hostnames and
resource names, discovers Cloudflare account/zone IDs from the configured zone
with read-only calls, and keeps all credentials in environment/secret-manager
references. Raw credential fields are rejected by the loader. The exact API
token permission set and the owner-facing three-value setup are recorded in
`docs/operations/project-runtime-config.md`.

The project-wide configuration implementation is commit
`34285f467de4fc6b3c68350814e912f0016228e6`. The final documentation closure
commit is `93c638fd1231e904fab50b3aeb21eab7e6e41874`; GitHub Actions run
`35496754597` passed its `test` job and all 20 execution steps, including the
project-config validation step.

## 16. Owner-authorized live deployment closure — 2026-09-20

The owner-provided project configuration and Cloudflare API token were
available in the execution environment through ignored private files and
environment references. The target was the explicitly validated
`ResearchSurfaceSnapshotV1` for `HK0288` (`as_of=2026-09-20`), served from
`.tve-private/surface/research-surface.json`. Its `surface_id` and
`content_sha256` are both
`1564c885738b010148225e8f2aa84d198ea819fc517c4ffcf21fbc0649053862`, and the
deterministic analysis identity is `analysis-18069e2f1b8f3cb9fb8d9d9c`.
The analysis remains `SPECIAL_REVIEW` with low data quality and no automated
recommendation; M6-C2 did not alter that result.

The current-main baseline was checked before the final edits:
`origin/main` and local `main` were `6f28fb034612cb9b1101268f6abd2468a3238e74`.
GitHub Actions run `35500161280` for that SHA completed with `success`; the
latest required CI job was green.

The owner-authorized deployment command was run with the token and service
credentials resolved only in the process environment:

```bash
set -a; source .tve-private/cloudflare-service-tokens.env; set +a
export CLOUDFLARE_API_TOKEN="$(<.tve-private/cloudflare.token)"
python3 scripts/dashboard_deploy.py deploy \
  --project-config .tve-private/project.toml --apply --live-smoke
```

It completed with exit code 0. `verify` completed with exit code 0, and the
official `cloudflared 2026.9.1` binary validated the checked-in ingress with
exit code 0 (`Validating rules... OK`). The non-secret live resources are:

- Cloudflare account `51eaede3a49980ea51dfe61d01cab7f7`, zone
  `9a7d331c8d376c528f9180dba7b1fc91`;
- Worker `tve-personal-dashboard`, final deployment version
  `34f96111-1369-4e76-bf62-b255894a2a87`;
- Dashboard `https://tve-private-dashboard.haoqi90.top`;
- authenticated origin `https://tve-private-surface.haoqi90.top`;
- remotely managed Tunnel
  `0e19c8cc-1af4-48d9-8af5-d65717b56a6c`, with the exact ingress
  `tve-private-surface.haoqi90.top -> http://127.0.0.1:8787` and terminal
  `http_status:404`;
- origin DNS record `dd049985edcfd6082d518d58adcfb1d6`;
- Dashboard Access app `715ee443-7eeb-4108-9a35-8ea8f2c15f3d` and origin
  Access app `f4bedf6f-7a53-4787-a8fa-cc5d7957f152`.

The deployment verifier proved workers.dev and preview ingress disabled, the
custom-domain set exact, the zone Worker-route set empty, Access targets exact
and non-overlapping, Dashboard policy decisions exactly service-auth plus the
configured owner email, origin policy exactly service-auth, and Tunnel ingress
loopback-only. The live smoke completed with exit code 0 and proved:

- unauthenticated Dashboard and origin requests are blocked;
- invalid origin credentials are blocked and the valid origin service token
  reaches `/healthz`;
- authenticated Dashboard -> Worker -> HTTPS origin -> M6-B health/list/detail
  works for the known target surface;
- `surface_id`/`content_sha256` are preserved, ETag revalidation returns 304,
  an unknown surface returns 404, and POST/PUT/PATCH/DELETE each return 405;
- no alternate Dashboard or origin URL configured by the smoke bypasses the
  corresponding authentication boundary.

The first live probe correctly failed with HTTP 403 because Cloudflare's
Browser Integrity Check rejected Python's default `Python-urllib` signature
with explicit Error 1010 `browser_signature_banned`. A direct comparison with
the same valid service token returned 200 using an explicit smoke User-Agent.
The repeatable smoke now sends `tve-m6-c2-live-smoke/1`; its regression test
and the full live smoke both pass. This is a deterministic probe transport
fix, not an Access-policy bypass.

Final local verification after the fix: Ruff exit 0; full pytest exit 0 with
`6320 passed, 2 skipped`; frozen pnpm install exit 0; Dashboard lint,
typecheck, Vitest (`15 passed`) and production build all exit 0; OpenAPI drift,
generated API type drift, client-bundle secret scan and real local cross-stack
smoke all exit 0; deployment-helper/live-smoke tests pass; tracked files and
generated/log output contain none of the private credential values.

The only remaining acceptance item is the goal-defined owner interactive
check: open the Dashboard URL in an incognito browser, see the Access wall
before Dashboard content, sign in as the configured owner identity, read the
overview and one detail, then use a fresh unauthenticated session to confirm
the Dashboard is not visible. No Phase 6, M5-C/R2, M4-D/M4-E or M2-D work was
started.

The closure commit is `4365a950c3a5afa28656545e7fbca1ef6253f1f9`.
GitHub Actions run `35502629180` completed with `success`; its single `test`
job and all 20 required execution steps passed.
