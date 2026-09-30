"""Typed, persisted contracts for controlled-evolution evaluation.

This module contains data envelopes plus the canonical admission-check set
that defines this contract version.  The Phase 7-A evaluation boundary is
offline, non-mutating and owns no investment rule: it admits or blocks a
frozen evidence chain for later human review and never applies a profile.
"""

from __future__ import annotations

import hashlib
from typing import Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.providers.normalization import deterministic_id

EVOLUTION_CONTRACT_VERSION = "controlled-evolution-v1"
_HASH_PATTERN = r"^[0-9a-f]{64}$"

CHECK_BASE_PROFILE_BYTES_HASH = "BASE_PROFILE_BYTES_HASH"
CHECK_BASE_PROFILE_IDENTITY_AGREEMENT = "BASE_PROFILE_IDENTITY_AGREEMENT"
CHECK_EVIDENCE_BINDING_PRESENT = "EVIDENCE_BINDING_PRESENT"
CHECK_EVIDENCE_BINDING_MANIFEST_IDENTITY = "EVIDENCE_BINDING_MANIFEST_IDENTITY"
CHECK_EVIDENCE_BINDING_EXPERIMENT_IDENTITY = "EVIDENCE_BINDING_EXPERIMENT_IDENTITY"
CHECK_EVIDENCE_BINDING_OBSERVATIONS_IDENTITY = "EVIDENCE_BINDING_OBSERVATIONS_IDENTITY"
CHECK_EVIDENCE_BINDING_BASE_PROFILE_IDENTITY = "EVIDENCE_BINDING_BASE_PROFILE_IDENTITY"
CHECK_EVIDENCE_BINDING_PROPOSAL_IDENTITY = "EVIDENCE_BINDING_PROPOSAL_IDENTITY"
CHECK_MANIFEST_IDENTITY = "MANIFEST_IDENTITY"
CHECK_EXPERIMENT_CONTENT_HASH = "EXPERIMENT_CONTENT_HASH"
CHECK_PROPOSAL_EMBEDDING = "PROPOSAL_EMBEDDING"
CHECK_SELECTED_TRIAL_AGREEMENT = "SELECTED_TRIAL_AGREEMENT"
CHECK_SEARCH_HOLDOUT_ISOLATION = "SEARCH_HOLDOUT_ISOLATION"
CHECK_CHRONOLOGY_DISJOINT_ORDERED = "CHRONOLOGY_DISJOINT_ORDERED"
CHECK_PROPOSAL_STATUS_PROPOSAL_ONLY = "PROPOSAL_STATUS_PROPOSAL_ONLY"
CHECK_HOLDOUT_BINDING = "HOLDOUT_BINDING"
CHECK_HOLDOUT_CONTENT_HASH = "HOLDOUT_CONTENT_HASH"
CHECK_CANONICAL_REPRODUCTION = "CANONICAL_REPRODUCTION"
CHECK_HOLDOUT_REPRODUCTION = "HOLDOUT_REPRODUCTION"

#: The one canonical required-check set for ``controlled_evolution_evaluation_v1``.
#: A persisted dossier is valid only when its checks are exactly this
#: sequence — no omission, duplicate, unknown substitution or reordering.
REQUIRED_EVALUATION_CHECK_NAMES: tuple[str, ...] = (
    CHECK_BASE_PROFILE_BYTES_HASH,
    CHECK_BASE_PROFILE_IDENTITY_AGREEMENT,
    CHECK_EVIDENCE_BINDING_PRESENT,
    CHECK_EVIDENCE_BINDING_MANIFEST_IDENTITY,
    CHECK_EVIDENCE_BINDING_EXPERIMENT_IDENTITY,
    CHECK_EVIDENCE_BINDING_OBSERVATIONS_IDENTITY,
    CHECK_EVIDENCE_BINDING_BASE_PROFILE_IDENTITY,
    CHECK_EVIDENCE_BINDING_PROPOSAL_IDENTITY,
    CHECK_MANIFEST_IDENTITY,
    CHECK_EXPERIMENT_CONTENT_HASH,
    CHECK_PROPOSAL_EMBEDDING,
    CHECK_SELECTED_TRIAL_AGREEMENT,
    CHECK_SEARCH_HOLDOUT_ISOLATION,
    CHECK_CHRONOLOGY_DISJOINT_ORDERED,
    CHECK_PROPOSAL_STATUS_PROPOSAL_ONLY,
    CHECK_HOLDOUT_BINDING,
    CHECK_HOLDOUT_CONTENT_HASH,
    CHECK_CANONICAL_REPRODUCTION,
    CHECK_HOLDOUT_REPRODUCTION,
)

EvaluationCheckName: TypeAlias = Literal[*REQUIRED_EVALUATION_CHECK_NAMES]


class EvaluationCheckV1(BaseModel):
    """One machine-readable admission check with a stable canonical name."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: EvaluationCheckName
    state: Literal["PASS", "BLOCKED"]
    detail: StrictStr = Field(min_length=1, max_length=2_000)


class ControlledEvolutionEvaluationV1(BaseModel):
    """Immutable evaluation/admission dossier for one proposal-only evidence chain.

    The dossier binds the frozen dataset manifest, calibration experiment,
    embedded ``PROPOSAL_ONLY`` proposal, separate holdout result, frozen
    observations, the exact base-profile bytes and the prior
    calibration-time evidence binding into one deterministic artifact.
    ``admission_state`` is only an evidence-admission decision; it is never
    an investment decision, a performance verdict or an approval.
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
    evidence_binding_id: StrictStr | None = Field(default=None, min_length=1)
    evidence_binding_sha256: StrictStr | None = Field(
        default=None, pattern=_HASH_PATTERN
    )
    scorer_kind: Literal["BUILT_IN_CANONICAL"] = "BUILT_IN_CANONICAL"
    checks: list[EvaluationCheckV1] = Field(
        min_length=len(REQUIRED_EVALUATION_CHECK_NAMES),
        max_length=len(REQUIRED_EVALUATION_CHECK_NAMES),
    )
    admission_state: Literal["READY_FOR_HUMAN_REVIEW", "BLOCKED"]
    requires_human_approval: Literal[True] = True
    automatic_application_allowed: Literal[False] = False
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_evaluation(self) -> Self:
        names = [check.name for check in self.checks]
        if names != list(REQUIRED_EVALUATION_CHECK_NAMES):
            raise ValueError(
                "evaluation checks must contain exactly the canonical required "
                "check set for this contract version, in canonical order "
                f"(expected {len(REQUIRED_EVALUATION_CHECK_NAMES)} checks, "
                f"got {len(names)})"
            )
        if (self.evidence_binding_id is None) != (self.evidence_binding_sha256 is None):
            raise ValueError("evidence binding identity fields must be supplied together")
        blocked = any(check.state == "BLOCKED" for check in self.checks)
        if self.admission_state == "READY_FOR_HUMAN_REVIEW":
            if blocked:
                raise ValueError("READY_FOR_HUMAN_REVIEW requires every check to PASS")
            if self.evidence_binding_id is None or self.evidence_binding_sha256 is None:
                raise ValueError(
                    "READY_FOR_HUMAN_REVIEW requires a bound calibration evidence binding"
                )
        if self.admission_state == "BLOCKED" and not blocked:
            raise ValueError("BLOCKED requires at least one BLOCKED check")
        expected_evaluation_id = deterministic_id(
            "controlled-evolution-evaluation",
            self.base_profile_id,
            self.base_profile_sha256,
            self.dataset_id,
            self.manifest_content_sha256,
            self.experiment_id,
            self.experiment_content_sha256,
            self.proposal_id,
            self.proposal_payload_sha256,
            self.holdout_content_sha256,
            self.observations_content_sha256,
            self.evidence_binding_id,
            self.evidence_binding_sha256,
        )
        if self.evaluation_id != expected_evaluation_id:
            raise ValueError(
                "evaluation_id does not match the deterministic identity of the "
                "bound artifacts"
            )
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
        evidence_binding_id: str | None,
        evidence_binding_sha256: str | None,
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
            evidence_binding_id=evidence_binding_id,
            evidence_binding_sha256=evidence_binding_sha256,
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
    "CHECK_BASE_PROFILE_BYTES_HASH",
    "CHECK_BASE_PROFILE_IDENTITY_AGREEMENT",
    "CHECK_CANONICAL_REPRODUCTION",
    "CHECK_CHRONOLOGY_DISJOINT_ORDERED",
    "CHECK_EVIDENCE_BINDING_BASE_PROFILE_IDENTITY",
    "CHECK_EVIDENCE_BINDING_EXPERIMENT_IDENTITY",
    "CHECK_EVIDENCE_BINDING_MANIFEST_IDENTITY",
    "CHECK_EVIDENCE_BINDING_OBSERVATIONS_IDENTITY",
    "CHECK_EVIDENCE_BINDING_PRESENT",
    "CHECK_EVIDENCE_BINDING_PROPOSAL_IDENTITY",
    "CHECK_EXPERIMENT_CONTENT_HASH",
    "CHECK_HOLDOUT_BINDING",
    "CHECK_HOLDOUT_CONTENT_HASH",
    "CHECK_HOLDOUT_REPRODUCTION",
    "CHECK_MANIFEST_IDENTITY",
    "CHECK_PROPOSAL_EMBEDDING",
    "CHECK_PROPOSAL_STATUS_PROPOSAL_ONLY",
    "CHECK_SEARCH_HOLDOUT_ISOLATION",
    "CHECK_SELECTED_TRIAL_AGREEMENT",
    "REQUIRED_EVALUATION_CHECK_NAMES",
    "ControlledEvolutionEvaluationV1",
    "EvaluationCheckName",
    "EvaluationCheckV1",
    "persisted_content_sha256",
]
