"""Controlled-evolution evaluation boundaries (Phase 7-A).

Offline, deterministic, non-mutating evaluation of one frozen proposal-only
calibration evidence chain.  The package admits evidence for later human
review; it never materializes, edits or approves a rule profile.
"""

from .contracts import (
    EVOLUTION_CONTRACT_VERSION,
    ControlledEvolutionEvaluationV1,
    EvaluationCheckV1,
    persisted_content_sha256,
)
from .evaluate import (
    CHECK_BASE_PROFILE_BYTES_HASH,
    CHECK_BASE_PROFILE_IDENTITY_AGREEMENT,
    CHECK_CANONICAL_REPRODUCTION,
    CHECK_CHRONOLOGY_DISJOINT_ORDERED,
    CHECK_EXPERIMENT_CONTENT_HASH,
    CHECK_HOLDOUT_BINDING,
    CHECK_HOLDOUT_CONTENT_HASH,
    CHECK_HOLDOUT_REPRODUCTION,
    CHECK_MANIFEST_IDENTITY,
    CHECK_PROPOSAL_EMBEDDING,
    CHECK_PROPOSAL_STATUS_PROPOSAL_ONLY,
    CHECK_SEARCH_HOLDOUT_ISOLATION,
    CHECK_SELECTED_TRIAL_AGREEMENT,
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
    "CHECK_EXPERIMENT_CONTENT_HASH",
    "CHECK_HOLDOUT_BINDING",
    "CHECK_HOLDOUT_CONTENT_HASH",
    "CHECK_HOLDOUT_REPRODUCTION",
    "CHECK_MANIFEST_IDENTITY",
    "CHECK_PROPOSAL_EMBEDDING",
    "CHECK_PROPOSAL_STATUS_PROPOSAL_ONLY",
    "CHECK_SEARCH_HOLDOUT_ISOLATION",
    "CHECK_SELECTED_TRIAL_AGREEMENT",
    "EVOLUTION_CONTRACT_VERSION",
    "ControlledEvolutionEvaluationV1",
    "EvaluationCheckV1",
    "EvolutionEvaluationError",
    "evaluate_controlled_evolution",
    "frozen_observations_sha256",
    "persisted_content_sha256",
    "proposal_payload_sha256",
]
