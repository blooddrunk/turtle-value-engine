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
from turtle_value_engine.config import (
    ProfileLoadError,
    ProjectConfigError,
    load_profile,
    load_project_config,
    write_project_config_template,
)
from turtle_value_engine.historical import (
    AcquisitionError,
    AcquisitionReadinessReportV1,
    FilesystemArtifactObjectStore,
    HistoricalAcquisitionPlanV1,
    HistoricalAcquisitionService,
    HistoricalArtifactMirrorManifest,
    HistoricalArtifactStore,
    HistoricalDatasetCompiler,
    HistoricalDatasetManifest,
    HistoricalDatasetValidationError,
    HistoricalIngestionCompiler,
    HistoricalReconciliationSampleSpec,
    HistoricalResearchArchiveError,
    RawAcquisitionBatchManifestV1,
    RawBlobStore,
    S3CompatibleArtifactObjectStore,
    build_historical_artifact_mirror_manifest,
    build_readiness_report,
    compile_backtest_manifest,
    freeze_decision_snapshots,
    pull_historical_artifact_mirror,
    push_historical_artifact_mirror,
    reconcile_observations,
    reconcile_sampled_market_bars_from_artifacts,
    validate_historical_dataset,
    validate_private_acceptance,
    verify_historical_artifact_mirror,
)
from turtle_value_engine.input_loader import NormalizedInputLoadError, parse_normalized_input
from turtle_value_engine.models import CDCInput, Company, CompanyAnalysis
from turtle_value_engine.monitoring import (
    MonitoringEventBatchV1,
    MonitoringWorkspace,
    WatchlistSpecV1,
    build_event_batch,
    run_monitoring,
)
from turtle_value_engine.monitoring.canonical import to_utc_datetime
from turtle_value_engine.monitoring_cycle import (
    CninfoCycleAcquisition,
    MonitoringCycleRunner,
    MonitoringCycleSpecV1,
    MonitoringCycleStore,
    MonitoringExecutionCatalogV1,
)
from turtle_value_engine.monitoring_delivery import (
    DeliveryLedgerStore,
    DeliverySettingsV1,
    MonitoringDeliveryService,
    WebhookHttpTransport,
)
from turtle_value_engine.monitoring_execution import (
    ReanalysisExecutor,
    ReanalysisJobStore,
)
from turtle_value_engine.monitoring_runner import (
    MonitoringRunnerService,
    RunnerConfigV1,
    RunnerLease,
    RunnerLeaseBusyError,
    RunnerStore,
    UnattendedCycleBoundary,
)
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
from turtle_value_engine.surface import (
    build_research_surface_snapshot,
    load_research_surface_snapshot,
)


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
    dataset_reconcile_artifacts = dataset_commands.add_parser(
        "reconcile-artifacts",
        help="reconcile two frozen A-share MARKET_BAR manifests under an M4 sample",
    )
    dataset_reconcile_artifacts.add_argument("--sample", required=True, type=Path)
    dataset_reconcile_artifacts.add_argument("--canonical-manifest", required=True, type=Path)
    dataset_reconcile_artifacts.add_argument("--canonical-store", required=True, type=Path)
    dataset_reconcile_artifacts.add_argument(
        "--independent-manifest", required=True, type=Path
    )
    dataset_reconcile_artifacts.add_argument("--independent-store", required=True, type=Path)
    dataset_reconcile_artifacts.add_argument("--report-store", type=Path, default=None)
    dataset_reconcile_artifacts.add_argument("--report-id", default=None)
    dataset_reconcile_artifacts.add_argument("--output", type=Path, default=None)

    artifacts_parser = subparsers.add_parser(
        "artifacts",
        help="move explicitly declared frozen artifacts between offline backends",
    )
    artifacts_commands = artifacts_parser.add_subparsers(
        dest="artifacts_command", required=True
    )
    artifacts_mirror = artifacts_commands.add_parser(
        "mirror",
        help="plan, push, verify or pull a declared historical dataset mirror",
    )
    mirror_commands = artifacts_mirror.add_subparsers(
        dest="mirror_command", required=True
    )
    mirror_plan = mirror_commands.add_parser("plan", help="build a mirror manifest offline")
    mirror_plan.add_argument("--manifest", required=True, type=Path)
    mirror_plan.add_argument("--store", required=True, type=Path)
    mirror_plan.add_argument("--output", type=Path, default=None)
    mirror_push = mirror_commands.add_parser(
        "push",
        help="push declared objects to the selected artifact backend",
    )
    mirror_push.add_argument("--mirror-manifest", required=True, type=Path)
    mirror_push.add_argument("--manifest", required=True, type=Path)
    mirror_push.add_argument("--store", required=True, type=Path)
    mirror_push.add_argument("--destination", type=Path, default=None)
    mirror_push.add_argument("--backend", choices=("filesystem", "s3"), default="filesystem")
    mirror_push.add_argument("--remote-config", type=Path, default=None)
    mirror_push.add_argument("--network", choices=("deny", "allow"), default="deny")
    mirror_push.add_argument("--output", type=Path, default=None)
    mirror_verify = mirror_commands.add_parser(
        "verify", help="verify every declared object in the selected artifact backend"
    )
    mirror_verify.add_argument("--mirror-manifest", required=True, type=Path)
    mirror_verify.add_argument("--destination", type=Path, default=None)
    mirror_verify.add_argument("--backend", choices=("filesystem", "s3"), default="filesystem")
    mirror_verify.add_argument("--remote-config", type=Path, default=None)
    mirror_verify.add_argument("--network", choices=("deny", "allow"), default="deny")
    mirror_verify.add_argument("--output", type=Path, default=None)
    mirror_pull = mirror_commands.add_parser(
        "pull", help="restore and validate a declared mirror from the selected backend"
    )
    mirror_pull.add_argument("--mirror-manifest", required=True, type=Path)
    mirror_pull.add_argument("--source", type=Path, default=None)
    mirror_pull.add_argument("--target", required=True, type=Path)
    mirror_pull.add_argument("--backend", choices=("filesystem", "s3"), default="filesystem")
    mirror_pull.add_argument("--remote-config", type=Path, default=None)
    mirror_pull.add_argument("--network", choices=("deny", "allow"), default="deny")
    mirror_pull.add_argument("--output", type=Path, default=None)

    surface_parser = subparsers.add_parser(
        "surface",
        help="build or validate an offline read-only research surface",
    )
    surface_commands = surface_parser.add_subparsers(
        dest="surface_command", required=True
    )
    surface_build = surface_commands.add_parser(
        "build",
        help="project explicit frozen analysis/research artifacts",
    )
    surface_build.add_argument("--analysis", required=True, type=Path)
    surface_build.add_argument("--trace", type=Path, default=None)
    surface_build.add_argument("--report", type=Path, default=None)
    surface_build.add_argument("--historical-manifest", type=Path, default=None)
    surface_build.add_argument("--acceptance", type=Path, default=None)
    surface_build.add_argument("--readiness", type=Path, default=None)
    surface_build.add_argument("--validation", type=Path, default=None)
    surface_build.add_argument("--output", required=True, type=Path)
    surface_validate = surface_commands.add_parser(
        "validate",
        help="validate one persisted research surface snapshot",
    )
    surface_validate.add_argument("--input", required=True, type=Path)
    surface_serve = surface_commands.add_parser(
        "serve",
        help="serve explicitly supplied validated research surfaces over loopback",
    )
    surface_serve.add_argument(
        "--snapshot",
        action="append",
        required=True,
        type=Path,
        help="explicit ResearchSurfaceSnapshotV1 JSON path; repeat for multiple surfaces",
    )
    surface_serve.add_argument("--host", default="127.0.0.1")
    surface_serve.add_argument("--port", default=8787, type=int)
    surface_serve.add_argument(
        "--allow-non-loopback",
        action="store_true",
        help="explicitly permit a non-loopback bind address",
    )
    surface_serve.add_argument(
        "--monitoring-runner-config",
        type=Path,
        default=None,
        help="explicit RunnerConfigV1 JSON path enabling the read-only "
        "monitoring operations endpoint",
    )
    surface_serve.add_argument(
        "--monitoring-project-config",
        type=Path,
        default=None,
        help="explicit project TOML path supplying the delivery ledger root "
        "for the monitoring endpoint",
    )

    config_parser = subparsers.add_parser(
        "config",
        help="create or validate the project-wide non-secret runtime configuration",
    )
    config_commands = config_parser.add_subparsers(
        dest="config_command", required=True
    )
    config_init = config_commands.add_parser(
        "init",
        help="write config/project.example.toml to a private local path",
    )
    config_init.add_argument(
        "--output", type=Path, default=Path(".tve-private/project.toml")
    )
    config_init.add_argument(
        "--force",
        action="store_true",
        help="overwrite the selected path explicitly",
    )
    config_validate = config_commands.add_parser(
        "validate",
        help="validate one project TOML file and print only a safe summary",
    )
    config_validate.add_argument(
        "--input", type=Path, default=Path(".tve-private/project.toml")
    )

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
    historical_accept = historical_commands.add_parser(
        "accept", help="audit a private A/H corpus using offline artifacts only"
    )
    historical_accept.add_argument("--batch", required=True, type=Path)
    historical_accept.add_argument("--probe-report", required=True, type=Path)
    historical_accept.add_argument("--raw-store", required=True, type=Path)
    historical_accept.add_argument("--manifest", required=True, type=Path)
    historical_accept.add_argument("--store", required=True, type=Path)
    historical_accept.add_argument("--output", required=True, type=Path)

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

    watch_parser = subparsers.add_parser(
        "watch",
        help="deterministic watchlist monitoring (offline by default; live "
        "acquisition requires explicit network opt-in)",
    )
    watch_commands = watch_parser.add_subparsers(dest="watch_command", required=True)
    watch_validate = watch_commands.add_parser(
        "validate", help="validate a watchlist specification offline"
    )
    watch_validate.add_argument("--watchlist", required=True, type=Path)
    watch_replay = watch_commands.add_parser(
        "replay",
        help="plan and atomically commit one monitoring run from frozen events",
    )
    watch_replay.add_argument("--watchlist", required=True, type=Path)
    watch_replay.add_argument("--events", required=True, type=Path)
    watch_replay.add_argument("--workspace", required=True, type=Path)
    watch_replay.add_argument("--as-of", required=True, type=_parse_datetime)
    watch_replay.add_argument("--output", type=Path, default=None)
    watch_status = watch_commands.add_parser(
        "status", help="read the committed watchlist monitoring state"
    )
    watch_status.add_argument("--workspace", required=True, type=Path)
    watch_status.add_argument("--watchlist-id", required=True)
    watch_execute = watch_commands.add_parser(
        "execute-reanalysis",
        help="execute only requests from one committed monitoring run",
    )
    watch_execute.add_argument("--workspace", required=True, type=Path)
    watch_execute.add_argument("--run-id", required=True)
    watch_execute.add_argument("--job-root", required=True, type=Path)
    watch_execute.add_argument("--listing", default=None)
    watch_execute.add_argument("--request-id", default=None)
    watch_execute.add_argument("--network", choices=("deny", "allow"), default="deny")
    watch_execute.add_argument("--provider", default="akshare")
    watch_execute.add_argument("--cache-dir", type=Path, default=Path(".tve-cache"))
    watch_execute.add_argument("--prepared-input", type=Path, default=None)
    watch_execute.add_argument("--prior-analysis", type=Path, default=None)
    watch_execute.add_argument("--research-root", type=Path, default=None)
    watch_execute.add_argument(
        "--company-json",
        type=Path,
        default=None,
        help="explicit Company context used when preparation is performed",
    )
    watch_execute.add_argument("--name", default=None)
    watch_execute.add_argument("--sector", default=None)
    watch_execute.add_argument("--reporting-currency", default=None)
    watch_status_reanalysis = watch_commands.add_parser(
        "reanalysis-status",
        help="read one persisted Phase 6-C re-analysis job",
    )
    watch_status_reanalysis.add_argument("--job-root", required=True, type=Path)
    watch_status_reanalysis.add_argument("--job-id", required=True)
    watch_acquire = watch_commands.add_parser(
        "acquire-events",
        help="acquire official filing events into a canonical batch "
        "(explicit network opt-in; Phase 6-B)",
    )
    watch_acquire.add_argument(
        "--source", default="CNINFO", choices=("CNINFO",)
    )
    watch_acquire.add_argument(
        "--listing",
        action="append",
        default=None,
        help="canonical listing id, e.g. SH600519; repeatable",
    )
    watch_acquire.add_argument(
        "--watchlist",
        type=Path,
        default=None,
        help="take the enabled listing scope from a watchlist file",
    )
    watch_acquire.add_argument(
        "--from",
        dest="published_from",
        type=_parse_date,
        default=None,
        help="explicit window start (required unless derived from a committed cursor)",
    )
    watch_acquire.add_argument("--to", dest="published_to", required=True, type=_parse_date)
    watch_acquire.add_argument("--limit", type=_acquire_limit, default=30)
    watch_acquire.add_argument("--as-of", type=_parse_datetime, default=None)
    watch_acquire.add_argument("--cache-dir", type=Path, default=None)
    watch_acquire.add_argument("--output", type=Path, default=None)
    watch_acquire.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="read-only: derive the window start from the committed cursor",
    )
    watch_acquire.add_argument("--network", choices=("deny", "allow"), default="deny")
    watch_acquire.add_argument(
        "--from-cache",
        action="store_true",
        help="offline replay from the persisted raw cache (no network)",
    )
    watch_acquire.add_argument("--timeout-seconds", type=_acquire_timeout, default=15.0)
    watch_acquire.add_argument(
        "--max-response-bytes", type=_acquire_max_bytes, default=512 * 1024
    )
    watch_cycle = watch_commands.add_parser(
        "cycle",
        help="run one synchronous Phase 6-D1 monitoring cycle",
    )
    watch_cycle.add_argument("--watchlist", required=True, type=Path)
    watch_cycle.add_argument("--workspace", required=True, type=Path)
    watch_cycle.add_argument("--job-root", required=True, type=Path)
    watch_cycle.add_argument("--cycle-root", required=True, type=Path)
    watch_cycle.add_argument("--as-of", required=True, type=_parse_datetime)
    watch_cycle.add_argument(
        "--from", dest="published_from", required=True, type=_parse_date
    )
    watch_cycle.add_argument("--to", dest="published_to", required=True, type=_parse_date)
    watch_cycle.add_argument("--source", choices=("CNINFO",), default="CNINFO")
    watch_cycle.add_argument("--adapter-version", default=None)
    watch_cycle.add_argument("--acquisition-policy-id", default="monitoring-acquisition-v1")
    watch_cycle.add_argument("--limit", type=_acquire_limit, default=30)
    watch_cycle.add_argument("--network", choices=("deny", "allow"), default="deny")
    watch_cycle.add_argument(
        "--from-cache",
        action="store_true",
        help="replay Phase 6-B raw cache with sockets unused",
    )
    watch_cycle.add_argument("--cache-dir", type=Path, default=Path(".tve-cache"))
    watch_cycle.add_argument("--execution-catalog", type=Path, default=None)
    watch_cycle.add_argument("--timeout-seconds", type=_acquire_timeout, default=15.0)
    watch_cycle.add_argument(
        "--max-response-bytes", type=_acquire_max_bytes, default=512 * 1024
    )
    watch_cycle.add_argument("--output", type=Path, default=None)
    watch_cycle_status = watch_commands.add_parser(
        "cycle-status", help="read one terminal Phase 6-D1 cycle and alert outbox"
    )
    watch_cycle_status.add_argument("--cycle-root", required=True, type=Path)
    watch_cycle_status.add_argument("--cycle-id", required=True)
    watch_unattended_run = watch_commands.add_parser(
        "unattended-run",
        help="run one durable Phase 6-D2A unattended monitoring activation",
    )
    watch_unattended_run.add_argument("--runner-config", required=True, type=Path)
    watch_unattended_run.add_argument("--output", type=Path, default=None)
    watch_unattended_status = watch_commands.add_parser(
        "unattended-status",
        help="read the durable Phase 6-D2A unattended runner state",
    )
    watch_unattended_status.add_argument("--runner-root", required=True, type=Path)
    watch_unattended_status.add_argument("--runner-id", default=None)
    watch_unattended_status.add_argument("--activation-id", default=None)
    watch_deliver = watch_commands.add_parser(
        "deliver",
        help="deliver one terminal D2A/D1 alert outbox through the Phase 6-D2B "
        "notification boundary",
    )
    watch_deliver.add_argument("--runner-config", required=True, type=Path)
    watch_deliver.add_argument("--project-config", required=True, type=Path)
    watch_deliver.add_argument("--activation-id", default=None)
    watch_deliver.add_argument("--network", choices=("deny", "allow"), default="deny")
    watch_deliver.add_argument("--output", type=Path, default=None)
    watch_delivery_status = watch_commands.add_parser(
        "delivery-status",
        help="read the durable Phase 6-D2B delivery ledger state",
    )
    watch_delivery_status.add_argument("--delivery-root", required=True, type=Path)
    watch_delivery_status.add_argument("--delivery-id", default=None)
    watch_delivery_status.add_argument("--activation-id", default=None)
    return parser


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def _parse_datetime(value: str) -> object:
    try:
        return to_utc_datetime(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "as-of must be an ISO-8601 datetime, e.g. 2026-06-01T00:00:00+00:00"
        ) from exc


def _acquire_limit(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("limit must be an integer") from exc
    if not 1 <= parsed <= 30:
        raise argparse.ArgumentTypeError(
            "limit must be between 1 and 30 (one bounded CNINFO page)"
        )
    return parsed


def _acquire_timeout(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout-seconds must be a number") from exc
    if not 0 < parsed <= 60:
        raise argparse.ArgumentTypeError("timeout-seconds must be in (0, 60]")
    return parsed


def _acquire_max_bytes(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("max-response-bytes must be an integer") from exc
    if not 1024 <= parsed <= 8 * 1024 * 1024:
        raise argparse.ArgumentTypeError(
            "max-response-bytes must be between 1 KiB and 8 MiB"
        )
    return parsed


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


def _run_config_command(args: argparse.Namespace) -> object:
    if args.config_command == "init":
        output = write_project_config_template(args.output, force=args.force)
        return {
            "status": "created",
            "path": str(output),
            "message": "edit only non-secret values; keep credential values in the environment",
        }
    if args.config_command == "validate":
        config = load_project_config(args.input)
        return {"status": "valid", **config.safe_summary()}
    raise ValueError(f"unsupported config command: {args.config_command}")


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
    if args.dataset_command == "reconcile-artifacts":
        if args.output is None and args.report_store is None:
            raise ValueError("reconcile-artifacts requires --output or --report-store")
        sample = HistoricalReconciliationSampleSpec.model_validate(_read_json(args.sample))
        canonical_manifest = HistoricalDatasetManifest.model_validate(
            _read_json(args.canonical_manifest)
        )
        independent_manifest = HistoricalDatasetManifest.model_validate(
            _read_json(args.independent_manifest)
        )
        report_store = (
            HistoricalArtifactStore(args.report_store) if args.report_store is not None else None
        )
        report = reconcile_sampled_market_bars_from_artifacts(
            sample=sample,
            canonical_manifest=canonical_manifest,
            canonical_store=HistoricalArtifactStore(args.canonical_store),
            independent_manifest=independent_manifest,
            independent_store=HistoricalArtifactStore(args.independent_store),
            report_store=report_store,
            report_id=args.report_id,
        )
        _write_optional(args.output, report)
        return report
    raise ValueError(f"unsupported dataset command: {args.dataset_command}")


def _load_mirror_manifest(path: Path) -> HistoricalArtifactMirrorManifest:
    return HistoricalArtifactMirrorManifest.model_validate(_read_json(path))


def _artifact_mirror_backend(args: argparse.Namespace, *, argument: str):
    backend = getattr(args, "backend", "filesystem")
    if backend == "filesystem":
        root = getattr(args, argument, None)
        if root is None:
            raise ValueError(f"filesystem mirror backend requires --{argument}")
        if getattr(args, "remote_config", None) is not None:
            raise ValueError("--remote-config is only valid with --backend s3")
        return FilesystemArtifactObjectStore(root)
    if backend != "s3":
        raise ValueError(f"unsupported artifact mirror backend: {backend}")
    config_path = getattr(args, "remote_config", None)
    if config_path is None:
        raise ValueError("S3 mirror backend requires --remote-config")
    return S3CompatibleArtifactObjectStore(
        _read_json(config_path),
        network_allowed=getattr(args, "network", "deny") == "allow",
    )


def _run_artifacts(args: argparse.Namespace) -> object:
    if args.artifacts_command != "mirror":
        raise ValueError(f"unsupported artifacts command: {args.artifacts_command}")
    mirror_manifest = (
        _load_mirror_manifest(args.mirror_manifest)
        if args.mirror_command != "plan"
        else None
    )
    if args.mirror_command == "plan":
        manifest = HistoricalDatasetManifest.model_validate(_read_json(args.manifest))
        mirror_manifest = build_historical_artifact_mirror_manifest(
            manifest,
            HistoricalArtifactStore(args.store),
        )
        _write_optional(args.output, mirror_manifest)
        return mirror_manifest
    if args.mirror_command == "push":
        source_manifest = HistoricalDatasetManifest.model_validate(_read_json(args.manifest))
        keys = push_historical_artifact_mirror(
            mirror_manifest,
            source_manifest,
            HistoricalArtifactStore(args.store),
            _artifact_mirror_backend(args, argument="destination"),
        )
        result = {
            "mirror_id": mirror_manifest.mirror_id,
            "verified": True,
            "object_keys": list(keys),
        }
        _write_optional(args.output, result)
        return result
    if args.mirror_command == "verify":
        keys = verify_historical_artifact_mirror(
            mirror_manifest,
            _artifact_mirror_backend(args, argument="destination"),
        )
        result = {
            "mirror_id": mirror_manifest.mirror_id,
            "verified": True,
            "object_keys": list(keys),
        }
        _write_optional(args.output, result)
        return result
    if args.mirror_command == "pull":
        restored = pull_historical_artifact_mirror(
            mirror_manifest,
            _artifact_mirror_backend(args, argument="source"),
            args.target,
        )
        result = {
            "mirror_id": mirror_manifest.mirror_id,
            "dataset_id": restored.manifest.dataset_id,
            "target": str(args.target),
            "validated": restored.validation.valid,
            "validation": restored.validation,
        }
        _write_optional(args.output, result)
        return result
    raise ValueError(f"unsupported mirror command: {args.mirror_command}")


def _run_surface(args: argparse.Namespace) -> object:
    if args.surface_command == "serve":
        from turtle_value_engine.monitoring_operations import sources_from_runner_config
        from turtle_value_engine.surface.api import serve_surface_snapshots

        monitoring_sources = None
        if args.monitoring_runner_config is not None:
            runner_config = _load_runner_config(args.monitoring_runner_config)
            delivery_root = None
            if args.monitoring_project_config is not None:
                project_config = load_project_config(args.monitoring_project_config)
                delivery_root = str(
                    project_config.resolve_path(
                        project_config.monitoring.delivery.delivery_root
                    )
                )
            monitoring_sources = sources_from_runner_config(
                runner_config, delivery_root=delivery_root
            )
        elif args.monitoring_project_config is not None:
            raise ValueError(
                "--monitoring-project-config requires --monitoring-runner-config"
            )
        return serve_surface_snapshots(
            args.snapshot,
            host=args.host,
            port=args.port,
            allow_non_loopback=args.allow_non_loopback,
            monitoring_sources=monitoring_sources,
        )
    if args.surface_command == "build":
        snapshot = build_research_surface_snapshot(
            _read_json(args.analysis),
            decision_trace=None if args.trace is None else _read_json(args.trace),
            research_report=None if args.report is None else _read_json(args.report),
            historical_manifest=(
                None
                if args.historical_manifest is None
                else _read_json(args.historical_manifest)
            ),
            historical_acceptance=(
                None if args.acceptance is None else _read_json(args.acceptance)
            ),
            historical_readiness=(
                None if args.readiness is None else _read_json(args.readiness)
            ),
            historical_validation=(
                None if args.validation is None else _read_json(args.validation)
            ),
        )
        _atomic_write(args.output, snapshot.canonical_bytes())
        return snapshot
    if args.surface_command == "validate":
        return load_research_surface_snapshot(args.input)
    raise ValueError(f"unsupported surface command: {args.surface_command}")


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


def _validation_blocker(exc: ValidationError) -> str:
    errors = exc.errors()
    first = errors[0] if errors else {}
    location = ".".join(str(part) for part in first.get("loc", ()))
    message = str(first.get("msg", "invalid payload")).removeprefix("Value error, ")
    return f"{location}: {message}" if location else message


def _load_watchlist(path: Path) -> WatchlistSpecV1:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"watchlist file must contain a JSON object: {path}")
    try:
        return WatchlistSpecV1.build(**payload)
    except ValidationError as exc:
        raise ValueError(
            f"invalid watchlist {path}: {_validation_blocker(exc)}"
        ) from exc


def _load_event_batch(path: Path) -> MonitoringEventBatchV1:
    payload = _read_json(path)
    if isinstance(payload, dict):
        if payload.get("contract") != "monitoring_event_batch_v1":
            raise ValueError(
                f"events file must be a JSON array or a monitoring_event_batch_v1 "
                f"object: {path}"
            )
        try:
            return MonitoringEventBatchV1.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(
                f"invalid event batch {path}: {_validation_blocker(exc)}"
            ) from exc
    if isinstance(payload, list):
        if not all(isinstance(item, dict) for item in payload):
            raise ValueError(f"events array entries must be JSON objects: {path}")
        try:
            return build_event_batch(payload)
        except ValidationError as exc:
            raise ValueError(
                f"invalid monitoring event in {path}: {_validation_blocker(exc)}"
            ) from exc
    raise ValueError(f"events file must be a JSON array or a batch object: {path}")


def _run_watch_command(args: argparse.Namespace) -> object:
    if args.watch_command == "validate":
        return _load_watchlist(args.watchlist)
    if args.watch_command == "replay":
        watchlist = _load_watchlist(args.watchlist)
        batch = _load_event_batch(args.events)
        workspace = MonitoringWorkspace(args.workspace)
        prior_state = workspace.load_current_state(watchlist.watchlist_id)
        run = run_monitoring(
            watchlist,
            batch,
            prior_state,
            to_utc_datetime(args.as_of),
        )
        workspace.commit_run(run, watchlist=watchlist, batch=batch)
        _write_optional(args.output, run)
        return run
    if args.watch_command == "status":
        workspace = MonitoringWorkspace(args.workspace)
        return workspace.status(args.watchlist_id)
    if args.watch_command == "execute-reanalysis":
        return _run_watch_execute_reanalysis(args)
    if args.watch_command == "reanalysis-status":
        store = ReanalysisJobStore(args.job_root)
        attempt = store.load_latest(args.job_id)
        if attempt is None:
            raise ValueError("re-analysis job was not found")
        return {
            "attempt_id": attempt.attempt_id,
            "attempt_number": attempt.attempt_number,
            "job": attempt.job,
        }
    if args.watch_command == "acquire-events":
        return _run_watch_acquire_events(args)
    if args.watch_command == "cycle":
        return _run_watch_cycle(args)
    if args.watch_command == "cycle-status":
        status = MonitoringCycleStore(args.cycle_root).load_status(args.cycle_id)
        if status is None:
            raise ValueError("monitoring cycle was not found")
        return status
    if args.watch_command == "unattended-run":
        return _run_watch_unattended_run(args)
    if args.watch_command == "unattended-status":
        return _run_watch_unattended_status(args)
    if args.watch_command == "deliver":
        return _run_watch_deliver(args)
    if args.watch_command == "delivery-status":
        return _run_watch_delivery_status(args)
    raise ValueError(f"unsupported watch command: {args.watch_command}")


def _load_execution_catalog(path: Path | None) -> MonitoringExecutionCatalogV1:
    if path is None:
        return MonitoringExecutionCatalogV1.build()
    payload = _read_json(path)
    try:
        return MonitoringExecutionCatalogV1.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"invalid execution catalog {path}: {_validation_blocker(exc)}") from exc


def _run_watch_cycle(args: argparse.Namespace) -> object:
    from turtle_value_engine.providers.cninfo_disclosure import (
        cninfo_filing_provider_version,
    )

    if args.network == "allow" and args.from_cache:
        raise ValueError("--network allow and --from-cache are mutually exclusive")
    watchlist = _load_watchlist(args.watchlist)
    catalog = _load_execution_catalog(args.execution_catalog)
    workspace = MonitoringWorkspace(args.workspace)
    job_store = ReanalysisJobStore(args.job_root)
    cycle_store = MonitoringCycleStore(args.cycle_root)
    network_allowed = args.network == "allow"
    spec = MonitoringCycleSpecV1.build(
        watchlist_id=watchlist.watchlist_id,
        watchlist_content_sha256=watchlist.content_sha256,
        as_of=args.as_of,
        acquisition_policy_id=args.acquisition_policy_id,
        source_id=args.source,
        adapter_version=args.adapter_version or cninfo_filing_provider_version(),
        published_from=args.published_from,
        published_to=args.published_to,
        acquisition_limit=args.limit,
        network_allowed=network_allowed,
        offline_replay=args.from_cache,
        monitoring_workspace_root=str(workspace.root),
        reanalysis_job_root=str(job_store.root),
        cycle_store_root=str(cycle_store.root),
        execution_catalog=catalog,
    )
    preparation = NormalizedCompanyInputBuilder(
        AKShareProvider(), FilesystemRawResponseCache(args.cache_dir)
    )
    acquisition = CninfoCycleAcquisition(
        args.cache_dir,
        timeout_seconds=args.timeout_seconds,
        max_response_bytes=args.max_response_bytes,
    )
    outcome = MonitoringCycleRunner(
        workspace,
        job_store,
        cycle_store,
        acquisition=acquisition,
        preparation=preparation,
        model_allowed=False,
    ).run(spec, watchlist)
    result = {
        "cycle": outcome.result,
        "alert_batch": outcome.alert_batch,
        "reused": outcome.reused,
    }
    _write_optional(args.output, result)
    return result


class _CliPayloadExit(Exception):
    """Print a bounded JSON payload and exit with a specific code."""

    def __init__(self, payload: dict, code: int) -> None:
        super().__init__("classified CLI exit")
        self.payload = payload
        self.code = code


def _load_runner_config(path: Path) -> RunnerConfigV1:
    payload = _read_json(path)
    try:
        return RunnerConfigV1.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"invalid runner config {path}: {_validation_blocker(exc)}") from exc


def _runner_d1_boundary(config: RunnerConfigV1) -> UnattendedCycleBoundary:
    """Wire the runner to the unchanged public D1 composition only."""

    workspace = MonitoringWorkspace(config.monitoring_workspace_root)
    job_store = ReanalysisJobStore(config.reanalysis_job_root)
    cycle_store = MonitoringCycleStore(config.cycle_store_root)
    preparation = NormalizedCompanyInputBuilder(
        AKShareProvider(), FilesystemRawResponseCache(config.cache_dir)
    )
    acquisition = CninfoCycleAcquisition(
        config.cache_dir,
        timeout_seconds=config.timeout_seconds,
        max_response_bytes=config.max_response_bytes,
    )

    class _Boundary:
        def run_cycle(self, spec, watchlist):
            return MonitoringCycleRunner(
                workspace,
                job_store,
                cycle_store,
                acquisition=acquisition,
                preparation=preparation,
                model_allowed=False,
            ).run(spec, watchlist)

    return _Boundary()


def _run_watch_unattended_run(args: argparse.Namespace) -> object:
    from turtle_value_engine.providers.cninfo_disclosure import (
        cninfo_filing_provider_version,
    )

    config = _load_runner_config(args.runner_config)
    adapter_version = config.adapter_version or cninfo_filing_provider_version()
    watchlist_path = Path(config.watchlist_path)
    store = RunnerStore(config.runner_root)
    lease = RunnerLease(
        config.runner_root, config.runner_id, ttl_seconds=config.lease_ttl_seconds
    )
    service = MonitoringRunnerService(
        config=config,
        store=store,
        cycle_store=MonitoringCycleStore(config.cycle_store_root),
        lease=lease,
        d1=_runner_d1_boundary(config),
        watchlist_loader=lambda: _load_watchlist(watchlist_path),
        adapter_version=adapter_version,
    )
    try:
        outcome = service.run()
    except RunnerLeaseBusyError as exc:
        raise _CliPayloadExit(
            {
                "classification": "LEASE_BUSY",
                "runner_id": config.runner_id,
                "runner_root": config.runner_root,
                "message": (
                    "Another live invocation holds this runner lease; no "
                    "provider, model or D1 work was performed."
                ),
                "prior_holder_activation_id": (
                    None if exc.record is None else exc.record.activation_id
                ),
            },
            3,
        ) from exc
    payload = {
        "classification": outcome.classification.value,
        "runner_id": config.runner_id,
        "activation_id": outcome.activation.activation_id,
        "cycle_id": outcome.activation.spec.cycle_id,
        "as_of": outcome.activation.spec.as_of.isoformat(),
        "d1_status": outcome.receipt.d1_status,
        "d1_failure_code": outcome.receipt.d1_failure_code,
        "result_content_sha256": outcome.receipt.result_content_sha256,
        "alert_batch_id": outcome.receipt.alert_batch_id,
        "alert_batch_content_sha256": outcome.receipt.alert_batch_content_sha256,
        "reused_terminal": outcome.reused_terminal,
    }
    _write_optional(args.output, payload)
    return payload


def _run_watch_unattended_status(args: argparse.Namespace) -> object:
    store = RunnerStore(args.runner_root)
    runner_ids = [args.runner_id] if args.runner_id else store.list_runner_ids()
    runners: list[dict[str, object]] = []
    for runner_id in runner_ids:
        lease = RunnerLease(args.runner_root, runner_id)
        latest = store.load_latest(runner_id)
        active = store.load_active(runner_id)
        unfinished = store.list_unfinished_activations(runner_id)
        runners.append(
            {
                "runner_id": runner_id,
                "lease": lease.probe(),
                "latest": None if latest is None else latest.model_dump(mode="json"),
                "active_activation": None if active is None else active.model_dump(mode="json"),
                "unfinished_activation_ids": [item.activation_id for item in unfinished],
            }
        )
    payload: dict[str, object] = {
        "runner_root": str(args.runner_root),
        "runners": runners,
    }
    if args.activation_id is not None:
        intent = store.load_intent(args.activation_id)
        receipt = store.load_receipt(args.activation_id)
        payload["activation"] = {
            "intent": {
                "activation_id": intent.activation_id,
                "runner_id": intent.runner_id,
                "cycle_id": intent.spec.cycle_id,
                "as_of": intent.spec.as_of.isoformat(),
                "created_at": intent.created_at.isoformat(),
                "request_fingerprint": intent.request_fingerprint,
            },
            "receipt": None if receipt is None else receipt.model_dump(mode="json"),
        }
    return payload


def _run_watch_delivery_status(args: argparse.Namespace) -> object:
    from turtle_value_engine.monitoring_delivery import delivery_status_projection

    ledger = DeliveryLedgerStore(args.delivery_root)
    return delivery_status_projection(
        ledger,
        delivery_id=args.delivery_id,
        activation_id=args.activation_id,
    )


def _run_watch_deliver(args: argparse.Namespace) -> object:
    from datetime import UTC, datetime

    from turtle_value_engine.monitoring_delivery import (
        DeliveryDisabledError,
        DeliveryEndpointUnresolvedError,
        DeliveryNetworkDeniedError,
        DeliveryStatus,
    )

    if args.network != "allow":
        raise DeliveryNetworkDeniedError(
            "DELIVERY_NETWORK_DENIED: `tve watch deliver` requires an explicit "
            "--network allow opt-in; no outbound request was attempted"
        )
    runner_config = _load_runner_config(args.runner_config)
    project_config = load_project_config(args.project_config)
    delivery = project_config.monitoring.delivery
    if not delivery.enabled:
        raise DeliveryDisabledError(
            "DELIVERY_DISABLED: [monitoring.delivery] is not enabled in the project "
            "configuration"
        )
    settings = DeliverySettingsV1(
        destination_id=delivery.destination_id,
        max_attempts=delivery.max_attempts,
        timeout_seconds=delivery.timeout_seconds,
        backoff_base_seconds=delivery.backoff_base_seconds,
        backoff_cap_seconds=delivery.backoff_cap_seconds,
        max_response_bytes=delivery.max_response_bytes,
        receiver_idempotency_declared=delivery.receiver_idempotency_declared,
    )
    ledger_root = project_config.resolve_path(delivery.delivery_root)
    ledger = DeliveryLedgerStore(ledger_root)
    endpoint_ref = delivery.endpoint_ref
    auth_ref = delivery.auth_token_ref

    def _endpoint_resolver() -> str:
        if endpoint_ref is None:
            raise DeliveryEndpointUnresolvedError(
                "DELIVERY_ENDPOINT_UNRESOLVED: [monitoring.delivery] endpoint_ref is not "
                "configured; no outbound request was attempted"
            )
        raw = os.environ.get(endpoint_ref.env, "")
        if not raw or not raw.strip():
            raise DeliveryEndpointUnresolvedError(
                f"DELIVERY_ENDPOINT_UNRESOLVED: environment reference {endpoint_ref.env} "
                "resolved to nothing; no outbound request was attempted"
            )
        return raw

    def _auth_resolver() -> str | None:
        if auth_ref is None:
            return None
        raw = os.environ.get(auth_ref.env, "")
        return raw if raw.strip() else None

    service = MonitoringDeliveryService(
        settings=settings,
        ledger=ledger,
        runner_store=RunnerStore(runner_config.runner_root),
        cycle_store=MonitoringCycleStore(runner_config.cycle_store_root),
        transport=WebhookHttpTransport(),
        endpoint_resolver=_endpoint_resolver,
        auth_resolver=_auth_resolver,
        clock=lambda: datetime.now(UTC),
        runner_id=runner_config.runner_id,
        network_allowed=args.network == "allow",
        enabled=delivery.enabled,
    )
    outcome = _deliver_with_busy_exit(service, args.activation_id)
    payload = {
        "classification": outcome.status.value,
        "delivery_id": outcome.delivery_id,
        "runner_id": outcome.intent.runner_id,
        "activation_id": outcome.intent.activation_id,
        "cycle_id": outcome.intent.cycle_id,
        "alert_batch_id": outcome.intent.alert_batch_id,
        "destination_id": outcome.intent.destination_id,
        "attempt_count": outcome.state.attempt_count,
        "http_requests": outcome.http_requests,
        "reused": outcome.reused,
        "terminal": outcome.state.terminal,
        "next_attempt_not_before": None
        if outcome.state.next_attempt_not_before is None
        else outcome.state.next_attempt_not_before.isoformat(),
        "last_http_status": outcome.state.last_http_status,
        "last_error_code": None
        if outcome.state.last_error_code is None
        else outcome.state.last_error_code.value,
        "message": outcome.message,
    }
    _write_optional(args.output, payload)
    if outcome.status not in {DeliveryStatus.DELIVERED, DeliveryStatus.NOOP}:
        raise _CliPayloadExit(payload, 4)
    return payload


def _deliver_with_busy_exit(service, activation_id: str | None):
    """Map real single-flight contention to the additive exit-3 busy result.

    Only ``DeliveryLockBusyError`` (the platform's real lock-contention
    errors) lands here; every other lock/filesystem failure stays a normal
    fail-closed exit-2 error and is never disguised as busy.
    """

    from turtle_value_engine.monitoring_delivery import DeliveryLockBusyError

    try:
        return service.deliver(activation_id)
    except DeliveryLockBusyError as exc:
        raise _CliPayloadExit(
            {
                "classification": "DELIVERY_BUSY",
                "delivery_id": exc.delivery_id,
                "message": "another live invocation is delivering this delivery "
                "identity; this invocation performed zero outbound requests",
            },
            3,
        ) from exc


def _run_watch_execute_reanalysis(args: argparse.Namespace) -> object:
    if args.provider.lower() != "akshare":
        raise ValueError("only the implemented akshare provider is available")
    prepared_input = None
    if args.prepared_input is not None:
        prepared_input = parse_normalized_input(
            args.prepared_input.read_bytes()
        )
    prior_analysis = None
    if args.prior_analysis is not None:
        prior_analysis = CompanyAnalysis.model_validate(_read_json(args.prior_analysis))

    preparation = None
    if prepared_input is None:
        preparation = NormalizedCompanyInputBuilder(
            AKShareProvider(),
            FilesystemRawResponseCache(args.cache_dir),
        )
    company = None
    if any(
        value is not None
        for value in (args.company_json, args.name, args.sector, args.reporting_currency)
    ):
        if args.listing is None:
            raise ValueError("company context requires --listing")
        company = _prepare_company(args, args.listing)
    executor = ReanalysisExecutor(
        MonitoringWorkspace(args.workspace),
        ReanalysisJobStore(args.job_root),
        preparation=preparation,
        research_root=args.research_root,
        company=company,
        provider=args.provider,
        model_allowed=False,
    )
    results = executor.execute(
        args.run_id,
        listing_id=args.listing,
        request_id=args.request_id,
        network_allowed=args.network == "allow",
        prepared_input=prepared_input,
        prior_analysis=prior_analysis,
        company=company,
        provider=args.provider,
    )
    return {
        "jobs": [result.job for result in results],
        "reused_job_ids": [result.job.job_id for result in results if result.reused],
    }


def _run_watch_acquire_events(args: argparse.Namespace) -> object:
    from turtle_value_engine.monitoring.canonical import canonical_json_bytes
    from turtle_value_engine.monitoring_acquisition import (
        AcquisitionWindow,
        NetworkDeniedError,
        acquire_filing_events,
        derive_window_start_from_state,
    )
    from turtle_value_engine.providers.cache import FilesystemRawResponseCache
    from turtle_value_engine.providers.cninfo_disclosure import (
        UrllibCninfoHttpTransport,
        cninfo_disclosure_source_client,
        cninfo_filing_provider_version,
    )
    from turtle_value_engine.providers.filings import (
        FilingSource,
        OfficialFilingDiscoveryProvider,
    )

    if args.network == "allow" and args.from_cache:
        raise ValueError(
            "--network=allow and --from-cache are mutually exclusive; choose live "
            "acquisition or offline replay"
        )
    if args.network != "allow" and not args.from_cache:
        raise NetworkDeniedError(
            "network is denied; pass --network=allow for an explicit live "
            "acquisition or --from-cache for offline replay"
        )

    listings: list[str] = list(args.listing or [])
    watchlist = None
    if args.watchlist is not None:
        watchlist = _load_watchlist(args.watchlist)
        listings.extend(
            entry.listing_id for entry in watchlist.entries if entry.enabled
        )
    unique: list[str] = []
    for listing_id in listings:
        if listing_id in unique:
            raise ValueError(f"duplicate listing in acquisition scope: {listing_id}")
        unique.append(listing_id)
    if not unique:
        raise ValueError(
            "no listing scope: pass --listing at least once or --watchlist with "
            "enabled entries"
        )

    published_from = args.published_from
    if published_from is None and args.workspace is not None and watchlist is not None:
        state = MonitoringWorkspace(args.workspace).load_current_state(
            watchlist.watchlist_id
        )
        if state is not None:
            derived = [
                derive_window_start_from_state(state, listing_id, args.source)
                for listing_id in unique
            ]
            if all(start is not None for start in derived):
                published_from = min(derived)
    if published_from is None:
        raise ValueError(
            "acquisition window start is required: pass --from explicitly, or pass "
            "--workspace together with --watchlist when a committed cursor exists"
        )
    window = AcquisitionWindow(published_from=published_from, published_to=args.published_to)

    cache_dir = (
        args.cache_dir
        if args.cache_dir is not None
        else Path(".tve-private/monitoring/provider-cache")
    )
    transport = UrllibCninfoHttpTransport(
        timeout_seconds=args.timeout_seconds,
        max_response_bytes=args.max_response_bytes,
    )
    client = cninfo_disclosure_source_client(transport)
    provider = OfficialFilingDiscoveryProvider(
        {FilingSource.CNINFO: client},
        provider_version=cninfo_filing_provider_version(),
    )
    outcome = acquire_filing_events(
        provider=provider,
        listings=unique,
        window=window,
        source_id=args.source,
        adapter_version=cninfo_filing_provider_version(),
        cache=FilesystemRawResponseCache(cache_dir),
        limit=args.limit,
        as_of=args.as_of,
        network_allowed=args.network == "allow",
        offline=args.from_cache,
    )
    if args.output is not None:
        _atomic_write(
            args.output,
            canonical_json_bytes(
                outcome.batch.model_dump(mode="json", warnings=False)
            )
            + b"\n",
        )
    return outcome.summary


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
    if args.historical_command == "accept":
        batch = RawAcquisitionBatchManifestV1.model_validate(_read_json(args.batch))
        probe_report = AcquisitionReadinessReportV1.model_validate(
            _read_json(args.probe_report)
        )
        manifest = HistoricalDatasetManifest.model_validate(_read_json(args.manifest))
        raw_store = RawBlobStore(args.raw_store)
        artifact_store = HistoricalArtifactStore(args.store)
        report = validate_private_acceptance(
            batch,
            manifest,
            raw_store,
            artifact_store,
            probe_report=probe_report,
        )
        _write_optional(args.output, report)
        if not report.accepted:
            raise AcquisitionError(
                "PRIVATE_ACCEPTANCE_BLOCKED: " + "; ".join(report.blockers)
            )
        return report
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
        elif args.command == "artifacts":
            result = _run_artifacts(args)
        elif args.command == "surface":
            result = _run_surface(args)
        elif args.command == "backtest":
            result = _run_backtest_command(args)
        elif args.command == "calibrate":
            result = _run_calibration_command(args)
        elif args.command == "historical":
            result = _run_historical_command(args)
        elif args.command == "watch":
            result = _run_watch_command(args)
        elif args.command == "config":
            result = _run_config_command(args)
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
    except _CliPayloadExit as exc:
        print(json.dumps(_json_payload(exc.payload), ensure_ascii=False, indent=2))
        return exc.code
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
        ProjectConfigError,
    ) as exc:
        print(f"tve: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(_json_payload(result), ensure_ascii=False, indent=2))
    return 0
