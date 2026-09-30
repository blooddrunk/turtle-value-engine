"""Candidate-profile materialization (Phase 7-B1).

This module owns the immutable ``CandidateProfileMaterializationV1`` record
and the pure orchestration that turns one *freshly re-admitted*
``READY_FOR_HUMAN_REVIEW`` evaluation into candidate-only profile bytes plus
a profile-aware frozen PIT replay.  It never writes a file: the CLI boundary
owns path guarding and non-destructive output.

Authority model (Phase 7-A-R2 preserved): a persisted dossier is audit
evidence only.  The caller must resolve the authoritative calibration
workspace, re-run the controlled-evolution admission chain and supply the
resulting fresh evaluation together with the anchored freeze record and
binding; this boundary cross-checks those identities before projecting.  A
dossier file, a sidecar binding or manually supplied freeze-record bytes are
never sufficient authority.

Legacy compatibility fail-closed: a proposal whose search space froze no
materialization semantics — the entire pre-B1 history, including the
canonical ``min_quality`` fixture — is classified ``NON_MATERIALIZABLE``
with an explicit machine-readable reason.  Semantics are never inferred from
parameter names, feature names, candidate ids, rationale text or score
behavior.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from turtle_value_engine.backtest.contracts import (
    BacktestDatasetManifest,
    CalibrationEvidenceBindingV1,
    CalibrationExperiment,
    CalibrationFreezeRecordV1,
    CalibrationHoldoutResult,
    CalibrationObservation,
)
from turtle_value_engine.backtest.materialization_semantics import (
    MaterializableParameterSemanticsSetV1,
    MaterializationSemanticsError,
    resolve_materialization_semantics,
)
from turtle_value_engine.evolution.candidate_projection import (
    ProjectedCandidate,
    project_candidate_profile,
)
from turtle_value_engine.evolution.contracts import ControlledEvolutionEvaluationV1
from turtle_value_engine.evolution.replay import (
    CandidateProfileReplayV1,
    replay_candidate_profile,
)
from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.providers.normalization import deterministic_id

_HASH_PATTERN = r"^[0-9a-f]{64}$"

#: Stable machine-readable reason codes for blocked materialization.
REASON_NO_FROZEN_MATERIALIZATION_SEMANTICS = "NO_FROZEN_MATERIALIZATION_SEMANTICS"
REASON_SEMANTICS_REFERENCE_UNRESOLVED = "SEMANTICS_REFERENCE_UNRESOLVED"
REASON_UNKNOWN_MATERIALIZABLE_PARAMETER = "UNKNOWN_MATERIALIZABLE_PARAMETER"
REASON_PARAMETER_VALUE_OUT_OF_CONTRACT = "PARAMETER_VALUE_OUT_OF_CONTRACT"
REASON_ADMISSION_NOT_READY = "ADMISSION_NOT_READY"
REASON_ANCHORED_IDENTITY_MISMATCH = "ANCHORED_IDENTITY_MISMATCH"


class CandidateMaterializationError(ValueError):
    """Raised when materialization is blocked before any candidate output.

    ``classification`` is ``NON_MATERIALIZABLE`` for proposal-semantics
    blockers (legacy/unbound proposals, post-hoc substitution, unknown or
    out-of-contract overrides) and ``MATERIALIZATION_BLOCKED`` for authority
    or replay blockers.  ``reason_code`` is one of the ``REASON_*`` constants.
    """

    def __init__(
        self, message: str, *, classification: str, reason_code: str
    ) -> None:
        super().__init__(message)
        self.classification = classification
        self.reason_code = reason_code


def _non_materializable(message: str, reason_code: str) -> CandidateMaterializationError:
    return CandidateMaterializationError(
        message, classification="NON_MATERIALIZABLE", reason_code=reason_code
    )


class CandidateRuleLeafChangeV1(BaseModel):
    """One registered scalar rule leaf changed by materialization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["candidate_rule_leaf_change_v1"] = "candidate_rule_leaf_change_v1"
    target_key: StrictStr = Field(min_length=1)
    profile_path: StrictStr = Field(min_length=1)
    before: float | int | str | bool
    after: float | int | str | bool


class CandidateMetadataChangeV1(BaseModel):
    """One candidate-only profile metadata field changed by materialization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["candidate_metadata_change_v1"] = "candidate_metadata_change_v1"
    field: Literal["id", "name", "status", "description"]
    before: StrictStr
    after: StrictStr


class CandidateProfileMaterializationV1(BaseModel):
    """Immutable record binding one admitted proposal to candidate bytes.

    Binds the fresh controlled-evolution evaluation identity, the
    authoritative freeze anchor and evidence binding it was re-admitted
    through, the experiment/proposal identities, the exact base-profile
    bytes, the frozen parameter-semantics identity, the exact changed rule
    leaves and metadata, the candidate content hash and the profile-aware
    frozen PIT replay behind one deterministic ``materialization_id`` and
    ``content_sha256``.  Materialization is review input only: it requires
    human approval and can never authorize automatic application.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["candidate_profile_materialization_v1"] = (
        "candidate_profile_materialization_v1"
    )
    materialization_id: StrictStr = Field(min_length=1)
    evaluation_id: StrictStr = Field(min_length=1)
    evaluation_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    freeze_anchor_id: StrictStr = Field(min_length=1)
    freeze_anchor_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    evidence_binding_id: StrictStr = Field(min_length=1)
    evidence_binding_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    experiment_id: StrictStr = Field(min_length=1)
    experiment_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    proposal_id: StrictStr = Field(min_length=1)
    proposal_payload_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    base_profile_id: StrictStr = Field(min_length=1)
    base_profile_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    semantics_id: StrictStr = Field(min_length=1)
    semantics_version: StrictStr = Field(min_length=1)
    semantics_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    rule_changes: list[CandidateRuleLeafChangeV1] = Field(min_length=1, max_length=64)
    metadata_changes: list[CandidateMetadataChangeV1] = Field(min_length=1, max_length=4)
    candidate_profile_id: StrictStr = Field(min_length=1)
    candidate_content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    replay: CandidateProfileReplayV1
    requires_human_approval: Literal[True] = True
    automatic_application_allowed: Literal[False] = False
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_materialization(self) -> Self:
        expected_id = deterministic_id(
            "candidate-profile-materialization",
            self.evaluation_id,
            self.evaluation_content_sha256,
            self.semantics_id,
            self.semantics_content_sha256,
            self.base_profile_id,
            self.base_profile_sha256,
            self.candidate_profile_id,
            self.candidate_content_sha256,
            self.replay.replay_id,
        )
        if self.materialization_id != expected_id:
            raise ValueError(
                "materialization_id does not match the deterministic identity of "
                "the bound artifacts"
            )
        if self.candidate_profile_id == self.base_profile_id:
            raise ValueError("candidate profile must be distinct from the base profile")
        if self.candidate_profile_id == "strict-v2":
            raise ValueError(
                "materialization must never assign the human release name strict-v2"
            )
        if self.replay.candidate_profile_id != self.candidate_profile_id or (
            self.replay.candidate_profile_sha256 != self.candidate_content_sha256
        ):
            raise ValueError("replay identity does not match the candidate identity")
        if self.replay.base_profile_id != self.base_profile_id or (
            self.replay.base_profile_sha256 != self.base_profile_sha256
        ):
            raise ValueError("replay identity does not match the base-profile identity")
        payload = self.model_dump(mode="json", warnings=False, exclude={"content_sha256"})
        expected = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        if self.content_sha256 != expected:
            raise ValueError(
                "candidate materialization content_sha256 does not match content"
            )
        return self

    @classmethod
    def build(
        cls,
        *,
        evaluation: ControlledEvolutionEvaluationV1,
        semantics: MaterializableParameterSemanticsSetV1,
        base_profile_id: str,
        base_profile_sha256: str,
        rule_changes: list[CandidateRuleLeafChangeV1],
        metadata_changes: list[CandidateMetadataChangeV1],
        candidate_profile_id: str,
        candidate_content_sha256: str,
        replay: CandidateProfileReplayV1,
    ) -> CandidateProfileMaterializationV1:
        """Construct a materialization record with its deterministic identity."""

        materialization_id = deterministic_id(
            "candidate-profile-materialization",
            evaluation.evaluation_id,
            evaluation.content_sha256,
            semantics.semantics_id,
            semantics.content_sha256,
            base_profile_id,
            base_profile_sha256,
            candidate_profile_id,
            candidate_content_sha256,
            replay.replay_id,
        )
        candidate = cls.model_construct(
            contract="candidate_profile_materialization_v1",
            materialization_id=materialization_id,
            evaluation_id=evaluation.evaluation_id,
            evaluation_content_sha256=evaluation.content_sha256,
            freeze_anchor_id=evaluation.freeze_anchor_id or "",
            freeze_anchor_sha256=evaluation.freeze_anchor_sha256 or "",
            evidence_binding_id=evaluation.evidence_binding_id or "",
            evidence_binding_sha256=evaluation.evidence_binding_sha256 or "",
            experiment_id=evaluation.experiment_id,
            experiment_content_sha256=evaluation.experiment_content_sha256,
            proposal_id=evaluation.proposal_id,
            proposal_payload_sha256=evaluation.proposal_payload_sha256,
            base_profile_id=base_profile_id,
            base_profile_sha256=base_profile_sha256,
            semantics_id=semantics.semantics_id,
            semantics_version=semantics.semantics_version,
            semantics_content_sha256=semantics.content_sha256,
            rule_changes=rule_changes,
            metadata_changes=metadata_changes,
            candidate_profile_id=candidate_profile_id,
            candidate_content_sha256=candidate_content_sha256,
            replay=replay,
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


@dataclass(frozen=True)
class MaterializationOutcome:
    """Everything one materialization produces; nothing is written to disk."""

    projected: ProjectedCandidate
    replay: CandidateProfileReplayV1
    record: CandidateProfileMaterializationV1


def classify_proposal_materializability(
    *, experiment: CalibrationExperiment
) -> MaterializableParameterSemanticsSetV1:
    """Resolve the frozen semantics of one experiment's proposal.

    Returns the installed set the experiment's search space froze.  Every
    blocker is a ``NON_MATERIALIZABLE`` classification with a stable reason
    code: legacy/unbound search spaces, references that no longer resolve to
    an installed set (post-hoc substitution) and unregistered override keys.
    """

    reference = experiment.search_space.materialization_semantics
    if reference is None:
        raise _non_materializable(
            "the experiment's search space froze no materialization semantics; "
            "legacy/unbound proposals are evaluable history but never "
            "materializable",
            REASON_NO_FROZEN_MATERIALIZATION_SEMANTICS,
        )
    try:
        semantics = resolve_materialization_semantics(reference)
    except MaterializationSemanticsError as exc:
        raise _non_materializable(
            f"the frozen materialization semantics reference does not resolve: {exc}",
            REASON_SEMANTICS_REFERENCE_UNRESOLVED,
        ) from exc
    proposal = experiment.proposal
    if proposal is None:
        raise _non_materializable(
            "the experiment carries no selected proposal",
            REASON_NO_FROZEN_MATERIALIZATION_SEMANTICS,
        )
    for key in sorted(proposal.parameter_overrides):
        if key not in semantics.parameters:
            raise _non_materializable(
                f"proposal override {key!r} is not a registered materializable "
                f"parameter of semantics {semantics.semantics_id}",
                REASON_UNKNOWN_MATERIALIZABLE_PARAMETER,
            )
        parameter = semantics.parameters[key]
        try:
            parameter.target.validate_candidate_value(proposal.parameter_overrides[key])
        except MaterializationSemanticsError as exc:
            raise _non_materializable(
                f"proposal override {key!r} violates its frozen value contract: {exc}",
                REASON_PARAMETER_VALUE_OUT_OF_CONTRACT,
            ) from exc
    return semantics


def materialize_candidate_profile(
    *,
    manifest: BacktestDatasetManifest,
    experiment: CalibrationExperiment,
    holdout: CalibrationHoldoutResult,
    observations: list[CalibrationObservation],
    base_profile_bytes: bytes,
    evaluation: ControlledEvolutionEvaluationV1,
    freeze_record: CalibrationFreezeRecordV1,
    evidence_binding: CalibrationEvidenceBindingV1,
) -> MaterializationOutcome:
    """Materialize one freshly re-admitted proposal into candidate bytes.

    The caller supplies the authoritative anchored evidence and the fresh
    evaluation computed from it.  This boundary requires the evaluation to be
    ``READY_FOR_HUMAN_REVIEW`` and cross-checks it against the anchored
    identities, resolves the frozen semantics (fail-closed for legacy or
    substituted proposals), projects the candidate-only profile and proves it
    through profile-aware frozen PIT replay.  No output path is touched.
    """

    if evaluation.admission_state != "READY_FOR_HUMAN_REVIEW":
        raise CandidateMaterializationError(
            "the fresh controlled-evolution evaluation is BLOCKED ("
            + ", ".join(
                check.name for check in evaluation.checks if check.state == "BLOCKED"
            )
            + "); materialization requires a READY_FOR_HUMAN_REVIEW admission",
            classification="MATERIALIZATION_BLOCKED",
            reason_code=REASON_ADMISSION_NOT_READY,
        )
    if (
        evaluation.freeze_anchor_id != freeze_record.freeze_id
        or evaluation.freeze_anchor_sha256 != freeze_record.content_sha256
        or evaluation.evidence_binding_id != evidence_binding.binding_id
        or evaluation.evidence_binding_sha256 != evidence_binding.content_sha256
        or evaluation.experiment_id != experiment.experiment_id
        or evaluation.experiment_content_sha256 != experiment.content_sha256
    ):
        raise CandidateMaterializationError(
            "the fresh evaluation is not bound to the supplied anchored "
            "evidence; dossier-only authority is insufficient",
            classification="MATERIALIZATION_BLOCKED",
            reason_code=REASON_ANCHORED_IDENTITY_MISMATCH,
        )

    semantics = classify_proposal_materializability(experiment=experiment)
    proposal = experiment.proposal
    assert proposal is not None  # READY evaluation guarantees a selected proposal.

    projected = project_candidate_profile(
        base_profile_bytes=base_profile_bytes,
        proposal=proposal,
        semantics=semantics,
    )
    replay = replay_candidate_profile(
        manifest=manifest,
        observations=observations,
        split=experiment.split,
        base_profile=projected.base_profile,
        candidate_profile=projected.profile,
        base_profile_sha256=proposal.base_profile_sha256,
        candidate_profile_sha256=projected.candidate_content_sha256,
    )
    record = CandidateProfileMaterializationV1.build(
        evaluation=evaluation,
        semantics=semantics,
        base_profile_id=proposal.base_profile_id,
        base_profile_sha256=proposal.base_profile_sha256,
        rule_changes=[
            CandidateRuleLeafChangeV1(
                target_key=change.target_key,
                profile_path=change.profile_path,
                before=change.before,
                after=change.after,
            )
            for change in projected.rule_changes
        ],
        metadata_changes=[
            CandidateMetadataChangeV1(
                field=change.field, before=change.before, after=change.after
            )
            for change in projected.metadata_changes
        ],
        candidate_profile_id=projected.profile.profile.id,
        candidate_content_sha256=projected.candidate_content_sha256,
        replay=replay,
    )
    return MaterializationOutcome(
        projected=projected, replay=replay, record=record
    )


__all__ = [
    "CandidateMaterializationError",
    "CandidateMetadataChangeV1",
    "CandidateProfileMaterializationV1",
    "CandidateRuleLeafChangeV1",
    "MaterializationOutcome",
    "REASON_ADMISSION_NOT_READY",
    "REASON_ANCHORED_IDENTITY_MISMATCH",
    "REASON_NO_FROZEN_MATERIALIZATION_SEMANTICS",
    "REASON_PARAMETER_VALUE_OUT_OF_CONTRACT",
    "REASON_SEMANTICS_REFERENCE_UNRESOLVED",
    "REASON_UNKNOWN_MATERIALIZABLE_PARAMETER",
    "classify_proposal_materializability",
    "materialize_candidate_profile",
]
