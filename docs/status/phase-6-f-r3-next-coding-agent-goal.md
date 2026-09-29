# Phase 6-F-R3 coding-agent handoff — Runtime Credential Drift and Service-Effective Gate Hardening

Status: **SELECTED / NOT IMPLEMENTED**

Canonical goal:
`docs/goals/phase-6-f-r3-runtime-credential-drift-hardening.md`

Selection audit:
`docs/status/phase-6-f-r2-post-closure-review-2026-09-29.md`

Predecessor closure:
`docs/status/phase-6-f-r2-2026-09-29.md`

## Mission

Implement only Phase 6-F-R3.

R2 is accepted and CLOSED, but its canonical credential proof is currently a
render-time proof. systemd reads `EnvironmentFile=` shortly before each
service execution, so a private credential file can drift after render/apply.
Current apply/activate/verify/report do not all revalidate that file and the
installed delivery service has no per-start canonical gate.

Also close the small Unicode parity gap: systemd rejects Unicode
noncharacters/U+FEFF in EnvironmentFile content while the current canonical
parser can accept them.

## Execution rules

- Read the canonical R3 goal and post-R2 review before editing.
- Add focused regressions that fail on current main before implementing.
- Reuse one current-credential validation primitive; do not create another
  EnvironmentFile parser.
- Reject U+FEFF and Unicode noncharacters anywhere in the decoded file.
- Gate apply/converge and activate before mutation when delivery is enabled.
- Make verify/report fail closed on current credential drift.
- Preserve safe deactivate even with invalid/missing credentials.
- Render a delivery-only pre-start gate before the unchanged
  `unattended-notify` ExecStart.
- The pre-start checker must compare systemd-inherited referenced values with
  canonical parsed values byte-for-byte in memory and emit no value.
- Never persist a secret value or secret-derived digest/fingerprint.
- Keep all ordinary tests offline and host-mutation-free.
- Run every machine-verifiable check yourself; do not delegate validation to
  the owner.
- If a usable service manager allows a bounded fake-sentinel integration proof,
  run it automatically without network delivery or persistent host mutation.
- If the existing private production config is available, rerun only the
  goal-specified non-destructive delivery-disabled production checks.
- Do not enable real notification delivery merely to close R3.
- Push the exact implementation SHA and close only after exact-head GitHub
  Actions succeeds.
- Record fail-on-main evidence, exact commands/results and test counts in a
  dated R3 closure document.
- Stop at R3.

## Required deliverables

- whole-file systemd-valid Unicode correction in the canonical credential
  validator;
- shared current-credential validation reused across lifecycle commands;
- delivery-only service pre-start gate proving canonicality and inherited-value
  byte equality before unattended notification execution;
- apply/activate/verify/report drift fail-closed behavior with deactivate
  remaining safe;
- deterministic runtime-drift, Unicode and pre-start regressions;
- full automatic gate and exact-head CI evidence;
- dated R3 closure record and narrow source-of-truth documentation updates.
