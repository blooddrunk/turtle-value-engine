# Phase 6-F-R3 post-closure review — 2026-09-29

Status: R3 IMPLEMENTATION ACCEPTED; TWO SERIALIZATION-PARITY DEFECTS FOUND; PHASE 6-F-R4 SELECTED

Reviewed head:
7ee61df709b7eee3e45c5d24a989e5de8c613f52

R3 implementation:
4f3fa0df9381649c0929135dd7b9480a43d5ea91

R3 closure:
docs/status/phase-6-f-r3-2026-09-29.md

Selected next package:
docs/goals/phase-6-f-r4-production-artifact-serialization-hardening.md

Coding-agent handoff:
docs/status/phase-6-f-r4-next-coding-agent-goal.md

## 1. R3 acceptance

The R3 implementation is accepted at its declared runtime-credential boundary.

Independent repository/API review confirmed:

- main records the R3 closure at 7ee61df709b7eee3e45c5d24a989e5de8c613f52;
- implementation commit 4f3fa0df9381649c0929135dd7b9480a43d5ea91 contains the one current-credential validation primitive, lifecycle drift gates, the delivery-only ExecStartPre credential gate, and the recover-proof byte-equality upgrade;
- GitHub Actions run 36542078579 is a push run with head_sha exactly 4f3fa0df9381649c0929135dd7b9480a43d5ea91 and conclusion success;
- the CI job records Ruff success, 6823 passed / 2 skipped, reference systemd verification, 55 Dashboard tests, client-bundle secret scan, strict Wrangler dry-run and cross-stack smoke;
- the focused R3 tests cover Unicode rejection, lifecycle drift, gate missing/mismatch/noncanonical cases, delivery-disabled preservation and a real transient user-manager proof.

No evidence was found that requires reopening the credential-validation or byte-equality design itself.

## 2. Finding F1 — systemd command serialization is not a proven semantic round-trip

ProductionConfigV1 accepts absolute path inputs with a broad character domain. Apart from the delivery EnvironmentFile control-character rejection, path-like owner inputs may contain spaces, quotes, backslashes, dollar signs and percent signs.

The generated service unit does not yet have one systemd-native serializer for these values:

- credential_gate_command() uses shlex.join(), which serializes for POSIX-shell tokenization rather than systemd.syntax command-line tokenization;
- the main ExecStart line is assembled by direct string interpolation, so whitespace and systemd expansion characters in executable/config paths are not protected as literal argument data;
- EnvironmentFile and WorkingDirectory are rendered from owner paths without an explicit literal-specifier escaping contract;
- systemd Exec command lines perform their own quoting, environment-variable expansion and percent-specifier expansion. A literal percent must be encoded for systemd rather than left to shlex semantics.

The present regression suite proves ordinary temporary paths. The exact gate CLI test executes credential_gate_argv() directly with subprocess, bypassing the unit parser. The real transient proof also uses ordinary paths. The rendered-unit test checks textual presence and systemd-analyze verify, but it does not prove that manager-effective argv for an adversarial yet valid owner path equals the typed input.

Consequence: a config that is valid under ProductionConfigV1 can produce a unit whose manager-effective argv differs from the intended argv or is not loadable. This is a parser-boundary defect, not a credential-value defect.

## 3. Finding F2 — generated project TOML has the same class of typed-input gap

render_project_config() interpolates path and string fields directly inside TOML basic strings.

ProductionConfigV1 does not reject TOML-significant characters such as a double quote or backslash in those path/string fields. Therefore an otherwise valid typed config can produce:

- syntactically invalid generated TOML; or
- TOML that parses successfully but yields a value different from the owner input because an escape sequence was interpreted.

The current production paths do not exercise this edge and the accepted delivery-disabled deployment remains valid. The defect is nevertheless inside the declared typed configuration domain and should be closed before controlled-evolution work.

## 4. Why this does not reverse R3

R3's credential contract, lifecycle revalidation and service-time byte-equality gate are internally coherent and have exact-head CI evidence. The accepted production configuration also uses ordinary paths for which the generated artifacts are already parser-valid.

The new findings concern a broader owner-input serialization domain that the R3 tests did not claim to exercise. They should therefore be closed as a narrow follow-on rather than by reopening the R3 credential semantics.

## 5. Selected next package

Phase 6-F-R4 — Production Artifact Serialization Parity Hardening.

R4 must establish one explicit semantic invariant:

typed non-secret owner input -> rendered systemd/TOML bytes -> parser/manager effective value

must preserve the intended value exactly for every accepted input in the supported character domain.

R4 is deliberately narrow. It must not add providers, enable real notification delivery, change delivery ledger semantics, change monitoring identity/cadence, change strict-v1/investment math, start Bridge/FQGate integration or start Phase 7 controlled evolution.

## 6. Verification policy

R4 is expected to be fully machine-verifiable.

Required evidence includes deterministic fail-on-main regressions, parser round-trip tests, real systemd-analyze verification of rendered edge-character units, a bounded real user-manager execution proof when available, the complete repository gate, and exact-head successful GitHub Actions.

No owner secret, Telegram/webhook credential, reboot, sudo action or real delivery is required for closure.
