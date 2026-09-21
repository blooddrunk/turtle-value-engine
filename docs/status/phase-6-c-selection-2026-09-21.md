# Phase 6-C selection audit — 2026-09-21

Status: **SELECTED / NOT IMPLEMENTED**

Audited main head:
`64aa64f17dac72c3e04319f799803584d3f85681`

## 1. Phase 6-B audit result

Phase 6-B is CLOSED at its live acquisition integration boundary.

Evidence checked on GitHub:

- implementation/hardening head
  `4d5320d1b724cc27388289ebcecf9dfd13e3e518`;
- exact Actions run `35575859074` -> `success`;
- post-sync evidence head
  `8d75fe680fc70e27613115de1433781a86a5a542`;
- exact Actions run `35577062233` -> `success`;
- closure-marking head
  `64aa64f17dac72c3e04319f799803584d3f85681`;
- exact Actions run `35577307808` -> `success`;
- local hardened suite recorded as 6496 passed, 2 skipped;
- real hardened CNINFO SH600519 annual-report and SZ000858 interim-report
  acquisition;
- cache-only byte-identical replay;
- cursor movement proven only through Phase 6-A atomic replay/commit;
- no CAPTCHA/login/consent and no deferred manual acceptance.

The hardening closes duplicate-scope, source/limit, exchange-plate/orgId,
timestamp-range and fixed-endpoint validation gaps without widening the first
live source.

Phase 5R strict A6 / `PRODUCTION_ELIGIBLE` remains `ACTIVE / PARTIAL`.
That separate state does not block bounded personal-research Phase 6 work.

## 2. Selected next package

**Phase 6-C — Controlled Re-analysis Executor**

Source of truth:

`docs/goals/phase-6-c-reanalysis-executor.md`

Phase 6-A already emits `ReanalysisPlanV1`; Phase 6-B can now feed that
planner with a bounded real disclosure source. The missing architecture link is
execution: a committed request must be transformed into controlled
preparation/research/analysis work with durable, retryable evidence.

## 3. Why this is smaller than Phase 6-D

Do not automate scheduling or notifications before the execution job itself is
idempotent, restart-safe and fail-closed. Phase 6-D should schedule a proven
Phase 6-C API instead of inventing execution semantics inside cron, Hermes or
GitHub Actions.

## 4. State/storage decision

Phase 6-C uses a separate re-analysis job store and does **not** mutate the
Phase 6-A `MonitoringWorkspace`.

Reason:

- Phase 6-A workspace is the event/cursor atomic-commit domain;
- re-analysis has a different lifecycle (provider/model failures, retries,
  blockers, output artifacts);
- mixing them would make cursor provenance and failure recovery harder to audit;
- Phase 6-D can later join the read-only monitoring status with latest
  re-analysis job/surface status.

This keeps the Phase 6-A frozen state contracts stable while making Phase 6-C
retryable.

## 5. Source expansion is not the blocker

Additional CNINFO event taxonomy, BJ/H sources and a future
`fqgate-remote-bridge` adapter are additive source work. They are not needed
to prove:

`real event -> deterministic plan -> controlled executor -> analysis/surface`.

Unverified CNINFO classes already fail closed to informational/no-action
behavior.

## 6. Verification policy

The coding agent owns deterministic verification.

No live LLM call and no manual functional acceptance is required to close
Phase 6-C. FULL_REANALYSIS is accepted in ordinary CI with scripted injected
analyst clients.

If a genuinely unavoidable new external human-auth boundary appears, the agent
must document exact pre-command -> exact human action -> exact resume command
-> expected output -> remaining automatic checks. Vague "evidence incomplete"
or internal shorthand is not acceptable.
