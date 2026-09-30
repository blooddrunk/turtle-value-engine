"""Calibration-time evidence binding for the frozen evolution evidence chain.

The functions here run at the calibration/freeze boundary, where the exact
dataset manifest, the exact observation rows and the resulting experiment are
simultaneously available.  They are the only sanctioned producers of
:class:`CalibrationEvidenceBindingV1`; the controlled-evolution evaluator
consumes a previously persisted binding and never synthesizes one from its
own untrusted inputs.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from turtle_value_engine.providers.models import canonical_json_bytes

from .contracts import (
    BacktestDatasetManifest,
    CalibrationEvidenceBindingV1,
    CalibrationExperiment,
    CalibrationObservation,
    CandidateProfileProposal,
)


class EvidenceBindingError(ValueError):
    """Raised when no calibration evidence binding can be produced."""


def _ordered_observations(
    observations: Iterable[CalibrationObservation],
) -> list[CalibrationObservation]:
    return sorted(
        observations, key=lambda item: (item.observed_at, item.observation_id)
    )


def canonical_observations_sha256(
    observations: Iterable[CalibrationObservation],
) -> str:
    """Hash the frozen observation rows in canonical chronological order.

    This is the one canonical observation-set identity: it is computed
    identically at the calibration/freeze boundary and at evaluation time, so
    any difference in the supplied rows — including non-scoring provenance
    such as ``source_hash`` — changes the identity.
    """

    ordered = _ordered_observations(observations)
    return hashlib.sha256(
        canonical_json_bytes(
            [item.model_dump(mode="json", warnings=False) for item in ordered]
        )
    ).hexdigest()


def canonical_proposal_payload_sha256(proposal: CandidateProfileProposal) -> str:
    """Hash the canonical proposal payload without mutating its contract."""

    return hashlib.sha256(
        canonical_json_bytes(proposal.model_dump(mode="json", warnings=False))
    ).hexdigest()


def build_calibration_evidence_binding(
    *,
    manifest: BacktestDatasetManifest,
    experiment: CalibrationExperiment,
    observations: Iterable[CalibrationObservation],
) -> CalibrationEvidenceBindingV1:
    """Bind the exact calibration-time evidence identities into one artifact.

    The caller supplies the exact manifest the calibration ran against, the
    exact frozen observation rows and the resulting experiment.  A manifest
    whose identity disagrees with the experiment, or an experiment without a
    selected proposal, fails closed: a binding across mismatched evidence
    must never be persisted.
    """

    if manifest.dataset_id != experiment.manifest_id:
        raise EvidenceBindingError(
            "evidence binding requires the manifest the experiment calibrated "
            f"against (manifest dataset_id={manifest.dataset_id}, experiment "
            f"manifest_id={experiment.manifest_id})"
        )
    proposal = experiment.proposal
    if proposal is None or experiment.selected_trial_id is None:
        raise EvidenceBindingError(
            "evidence binding requires an experiment with a selected proposal"
        )
    ordered = _ordered_observations(observations)
    return CalibrationEvidenceBindingV1.build(
        manifest_id=manifest.dataset_id,
        manifest_content_sha256=manifest.content_sha256,
        experiment_id=experiment.experiment_id,
        experiment_content_sha256=experiment.content_sha256,
        observations_content_sha256=canonical_observations_sha256(ordered),
        observation_count=len(ordered),
        base_profile_id=experiment.base_profile_id,
        base_profile_sha256=experiment.base_profile_sha256,
        proposal_id=proposal.proposal_id,
        proposal_payload_sha256=canonical_proposal_payload_sha256(proposal),
    )


__all__ = [
    "EvidenceBindingError",
    "build_calibration_evidence_binding",
    "canonical_observations_sha256",
    "canonical_proposal_payload_sha256",
]
