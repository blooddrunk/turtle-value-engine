"""Authoritative calibration-freeze anchor: commit and resolution boundaries.

This module is the explicit filesystem/workspace boundary of the Phase 7-A-R2
provenance chain.  :func:`commit_calibration_freeze` runs at the
calibration/freeze boundary, persisting the prerequisite artifacts first and
publishing the authoritative experiment-keyed freeze record last, so a crash
may leave unreferenced prerequisites but never an anchor pointing at missing
or conflicting content.  :func:`resolve_anchored_calibration_evidence` is the
loader the controlled-evolution evaluation CLI uses to obtain already
validated anchored evidence for the pure evaluator; neither function performs
network, provider, model or transport I/O.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .contracts import (
    BacktestDatasetManifest,
    CalibrationEvidenceBindingV1,
    CalibrationExperiment,
    CalibrationFreezeRecordV1,
    CalibrationObservation,
)
from .evidence_binding import build_calibration_evidence_binding
from .workspace import BacktestWorkspace, BacktestWorkspaceError


class CalibrationFreezeError(ValueError):
    """Raised when an authoritative calibration freeze cannot be produced or
    resolved for one experiment identity."""


@dataclass(frozen=True)
class AnchoredCalibrationEvidence:
    """The authoritative freeze chain resolved from one calibration workspace.

    ``freeze_record`` is the committed anchor for ``experiment_id``;
    ``binding`` is exactly the evidence binding it references; ``experiment``
    is the committed experiment whose content the anchor binds.  The dataclass
    carries validated typed models only — no paths, no secrets.
    """

    freeze_record: CalibrationFreezeRecordV1
    experiment: CalibrationExperiment
    binding: CalibrationEvidenceBindingV1


def commit_calibration_freeze(
    workspace: BacktestWorkspace,
    *,
    manifest: BacktestDatasetManifest,
    experiment: CalibrationExperiment,
    observations: Iterable[CalibrationObservation],
) -> tuple[CalibrationEvidenceBindingV1, CalibrationFreezeRecordV1]:
    """Commit the authoritative calibration freeze for one experiment.

    The compiled manifest, the calibration experiment and its evidence
    binding are committed as immutable prerequisites first; the authoritative
    freeze record is published last under ``experiment_id``.  A repeated
    byte-identical freeze is idempotent; a conflicting freeze for the same
    ``experiment_id`` fails closed through the workspace's immutable-store
    guard before any existing authoritative byte is replaced, truncated or
    deleted.
    """

    binding = build_calibration_evidence_binding(
        manifest=manifest, experiment=experiment, observations=observations
    )
    workspace.save_manifest(manifest)
    workspace.save_calibration_experiment(experiment)
    workspace.save_calibration_evidence_binding(binding)
    record = CalibrationFreezeRecordV1.build(
        experiment_id=experiment.experiment_id,
        experiment_content_sha256=experiment.content_sha256,
        binding_id=binding.binding_id,
        binding_content_sha256=binding.content_sha256,
    )
    workspace.save_calibration_freeze_record(record)
    return binding, record


def resolve_anchored_calibration_evidence(
    workspace: BacktestWorkspace, *, experiment_id: str
) -> AnchoredCalibrationEvidence:
    """Resolve the authoritative freeze chain for one experiment, fail-closed.

    Every failure mode — a missing, corrupt or foreign freeze record, an
    anchor referencing a missing or mismatched experiment/binding — raises
    :class:`CalibrationFreezeError`.  The returned evidence is already
    cross-validated, so the pure evaluator can consume it without performing
    any filesystem I/O of its own.
    """

    try:
        record = workspace.load_calibration_freeze_record(experiment_id)
    except BacktestWorkspaceError as exc:
        raise CalibrationFreezeError(
            f"no authoritative calibration freeze record for experiment {experiment_id!r} "
            f"is readable in the calibration workspace: {exc}"
        ) from exc
    if record.experiment_id != experiment_id:
        raise CalibrationFreezeError(
            "authoritative calibration freeze record is foreign to the requested "
            f"experiment (record experiment_id={record.experiment_id}, requested "
            f"{experiment_id})"
        )
    try:
        experiment = workspace.load_calibration_experiment(experiment_id)
        binding = workspace.load_calibration_evidence_binding(record.binding_id)
    except BacktestWorkspaceError as exc:
        raise CalibrationFreezeError(
            f"the authoritative calibration freeze for experiment {experiment_id!r} "
            f"references an artifact that is missing or corrupt: {exc}"
        ) from exc
    if record.experiment_content_sha256 != experiment.content_sha256:
        raise CalibrationFreezeError(
            "authoritative calibration freeze record does not bind the committed "
            f"experiment content (record experiment content="
            f"{record.experiment_content_sha256}, committed="
            f"{experiment.content_sha256})"
        )
    if binding.binding_id != record.binding_id or (
        binding.content_sha256 != record.binding_content_sha256
    ):
        raise CalibrationFreezeError(
            "authoritative calibration freeze record does not bind the referenced "
            f"evidence binding exactly (record binding={record.binding_id}/"
            f"{record.binding_content_sha256}, stored binding="
            f"{binding.binding_id}/{binding.content_sha256})"
        )
    if (
        binding.experiment_id != experiment.experiment_id
        or binding.experiment_content_sha256 != experiment.content_sha256
    ):
        raise CalibrationFreezeError(
            "the evidence binding anchored for experiment "
            f"{experiment_id!r} does not bind that experiment "
            f"(binding experiment={binding.experiment_id}/"
            f"{binding.experiment_content_sha256})"
        )
    return AnchoredCalibrationEvidence(
        freeze_record=record, experiment=experiment, binding=binding
    )


__all__ = [
    "AnchoredCalibrationEvidence",
    "CalibrationFreezeError",
    "commit_calibration_freeze",
    "resolve_anchored_calibration_evidence",
]
