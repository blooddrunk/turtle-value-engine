"""Command-line interface for the deterministic calculation pipeline."""

import argparse
import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

from pydantic import ValidationError

from turtle_value_engine.calculations import CDCCalculationError
from turtle_value_engine.config import ProfileLoadError, load_profile
from turtle_value_engine.input_loader import NormalizedInputLoadError, parse_normalized_input
from turtle_value_engine.models import CDCInput, Company
from turtle_value_engine.pipeline import (
    run_analyze_from_normalized_input,
    run_cdc,
    run_cdc_from_normalized_input,
)
from turtle_value_engine.preparation import (
    AcquisitionRequest,
    NormalizedCompanyInputBuilder,
    PreparationError,
)
from turtle_value_engine.providers import AKShareProvider, FilesystemRawResponseCache


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

    analyze_parser = subparsers.add_parser(
        "analyze",
        help="run the complete offline deterministic CompanyAnalysis pipeline",
    )
    analyze_parser.add_argument("--input", required=True, type=Path)
    analyze_parser.add_argument("--profile", default="strict-v1")
    analyze_parser.add_argument("--rules-dir", type=Path, default=None)
    analyze_parser.add_argument(
        "--cyclical",
        action="store_true",
        default=None,
        help="force full-cycle CDC normalization; otherwise honor the input special_model",
    )

    prepare_parser = subparsers.add_parser(
        "prepare",
        help="acquire/cache/normalize provider data into a frozen normalized input",
    )
    prepare_parser.add_argument("listing_id", help="A/H listing, e.g. 600519.SH or HK00700")
    prepare_parser.add_argument("--as-of", required=True, type=_parse_date)
    prepare_parser.add_argument("--provider", default="akshare")
    prepare_parser.add_argument("--profile", default="strict-v1")
    prepare_parser.add_argument("--rules-dir", type=Path, default=None)
    prepare_parser.add_argument("--analysis-id", default=None)
    prepare_parser.add_argument("--cache-dir", type=Path, default=Path(".tve-cache"))
    prepare_parser.add_argument("--offline", action="store_true")
    prepare_parser.add_argument("--allow-stale", action="store_true")
    prepare_parser.add_argument("--max-age-days", type=float, default=None)
    prepare_parser.add_argument("--output", type=Path, default=None)
    prepare_parser.add_argument(
        "--company-json",
        type=Path,
        default=None,
        help="JSON object containing explicit Company context",
    )
    prepare_parser.add_argument("--name", default=None, help="explicit company name")
    prepare_parser.add_argument("--sector", default=None, help="explicit company sector")
    prepare_parser.add_argument(
        "--reporting-currency",
        default=None,
        help="explicit three-letter reporting currency",
    )
    return parser


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def _prepare_company(args: argparse.Namespace, listing_id: str) -> Company | None:
    if args.company_json is not None and any(
        value is not None for value in (args.name, args.sector, args.reporting_currency)
    ):
        raise ValueError("use either --company-json or the explicit company fields, not both")
    if args.company_json is not None:
        try:
            payload = json.loads(args.company_json.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read --company-json: {exc}") from exc
        if isinstance(payload, dict) and "company" in payload:
            payload = payload["company"]
        return Company.model_validate(payload)
    supplied = (args.name, args.sector, args.reporting_currency)
    if any(value is not None for value in supplied):
        if not all(value is not None for value in supplied):
            raise ValueError("--name, --sector and --reporting-currency must be supplied together")
        return Company(
            name=args.name,
            primary_listing=listing_id,
            sector=args.sector,
            reporting_currency=args.reporting_currency,
        )
    return None


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _run_prepare(args: argparse.Namespace) -> object:
    if args.provider.lower() != "akshare":
        raise ValueError("only the implemented akshare provider is available to `tve prepare`")
    listing_id = AcquisitionRequest(
        listing_id=args.listing_id,
        as_of=args.as_of,
        provider=args.provider,
        analysis_id=args.analysis_id,
        profile_id=args.profile,
    )
    company = _prepare_company(args, listing_id.listing_id)
    provider = AKShareProvider()
    cache = FilesystemRawResponseCache(args.cache_dir)
    builder = NormalizedCompanyInputBuilder(provider, cache)
    max_age = (
        None if args.max_age_days is None else timedelta(days=args.max_age_days)
    )
    _bundle, normalized = builder.prepare(
        listing_id,
        company=company,
        offline=args.offline,
        max_age=max_age,
        allow_stale=args.allow_stale,
    )
    serialized = json.dumps(
        normalized.model_dump(mode="json"), ensure_ascii=False, indent=2
    ).encode("utf-8") + b"\n"
    if args.output is not None:
        _atomic_write(args.output, serialized)
    return normalized


def main(argv: list[str] | None = None) -> int:
    """Run a CLI command and return a shell-compatible exit code."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = _run_prepare(args)
        else:
            raw_input = args.input.read_bytes()
            profile = load_profile(args.profile, rules_dir=args.rules_dir)
            if args.command == "analyze":
                normalized_input = parse_normalized_input(raw_input)
                result = run_analyze_from_normalized_input(
                    normalized_input,
                    profile,
                    cyclical=args.cyclical,
                )
            else:
                try:
                    inputs = CDCInput.model_validate_json(raw_input)
                except ValidationError:
                    normalized_input = parse_normalized_input(raw_input)
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
        NormalizedInputLoadError,
        PreparationError,
        ValidationError,
        ValueError,
    ) as exc:
        print(f"tve: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0
