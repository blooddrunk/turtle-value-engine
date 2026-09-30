"""Deterministic admission evaluation for one frozen proposal evidence chain.

Phase 7-A owns evaluation only.  This module is a pure offline function over
already-frozen typed inputs: it constructs no provider, model, transport or
network client, writes nothing, opens no pull request and records no approval.
Its machine decision is limited to evidence integrity and reproducibility;
it never compares candidates economically and never selects a "better" rule.

Phase 7-A-R1 adds the frozen-evidence binding boundary:
``READY_FOR_HUMAN_REVIEW`` is possible only when a prior
:class:`~turtle_value_engine.backtest.contracts.CalibrationEvidenceBindingV1`
— produced at the calibration/freeze boundary while the exact manifest,
observations and resulting experiment were simultaneously available — is
supplied and matches the supplied evidence exactly.  The evaluator never
synthesizes the expected evidence identity from its own inputs.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from turtle_value_engine.backtest.calibration import (
    CalibrationError,
    CalibrationRunner,
    split_observations,
)
from turtle_value_engine.backtest.contracts import (
    BacktestDatasetManifest,
    CalibrationEvidenceBindingV1,
    CalibrationExperiment,
    CalibrationHoldoutResult,
    CalibrationObservation,
    CalibrationStage,
    CandidateProfileProposal,
)
from turtle_value_engine.backtest.evidence_binding import (
    canonical_observations_sha256,
    canonical_proposal_payload_sha256,
)
from turtle_value_engine.providers.normalization import deterministic_id

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
    CHECK_HOLDOUT_BINDING,
    CHECK_HOLDOUT_CONTENT_HASH,
    CHECK_HOLDOUT_REPRODUCTION,
    CHECK_MANIFEST_IDENTITY,
    CHECK_PROPOSAL_EMBEDDING,
    CHECK_PROPOSAL_STATUS_PROPOSAL_ONLY,
    CHECK_SEARCH_HOLDOUT_ISOLATION,
    CHECK_SELECTED_TRIAL_AGREEMENT,
    REQUIRED_EVALUATION_CHECK_NAMES,
    ControlledEvolutionEvaluationV1,
    EvaluationCheckV1,
    persisted_content_sha256,
)

_MAX_DETAIL_LENGTH = 500


class EvolutionEvaluationError(ValueError):
    """Raised when no evaluation dossier can be produced from the inputs."""


def proposal_payload_sha256(proposal: CandidateProfileProposal) -> str:
    """Hash the canonical proposal payload without mutating its contract."""

    return canonical_proposal_payload_sha256(proposal)


def frozen_observations_sha256(
    observations: Sequence[CalibrationObservation],
) -> str:
    """Bind the frozen observation rows in canonical chronological order."""

    return canonical_observations_sha256(observations)


def _detail(message: str) -> str:
    text = " ".join(str(message).split())
    return text[:_MAX_DETAIL_LENGTH]


def _check(name: str, passed: bool, ok_detail: str, blocked_detail: str) -> EvaluationCheckV1:
    return EvaluationCheckV1(
        name=name,  # type: ignore[arg-type]
        state="PASS" if passed else "BLOCKED",
        detail=_detail(ok_detail if passed else blocked_detail),
    )


def _reproduction_payload(experiment: CalibrationExperiment) -> dict:
    """Project an experiment onto the fields the canonical path determines.

    ``content_sha256`` is recomputed by the reproduction itself and the free
    text ``rationale`` is not a deterministic product of the search, so both
    are excluded from equality; every other field must match exactly.
    """

    payload = experiment.model_dump(mode="json", warnings=False)
    payload.pop("content_sha256", None)
    proposal = payload.get("proposal")
    if isinstance(proposal, dict):
        proposal.pop("rationale", None)
    return payload


def _manifest_payload_hash(manifest: BacktestDatasetManifest) -> str:
    return persisted_content_sha256(manifest)


def _binding_identity(evidence_binding: CalibrationEvidenceBindingV1 | None) -> tuple:
    if evidence_binding is None:
        return (None, None)
    return (evidence_binding.binding_id, evidence_binding.content_sha256)


def evaluate_controlled_evolution(
    *,
    manifest: BacktestDatasetManifest,
    experiment: CalibrationExperiment,
    holdout: CalibrationHoldoutResult,
    observations: Sequence[CalibrationObservation],
    base_profile_bytes: bytes,
    evidence_binding: CalibrationEvidenceBindingV1 | None = None,
) -> ControlledEvolutionEvaluationV1:
    """Evaluate one frozen evidence chain and emit an admission dossier.

    The function is deterministic and total over parseable inputs: every
    semantic violation is reported as a ``BLOCKED`` check with a stable name,
    and only a structurally unusable experiment (no selected proposal) raises
    :class:`EvolutionEvaluationError`.  The admissible scoring path is exactly
    the repository's canonical built-in calibration scorer; an experiment
    produced by an unrecorded custom scorer cannot be proven reproducible and
    is blocked rather than guessed compatible.

    ``evidence_binding`` is the prior calibration-time binding of the exact
    frozen evidence.  A missing binding fail-closes admission: the dossier is
    ``BLOCKED`` (never ``READY_FOR_HUMAN_REVIEW``), and every supplied
    identity — manifest, experiment, observation set and base profile — must
    equal the binding exactly before admission is possible.
    """

    proposal = experiment.proposal
    if proposal is None or experiment.selected_trial_id is None:
        raise EvolutionEvaluationError(
            "evaluation requires an experiment with a selected proposal and trial"
        )

    ordered = tuple(
        sorted(observations, key=lambda item: (item.observed_at, item.observation_id))
    )
    split = experiment.split
    actual_base_sha256 = hashlib.sha256(base_profile_bytes).hexdigest()
    proposal_sha = proposal_payload_sha256(proposal)
    observations_sha = frozen_observations_sha256(ordered)
    selected = next(
        (trial for trial in experiment.trials if trial.trial_id == experiment.selected_trial_id),
        None,
    )
    binding = evidence_binding

    checks: list[EvaluationCheckV1] = []

    checks.append(
        _check(
            CHECK_BASE_PROFILE_BYTES_HASH,
            actual_base_sha256 == experiment.base_profile_sha256,
            f"supplied base-profile bytes hash to {experiment.base_profile_sha256}",
            "supplied base-profile bytes hash to "
            f"{actual_base_sha256}, expected {experiment.base_profile_sha256}",
        )
    )

    identity_ok = (
        proposal.base_profile_id == experiment.base_profile_id
        and experiment.search_space.base_profile_id == experiment.base_profile_id
        and proposal.base_profile_sha256 == experiment.base_profile_sha256
    )
    checks.append(
        _check(
            CHECK_BASE_PROFILE_IDENTITY_AGREEMENT,
            identity_ok,
            "experiment, proposal and search space share one base-profile identity",
            "base-profile identity disagrees across experiment, proposal and "
            f"search space (experiment={experiment.base_profile_id}/"
            f"{experiment.base_profile_sha256}, proposal={proposal.base_profile_id}/"
            f"{proposal.base_profile_sha256}, search_space="
            f"{experiment.search_space.base_profile_id})",
        )
    )

    checks.append(
        _check(
            CHECK_EVIDENCE_BINDING_PRESENT,
            binding is not None,
            "prior calibration evidence binding supplied and content-verified",
            "no prior calibration evidence binding was supplied; admission "
            "requires the binding frozen at calibration time",
        )
    )

    binding_manifest_ok = (
        binding is not None
        and binding.manifest_id == experiment.manifest_id
        and manifest.dataset_id == binding.manifest_id
        and manifest.content_sha256 == binding.manifest_content_sha256
    )
    checks.append(
        _check(
            CHECK_EVIDENCE_BINDING_MANIFEST_IDENTITY,
            binding_manifest_ok,
            "supplied manifest is exactly the manifest bound at calibration time",
            "supplied manifest is not the manifest bound at calibration time "
            f"(binding manifest_id={None if binding is None else binding.manifest_id}, "
            "binding manifest content="
            f"{None if binding is None else binding.manifest_content_sha256}, "
            f"supplied dataset_id={manifest.dataset_id}, supplied content="
            f"{manifest.content_sha256}, experiment manifest_id={experiment.manifest_id})",
        )
    )

    binding_experiment_ok = (
        binding is not None
        and binding.experiment_id == experiment.experiment_id
        and binding.experiment_content_sha256 == experiment.content_sha256
    )
    checks.append(
        _check(
            CHECK_EVIDENCE_BINDING_EXPERIMENT_IDENTITY,
            binding_experiment_ok,
            "supplied experiment is exactly the experiment bound at calibration time",
            "supplied experiment is not the experiment bound at calibration time "
            f"(binding experiment_id={None if binding is None else binding.experiment_id}, "
            f"binding experiment content="
            f"{None if binding is None else binding.experiment_content_sha256}, "
            f"supplied experiment_id={experiment.experiment_id}, supplied content="
            f"{experiment.content_sha256})",
        )
    )

    binding_observations_ok = (
        binding is not None
        and binding.observations_content_sha256 == observations_sha
        and binding.observation_count == len(ordered)
    )
    checks.append(
        _check(
            CHECK_EVIDENCE_BINDING_OBSERVATIONS_IDENTITY,
            binding_observations_ok,
            "supplied observation set is exactly the frozen set bound at "
            "calibration time",
            "supplied observation set is not the frozen set bound at "
            "calibration time (binding observations content="
            f"{None if binding is None else binding.observations_content_sha256}, "
            f"binding count={None if binding is None else binding.observation_count}, "
            f"supplied content={observations_sha}, supplied count={len(ordered)})",
        )
    )

    binding_base_profile_ok = (
        binding is not None
        and binding.base_profile_id == experiment.base_profile_id
        and binding.base_profile_sha256 == experiment.base_profile_sha256
    )
    checks.append(
        _check(
            CHECK_EVIDENCE_BINDING_BASE_PROFILE_IDENTITY,
            binding_base_profile_ok,
            "supplied base profile is exactly the base profile bound at "
            "calibration time",
            "supplied base profile is not the base profile bound at calibration "
            f"time (binding profile={None if binding is None else binding.base_profile_id}"
            f"/{None if binding is None else binding.base_profile_sha256}, supplied "
            f"profile={experiment.base_profile_id}/{experiment.base_profile_sha256})",
        )
    )

    binding_proposal_ok = (
        binding is not None
        and binding.proposal_id == proposal.proposal_id
        and binding.proposal_payload_sha256 == proposal_sha
    )
    checks.append(
        _check(
            CHECK_EVIDENCE_BINDING_PROPOSAL_IDENTITY,
            binding_proposal_ok,
            "supplied proposal is exactly the proposal bound at calibration time",
            "supplied proposal is not the proposal bound at calibration time "
            f"(binding proposal_id={None if binding is None else binding.proposal_id}, "
            f"binding payload={None if binding is None else binding.proposal_payload_sha256}, "
            f"supplied proposal_id={proposal.proposal_id}, supplied payload={proposal_sha})",
        )
    )

    manifest_hash = _manifest_payload_hash(manifest)
    manifest_ok = (
        manifest.dataset_id == experiment.manifest_id
        and manifest_hash == manifest.content_sha256
    )
    checks.append(
        _check(
            CHECK_MANIFEST_IDENTITY,
            manifest_ok,
            f"manifest {manifest.dataset_id} matches the experiment and its content hash",
            "manifest identity mismatch (manifest dataset_id="
            f"{manifest.dataset_id}, experiment manifest_id={experiment.manifest_id}, "
            f"content hash recomputed={manifest_hash}, declared="
            f"{manifest.content_sha256})",
        )
    )

    experiment_hash = persisted_content_sha256(experiment)
    checks.append(
        _check(
            CHECK_EXPERIMENT_CONTENT_HASH,
            experiment_hash == experiment.content_sha256,
            f"experiment content hash verified as {experiment_hash}",
            f"experiment content hash recomputed to {experiment_hash}, declared "
            f"{experiment.content_sha256}",
        )
    )

    if selected is None:
        expected_proposal_id = ""
    else:
        expected_proposal_id = deterministic_id(
            "candidate-profile-proposal", experiment.experiment_id, selected.trial_id
        )
    embedding_ok = selected is not None and proposal.proposal_id == expected_proposal_id
    checks.append(
        _check(
            CHECK_PROPOSAL_EMBEDDING,
            embedding_ok,
            "proposal is the deterministic proposal of this experiment's selected trial",
            "proposal is not the proposal embedded in this experiment "
            f"(proposal_id={proposal.proposal_id}, expected "
            f"{expected_proposal_id or '<no selected trial>'})",
        )
    )

    selected_ok = False
    if selected is not None:
        selected_ok = (
            selected.candidate_profile_id == proposal.candidate_profile_id
            and selected.parameters == proposal.parameter_overrides
            and selected.candidate_profile_id
            == deterministic_id(
                "candidate-profile", experiment.base_profile_id, selected.parameters
            )
        )
    checks.append(
        _check(
            CHECK_SELECTED_TRIAL_AGREEMENT,
            selected_ok,
            "selected trial, candidate id and parameter overrides agree with the proposal",
            "selected trial disagrees with the proposal (selected_trial_id="
            f"{experiment.selected_trial_id}, trial candidate="
            f"{None if selected is None else selected.candidate_profile_id}, "
            f"proposal candidate={proposal.candidate_profile_id})",
        )
    )

    _train, _validation, holdout_rows = split_observations(ordered, split)
    holdout_ids = {item.observation_id for item in holdout_rows}
    leaked_ids = sorted(
        {
            observation_id
            for trial in experiment.trials
            for observation_id in trial.observation_ids
            if observation_id in holdout_ids
        }
    )
    isolation_ok = (
        not leaked_ids
        and experiment.holdout_locked
        and not experiment.holdout_observation_ids
        and all(
            trial.stage is CalibrationStage.SEARCH
            and trial.holdout_count == 0
            and trial.holdout_score is None
            for trial in experiment.trials
        )
    )
    checks.append(
        _check(
            CHECK_SEARCH_HOLDOUT_ISOLATION,
            isolation_ok,
            "search trials contain no holdout observations or scores",
            "search trials leak holdout evidence (leaked observation ids: "
            f"{leaked_ids[:10]})" if leaked_ids else "search trials carry holdout state",
        )
    )

    chronology_ok = (
        split.train_start
        <= split.train_end
        < split.validation_start
        <= split.validation_end
        < split.holdout_start
        <= split.holdout_end
    )
    checks.append(
        _check(
            CHECK_CHRONOLOGY_DISJOINT_ORDERED,
            chronology_ok,
            "train, validation and holdout ranges are chronological and disjoint",
            "split ranges are not chronological and disjoint "
            f"(train={split.train_start}..{split.train_end}, validation="
            f"{split.validation_start}..{split.validation_end}, holdout="
            f"{split.holdout_start}..{split.holdout_end})",
        )
    )

    status_ok = proposal.status == "PROPOSAL_ONLY" and not proposal.automatic_application_allowed
    checks.append(
        _check(
            CHECK_PROPOSAL_STATUS_PROPOSAL_ONLY,
            status_ok,
            "proposal is PROPOSAL_ONLY and cannot authorize automatic application",
            f"proposal status is {proposal.status}, automatic_application_allowed="
            f"{proposal.automatic_application_allowed}; only PROPOSAL_ONLY without "
            "automatic application is admissible",
        )
    )

    holdout_binding_ok = (
        holdout.experiment_id == experiment.experiment_id
        and holdout.proposal_id == proposal.proposal_id
        and holdout.holdout_start == split.holdout_start
        and holdout.holdout_end == split.holdout_end
    )
    checks.append(
        _check(
            CHECK_HOLDOUT_BINDING,
            holdout_binding_ok,
            "holdout result belongs to this experiment, proposal and holdout range",
            "holdout result is foreign (experiment_id="
            f"{holdout.experiment_id}, proposal_id={holdout.proposal_id}, range="
            f"{holdout.holdout_start}..{holdout.holdout_end}, expected experiment "
            f"{experiment.experiment_id}, proposal {proposal.proposal_id}, range "
            f"{split.holdout_start}..{split.holdout_end})",
        )
    )

    holdout_hash = persisted_content_sha256(holdout)
    checks.append(
        _check(
            CHECK_HOLDOUT_CONTENT_HASH,
            holdout_hash == holdout.content_sha256,
            f"holdout content hash verified as {holdout_hash}",
            f"holdout content hash recomputed to {holdout_hash}, declared "
            f"{holdout.content_sha256}",
        )
    )

    reproduced_experiment_payload: dict | None = None
    reproduced_holdout: CalibrationHoldoutResult | None = None
    reproduction_error: str | None = None
    try:
        canonical_runner = CalibrationRunner(
            manifest_id=experiment.manifest_id,
            base_profile_id=experiment.base_profile_id,
            base_profile_sha256=experiment.base_profile_sha256,
            search_space=experiment.search_space,
            split=split,
        )
        reproduced_experiment = canonical_runner.run(ordered)
        reproduced_holdout = canonical_runner.evaluate_holdout(reproduced_experiment, ordered)
        reproduced_experiment_payload = _reproduction_payload(reproduced_experiment)
    except (CalibrationError, ValueError) as exc:
        reproduction_error = str(exc)

    reproduction_ok = (
        reproduction_error is None
        and reproduced_experiment_payload is not None
        and reproduced_experiment_payload == _reproduction_payload(experiment)
    )
    if reproduction_error is not None:
        reproduction_detail = (
            "canonical built-in scorer failed on the frozen observations: "
            + reproduction_error
        )
    elif reproduction_ok:
        reproduction_detail = (
            "canonical built-in scorer reproduces the experiment and proposal exactly"
        )
    else:
        reproduction_detail = (
            "canonical built-in scorer does not reproduce the admitted experiment; "
            "an unrecorded custom scorer cannot be claimed reproducible"
        )
    checks.append(
        _check(
            CHECK_CANONICAL_REPRODUCTION,
            reproduction_ok,
            reproduction_detail,
            reproduction_detail,
        )
    )

    holdout_reproduction_ok = (
        reproduction_error is None
        and reproduced_holdout is not None
        and reproduced_holdout == holdout
    )
    checks.append(
        _check(
            CHECK_HOLDOUT_REPRODUCTION,
            holdout_reproduction_ok,
            "canonical recomputation reproduces the supplied holdout artifact",
            "canonical holdout recomputation does not reproduce the supplied "
            "artifact (recomputed score="
            f"{None if reproduced_holdout is None else reproduced_holdout.score}, "
            f"supplied score={holdout.score})"
            if reproduction_error is None
            else "canonical holdout recomputation failed: " + reproduction_error,
        )
    )

    assert [check.name for check in checks] == list(REQUIRED_EVALUATION_CHECK_NAMES), (
        "evaluator must emit exactly the canonical required check set in order"
    )

    admission_state = (
        "BLOCKED"
        if any(check.state == "BLOCKED" for check in checks)
        else "READY_FOR_HUMAN_REVIEW"
    )
    binding_id, binding_sha = _binding_identity(binding)
    evaluation_id = deterministic_id(
        "controlled-evolution-evaluation",
        experiment.base_profile_id,
        experiment.base_profile_sha256,
        manifest.dataset_id,
        manifest.content_sha256,
        experiment.experiment_id,
        experiment.content_sha256,
        proposal.proposal_id,
        proposal_sha,
        holdout.content_sha256,
        observations_sha,
        binding_id,
        binding_sha,
    )
    return ControlledEvolutionEvaluationV1.build(
        evaluation_id=evaluation_id,
        base_profile_id=experiment.base_profile_id,
        base_profile_sha256=experiment.base_profile_sha256,
        dataset_id=manifest.dataset_id,
        manifest_content_sha256=manifest.content_sha256,
        experiment_id=experiment.experiment_id,
        experiment_content_sha256=experiment.content_sha256,
        proposal_id=proposal.proposal_id,
        proposal_payload_sha256=proposal_sha,
        candidate_profile_id=proposal.candidate_profile_id,
        parameter_overrides=dict(proposal.parameter_overrides),
        holdout_content_sha256=holdout.content_sha256,
        observations_content_sha256=observations_sha,
        observation_count=len(ordered),
        evidence_binding_id=binding_id,
        evidence_binding_sha256=binding_sha,
        checks=checks,
        admission_state=admission_state,
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
    "CHECK_HOLDOUT_BINDING",
    "CHECK_HOLDOUT_CONTENT_HASH",
    "CHECK_HOLDOUT_REPRODUCTION",
    "CHECK_MANIFEST_IDENTITY",
    "CHECK_PROPOSAL_EMBEDDING",
    "CHECK_PROPOSAL_STATUS_PROPOSAL_ONLY",
    "CHECK_SEARCH_HOLDOUT_ISOLATION",
    "CHECK_SELECTED_TRIAL_AGREEMENT",
    "EvolutionEvaluationError",
    "evaluate_controlled_evolution",
    "frozen_observations_sha256",
    "proposal_payload_sha256",
]
