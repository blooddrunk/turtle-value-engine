# Phase 6-F-R2 post-closure review — 2026-09-29

Status: **R2 IMPLEMENTATION ACCEPTED; NARROW RUNTIME CREDENTIAL-DRIFT DEFECT FOUND; PHASE 6-F-R3 SELECTED**

Reviewed head:
`1799c81cbce617f04d2cbc23592d8ab1c1082368`

R2 implementation:
`c064cda68a0e31b0dc1b47ed451bd59977e7c931`

R2 implementation CI:
GitHub Actions run `36533726274`, `conclusion=success`, exact
`head_sha=c064cda68a0e31b0dc1b47ed451bd59977e7c931`.

R2 closure-doc head CI:
GitHub Actions run `36534043916`, `conclusion=success`, exact
`head_sha=1799c81cbce617f04d2cbc23592d8ab1c1082368`.

The implementation CI records 6803 Python tests passed / 2 skipped, 55
Dashboard tests passed, with Ruff, runtime-config validation, reference systemd
verification, generated API/type drift checks, Dashboard build/client-bundle
secret scan, strict Wrangler dry-run and cross-stack smoke all green.

## 1. What remains accepted

Phase 6-F stays `CLOSED / OWNER_ACCEPTED`. Phase 6-F-R2 also stays
`CLOSED`: it correctly replaced the permissive EnvironmentFile reader with a
single canonical parser, made render fail before writing artifacts on
unreadable/incomplete/non-canonical credentials, preserved R1 dual-source
secret scanning, and recorded exact-head CI plus fail-on-main evidence.

The accepted production deployment is still monitoring-only with
`delivery_enabled=false`; no production credential is configured and the
active timer was not changed by R2. The findings below therefore do not reverse
the accepted production monitoring closure.

## 2. Finding F1 — the canonical character set is still slightly wider than systemd's

R2's parser performs strict UTF-8 decoding and rejects whitespace, quotes,
backslashes and Unicode category `Cc` in values. That rejects NUL, but it
does **not** reject:

- `U+FEFF` (byte order mark, category `Cf`);
- Unicode noncharacters `U+FDD0..U+FDEF`;
- any code point ending in `FFFE` or `FFFF` in planes 0..16.

Upstream systemd's current `EnvironmentFile=` contract explicitly excludes
Unicode noncharacters, `U+0000` and `U+FEFF` from the whole file. Thus the
TVE canonical parser can currently accept a credential file/value that systemd
will reject before service execution.

This is a narrow R2 invariant gap, not a reason to reopen the monitoring-only
deployment.

Reference:
`systemd/systemd: man/systemd.exec.xml` (`EnvironmentFile=` valid-character
contract).

## 3. Finding F2 — canonicality is render-time, while systemd reads the file at run-time

The more important gap is a time-of-check/time-of-use boundary.

R2 validates the private EnvironmentFile before render, but:

- `cmd_apply()` checks rendered unit bytes, not the current credential file;
- `cmd_activate()` starts/enables the timer without current credential
  validation;
- `cmd_verify()` does not fail when a delivery-enabled credential file has
  drifted out of the canonical subset;
- `cmd_report()` can reuse old green records and does not add a current
  credential-contract failure;
- the rendered service has no pre-start canonical credential gate.

Upstream systemd reads files named by `EnvironmentFile=` shortly before the
process is executed. Therefore the owner can legitimately rotate/edit the
private file after render. If it is changed to syntax that systemd accepts but
the TVE canonical parser refuses (for example quoted or escaped syntax), the
existing unit can still receive those values at a later timer firing.

At the same time, `effective_secret_values()` intentionally contributes no
file values after a syntax-level parser failure. That is safe only if the
service is also prevented from executing. Today that prevention is not part of
the installed unit.

## 4. Finding F3 — the existing restart proof checks presence, not byte equality

`recover-proof` has a useful bounded `systemd-run` check after manager
refresh, but it only proves that every referenced environment name is non-empty.
It does not prove that the bytes systemd injected equal the bytes returned by
the canonical parser, and it runs only during the explicit recovery proof, not
at every scheduled service firing.

## 5. Selected correction: Phase 6-F-R3

Select the narrow follow-on:

**Phase 6-F-R3 — Runtime Credential Drift and Service-Effective Gate Hardening**

Canonical goal:
`docs/goals/phase-6-f-r3-runtime-credential-drift-hardening.md`

Coding-agent handoff:
`docs/status/phase-6-f-r3-next-coding-agent-goal.md`

R3 must make the R2 contract continuously true without changing delivery
ledger semantics:

1. close the Unicode noncharacter / U+FEFF parity gap;
2. revalidate the current private credential contract at lifecycle boundaries;
3. render a delivery-only pre-start gate that runs before
   `unattended-notify`;
4. have that gate compare the inherited referenced environment values with the
   canonical parser's in-memory values byte-for-byte, while emitting no value;
5. make drift block notification execution even if it occurs after render and
   after activation.

Do not persist a hash/fingerprint derived from secret content merely to detect
drift. Re-read and validate the private file in memory instead.

## 6. Owner/manual boundary

No owner action is planned for R3 implementation or CI closure.

Do not ask for a Telegram token, webhook URL, credential rotation, Windows
reboot, sudo action, log inspection or manual hash comparison. The accepted
production deployment has delivery disabled, so R3 can be closed
deterministically and by exact-head CI while automatically rerunning the
existing non-destructive production checks if the private config remains
available.

Enabling real production notification delivery remains a separate explicit
owner decision after R3 and is not part of this package.
