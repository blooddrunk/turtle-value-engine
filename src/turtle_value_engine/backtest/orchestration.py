"""Offline orchestration for signal evaluation and portfolio replay."""

from __future__ import annotations

import hashlib

from turtle_value_engine.providers.models import canonical_json_bytes

from .contracts import (
    BacktestDatasetManifest,
    BacktestResult,
    BacktestRunSpec,
    DecisionSnapshot,
    FailureAttribution,
    PortfolioPolicy,
    SignalEvaluationResult,
)
from .dataset import validate_manifest
from .portfolio import simulate_portfolio
from .signals import SignalEvaluationSpec, evaluate_signals
from .workspace import BacktestWorkspace


class BacktestOrchestrationError(ValueError):
    """Raised when a run specification does not match its frozen inputs."""


class BacktestOrchestrator:
    """Compose already-frozen inputs without acquiring data or calling models."""

    def __init__(
        self, manifest: BacktestDatasetManifest, workspace: BacktestWorkspace | None = None
    ):
        self.manifest = validate_manifest(manifest)
        self.workspace = workspace

    def evaluate_signals(
        self,
        snapshots: list[DecisionSnapshot] | tuple[DecisionSnapshot, ...],
        run_spec: BacktestRunSpec,
    ) -> SignalEvaluationResult:
        self._validate_run_spec(run_spec)
        selected = self._select_snapshots(snapshots, run_spec)
        result = evaluate_signals(
            self.manifest,
            selected,
            spec=SignalEvaluationSpec(
                spec_id=f"{run_spec.run_id}-signals",
                horizons=list(run_spec.horizons),
            ),
        )
        if self.workspace is not None:
            for snapshot in selected:
                self.workspace.save_snapshot(snapshot)
            self.workspace.save_signal_evaluation(result)
        return result

    def simulate_portfolio(
        self,
        snapshots: list[DecisionSnapshot] | tuple[DecisionSnapshot, ...],
        run_spec: BacktestRunSpec,
        policy: PortfolioPolicy,
        *,
        signal_evaluation: SignalEvaluationResult | None = None,
    ):
        self._validate_run_spec(run_spec)
        if run_spec.portfolio_policy_id != policy.policy_id:
            raise BacktestOrchestrationError("run spec and portfolio policy IDs do not match")
        selected = self._select_snapshots(snapshots, run_spec)
        result = simulate_portfolio(
            self.manifest,
            selected,
            policy,
            start_date=run_spec.start_date,
            end_date=run_spec.end_date,
            benchmark_ids=run_spec.benchmark_ids,
            signal_evaluation=signal_evaluation,
        )
        if self.workspace is not None:
            for snapshot in selected:
                self.workspace.save_snapshot(snapshot)
            self.workspace.save_policy(policy)
            self.workspace.save_portfolio_simulation(result)
        return result

    def run(
        self,
        run_spec: BacktestRunSpec,
        snapshots: list[DecisionSnapshot] | tuple[DecisionSnapshot, ...],
        *,
        policy: PortfolioPolicy | None = None,
    ) -> BacktestResult:
        """Run the requested offline stages and persist the combined result."""

        self._validate_run_spec(run_spec)
        if self.workspace is not None:
            self.workspace.save_manifest(self.manifest)
            self.workspace.save_run_spec(run_spec)
        signal_result = (
            self.evaluate_signals(snapshots, run_spec) if run_spec.run_signal_evaluation else None
        )
        portfolio_result = None
        if run_spec.run_portfolio_simulation:
            if policy is None:
                raise BacktestOrchestrationError("portfolio policy is required by run spec")
            portfolio_result = self.simulate_portfolio(
                snapshots,
                run_spec,
                policy,
                signal_evaluation=signal_result,
            )
        metrics = portfolio_result.metrics if portfolio_result is not None else None
        failure_attribution = (
            portfolio_result.failure_attribution
            if portfolio_result is not None
            else signal_result.failure_attribution
            if signal_result is not None
            else FailureAttribution()
        )
        candidate = BacktestResult.model_construct(
            contract="backtest_result_v1",
            run_id=run_spec.run_id,
            manifest_id=self.manifest.dataset_id,
            run_spec_sha256=run_spec.spec_sha256,
            signal_evaluation=signal_result,
            portfolio_simulation=portfolio_result,
            metrics=metrics,
            failure_attribution=failure_attribution,
            content_sha256="0" * 64,
        )
        payload = candidate.model_dump(mode="json", warnings=False)
        payload["content_sha256"] = hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in payload.items() if key != "content_sha256"}
            )
        ).hexdigest()
        result = BacktestResult.model_validate(payload)
        if self.workspace is not None:
            self.workspace.save_result(result)
        return result

    def _validate_run_spec(self, run_spec: BacktestRunSpec) -> None:
        if run_spec.manifest_id != self.manifest.dataset_id:
            raise BacktestOrchestrationError("run spec manifest_id does not match dataset")
        if (
            run_spec.start_date < self.manifest.start_date
            or run_spec.end_date > self.manifest.end_date
        ):
            raise BacktestOrchestrationError("run spec range lies outside dataset range")

    @staticmethod
    def _select_snapshots(
        snapshots: list[DecisionSnapshot] | tuple[DecisionSnapshot, ...],
        run_spec: BacktestRunSpec,
    ) -> list[DecisionSnapshot]:
        requested = set(run_spec.snapshot_ids)
        selected = [
            snapshot
            for snapshot in snapshots
            if run_spec.start_date <= snapshot.decision_time.date() <= run_spec.end_date
            and (not requested or snapshot.snapshot_id in requested)
        ]
        if requested and {item.snapshot_id for item in selected} != requested:
            missing = sorted(requested - {item.snapshot_id for item in selected})
            raise BacktestOrchestrationError(
                "run spec references snapshots outside its range or input set: "
                + ", ".join(missing)
            )
        if any(item.profile_id != run_spec.profile_id for item in selected):
            raise BacktestOrchestrationError(
                "run spec profile_id does not match selected decision snapshots"
            )
        return sorted(
            selected, key=lambda item: (item.decision_time, item.listing_id, item.snapshot_id)
        )


def run_backtest(
    manifest: BacktestDatasetManifest,
    run_spec: BacktestRunSpec,
    snapshots: list[DecisionSnapshot] | tuple[DecisionSnapshot, ...],
    *,
    policy: PortfolioPolicy | None = None,
    workspace: BacktestWorkspace | None = None,
) -> BacktestResult:
    """Functional facade for the offline orchestration boundary."""

    return BacktestOrchestrator(manifest, workspace=workspace).run(
        run_spec,
        snapshots,
        policy=policy,
    )


__all__ = ["BacktestOrchestrationError", "BacktestOrchestrator", "run_backtest"]
