"""Profile-aware frozen point-in-time replay under a candidate profile.

Phase 7-B1 proves candidate *semantics* by rerunning the unchanged
deterministic investment engine over the frozen point-in-time normalized
inputs already represented by the manifest's historical decision artifacts —
once under the exact base profile and once under the projected candidate
profile.  The generic calibration feature-filter score is not used here and
is not proof of candidate rule behavior.

Replay scope is exactly the search stage (train + validation) of the frozen
chronological split.  Holdout rows are never replayed, inspected or scored,
so the candidate is never selected, reinterpreted or modified through
holdout evidence.  Every required frozen input — an observation-to-artifact
reference, the artifact's embedded ``normalized_input`` and its provenance —
must exist and pass conservative point-in-time ordering; a missing input is
an explicit blocker, never a fallback to baseline decisions, baseline
analyses or generic filtering.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

from turtle_value_engine.backtest.contracts import (
    BacktestDatasetManifest,
    CalibrationObservation,
    ChronologicalSplit,
)
from turtle_value_engine.config.models import RuleProfile
from turtle_value_engine.pipeline import run_analyze
from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.providers.normalization import deterministic_id


class CandidateReplayError(ValueError):
    """Raised when candidate replay cannot be proven from frozen inputs."""


class CandidateReplayRowV1(BaseModel):
    """One replayed frozen decision under base and candidate profiles."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["candidate_replay_row_v1"] = "candidate_replay_row_v1"
    observation_id: StrictStr = Field(min_length=1)
    observed_at: date
    artifact_id: StrictStr = Field(min_length=1)
    artifact_source_hash: StrictStr = Field(min_length=1)
    baseline_decision_state: StrictStr = Field(min_length=1)
    candidate_decision_state: StrictStr = Field(min_length=1)
    baseline_analysis_sha256: StrictStr = Field(min_length=1)
    candidate_analysis_sha256: StrictStr = Field(min_length=1)
    changed: StrictBool

    @model_validator(mode="after")
    def validate_row(self) -> Self:
        if self.changed != (
            self.baseline_analysis_sha256 != self.candidate_analysis_sha256
        ):
            raise ValueError("changed must reflect the analysis digest comparison")
        return self


class CandidateProfileReplayV1(BaseModel):
    """Immutable result of one profile-aware frozen PIT replay.

    Binds the exact base/candidate profile identities, the replayed search-
    stage observation scope, one row per replayed frozen decision artifact
    and a deterministic ``replay_id`` recomputed from the bound identities.
    Holdout observations are structurally outside this contract.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["candidate_profile_replay_v1"] = "candidate_profile_replay_v1"
    replay_id: StrictStr = Field(min_length=1)
    replay_scope: Literal["SEARCH_STAGE_TRAIN_VALIDATION"] = (
        "SEARCH_STAGE_TRAIN_VALIDATION"
    )
    base_profile_id: StrictStr = Field(min_length=1)
    base_profile_sha256: StrictStr = Field(min_length=1)
    candidate_profile_id: StrictStr = Field(min_length=1)
    candidate_profile_sha256: StrictStr = Field(min_length=1)
    profile_rebind_from: StrictStr = Field(min_length=1)
    profile_rebind_to: StrictStr = Field(min_length=1)
    replayed_observation_count: StrictInt = Field(ge=1)
    changed_row_count: StrictInt = Field(ge=0)
    rows: list[CandidateReplayRowV1] = Field(min_length=1, max_length=100_000)
    notes: list[StrictStr] = Field(default_factory=list)
    content_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_replay(self) -> Self:
        if self.changed_row_count != sum(1 for row in self.rows if row.changed):
            raise ValueError("changed_row_count must equal the changed rows")
        if self.replayed_observation_count != len(self.rows):
            raise ValueError(
                "replayed_observation_count must equal the number of rows"
            )
        if self.profile_rebind_to != self.candidate_profile_id:
            raise ValueError(
                "profile rebind must rebind frozen inputs to the candidate profile id"
            )
        seen: set[str] = set()
        for row in self.rows:
            if row.observation_id in seen:
                raise ValueError("replay rows must be observation-unique")
            seen.add(row.observation_id)
        expected_replay_id = deterministic_id(
            "candidate-profile-replay",
            self.base_profile_id,
            self.base_profile_sha256,
            self.candidate_profile_id,
            self.candidate_profile_sha256,
            [
                {
                    "artifact_id": row.artifact_id,
                    "artifact_source_hash": row.artifact_source_hash,
                    "observation_id": row.observation_id,
                }
                for row in self.rows
            ],
        )
        if self.replay_id != expected_replay_id:
            raise ValueError(
                "replay_id does not match the deterministic identity of the "
                "replayed frozen inputs"
            )
        payload = self.model_dump(mode="json", warnings=False, exclude={"content_sha256"})
        expected = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        if self.content_sha256 != expected:
            raise ValueError("candidate replay content_sha256 does not match content")
        return self

    @classmethod
    def build(
        cls,
        *,
        base_profile_id: str,
        base_profile_sha256: str,
        candidate_profile_id: str,
        candidate_profile_sha256: str,
        profile_rebind_from: str,
        rows: list[CandidateReplayRowV1],
    ) -> CandidateProfileReplayV1:
        """Construct a replay result with its deterministic identities."""

        replay_id = deterministic_id(
            "candidate-profile-replay",
            base_profile_id,
            base_profile_sha256,
            candidate_profile_id,
            candidate_profile_sha256,
            [
                {
                    "artifact_id": row.artifact_id,
                    "artifact_source_hash": row.artifact_source_hash,
                    "observation_id": row.observation_id,
                }
                for row in rows
            ],
        )
        candidate = cls.model_construct(
            contract="candidate_profile_replay_v1",
            replay_id=replay_id,
            replay_scope="SEARCH_STAGE_TRAIN_VALIDATION",
            base_profile_id=base_profile_id,
            base_profile_sha256=base_profile_sha256,
            candidate_profile_id=candidate_profile_id,
            candidate_profile_sha256=candidate_profile_sha256,
            profile_rebind_from=profile_rebind_from,
            profile_rebind_to=candidate_profile_id,
            replayed_observation_count=len(rows),
            changed_row_count=sum(1 for row in rows if row.changed),
            rows=rows,
            notes=[
                "Holdout observations are outside the replay scope; candidate "
                "semantics were never selected or modified through holdout evidence.",
                "Each frozen normalized input is replayed unchanged except that "
                "profile_id is rebound to the candidate profile id so the "
                "deterministic engine executes under the projected profile.",
            ],
            content_sha256="0" * 64,
        )
        payload = candidate.model_dump(mode="json", warnings=False)
        payload["content_sha256"] = hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in payload.items() if key != "content_sha256"}
            )
        ).hexdigest()
        return cls.model_validate(payload)


def _available_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def replay_candidate_profile(
    *,
    manifest: BacktestDatasetManifest,
    observations: Iterable[CalibrationObservation],
    split: ChronologicalSplit,
    base_profile: RuleProfile,
    candidate_profile: RuleProfile,
    base_profile_sha256: str,
    candidate_profile_sha256: str,
) -> CandidateProfileReplayV1:
    """Replay the frozen search-stage inputs under base and candidate profiles.

    Fail-closed blockers, each with a stable machine-readable code prefix:

    - ``MISSING_FROZEN_NORMALIZED_INPUT`` — an observation carries no
      ``source_observation_id``, references an unknown decision artifact, or
      the artifact froze no ``normalized_input``;
    - ``OBSERVATION_PROVENANCE_MISMATCH`` — the observation's ``source_hash``
      disagrees with the referenced artifact's;
    - ``FUTURE_FROZEN_INPUT`` — the artifact's ``as_of``/``available_at``
      lies after the observation date (future-data leakage).

    No baseline decision, baseline analysis or generic feature-filter score is
    ever reused in place of a real engine replay.
    """

    ordered = tuple(
        sorted(observations, key=lambda item: (item.observed_at, item.observation_id))
    )
    train, validation, _holdout = _split(ordered, split)
    scope = (*train, *validation)
    if not scope:
        raise CandidateReplayError(
            "MISSING_FROZEN_NORMALIZED_INPUT: the frozen split provides no "
            "search-stage observations to replay"
        )

    artifacts = {artifact.artifact_id: artifact for artifact in manifest.decision_artifacts}
    rows: list[CandidateReplayRowV1] = []
    for observation in scope:
        artifact_id = observation.source_observation_id
        if not artifact_id:
            raise CandidateReplayError(
                "MISSING_FROZEN_NORMALIZED_INPUT: observation "
                f"{observation.observation_id} carries no source_observation_id "
                "referencing a frozen decision artifact"
            )
        artifact = artifacts.get(artifact_id)
        if artifact is None:
            raise CandidateReplayError(
                "MISSING_FROZEN_NORMALIZED_INPUT: observation "
                f"{observation.observation_id} references unknown decision "
                f"artifact {artifact_id!r}"
            )
        if artifact.normalized_input is None:
            raise CandidateReplayError(
                "MISSING_FROZEN_NORMALIZED_INPUT: decision artifact "
                f"{artifact_id} froze no normalized_input for engine replay"
            )
        if artifact.source_hash != observation.source_hash:
            raise CandidateReplayError(
                "OBSERVATION_PROVENANCE_MISMATCH: observation "
                f"{observation.observation_id} source_hash does not match the "
                f"referenced artifact {artifact_id}"
            )
        if artifact.as_of > observation.observed_at:
            raise CandidateReplayError(
                f"FUTURE_FROZEN_INPUT: decision artifact {artifact_id} is dated "
                f"{artifact.as_of}, after observation "
                f"{observation.observation_id} at {observation.observed_at}"
            )
        available = _available_date(artifact.available_at)
        if available is not None and available > observation.observed_at:
            raise CandidateReplayError(
                f"FUTURE_FROZEN_INPUT: decision artifact {artifact_id} became "
                f"available {available}, after observation "
                f"{observation.observation_id} at {observation.observed_at}"
            )

        normalized_input = artifact.normalized_input
        if normalized_input.profile_id != base_profile.profile.id:
            raise CandidateReplayError(
                "MISSING_FROZEN_NORMALIZED_INPUT: decision artifact "
                f"{artifact_id} froze a normalized input for profile "
                f"{normalized_input.profile_id!r}, not the replayed base profile "
                f"{base_profile.profile.id!r}"
            )
        baseline = run_analyze(normalized_input, profile=base_profile)
        candidate_input = normalized_input.model_copy(
            update={"profile_id": candidate_profile.profile.id}
        )
        candidate = run_analyze(candidate_input, profile=candidate_profile)
        baseline_digest = _analysis_digest(baseline)
        candidate_digest = _analysis_digest(candidate)
        rows.append(
            CandidateReplayRowV1(
                observation_id=observation.observation_id,
                observed_at=observation.observed_at,
                artifact_id=artifact.artifact_id,
                artifact_source_hash=artifact.source_hash,
                baseline_decision_state=str(baseline.decision.state.value),
                candidate_decision_state=str(candidate.decision.state.value),
                baseline_analysis_sha256=baseline_digest,
                candidate_analysis_sha256=candidate_digest,
                changed=baseline_digest != candidate_digest,
            )
        )

    return CandidateProfileReplayV1.build(
        base_profile_id=base_profile.profile.id,
        base_profile_sha256=base_profile_sha256,
        candidate_profile_id=candidate_profile.profile.id,
        candidate_profile_sha256=candidate_profile_sha256,
        profile_rebind_from=base_profile.profile.id,
        rows=rows,
    )


def _split(
    observations: Sequence[CalibrationObservation], split: ChronologicalSplit
) -> tuple[
    tuple[CalibrationObservation, ...],
    tuple[CalibrationObservation, ...],
    tuple[CalibrationObservation, ...],
]:
    train = tuple(
        item for item in observations if split.train_start <= item.observed_at <= split.train_end
    )
    validation = tuple(
        item
        for item in observations
        if split.validation_start <= item.observed_at <= split.validation_end
    )
    holdout = tuple(
        item
        for item in observations
        if split.holdout_start <= item.observed_at <= split.holdout_end
    )
    return train, validation, holdout


def _analysis_digest(analysis: object) -> str:
    return hashlib.sha256(
        canonical_json_bytes(analysis.model_dump(mode="json", warnings=False))  # type: ignore[attr-defined]
    ).hexdigest()


__all__ = [
    "CandidateProfileReplayV1",
    "CandidateReplayError",
    "CandidateReplayRowV1",
    "replay_candidate_profile",
]
