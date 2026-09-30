"""Point-in-time backtesting and calibration boundaries."""

from .calibration import CalibrationError, CalibrationRunner, run_calibration, split_observations
from .contracts import *  # noqa: F403
from .contracts import __all__ as _CONTRACT_EXPORTS
from .dataset import (
    DatasetValidationError,
    HistoricalUniverse,
    build_dataset_manifest,
    is_available_at,
    sha256_json,
    source_hash_for,
    validate_decision_artifact,
    validate_manifest,
)
from .evidence_binding import (
    EvidenceBindingError,
    build_calibration_evidence_binding,
    canonical_observations_sha256,
    canonical_proposal_payload_sha256,
)
from .metrics import (
    benchmark_daily_returns_for_snapshots,
    benchmark_result,
    benchmark_results,
    build_failure_attribution,
    calculate_performance_metrics,
)
from .orchestration import BacktestOrchestrationError, BacktestOrchestrator, run_backtest
from .portfolio import (
    PortfolioSimulationError,
    PortfolioSimulator,
    replay_cash_balance,
    simulate_portfolio,
)
from .returns import ReturnCalculationError, ReturnEngine, add_horizon, evaluate_forward_return
from .signals import (
    SignalEvaluationError,
    SignalEvaluationSpec,
    SignalEvaluator,
    build_decision_snapshot,
    decision_snapshot_from_analysis,
    evaluate_signals,
)
from .workspace import BacktestArtifactStore, BacktestWorkspace, BacktestWorkspaceError

__all__ = [
    *_CONTRACT_EXPORTS,
    "BacktestArtifactStore",
    "BacktestOrchestrationError",
    "BacktestOrchestrator",
    "BacktestWorkspace",
    "BacktestWorkspaceError",
    "CalibrationError",
    "CalibrationRunner",
    "DatasetValidationError",
    "EvidenceBindingError",
    "HistoricalUniverse",
    "PortfolioSimulationError",
    "PortfolioSimulator",
    "ReturnCalculationError",
    "ReturnEngine",
    "SignalEvaluationError",
    "SignalEvaluationSpec",
    "SignalEvaluator",
    "add_horizon",
    "benchmark_result",
    "benchmark_daily_returns_for_snapshots",
    "benchmark_results",
    "build_calibration_evidence_binding",
    "build_dataset_manifest",
    "build_decision_snapshot",
    "build_failure_attribution",
    "calculate_performance_metrics",
    "canonical_observations_sha256",
    "canonical_proposal_payload_sha256",
    "decision_snapshot_from_analysis",
    "evaluate_forward_return",
    "evaluate_signals",
    "is_available_at",
    "run_backtest",
    "run_calibration",
    "sha256_json",
    "simulate_portfolio",
    "replay_cash_balance",
    "source_hash_for",
    "split_observations",
    "validate_decision_artifact",
    "validate_manifest",
]
