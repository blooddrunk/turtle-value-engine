"""Export the deterministic OpenAPI contract for the read-only surface API."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "schemas" / "research-surface-api-v1.openapi.json"


def _build_openapi() -> dict[str, object]:
    import tempfile

    from turtle_value_engine import load_normalized_input
    from turtle_value_engine.monitoring_operations import (
        MonitoringOperationsReadService,
        MonitoringOperationsSourcesV1,
    )
    from turtle_value_engine.pipeline import run_analyze
    from turtle_value_engine.surface import (
        SurfaceRegistry,
        build_research_surface_snapshot,
        create_surface_app,
    )

    analysis = run_analyze(
        load_normalized_input(ROOT / "fixtures" / "healthy_cash_cow.json")
    )
    snapshot = build_research_surface_snapshot(analysis)
    # The monitoring route is registered over explicit placeholder sources;
    # construction alone performs no store I/O, and the paths never enter the
    # exported document (the response model is the projection contract).
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        sources = MonitoringOperationsSourcesV1(
            runner_id="openapi-export",
            watchlist_path=str(tmp_path / "watchlist.json"),
            monitoring_workspace_root=str(tmp_path / "workspace"),
            reanalysis_job_root=str(tmp_path / "jobs"),
            cycle_store_root=str(tmp_path / "cycles"),
            runner_root=str(tmp_path / "runner"),
            delivery_root=None,
        )
        app = create_surface_app(
            SurfaceRegistry.from_snapshots([snapshot]),
            monitoring_service=MonitoringOperationsReadService(sources),
        )
        return app.openapi()


def _canonical_bytes(document: dict[str, object]) -> bytes:
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="checked-in OpenAPI output path",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when the checked-in document differs from the deterministic export",
    )
    args = parser.parse_args(argv)

    generated = _canonical_bytes(_build_openapi())
    output = args.output if args.output.is_absolute() else ROOT / args.output

    if args.check:
        try:
            current = output.read_bytes()
        except FileNotFoundError:
            print(f"OpenAPI export is missing: {output}", file=sys.stderr)
            return 1
        if current != generated:
            print(
                f"OpenAPI export is stale: {output}; rerun without --check to update it",
                file=sys.stderr,
            )
            return 1
        print(f"OpenAPI export is deterministic and current: {output}")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(generated)
    print(f"Wrote deterministic OpenAPI export: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
