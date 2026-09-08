"""Command-line interface for the deterministic milestones."""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from turtle_value_engine.calculations import CDCCalculationError
from turtle_value_engine.config import ProfileLoadError, load_profile
from turtle_value_engine.models import CDCInput, NormalizedCompanyInput
from turtle_value_engine.pipeline import run_cdc, run_cdc_from_normalized_input


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tve")
    subparsers = parser.add_subparsers(dest="command", required=True)

    cdc_parser = subparsers.add_parser(
        "cdc", help="calculate the implemented deterministic CDC stage"
    )
    cdc_parser.add_argument("--input", required=True, type=Path)
    cdc_parser.add_argument("--profile", default="strict-v1")
    cdc_parser.add_argument("--rules-dir", type=Path, default=None)
    cdc_parser.add_argument(
        "--market-cap",
        type=float,
        default=None,
        help="listing-equivalent market cap when it is not present in the input facts",
    )
    cdc_parser.add_argument(
        "--cyclical",
        action="store_true",
        help="use the configured full-cycle CDC normalization method",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run a CLI command and return a shell-compatible exit code."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command != "cdc":
        parser.error(f"unsupported command: {args.command}")

    try:
        raw_input = json.loads(args.input.read_text(encoding="utf-8"))
        profile = load_profile(args.profile, rules_dir=args.rules_dir)
        try:
            inputs = CDCInput.model_validate(raw_input)
        except ValidationError:
            normalized_input = NormalizedCompanyInput.model_validate(raw_input)
            result = run_cdc_from_normalized_input(
                normalized_input,
                profile,
                current_market_cap=args.market_cap,
                cyclical=args.cyclical,
            )
        else:
            if args.market_cap is not None or args.cyclical:
                inputs = inputs.model_copy(
                    update={
                        "current_market_cap": args.market_cap
                        if args.market_cap is not None
                        else inputs.current_market_cap,
                        "cyclical": args.cyclical or inputs.cyclical,
                    }
                )
            result = run_cdc(inputs, profile)
    except (
        OSError,
        ProfileLoadError,
        CDCCalculationError,
        ValidationError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        print(f"tve: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0
