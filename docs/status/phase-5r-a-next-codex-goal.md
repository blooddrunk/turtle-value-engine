# Phase 5R-A next Codex goal — M6-C2

Status: **WAIT FOR GREEN CI BASELINE, THEN IMPLEMENT M6-C2**

Current `main` contains the M6-C1 implementation, the CI-hardening change and
the M6-C2 planning documents. The CI-hardening commit is:

`8446b47c936fdbac041ec34265c4b666661780ac`

Before implementing anything, inspect the latest GitHub Actions run covering
the current `main` tree and confirm the hardened CI is green.

- If it is green, use current `main` as the M6-C2 baseline.
- If it is red, inspect the exact failing job/step/log, reproduce/fix the root
  cause, push the repair, and require the replacement default-branch CI run to
  pass before M6-C2 implementation begins.
- Do not describe a red or unexecuted check as “evidence incomplete”.

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
