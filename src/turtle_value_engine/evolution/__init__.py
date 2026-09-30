"""Controlled-evolution evaluation boundaries (Phase 7-A).

Offline, deterministic, non-mutating evaluation of one frozen proposal-only
calibration evidence chain.  The package admits evidence for later human
review; it never materializes, edits or approves a rule profile.

Phase 7-A-R1 adds the frozen-evidence binding boundary: admission requires a
prior calibration-time :class:`CalibrationEvidenceBindingV1`, and the
persisted dossier carries exactly the canonical required-check set for its
contract version.

Phase 7-A-R2 adds the authoritative calibration-freeze anchor boundary:
admission additionally requires the binding to be referenced by the
:class:`~turtle_value_engine.backtest.contracts.CalibrationFreezeRecordV1`
committed for this experiment in the authoritative calibration workspace,
resolved through the workspace loader boundary rather than an arbitrary
sidecar path.
"""

from .contracts import (
    CHECK_BASE_PROFILE_BYTES_HASH,
    CHECK_BASE_PROFILE_IDENTITY_AGREEMENT,
    CHECK_CANONICAL_REPRODUCTION,
    CHECK_CHRONOLOGY_DISJOINT_ORDERED,
    CHECK_EVIDENCE_BINDING_BASE_PROFILE_IDENTITY,
    CHECK_EVIDENCE_BINDING_EXPERIMENT_IDENTITY,
    CHECK_EVIDENCE_BINDING_MANIFEST_IDENTITY,
    CHECK_EVIDENCE_BINDING_OBSERVATIONS_IDENTITY,
    CHECK_EVIDENCE_BINDING_PRESENT,
    CHECK_EVIDENCE_BINDING_PROPOSAL_IDENTITY,
    CHECK_EXPERIMENT_CONTENT_HASH,
    CHECK_FREEZE_ANCHOR_BINDING_IDENTITY,
    CHECK_FREEZE_ANCHOR_EXPERIMENT_IDENTITY,
    CHECK_FREEZE_ANCHOR_PRESENT,
    CHECK_HOLDOUT_BINDING,
    CHECK_HOLDOUT_CONTENT_HASH,
    CHECK_HOLDOUT_REPRODUCTION,
    CHECK_MANIFEST_IDENTITY,
    CHECK_PROPOSAL_EMBEDDING,
    CHECK_PROPOSAL_STATUS_PROPOSAL_ONLY,
    CHECK_SEARCH_HOLDOUT_ISOLATION,
    CHECK_SELECTED_TRIAL_AGREEMENT,
    EVOLUTION_CONTRACT_VERSION,
    REQUIRED_EVALUATION_CHECK_NAMES,
    ControlledEvolutionEvaluationV1,
    EvaluationCheckV1,
    persisted_content_sha256,
)
from .evaluate import (
    EvolutionEvaluationError,
    evaluate_controlled_evolution,
    frozen_observations_sha256,
    proposal_payload_sha256,
)

__all__ = [
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
    "CHECK_FREEZE_ANCHOR_BINDING_IDENTITY",
    "CHECK_FREEZE_ANCHOR_EXPERIMENT_IDENTITY",
    "CHECK_FREEZE_ANCHOR_PRESENT",
    "CHECK_HOLDOUT_BINDING",
    "CHECK_HOLDOUT_CONTENT_HASH",
    "CHECK_HOLDOUT_REPRODUCTION",
    "CHECK_MANIFEST_IDENTITY",
    "CHECK_PROPOSAL_EMBEDDING",
    "CHECK_PROPOSAL_STATUS_PROPOSAL_ONLY",
    "CHECK_SEARCH_HOLDOUT_ISOLATION",
    "CHECK_SELECTED_TRIAL_AGREEMENT",
    "EVOLUTION_CONTRACT_VERSION",
    "REQUIRED_EVALUATION_CHECK_NAMES",
    "ControlledEvolutionEvaluationV1",
    "EvaluationCheckV1",
    "EvolutionEvaluationError",
    "evaluate_controlled_evolution",
    "frozen_observations_sha256",
    "persisted_content_sha256",
    "proposal_payload_sha256",
]
