# Phase 6-F-R4 coding-agent handoff — Production Artifact Serialization Parity Hardening

Status: READY
Date: 2026-09-29

Canonical goal:
docs/goals/phase-6-f-r4-production-artifact-serialization-hardening.md

Selection audit:
docs/status/phase-6-f-r3-post-closure-review-2026-09-29.md

Baseline main:
7ee61df709b7eee3e45c5d24a989e5de8c613f52

Predecessor R3 implementation:
4f3fa0df9381649c0929135dd7b9480a43d5ea91

Predecessor CI:
GitHub Actions run 36542078579, success, exact head_sha match.

## Goal

Implement Phase 6-F-R4 exactly as the canonical goal specifies.

The core defect is a parser-boundary mismatch, not a credential-semantic redesign:

- ProductionConfigV1 accepts path/string characters that the current generated artifacts do not serialize with a proven semantic round-trip.
- credential_gate_command() uses POSIX-shell shlex.join() for a systemd ExecStartPre line.
- the main ExecStart and several path-bearing unit fields are raw interpolations.
- systemd performs its own quoting, dollar expansion and percent-specifier expansion.
- render_project_config() directly interpolates owner strings into TOML basic strings without a TOML-safe encoder.
- current tests mostly use ordinary paths; direct subprocess execution of credential_gate_argv() bypasses the unit parser.

## Required implementation shape

1. Introduce one systemd-native literal argument/value serialization boundary. Do not use shlex.join() for unit Exec lines.
2. Preserve literal spaces, quotes, backslashes, dollar signs, percent signs, semicolons, hashes and Unicode in every accepted owner path/value where systemd can represent them.
3. Apply the serializer to ExecStartPre, ExecStart and execution-critical path directives including EnvironmentFile/WorkingDirectory as required.
4. Preserve on_calendar as a systemd expression; do not quote away its semantics.
5. Make generated project TOML use a TOML-safe string writer/encoder and prove parsed values equal typed inputs exactly.
6. Strengthen verify to compare manager-effective argv structurally, not by substring.
7. Preserve all R1/R2/R3 credential boundaries and the gate-before-unattended-notify ordering.
8. Do not change investment semantics, delivery ledger semantics or provider behavior.

## Test-first requirement

Before implementation, add focused R4 regressions on pristine baseline 7ee61df709b7eee3e45c5d24a989e5de8c613f52 and record the failing result.

The matrix must include at least:
space, single quote, double quote, backslash, literal dollar sequence, literal %n, semicolon/hash and non-ASCII path text; exact effective ExecStartPre/ExecStart argv; exact EnvironmentFile path; TOML tomllib round-trip; ordinary-input compatibility; and R3 preservation.

Use fake sentinels only. No real notification secret or outbound delivery.

## Automatic verification

Run the complete command set from the canonical R4 goal yourself. In addition:

- run the focused R4 selection separately and record its count;
- run systemd-analyze verify on the edge-character rendered units;
- when a real user manager is available, automatically run the bounded transient argv/gate proof;
- if the private production config is available, run only gate, clean-tree preflight, verify --expect-active and report;
- query GitHub Actions after pushing and close only on exact implementation head_sha success.

Manual owner work is not part of the plan. If an unexpected authority limit genuinely blocks an automatic step, document the exact command, human action, data/secret boundary, exact resume command, machine-checkable success criterion and remaining unverified scope.

## Stop

Stop at R4 closure. Do not start Phase 7, Bridge/FQGate, provider/vendor expansion, Windows autostart, brokerage/trading or investment-rule changes.
