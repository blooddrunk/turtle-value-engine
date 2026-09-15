"""Command-line interface for the deterministic calculation pipeline."""

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Mapping
from datetime import date, timedelta
from pathlib import Path

from pydantic import BaseModel, ValidationError

from turtle_value_engine.backtest import (
    BacktestRunSpec,
    BacktestWorkspace,
    CalibrationObservation,
    CalibrationSearchSpace,
    ChronologicalSplit,
    PortfolioPolicy,
    run_backtest,
    run_calibration,
)
from turtle_value_engine.calculations import CDCCalculationError
from turtle_value_engine.config import ProfileLoadError, load_profile
from turtle_value_engine.historical import (
    AcquisitionError,
    HistoricalAcquisitionPlanV1,
    HistoricalAcquisitionService,
    HistoricalArtifactStore,
    HistoricalDatasetCompiler,
    HistoricalDatasetManifest,
    HistoricalDatasetValidationError,
    HistoricalIngestionCompiler,
    HistoricalResearchArchiveError,
    RawAcquisitionBatchManifestV1,
    RawBlobStore,
    build_readiness_report,
    compile_backtest_manifest,
    freeze_decision_snapshots,
    reconcile_observations,
    validate_historical_dataset,
)
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

    dataset_parser = subparsers.add_parser(
        "dataset",
        help="validate/freeze/report a source-aware offline historical dataset",
    )
    dataset_commands = dataset_parser.add_subparsers(dest="dataset_command", required=True)
    dataset_validate = dataset_commands.add_parser("validate")
    dataset_validate.add_argument("--manifest", required=True, type=Path)
    dataset_validate.add_argument("--store", required=True, type=Path)
    dataset_validate.add_argument("--require-production", action="store_true")
    dataset_freeze = dataset_commands.add_parser("freeze")
    dataset_freeze.add_argument("--manifest", required=True, type=Path)
    dataset_freeze.add_argument("--store", required=True, type=Path)
    dataset_freeze.add_argument("--output", type=Path, default=None)
    dataset_freeze.add_argument("--require-production", action="store_true")
    dataset_coverage = dataset_commands.add_parser("coverage")
    dataset_coverage.add_argument("--manifest", required=True, type=Path)
    dataset_coverage.add_argument("--store", required=True, type=Path)
    dataset_coverage.add_argument("--require-production", action="store_true")
    dataset_snapshot = dataset_commands.add_parser("snapshot")
    dataset_snapshot.add_argument("--manifest", required=True, type=Path)
    dataset_snapshot.add_argument("--store", required=True, type=Path)
    dataset_snapshot.add_argument("--output", type=Path, default=None)
    dataset_snapshot.add_argument("--require-production", action="store_true")
    dataset_reconcile = dataset_commands.add_parser("reconcile")
    dataset_reconcile.add_argument("--target-id", required=True)
    dataset_reconcile.add_argument("--canonical", required=True, type=Path)
    dataset_reconcile.add_argument("--independent", required=True, type=Path)
    dataset_reconcile.add_argument("--canonical-source", required=True)
    dataset_reconcile.add_argument("--independent-source", required=True)
    dataset_reconcile.add_argument("--absolute-tolerance", required=True, type=float)
    dataset_reconcile.add_argument("--relative-tolerance", required=True, type=float)
    dataset_reconcile.add_argument("--report-id", default="reconciliation")
    dataset_reconcile.add_argument("--output", type=Path, default=None)

    historical_parser = subparsers.add_parser(
        "historical",
        help="explicitly opt-in to historical source acquisition or compile raw bytes offline",
    )
    historical_commands = historical_parser.add_subparsers(
        dest="historical_command", required=True
    )
    historical_source = historical_commands.add_parser(
        "source", help="probe a documented source with explicit network opt-in"
    )
    historical_source_commands = historical_source.add_subparsers(
        dest="historical_source_command", required=True
    )
    historical_probe = historical_source_commands.add_parser("probe")
    historical_probe.add_argument("--plan", required=True, type=Path)
    historical_probe.add_argument("--network", choices=("deny", "allow"), default="deny")
    historical_probe.add_argument("--output", type=Path, default=None)
    historical_acquire = historical_commands.add_parser(
        "acquire", help="download exact raw bytes into a private local CAS"
    )
    historical_acquire.add_argument("--plan", required=True, type=Path)
    historical_acquire.add_argument("--network", choices=("deny", "allow"), default="deny")
    historical_acquire.add_argument("--raw-store", required=True, type=Path)
    historical_acquire.add_argument("--batch-output", required=True, type=Path)
    historical_acquire.add_argument("--report-output", type=Path, default=None)
    historical_compile = historical_commands.add_parser(
        "compile", help="compile a previously acquired batch without network access"
    )
    historical_compile.add_argument("--batch", required=True, type=Path)
    historical_compile.add_argument("--raw-store", required=True, type=Path)
    historical_compile.add_argument("--store", required=True, type=Path)
    historical_compile.add_argument("--output", required=True, type=Path)
    historical_compile.add_argument("--report-output", type=Path, default=None)
    historical_compile.add_argument(
        "--verify-replay",
        action="store_true",
        help="compile the same local batch twice and verify identical identities",
    )

    backtest_parser = subparsers.add_parser(
        "backtest",
        help="run an existing offline signal/portfolio backtest from frozen inputs",
    )
    backtest_parser.add_argument("--manifest", required=True, type=Path)
    backtest_parser.add_argument("--store", required=True, type=Path)
    backtest_parser.add_argument("--run-spec", required=True, type=Path)
    backtest_parser.add_argument("--snapshots", type=Path, default=None)
    backtest_parser.add_argument("--policy", type=Path, default=None)
    backtest_parser.add_argument("--workspace", type=Path, default=None)
    backtest_parser.add_argument("--output", type=Path, default=None)
    backtest_parser.add_argument("--require-production", action="store_true")

    calibrate_parser = subparsers.add_parser(
        "calibrate",
        help="run proposal-only calibration against an explicit frozen dataset",
    )
    calibrate_parser.add_argument("--manifest", required=True, type=Path)
    calibrate_parser.add_argument("--store", required=True, type=Path)
    calibrate_parser.add_argument("--search-space", required=True, type=Path)
    calibrate_parser.add_argument("--split", required=True, type=Path)
    calibrate_parser.add_argument("--observations", required=True, type=Path)
    calibrate_parser.add_argument("--base-profile-sha256", required=True)
    calibrate_parser.add_argument("--output", type=Path, default=None)
    calibrate_parser.add_argument("--require-production", action="store_true")
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


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_json_number)


def _reject_json_number(value: str) -> None:
    raise ValueError(f"invalid JSON numeric constant: {value}")


def _write_optional(path: Path | None, result: object) -> None:
    if path is None:
        return
    payload = _json_payload(result)
    _atomic_write(
        path,
        (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )


def _json_payload(result: object) -> object:
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json", warnings=False)
    if isinstance(result, Mapping):
        return {key: _json_payload(value) for key, value in result.items()}
    if isinstance(result, list):
        return [
            item.model_dump(mode="json", warnings=False)
            if isinstance(item, BaseModel)
            else item
            for item in result
        ]
    return result


def _load_historical_manifest_and_store(args: argparse.Namespace):
    manifest = HistoricalDatasetManifest.model_validate(_read_json(args.manifest))
    store = HistoricalArtifactStore(args.store)
    return manifest, store


def _run_dataset(args: argparse.Namespace) -> object:
    if args.dataset_command in {"validate", "coverage", "freeze", "snapshot"}:
        manifest, store = _load_historical_manifest_and_store(args)
        require_production = bool(getattr(args, "require_production", False))
        if args.dataset_command == "validate":
            return validate_historical_dataset(
                manifest,
                store,
                require_production=require_production,
            )
        if args.dataset_command == "coverage":
            summary = validate_historical_dataset(
                manifest,
                store,
                require_production=require_production,
            )
            return {
                "validation": summary,
                "coverage_reports": manifest.coverage_reports,
            }
        compiled = compile_backtest_manifest(
            manifest,
            store,
            require_production=require_production,
        )
        if args.dataset_command == "freeze":
            _write_optional(args.output, compiled)
            return compiled
        snapshots = freeze_decision_snapshots(compiled)
        _write_optional(args.output, snapshots)
        return snapshots
    if args.dataset_command == "reconcile":
        canonical_rows = _read_json(args.canonical)
        independent_rows = _read_json(args.independent)
        if not isinstance(canonical_rows, list) or not isinstance(independent_rows, list):
            raise ValueError("reconciliation input files must contain JSON arrays")

        def to_values(rows: list[object]) -> dict[tuple[str, date], float | None]:
            values: dict[tuple[str, date], float | None] = {}
            for row in rows:
                if not isinstance(row, Mapping):
                    raise ValueError("reconciliation rows must be JSON objects")
                key = (str(row["listing_id"]), date.fromisoformat(str(row["date"])))
                raw_value = row.get("value")
                values[key] = None if raw_value is None else float(raw_value)
            return values

        report = reconcile_observations(
            target_id=args.target_id,
            canonical_source_id=args.canonical_source,
            independent_source_id=args.independent_source,
            canonical_values=to_values(canonical_rows),
            independent_values=to_values(independent_rows),
            absolute_tolerance=args.absolute_tolerance,
            relative_tolerance=args.relative_tolerance,
            report_id=args.report_id,
        )
        _write_optional(args.output, report)
        return report
    raise ValueError(f"unsupported dataset command: {args.dataset_command}")


def _run_backtest_command(args: argparse.Namespace) -> object:
    historical_manifest, store = _load_historical_manifest_and_store(args)
    manifest = compile_backtest_manifest(
        historical_manifest,
        store,
        require_production=args.require_production,
    )
    run_spec = BacktestRunSpec.model_validate(_read_json(args.run_spec))
    if args.snapshots is None:
        snapshots = freeze_decision_snapshots(manifest)
    else:
        raw_snapshots = _read_json(args.snapshots)
        if not isinstance(raw_snapshots, list):
            raise ValueError("--snapshots must contain a JSON array")
        from turtle_value_engine.backtest import DecisionSnapshot

        snapshots = [DecisionSnapshot.model_validate(item) for item in raw_snapshots]
    policy = None
    if args.policy is not None:
        policy = PortfolioPolicy.model_validate(_read_json(args.policy))
    workspace = BacktestWorkspace(args.workspace) if args.workspace is not None else None
    result = run_backtest(manifest, run_spec, snapshots, policy=policy, workspace=workspace)
    _write_optional(args.output, result)
    return result


def _run_calibration_command(args: argparse.Namespace) -> object:
    historical_manifest, store = _load_historical_manifest_and_store(args)
    manifest = compile_backtest_manifest(
        historical_manifest,
        store,
        require_production=args.require_production,
    )
    search_space = CalibrationSearchSpace.model_validate(_read_json(args.search_space))
    split = ChronologicalSplit.model_validate(_read_json(args.split))
    raw_observations = _read_json(args.observations)
    if not isinstance(raw_observations, list):
        raise ValueError("--observations must contain a JSON array")
    observations = [CalibrationObservation.model_validate(item) for item in raw_observations]
    result = run_calibration(
        manifest_id=manifest.dataset_id,
        base_profile_id=search_space.base_profile_id,
        base_profile_sha256=args.base_profile_sha256,
        search_space=search_space,
        split=split,
        observations=observations,
    )
    _write_optional(args.output, result)
    return result


def _load_acquisition_plan(path: Path) -> HistoricalAcquisitionPlanV1:
    return HistoricalAcquisitionPlanV1.model_validate(_read_json(path))


def _run_historical_command(args: argparse.Namespace) -> object:
    if args.historical_command == "source":
        if args.historical_source_command != "probe":
            raise ValueError("unsupported historical source command")
        plan = _load_acquisition_plan(args.plan)
        result = HistoricalAcquisitionService().probe(
            plan,
            network_allowed=args.network == "allow",
        )
        _write_optional(args.output, result)
        return result
    if args.historical_command == "acquire":
        plan = _load_acquisition_plan(args.plan)
        raw_store = RawBlobStore(args.raw_store)
        result = HistoricalAcquisitionService().acquire(
            plan,
            raw_store=raw_store,
            network_allowed=args.network == "allow",
        )
        _write_optional(args.batch_output, result.batch)
        _write_optional(args.report_output, result.readiness)
        return {"batch": result.batch, "readiness": result.readiness}
    if args.historical_command == "compile":
        batch = RawAcquisitionBatchManifestV1.model_validate(_read_json(args.batch))
        raw_store = RawBlobStore(args.raw_store)
        artifact_store = HistoricalArtifactStore(args.store)
        compiler = HistoricalIngestionCompiler(
            raw_store=raw_store,
            artifact_store=artifact_store,
        )
        manifest = (
            compiler.compile_with_replay_check(batch)
            if args.verify_replay
            else compiler.compile(batch)
        )
        _write_optional(args.output, manifest)
        if args.report_output is not None:
            validation = HistoricalDatasetCompiler(
                manifest,
                artifact_store,
            ).validation_summary()
            readiness = build_readiness_report(
                batch.plan,
                batch=batch,
                raw_store=raw_store,
                validation_summary=validation,
                compiled_manifest=manifest,
                network_used=False,
            )
            _write_optional(
                args.report_output,
                {
                    "readiness": readiness,
                    "validation": validation,
                },
            )
        return manifest
    raise ValueError(f"unsupported historical command: {args.historical_command}")


def main(argv: list[str] | None = None) -> int:
    """Run a CLI command and return a shell-compatible exit code."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = _run_prepare(args)
        elif args.command == "dataset":
            result = _run_dataset(args)
        elif args.command == "backtest":
            result = _run_backtest_command(args)
        elif args.command == "calibrate":
            result = _run_calibration_command(args)
        elif args.command == "historical":
            result = _run_historical_command(args)
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
        HistoricalDatasetValidationError,
        HistoricalResearchArchiveError,
        AcquisitionError,
    ) as exc:
        print(f"tve: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(_json_payload(result), ensure_ascii=False, indent=2))
    return 0
