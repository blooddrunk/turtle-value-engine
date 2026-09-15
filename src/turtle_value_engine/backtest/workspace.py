"""Immutable JSON persistence for Phase 5 backtest artifacts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from turtle_value_engine.providers.models import canonical_json_bytes

from .contracts import (
    BacktestDatasetManifest,
    BacktestResult,
    BacktestRunSpec,
    BacktestWorkspaceIndex,
    CalibrationExperiment,
    CalibrationHoldoutResult,
    DecisionSnapshot,
    PortfolioPolicy,
    PortfolioSimulationResult,
    SignalEvaluationResult,
)


class BacktestWorkspaceError(ValueError):
    """Raised when a frozen backtest artifact is missing or inconsistent."""


ModelT = TypeVar("ModelT", bound=BaseModel)


class BacktestWorkspace:
    """Atomic, model-validated and immutable artifact store.

    The workspace contains no provider cache, model credentials or runtime
    state.  It is therefore safe to hand to an offline replay process.
    """

    _KINDS = {
        "manifests": BacktestDatasetManifest,
        "snapshots": DecisionSnapshot,
        "signal-evaluations": SignalEvaluationResult,
        "policies": PortfolioPolicy,
        "run-specs": BacktestRunSpec,
        "portfolio-simulations": PortfolioSimulationResult,
        "results": BacktestResult,
        "calibration-experiments": CalibrationExperiment,
        "calibration-holdouts": CalibrationHoldoutResult,
        "indexes": BacktestWorkspaceIndex,
    }

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def path_for(self, kind: str, artifact_id: str) -> Path:
        if kind not in self._KINDS:
            raise ValueError(f"unsupported backtest artifact kind: {kind!r}")
        if (
            not isinstance(artifact_id, str)
            or not artifact_id
            or "/" in artifact_id
            or "\\" in artifact_id
            or artifact_id in {".", ".."}
        ):
            raise ValueError("artifact_id must be a non-empty path-safe string")
        return self.root / kind / f"{artifact_id}.json"

    def _write(self, kind: str, artifact_id: str, artifact: BaseModel) -> Path:
        path = self.path_for(kind, artifact_id)
        serialized = canonical_json_bytes(artifact.model_dump(mode="json")) + b"\n"
        if path.exists():
            if path.is_symlink() or not path.is_file():
                raise BacktestWorkspaceError(f"backtest artifact is not a regular file: {path}")
            if path.read_bytes() != serialized:
                raise BacktestWorkspaceError(
                    f"backtest artifact ID {artifact_id!r} already has conflicting content"
                )
            return path
        descriptor = -1
        temporary_path: Path | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary_path, path)
            temporary_path.unlink()
            temporary_path = None
        except (OSError, TypeError, ValueError) as exc:
            raise BacktestWorkspaceError(f"cannot persist backtest artifact {path}: {exc}") from exc
        finally:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return path

    def _read(self, kind: str, artifact_id: str) -> BaseModel:
        path = self.path_for(kind, artifact_id)
        if path.is_symlink() or not path.is_file():
            raise BacktestWorkspaceError(f"backtest artifact is missing or not a file: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_number)
            model_type = self._KINDS[kind]
            contract_field = model_type.model_fields.get("contract")
            if contract_field is not None and (
                not isinstance(payload, dict)
                or payload.get("contract") != contract_field.default
            ):
                raise ValueError(f"persisted contract is missing or invalid for {kind}")
            model = model_type.model_validate(payload)
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
            ValidationError,
        ) as exc:
            raise BacktestWorkspaceError(f"invalid backtest artifact {path}: {exc}") from exc
        actual_id = _artifact_id(kind, model)
        if actual_id is not None and actual_id != artifact_id:
            raise BacktestWorkspaceError(
                f"backtest artifact filename does not match its persisted identity: {path}"
            )
        return model

    def save_manifest(self, value: BacktestDatasetManifest) -> Path:
        return self._write("manifests", value.dataset_id, value)

    def load_manifest(self, artifact_id: str) -> BacktestDatasetManifest:
        return self._read("manifests", artifact_id)  # type: ignore[return-value]

    def save_snapshot(self, value: DecisionSnapshot) -> Path:
        return self._write("snapshots", value.snapshot_id, value)

    def load_snapshot(self, artifact_id: str) -> DecisionSnapshot:
        return self._read("snapshots", artifact_id)  # type: ignore[return-value]

    def save_signal_evaluation(self, value: SignalEvaluationResult) -> Path:
        return self._write("signal-evaluations", value.evaluation_id, value)

    def load_signal_evaluation(self, artifact_id: str) -> SignalEvaluationResult:
        return self._read("signal-evaluations", artifact_id)  # type: ignore[return-value]

    def save_policy(self, value: PortfolioPolicy) -> Path:
        return self._write("policies", value.policy_id, value)

    def load_policy(self, artifact_id: str) -> PortfolioPolicy:
        return self._read("policies", artifact_id)  # type: ignore[return-value]

    def save_run_spec(self, value: BacktestRunSpec) -> Path:
        return self._write("run-specs", value.run_id, value)

    def load_run_spec(self, artifact_id: str) -> BacktestRunSpec:
        return self._read("run-specs", artifact_id)  # type: ignore[return-value]

    def save_portfolio_simulation(self, value: PortfolioSimulationResult) -> Path:
        return self._write("portfolio-simulations", value.simulation_id, value)

    def load_portfolio_simulation(self, artifact_id: str) -> PortfolioSimulationResult:
        return self._read("portfolio-simulations", artifact_id)  # type: ignore[return-value]

    def save_result(self, value: BacktestResult) -> Path:
        return self._write("results", value.run_id, value)

    def load_result(self, artifact_id: str) -> BacktestResult:
        return self._read("results", artifact_id)  # type: ignore[return-value]

    def save_calibration_experiment(self, value: CalibrationExperiment) -> Path:
        return self._write("calibration-experiments", value.experiment_id, value)

    def load_calibration_experiment(self, artifact_id: str) -> CalibrationExperiment:
        return self._read("calibration-experiments", artifact_id)  # type: ignore[return-value]

    def save_calibration_holdout(self, value: CalibrationHoldoutResult) -> Path:
        artifact_id = f"{value.experiment_id}-{value.proposal_id}"
        return self._write("calibration-holdouts", artifact_id, value)

    def load_calibration_holdout(self, artifact_id: str) -> CalibrationHoldoutResult:
        return self._read("calibration-holdouts", artifact_id)  # type: ignore[return-value]

    def save_index(self, value: BacktestWorkspaceIndex) -> Path:
        return self._write("indexes", value.workspace_id, value)

    def load_index(self, artifact_id: str) -> BacktestWorkspaceIndex:
        return self._read("indexes", artifact_id)  # type: ignore[return-value]


def _artifact_id(kind: str, model: BaseModel) -> str | None:
    fields = {
        "manifests": "dataset_id",
        "snapshots": "snapshot_id",
        "signal-evaluations": "evaluation_id",
        "policies": "policy_id",
        "run-specs": "run_id",
        "portfolio-simulations": "simulation_id",
        "results": "run_id",
        "calibration-experiments": "experiment_id",
        "indexes": "workspace_id",
    }
    if kind == "calibration-holdouts":
        return f"{model.experiment_id}-{model.proposal_id}"
    field = fields.get(kind)
    return getattr(model, field) if field is not None else None


def _reject_number(value: str) -> None:
    raise ValueError(f"invalid JSON numeric constant: {value}")


BacktestArtifactStore = BacktestWorkspace


__all__ = ["BacktestArtifactStore", "BacktestWorkspace", "BacktestWorkspaceError"]
