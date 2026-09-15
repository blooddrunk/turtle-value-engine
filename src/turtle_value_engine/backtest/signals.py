"""Decision snapshots and point-in-time forward-return evaluation."""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from datetime import UTC, datetime
from statistics import mean, median
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    model_validator,
)

from turtle_value_engine.models import CompanyAnalysis, NormalizedCompanyInput
from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.providers.normalization import deterministic_id

from .contracts import (
    BacktestDatasetManifest,
    DecisionSnapshot,
    FailureAttribution,
    ForwardReturnObservation,
    SignalBucket,
    SignalEvaluationResult,
    SignalOutcomeStatus,
)
from .dataset import validate_decision_artifact, validate_manifest
from .metrics import build_failure_attribution
from .returns import ReturnEngine


class SignalEvaluationError(ValueError):
    """Raised when signal evaluation cannot remain point-in-time and replayable."""


class SignalEvaluationSpec(BaseModel):
    """Horizon/timing assumptions kept outside the strict investment profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["signal_evaluation_spec_v1"] = "signal_evaluation_spec_v1"
    spec_id: StrictStr = Field(min_length=1)
    horizons: list[StrictStr] = Field(default_factory=lambda: ["1M", "3M", "6M", "12M"])
    entry_price: Literal["open", "close"] = "open"
    include_price_return: StrictBool = True
    include_total_return: StrictBool = True

    @model_validator(mode="after")
    def validate_spec(self) -> Self:
        if not self.horizons:
            raise ValueError("signal evaluation requires at least one horizon")
        if len(self.horizons) != len(set(self.horizons)):
            raise ValueError("signal evaluation horizons must be unique")
        if not self.include_price_return and not self.include_total_return:
            raise ValueError("signal evaluation must include a return type")
        for horizon in self.horizons:
            if (
                not horizon[:-1].isdigit()
                or int(horizon[:-1] or 0) <= 0
                or horizon[-1:] not in {"D", "W", "M", "Y"}
            ):
                raise ValueError(f"invalid forward-return horizon: {horizon}")
        return self


def _analysis_hash(analysis: CompanyAnalysis) -> str:
    return hashlib.sha256(
        canonical_json_bytes(analysis.model_dump(mode="json", warnings=False))
    ).hexdigest()


def _input_hash(value: NormalizedCompanyInput | None, analysis: CompanyAnalysis) -> str:
    payload = (
        analysis.model_dump(mode="json", warnings=False)
        if value is None
        else value.model_dump(mode="json", warnings=False)
    )
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _normalized_input_hash(value: NormalizedCompanyInput) -> str:
    return hashlib.sha256(
        canonical_json_bytes(value.model_dump(mode="json", warnings=False))
    ).hexdigest()


def decision_snapshot_from_analysis(
    analysis: CompanyAnalysis,
    *,
    decision_time: datetime | None = None,
    normalized_input: NormalizedCompanyInput | None = None,
    input_artifact_id: str | None = None,
    research_artifact_id: str | None = None,
) -> DecisionSnapshot:
    """Project an existing validated analysis without rerunning its semantics."""

    if not isinstance(analysis, CompanyAnalysis):
        raise TypeError("analysis must be a CompanyAnalysis")
    if normalized_input is not None:
        if (
            normalized_input.analysis_id != analysis.analysis_id
            or normalized_input.as_of != analysis.as_of
            or normalized_input.profile_id != analysis.profile_id
            or normalized_input.company.primary_listing != analysis.company.primary_listing
        ):
            raise SignalEvaluationError("normalized input and analysis scope do not match")
    if analysis.business_quality is not None and research_artifact_id is None:
        raise SignalEvaluationError(
            "historical Business Quality requires an explicit frozen research artifact"
        )
    active_time = decision_time or datetime.combine(
        analysis.as_of,
        datetime.max.time(),
        tzinfo=UTC,
    )
    if active_time.tzinfo is None:
        raise SignalEvaluationError("decision_time must be timezone-aware")
    input_id = input_artifact_id or (
        analysis.analysis_id if normalized_input is None else normalized_input.analysis_id
    )
    gate_statuses = {
        name: getattr(analysis.gates, name).status.value
        for name in (
            "universe",
            "balance_sheet",
            "cdc",
            "through_return",
            "business_quality",
            "governance_data_quality",
        )
    }
    gate_failure_reasons = {
        name: list(getattr(analysis.gates, name).blocking_reasons)
        for name in gate_statuses
        if getattr(analysis.gates, name).blocking_reasons
    }
    selected_metrics: dict[str, float | int | str | None] = {}
    for group_name in ("cdc", "net_cash", "through_return"):
        group = getattr(analysis.metrics, group_name)
        for name, value in group.model_dump(mode="python", warnings=False).items():
            if name in {"flags", "confidence", "source_evidence_ids", "year_results"}:
                continue
            if value is None or isinstance(value, bool):
                continue
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                selected_metrics[f"{group_name}.{name}"] = value
    analysis_hash = _analysis_hash(analysis)
    input_hash = _input_hash(normalized_input, analysis)
    snapshot_id = deterministic_id(
        "decision-snapshot",
        analysis.analysis_id,
        analysis.company.primary_listing,
        active_time.isoformat(),
        analysis.as_of.isoformat(),
        analysis.profile_id,
        input_id,
        input_hash,
        analysis_hash,
        research_artifact_id,
    )
    return DecisionSnapshot(
        snapshot_id=snapshot_id,
        analysis_id=analysis.analysis_id,
        listing_id=analysis.company.primary_listing,
        company_id=analysis.company.legal_name or analysis.company.name,
        decision_time=active_time,
        as_of=analysis.as_of,
        profile_id=analysis.profile_id,
        input_artifact_id=input_id,
        input_sha256=input_hash,
        analysis_sha256=analysis_hash,
        research_artifact_id=research_artifact_id,
        final_state=analysis.decision.state.value,
        valuation_state=analysis.valuation.current_valuation_state.value,
        valuation_tier=analysis.valuation.current_valuation_state.value,
        gate_statuses=gate_statuses,
        gate_failure_reasons=gate_failure_reasons,
        selected_metrics=selected_metrics,
        business_quality_evaluated=(
            analysis.business_quality is not None and research_artifact_id is not None
        ),
        unresolved_flags=list(
            dict.fromkeys(
                [
                    *analysis.data_quality.critical_missing_fields,
                    *analysis.flags,
                    *analysis.metrics.cdc.flags,
                    *analysis.metrics.net_cash.flags,
                    *analysis.metrics.through_return.flags,
                ]
            )
        ),
        flags=list(analysis.flags),
    )


build_decision_snapshot = decision_snapshot_from_analysis


def _hashed_signal_result(
    *,
    evaluation_id: str,
    manifest_id: str,
    profile_id: str,
    snapshot_ids: list[str],
    horizons: list[str],
    observations: list[ForwardReturnObservation],
    buckets: list[SignalBucket],
    coverage: dict[str, float],
    failure_attribution: FailureAttribution,
) -> SignalEvaluationResult:
    candidate = SignalEvaluationResult.model_construct(
        contract="signal_evaluation_result_v1",
        evaluation_id=evaluation_id,
        manifest_id=manifest_id,
        profile_id=profile_id,
        snapshot_ids=snapshot_ids,
        horizons=horizons,
        observations=observations,
        buckets=buckets,
        coverage=coverage,
        failure_attribution=failure_attribution,
        content_sha256="0" * 64,
    )
    payload = candidate.model_dump(mode="json", warnings=False)
    payload["content_sha256"] = hashlib.sha256(
        canonical_json_bytes(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
    ).hexdigest()
    return SignalEvaluationResult.model_validate(payload)


def _make_buckets(
    observations: list[ForwardReturnObservation],
    snapshots: dict[str, DecisionSnapshot],
) -> list[SignalBucket]:
    grouped: dict[tuple[str, str], list[ForwardReturnObservation]] = defaultdict(list)
    for observation in observations:
        snapshot = snapshots[observation.snapshot_id]
        bucket_key = "|".join(
            (
                f"state={snapshot.final_state}",
                f"valuation={snapshot.valuation_tier or 'UNKNOWN'}",
                "business_quality="
                f"{'EVALUATED' if snapshot.business_quality_evaluated else 'NOT_EVALUATED'}",
            )
        )
        grouped[(observation.horizon, bucket_key)].append(observation)
    result: list[SignalBucket] = []
    for (horizon, bucket_key), values in sorted(grouped.items()):
        complete = [
            item
            for item in values
            if item.status
            in {
                SignalOutcomeStatus.COMPLETE,
                SignalOutcomeStatus.DELISTED_TERMINAL,
            }
        ]
        result.append(
            SignalBucket(
                bucket_key=bucket_key,
                horizon=horizon,
                observation_count=len(values),
                complete_count=len(complete),
                mean_price_return=(
                    mean(item.price_return for item in complete if item.price_return is not None)
                    if complete
                    else None
                ),
                median_price_return=(
                    median(item.price_return for item in complete if item.price_return is not None)
                    if complete
                    else None
                ),
                mean_total_return=(
                    mean(item.total_return for item in complete if item.total_return is not None)
                    if complete
                    else None
                ),
                median_total_return=(
                    median(item.total_return for item in complete if item.total_return is not None)
                    if complete
                    else None
                ),
                positive_total_return_rate=(
                    sum(
                        1
                        for item in complete
                        if item.total_return is not None and item.total_return > 0
                    )
                    / len(complete)
                    if complete
                    else None
                ),
                failure_rate=1 - len(complete) / len(values) if values else None,
            )
        )
    return result


class SignalEvaluator:
    """Evaluate deterministic states before considering portfolio mechanics."""

    def __init__(self, manifest: BacktestDatasetManifest) -> None:
        self.manifest = validate_manifest(manifest)
        self.returns = ReturnEngine(self.manifest)

    def evaluate(
        self,
        snapshots: list[DecisionSnapshot] | tuple[DecisionSnapshot, ...],
        *,
        spec: SignalEvaluationSpec | None = None,
    ) -> SignalEvaluationResult:
        active_spec = spec or SignalEvaluationSpec(spec_id="signal-evaluation-default")
        ordered = sorted(
            snapshots, key=lambda item: (item.decision_time, item.listing_id, item.snapshot_id)
        )
        if len({item.snapshot_id for item in ordered}) != len(ordered):
            raise SignalEvaluationError("signal snapshots must have unique snapshot IDs")
        for snapshot in ordered:
            if snapshot.profile_id != self._profile_id(ordered):
                raise SignalEvaluationError("signal snapshots must use one rule profile")
            self._validate_snapshot(snapshot)
        snapshot_ids = [item.snapshot_id for item in ordered]
        snapshot_by_id = {item.snapshot_id: item for item in ordered}
        observations = [
            self.returns.forward_return(
                snapshot,
                horizon,
                entry_price=active_spec.entry_price,
            )
            for snapshot in ordered
            for horizon in active_spec.horizons
        ]
        buckets = _make_buckets(observations, snapshot_by_id)
        total = len(observations)
        complete = sum(
            item.status in {SignalOutcomeStatus.COMPLETE, SignalOutcomeStatus.DELISTED_TERMINAL}
            for item in observations
        )
        coverage = {
            "overall": complete / total if total else 0.0,
            "snapshot_count": float(len(ordered)),
            **{
                horizon: (
                    sum(
                        item.status
                        in {SignalOutcomeStatus.COMPLETE, SignalOutcomeStatus.DELISTED_TERMINAL}
                        for item in observations
                        if item.horizon == horizon
                    )
                    / max(1, sum(item.horizon == horizon for item in observations))
                )
                for horizon in active_spec.horizons
            },
        }
        evaluation_id = deterministic_id(
            "signal-evaluation",
            self.manifest.dataset_id,
            snapshot_ids,
            active_spec.model_dump(mode="json"),
        )
        failure_attribution = build_failure_attribution(
            observations,
            ordered,
            manifest=self.manifest,
        )
        return _hashed_signal_result(
            evaluation_id=evaluation_id,
            manifest_id=self.manifest.dataset_id,
            profile_id=self._profile_id(ordered),
            snapshot_ids=snapshot_ids,
            horizons=list(active_spec.horizons),
            observations=observations,
            buckets=buckets,
            coverage=coverage,
            failure_attribution=failure_attribution,
        )

    @staticmethod
    def _profile_id(snapshots: list[DecisionSnapshot]) -> str:
        if not snapshots:
            return "UNSPECIFIED"
        return snapshots[0].profile_id

    def validate_snapshot(self, snapshot: DecisionSnapshot) -> None:
        """Validate one snapshot at the same PIT boundary used by evaluation."""

        self._validate_snapshot(snapshot)

    def _validate_snapshot(self, snapshot: DecisionSnapshot) -> None:
        try:
            lifecycle = self.manifest.lifecycle(snapshot.listing_id)
        except KeyError as exc:
            raise SignalEvaluationError(str(exc)) from exc
        if not lifecycle.is_listed_on(snapshot.decision_time.date()):
            raise SignalEvaluationError("decision snapshot lies outside listing lifecycle")
        if not self.manifest.start_date <= snapshot.decision_time.date() <= self.manifest.end_date:
            raise SignalEvaluationError("decision snapshot lies outside dataset range")
        if (
            self.manifest.universe_coverage.value == "HISTORICAL"
            and snapshot.listing_id
            not in self.manifest.memberships_on(snapshot.decision_time.date())
        ):
            raise SignalEvaluationError("decision snapshot is outside the historical universe")
        matching = [
            item
            for item in self.manifest.decision_artifacts
            if item.artifact_id == snapshot.input_artifact_id
            or item.artifact_id == snapshot.analysis_id
        ]
        if (
            self.manifest.decision_artifacts or snapshot.business_quality_evaluated
        ) and not matching:
            raise SignalEvaluationError(
                "snapshot input artifact is not present in the dataset: "
                f"{snapshot.input_artifact_id}"
            )
        if (
            self.manifest.decision_artifacts
            and snapshot.input_artifact_id != snapshot.analysis_id
            and not any(item.artifact_id == snapshot.input_artifact_id for item in matching)
        ):
            raise SignalEvaluationError(
                "snapshot input artifact is not present in the dataset: "
                f"{snapshot.input_artifact_id}"
            )
        for artifact in matching:
            if artifact.listing_id != snapshot.listing_id or artifact.as_of != snapshot.as_of:
                raise SignalEvaluationError(
                    f"snapshot and decision artifact scope do not match: {artifact.artifact_id}"
                )
            if (
                artifact.analysis is not None
                and artifact.analysis.analysis_id != snapshot.analysis_id
            ):
                raise SignalEvaluationError(
                    f"snapshot analysis ID does not match artifact: {artifact.artifact_id}"
                )
            if (
                artifact.normalized_input is not None
                and artifact.normalized_input.analysis_id != snapshot.analysis_id
            ):
                raise SignalEvaluationError(
                    f"snapshot input analysis ID does not match artifact: {artifact.artifact_id}"
                )
            validate_decision_artifact(
                artifact,
                decision_time=snapshot.decision_time,
                allow_undated_evidence=self.manifest.allow_undated_evidence,
            )
            if (
                artifact.analysis is not None
                and _analysis_hash(artifact.analysis) != snapshot.analysis_sha256
            ):
                raise SignalEvaluationError(
                    f"snapshot analysis hash does not match artifact: {artifact.artifact_id}"
                )
            if (
                artifact.normalized_input is not None
                and _normalized_input_hash(artifact.normalized_input) != snapshot.input_sha256
            ):
                raise SignalEvaluationError(
                    f"snapshot input hash does not match artifact: {artifact.artifact_id}"
                )
        if snapshot.business_quality_evaluated and not any(
            artifact.historical_business_quality_valid
            and artifact.research_artifact_id == snapshot.research_artifact_id
            for artifact in matching
        ):
            raise SignalEvaluationError(
                "snapshot Business Quality requires a matching frozen historical artifact"
            )


def evaluate_signals(
    manifest: BacktestDatasetManifest,
    snapshots: list[DecisionSnapshot] | tuple[DecisionSnapshot, ...],
    *,
    spec: SignalEvaluationSpec | None = None,
) -> SignalEvaluationResult:
    """Functional signal-evaluation facade."""

    return SignalEvaluator(manifest).evaluate(snapshots, spec=spec)


__all__ = [
    "SignalEvaluationError",
    "SignalEvaluationSpec",
    "SignalEvaluator",
    "build_decision_snapshot",
    "decision_snapshot_from_analysis",
    "evaluate_signals",
]
