"""Chronological calibration experiments with a locked holdout boundary."""

from __future__ import annotations

import hashlib
import itertools
import math
import re
from collections.abc import Callable, Iterable
from statistics import mean, median, pstdev

from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.providers.normalization import deterministic_id

from .contracts import (
    CalibrationExperiment,
    CalibrationHoldoutResult,
    CalibrationObservation,
    CalibrationSearchSpace,
    CalibrationStage,
    CalibrationTrial,
    CandidateProfileProposal,
    ChronologicalSplit,
)


class CalibrationError(ValueError):
    """Raised when a calibration experiment violates chronological isolation."""


CandidateScorer = Callable[
    [dict[str, float | int | str | bool], tuple[CalibrationObservation, ...]], float
]


def _score_values(values: list[float], objective: str) -> float | None:
    if not values:
        return None
    if objective == "MEAN_RETURN":
        return mean(values)
    if objective == "MEDIAN_RETURN":
        return median(values)
    if objective == "HIT_RATE":
        return sum(value > 0 for value in values) / len(values)
    deviation = pstdev(values)
    return mean(values) / deviation if deviation > 0 else mean(values)


def _default_scorer(
    parameters: dict[str, float | int | str | bool],
    observations: tuple[CalibrationObservation, ...],
    *,
    objective: str = "RISK_ADJUSTED",
) -> float:
    """Score deterministic feature filters without interpreting strict-v1."""

    selected = _filter_observations(parameters, observations)

    values = [item.target_return for item in selected if item.eligible]
    return _score_values(values, objective) or float("-inf")


def _filter_observations(
    parameters: dict[str, float | int | str | bool],
    observations: tuple[CalibrationObservation, ...],
) -> list[CalibrationObservation]:
    """Apply only the generic, explicitly named candidate filters."""

    selected = list(observations)
    for name, threshold in sorted(parameters.items()):
        if name.startswith("min_"):
            feature = name[4:]
            try:
                threshold_value = float(threshold)
                selected = [
                    item
                    for item in selected
                    if feature in item.feature_values
                    and item.feature_values[feature] is not None
                    and not isinstance(item.feature_values[feature], bool)
                    and float(item.feature_values[feature]) >= threshold_value
                ]
            except (TypeError, ValueError) as exc:
                raise CalibrationError(
                    f"min_{feature} requires a numeric candidate and feature"
                ) from exc
        elif name.startswith("max_"):
            feature = name[4:]
            try:
                threshold_value = float(threshold)
                selected = [
                    item
                    for item in selected
                    if feature in item.feature_values
                    and item.feature_values[feature] is not None
                    and not isinstance(item.feature_values[feature], bool)
                    and float(item.feature_values[feature]) <= threshold_value
                ]
            except (TypeError, ValueError) as exc:
                raise CalibrationError(
                    f"max_{feature} requires a numeric candidate and feature"
                ) from exc
        elif name.startswith("equals_"):
            feature = name[7:]
            selected = [item for item in selected if item.feature_values.get(feature) == threshold]
    return selected


def split_observations(
    observations: Iterable[CalibrationObservation],
    split: ChronologicalSplit,
) -> tuple[
    tuple[CalibrationObservation, ...],
    tuple[CalibrationObservation, ...],
    tuple[CalibrationObservation, ...],
]:
    """Partition rows by date while preserving deterministic chronological order."""

    ordered = tuple(sorted(observations, key=lambda item: (item.observed_at, item.observation_id)))
    train = tuple(
        item for item in ordered if split.train_start <= item.observed_at <= split.train_end
    )
    validation = tuple(
        item
        for item in ordered
        if split.validation_start <= item.observed_at <= split.validation_end
    )
    holdout = tuple(
        item for item in ordered if split.holdout_start <= item.observed_at <= split.holdout_end
    )
    return train, validation, holdout


def _validate_observations(
    observations: tuple[CalibrationObservation, ...],
    split: ChronologicalSplit,
) -> None:
    ids = [item.observation_id for item in observations]
    if len(ids) != len(set(ids)):
        raise CalibrationError("calibration observation IDs must be unique")
    for item in observations:
        if split.stage_for(item.observed_at) is None:
            raise CalibrationError(
                f"observation {item.observation_id} lies outside calibration split"
            )


def _parameter_product(search_space: CalibrationSearchSpace):
    names = sorted(search_space.parameters)
    values = [search_space.parameters[name] for name in names]
    for combination in itertools.product(*values):
        yield {name: value for name, value in zip(names, combination, strict=True)}


class CalibrationRunner:
    """Run finite deterministic search and emit proposal-only profile output."""

    def __init__(
        self,
        *,
        manifest_id: str,
        base_profile_id: str,
        base_profile_sha256: str,
        search_space: CalibrationSearchSpace,
        split: ChronologicalSplit,
        scorer: CandidateScorer | None = None,
    ) -> None:
        if search_space.base_profile_id != base_profile_id:
            raise CalibrationError("search space and runner base profiles do not match")
        if re.fullmatch(r"[0-9a-f]{64}", base_profile_sha256 or "") is None:
            raise CalibrationError("base_profile_sha256 must identify the frozen profile")
        self.manifest_id = manifest_id
        self.base_profile_id = base_profile_id
        self.base_profile_sha256 = base_profile_sha256
        self.search_space = search_space
        self.split = split
        self.scorer = scorer

    def _score(
        self,
        parameters: dict[str, float | int | str | bool],
        observations: tuple[CalibrationObservation, ...],
    ) -> float:
        if self.scorer is not None:
            return self.scorer(parameters, observations)
        return _default_scorer(
            parameters,
            observations,
            objective=self.search_space.objective,
        )

    def run(
        self,
        observations: Iterable[CalibrationObservation],
        *,
        rationale: str = "Chronological candidate search; human review remains required.",
    ) -> CalibrationExperiment:
        ordered = tuple(
            sorted(observations, key=lambda item: (item.observed_at, item.observation_id))
        )
        _validate_observations(ordered, self.split)
        train, validation, holdout = split_observations(ordered, self.split)
        if not train or not validation:
            raise CalibrationError(
                "calibration search requires non-empty train and validation sets"
            )
        if not any(item.eligible for item in train) or not any(
            item.eligible for item in validation
        ):
            raise CalibrationError(
                "calibration search requires eligible train and validation observations"
            )
        if not holdout:
            raise CalibrationError("calibration experiment requires a non-empty holdout set")
        experiment_id = deterministic_id(
            "calibration-experiment",
            self.manifest_id,
            self.base_profile_id,
            self.base_profile_sha256,
            self.search_space.model_dump(mode="json"),
            self.split.model_dump(mode="json"),
        )
        trials: list[CalibrationTrial] = []
        for index, parameters in enumerate(_parameter_product(self.search_space)):
            if index >= self.search_space.max_trials:
                break
            train_score = self._score(parameters, train)
            validation_score = self._score(parameters, validation)
            train_selected = (
                tuple(_filter_observations(parameters, train)) if self.scorer is None else train
            )
            validation_selected = (
                tuple(_filter_observations(parameters, validation))
                if self.scorer is None
                else validation
            )
            train_values = [item.target_return for item in train_selected if item.eligible]
            validation_values = [
                item.target_return for item in validation_selected if item.eligible
            ]
            sample_penalty = 1 / math.sqrt(max(1, min(len(train_values), len(validation_values))))
            instability = (
                abs(train_score - validation_score)
                if math.isfinite(train_score) and math.isfinite(validation_score)
                else 1.0
            )
            stability_penalty = sample_penalty + 0.1 * instability
            objective_score = validation_score - stability_penalty
            candidate_profile_id = deterministic_id(
                "candidate-profile", self.base_profile_id, parameters
            )
            trial_id = deterministic_id("calibration-trial", experiment_id, parameters)
            trials.append(
                CalibrationTrial(
                    trial_id=trial_id,
                    experiment_id=experiment_id,
                    candidate_profile_id=candidate_profile_id,
                    parameters=parameters,
                    stage=CalibrationStage.SEARCH,
                    train_count=len(train_values),
                    validation_count=len(validation_values),
                    train_score=train_score if math.isfinite(train_score) else None,
                    validation_score=validation_score if math.isfinite(validation_score) else None,
                    stability_penalty=stability_penalty,
                    objective_score=objective_score if math.isfinite(objective_score) else None,
                    observation_ids=[
                        item.observation_id for item in (*train_selected, *validation_selected)
                    ],
                )
            )
        if not trials:
            raise CalibrationError("calibration search space produced no trials")
        if not any(item.objective_score is not None for item in trials):
            raise CalibrationError("calibration search produced no finite candidate score")
        selected = max(
            trials,
            key=lambda item: (
                item.objective_score if item.objective_score is not None else float("-inf"),
                item.trial_id,
            ),
        )
        proposal_id = deterministic_id(
            "candidate-profile-proposal", experiment_id, selected.trial_id
        )
        proposal = CandidateProfileProposal(
            proposal_id=proposal_id,
            base_profile_id=self.base_profile_id,
            base_profile_sha256=self.base_profile_sha256,
            candidate_profile_id=selected.candidate_profile_id,
            parameter_overrides=selected.parameters,
            train_score=selected.train_score,
            validation_score=selected.validation_score,
            stability_summary={
                "stability_penalty": selected.stability_penalty,
                "train_count": float(selected.train_count),
                "validation_count": float(selected.validation_count),
            },
            rationale=rationale,
        )
        return CalibrationExperiment.build(
            experiment_id=experiment_id,
            manifest_id=self.manifest_id,
            base_profile_id=self.base_profile_id,
            base_profile_sha256=self.base_profile_sha256,
            search_space=self.search_space,
            split=self.split,
            trials=trials,
            selected_trial_id=selected.trial_id,
            proposal=proposal,
            holdout_locked=True,
        )

    def evaluate_holdout(
        self,
        experiment: CalibrationExperiment,
        observations: Iterable[CalibrationObservation],
    ) -> CalibrationHoldoutResult:
        """Evaluate a selected proposal after search; never mutates the experiment."""

        if experiment.base_profile_sha256 != self.base_profile_sha256:
            raise CalibrationError("experiment profile hash does not match runner")
        if experiment.manifest_id != self.manifest_id:
            raise CalibrationError("experiment manifest_id does not match runner")
        if experiment.search_space != self.search_space or experiment.split != self.split:
            raise CalibrationError("experiment search space or split does not match runner")
        if experiment.proposal is None or experiment.selected_trial_id is None:
            raise CalibrationError("holdout evaluation requires a selected proposal")
        ordered = tuple(
            sorted(observations, key=lambda item: (item.observed_at, item.observation_id))
        )
        _validate_observations(ordered, self.split)
        _train, _validation, holdout = split_observations(ordered, self.split)
        if not holdout:
            raise CalibrationError("holdout evaluation requires holdout observations")
        score = self._score(experiment.proposal.parameter_overrides, holdout)
        payload = {
            "contract": "calibration_holdout_result_v1",
            "experiment_id": experiment.experiment_id,
            "proposal_id": experiment.proposal.proposal_id,
            "holdout_start": self.split.holdout_start.isoformat(),
            "holdout_end": self.split.holdout_end.isoformat(),
            "observation_count": len(holdout),
            "score": score if math.isfinite(score) else None,
            "notes": [
                "Holdout was evaluated after selection and was not included in search trials.",
                "holdout_observation_ids_sha256="
                + hashlib.sha256(
                    canonical_json_bytes([item.observation_id for item in holdout])
                ).hexdigest(),
            ],
        }
        payload["content_sha256"] = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        return CalibrationHoldoutResult.model_validate(payload)


def run_calibration(
    *,
    manifest_id: str,
    base_profile_id: str,
    base_profile_sha256: str,
    search_space: CalibrationSearchSpace,
    split: ChronologicalSplit,
    observations: Iterable[CalibrationObservation],
    scorer: CandidateScorer | None = None,
) -> CalibrationExperiment:
    """Functional facade for proposal-only chronological calibration."""

    return CalibrationRunner(
        manifest_id=manifest_id,
        base_profile_id=base_profile_id,
        base_profile_sha256=base_profile_sha256,
        search_space=search_space,
        split=split,
        scorer=scorer,
    ).run(observations)


__all__ = [
    "CalibrationError",
    "CalibrationRunner",
    "CandidateScorer",
    "run_calibration",
    "split_observations",
]
