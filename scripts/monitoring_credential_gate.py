"""Phase 6-F-R3 service-execution credential gate (``ExecStartPre=`` helper).

This is the dedicated non-secret CLI rendered ahead of the unchanged
``unattended-notify`` ``ExecStart=`` in every delivery-enabled production
service unit.  It exists only to run :func:`run_credential_gate` from
``scripts.monitoring_production_ops`` inside the service context systemd
prepared — including the environment injected from the unit's
``EnvironmentFile=`` — and to fail closed (nonzero) before
``unattended-notify`` executes whenever:

- the private credential file violates the R1 metadata/path/type/mode
  boundary;
- its content leaves the R2 canonical ``NAME=VALUE`` subset, is missing a
  referenced name, or carries systemd-invalid Unicode anywhere in the file
  (R3);
- any referenced value in the inherited service environment does not
  byte-match the canonical parser's current in-memory value.

Discipline: argv and output carry only non-secret paths, reference names,
categories and status.  No credential value, digest, HMAC or fingerprint is
ever read into an artifact, printed or persisted; drift detection always
re-reads the private file in memory.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _entry in (str(ROOT), str(ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from scripts.monitoring_production_ops import run_credential_gate  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="monitoring_credential_gate.py",
        description=(
            "Phase 6-F-R3 systemd ExecStartPre credential gate: revalidate the "
            "current private credential contract and prove byte equality with "
            "the inherited service environment, value-free"
        ),
    )
    parser.add_argument(
        "--environment-file",
        required=True,
        help="the private systemd EnvironmentFile path (non-secret fact)",
    )
    parser.add_argument(
        "--production-root",
        required=True,
        help="the production private root for containment checks (non-secret fact)",
    )
    parser.add_argument(
        "--reference",
        action="append",
        required=True,
        dest="references",
        help="a referenced secret environment name (repeatable, non-secret fact)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    code, payload = run_credential_gate(
        environment_file=args.environment_file,
        production_root=args.production_root,
        referenced_names=tuple(args.references),
    )
    print(json.dumps(payload, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
