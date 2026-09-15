"""Production-oriented source, shard, coverage and archive boundaries."""

from .archive import (
    HistoricalResearchArchiveError,
    archive_artifact_available_at,
    validate_research_archive,
)
from .compiler import (
    HistoricalDatasetCompiler,
    HistoricalDatasetValidationError,
    HistoricalValidationSummary,
    compile_backtest_manifest,
    freeze_decision_snapshots,
    validate_historical_dataset,
)
from .contracts import *  # noqa: F403
from .contracts import __all__ as _CONTRACT_EXPORTS
from .coverage import build_coverage_report
from .reconciliation import reconcile_observations
from .store import (
    HistoricalArtifactError,
    HistoricalArtifactStore,
    canonical_jsonl_bytes,
    jsonl_sha256,
)

__all__ = [
    *_CONTRACT_EXPORTS,
    "HistoricalArtifactError",
    "HistoricalArtifactStore",
    "HistoricalDatasetCompiler",
    "HistoricalDatasetValidationError",
    "HistoricalResearchArchiveError",
    "HistoricalValidationSummary",
    "archive_artifact_available_at",
    "build_coverage_report",
    "canonical_jsonl_bytes",
    "compile_backtest_manifest",
    "freeze_decision_snapshots",
    "jsonl_sha256",
    "reconcile_observations",
    "validate_historical_dataset",
    "validate_research_archive",
]
