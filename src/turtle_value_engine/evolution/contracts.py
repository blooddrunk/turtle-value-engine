"""Typed, persisted contracts for controlled-evolution evaluation.

This module contains data envelopes only.  The Phase 7-A evaluation boundary
is offline, non-mutating and owns no investment rule: it admits or blocks a
frozen evidence chain for later human review and never applies a profile.
"""

from __future__ import annotations

import hashlib
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from turtle_value_engine.providers.models import canonical_json_bytes

EVOLUTION_CONTRACT_VERSION = "controlled-evolution-v1"
_HASH_PATTERN = r"^[0-9a-f]{64}$"
_CHECK_NAME_PATTERN = r"^[A-Z][A-Z0-9_]{2,63}$"


class EvaluationCheckV1(BaseModel):
    """One machine-readable admission check with a stable name."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: StrictStr = Field(pattern=_CHECK_NAME_PATTERN)
    state: Literal["PASS", "BLOCKED"]
    detail: StrictStr = Field(min_length=1, max_length=2_000)


class ControlledEvolutionEvaluationV1(BaseModel):
    """Immutable evaluation/admission dossier for one proposal-only evidence chain.

    The dossier binds the frozen dataset manifest, calibration experiment,
    embedded ``PROPOSAL_ONLY`` proposal, separate holdout result, frozen
    observations and the exact base-profile bytes into one deterministic
    artifact.  ``admission_state`` is only an evidence-admission decision;
    it is never an investment decision, a performance verdict or an approval.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["controlled_evolution_evaluation_v1"] = (
        "controlled_evolution_evaluation_v1"
    )
    evaluation_id: StrictStr = Field(min_length=1)
    base_profile_id: StrictStr = Field(min_length=1)
    base_profile_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    dataset_id: StrictStr = Field(min_length=1)
    manifest_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    experiment_id: StrictStr = Field(min_length=1)
    experiment_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    proposal_id: StrictStr = Field(min_length=1)
    proposal_payload_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    candidate_profile_id: StrictStr = Field(min_length=1)
    parameter_overrides: dict[str, float | int | str | bool]
    holdout_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    observations_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    observation_count: StrictInt = Field(ge=0)
    scorer_kind: Literal["BUILT_IN_CANONICAL"] = "BUILT_IN_CANONICAL"
    checks: list[EvaluationCheckV1] = Field(min_length=1, max_length=256)
    admission_state: Literal["READY_FOR_HUMAN_REVIEW", "BLOCKED"]
    requires_human_approval: Literal[True] = True
    automatic_application_allowed: Literal[False] = False
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_evaluation(self) -> Self:
        names = [check.name for check in self.checks]
        if len(names) != len(set(names)):
            raise ValueError("evaluation check names must be unique")
        blocked = any(check.state == "BLOCKED" for check in self.checks)
        if self.admission_state == "READY_FOR_HUMAN_REVIEW" and blocked:
            raise ValueError("READY_FOR_HUMAN_REVIEW requires every check to PASS")
        if self.admission_state == "BLOCKED" and not blocked:
            raise ValueError("BLOCKED requires at least one BLOCKED check")
        payload = self.model_dump(mode="json", warnings=False, exclude={"content_sha256"})
        expected = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        if self.content_sha256 != expected:
            raise ValueError("evaluation content_sha256 does not match content")
        return self

    @classmethod
    def build(
        cls,
        *,
        evaluation_id: str,
        base_profile_id: str,
        base_profile_sha256: str,
        dataset_id: str,
        manifest_content_sha256: str,
        experiment_id: str,
        experiment_content_sha256: str,
        proposal_id: str,
        proposal_payload_sha256: str,
        candidate_profile_id: str,
        parameter_overrides: dict[str, float | int | str | bool],
        holdout_content_sha256: str,
        observations_content_sha256: str,
        observation_count: int,
        checks: list[EvaluationCheckV1],
        admission_state: str,
    ) -> ControlledEvolutionEvaluationV1:
        """Construct an evaluation dossier with its deterministic content hash."""

        candidate = cls.model_construct(
            contract="controlled_evolution_evaluation_v1",
            evaluation_id=evaluation_id,
            base_profile_id=base_profile_id,
            base_profile_sha256=base_profile_sha256,
            dataset_id=dataset_id,
            manifest_content_sha256=manifest_content_sha256,
            experiment_id=experiment_id,
            experiment_content_sha256=experiment_content_sha256,
            proposal_id=proposal_id,
            proposal_payload_sha256=proposal_payload_sha256,
            candidate_profile_id=candidate_profile_id,
            parameter_overrides=parameter_overrides,
            holdout_content_sha256=holdout_content_sha256,
            observations_content_sha256=observations_content_sha256,
            observation_count=observation_count,
            scorer_kind="BUILT_IN_CANONICAL",
            checks=checks,
            admission_state=admission_state,
            requires_human_approval=True,
            automatic_application_allowed=False,
            content_sha256="0" * 64,
        )
        payload = candidate.model_dump(mode="json", warnings=False)
        payload["content_sha256"] = hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in payload.items() if key != "content_sha256"}
            )
        ).hexdigest()
        return cls.model_validate(payload)


def persisted_content_sha256(model: BaseModel) -> str:
    """Recompute the canonical content hash of a persisted hash-carrying contract."""

    payload = model.model_dump(mode="json", warnings=False, exclude={"content_sha256"})
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


__all__ = [
    "EVOLUTION_CONTRACT_VERSION",
    "ControlledEvolutionEvaluationV1",
    "EvaluationCheckV1",
    "persisted_content_sha256",
]
