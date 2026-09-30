"""Frozen Phase 7-A controlled-evolution evaluation tests.

Every test drives the offline evaluation boundary only: no provider, model,
transport or network client is constructed, and no rule profile is mutated.

Phase 7-A-R1: admission additionally requires a prior calibration-time
``CalibrationEvidenceBindingV1``; the default helpers below build the honest
binding for each chain so every pre-existing scenario keeps testing exactly
its original check.
"""

from __future__ import annotations

import hashlib
import json
import socket
from datetime import date
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from turtle_value_engine.backtest import (
    BacktestDatasetManifest,
    CalibrationEvidenceBindingV1,
    CalibrationExperiment,
    CalibrationHoldoutResult,
    CalibrationObservation,
    CalibrationRunner,
    CalibrationSearchSpace,
    CandidateProfileProposal,
    ChronologicalSplit,
    ListingLifecycle,
    Market,
    UniverseCoverage,
    build_calibration_evidence_binding,
)
from turtle_value_engine.cli import main
from turtle_value_engine.evolution import (
    CHECK_BASE_PROFILE_BYTES_HASH,
    CHECK_CANONICAL_REPRODUCTION,
    CHECK_CHRONOLOGY_DISJOINT_ORDERED,
    CHECK_EXPERIMENT_CONTENT_HASH,
    CHECK_HOLDOUT_BINDING,
    CHECK_MANIFEST_IDENTITY,
    CHECK_PROPOSAL_EMBEDDING,
    CHECK_PROPOSAL_STATUS_PROPOSAL_ONLY,
    CHECK_SEARCH_HOLDOUT_ISOLATION,
    CHECK_SELECTED_TRIAL_AGREEMENT,
    REQUIRED_EVALUATION_CHECK_NAMES,
    ControlledEvolutionEvaluationV1,
    EvolutionEvaluationError,
    evaluate_controlled_evolution,
    proposal_payload_sha256,
)
from turtle_value_engine.providers.models import canonical_json_bytes

ROOT = Path(__file__).parents[1]
SOURCE_HASH = "a" * 64
BASE_PROFILE_PATH = ROOT / "rules" / "strict-v1.yaml"


def _observations() -> list[CalibrationObservation]:
    return [
        CalibrationObservation(
            observation_id=f"cal-{index}",
            observed_at=date(2020, 1, index + 1),
            target_return=float(index - 2),
            feature_values={"quality": float(index)},
            source_hash=SOURCE_HASH,
        )
        for index in range(1, 9)
    ]


def _split() -> ChronologicalSplit:
    return ChronologicalSplit(
        train_start=date(2020, 1, 2),
        train_end=date(2020, 1, 4),
        validation_start=date(2020, 1, 5),
        validation_end=date(2020, 1, 6),
        holdout_start=date(2020, 1, 7),
        holdout_end=date(2020, 1, 9),
    )


def _search_space(space_id: str = "quality-thresholds-v1") -> CalibrationSearchSpace:
    return CalibrationSearchSpace(
        space_id=space_id,
        base_profile_id="strict-v1",
        parameters={"min_quality": [0.0, 4.0]},
        objective="MEAN_RETURN",
    )


def _manifest(dataset_id: str = "frozen-ah-mini-v1") -> BacktestDatasetManifest:
    lifecycle = ListingLifecycle(
        listing_id="A-SH600001",
        company_id="economic-company-1",
        economic_company_id="economic-company-1",
        market=Market.A,
        currency="CNY",
        listing_date=date(2020, 1, 1),
        terminal_status="ACTIVE",
        trading_calendar="frozen-mini-ah-v1",
        timezone="Asia/Shanghai",
        sector="consumer",
    )
    return BacktestDatasetManifest.build(
        dataset_id=dataset_id,
        dataset_version="1",
        start_date=date(2020, 1, 1),
        end_date=date(2020, 2, 1),
        calendar_id="frozen-mini-ah-v1",
        universe_id="frozen-ah",
        universe_coverage=UniverseCoverage.FIXED_RESEARCH_UNIVERSE,
        listing_lifecycles=[lifecycle],
    )


def _canonical_chain(
    *,
    base_profile_sha256: str,
    scorer=None,
    space_id: str = "quality-thresholds-v1",
):
    """Build one canonical experiment plus its separate holdout result."""

    observations = _observations()
    runner = CalibrationRunner(
        manifest_id="frozen-ah-mini-v1",
        base_profile_id="strict-v1",
        base_profile_sha256=base_profile_sha256,
        search_space=_search_space(space_id),
        split=_split(),
        scorer=scorer,
    )
    experiment = runner.run(observations)
    holdout = runner.evaluate_holdout(experiment, observations)
    return experiment, holdout, observations


_KEEP = object()


def _rebuild_experiment(
    experiment: CalibrationExperiment,
    *,
    trials=_KEEP,
    proposal=_KEEP,
) -> CalibrationExperiment:
    """Re-serialize a tampered experiment with an honest recomputed hash."""

    return CalibrationExperiment.build(
        experiment_id=experiment.experiment_id,
        manifest_id=experiment.manifest_id,
        base_profile_id=experiment.base_profile_id,
        base_profile_sha256=experiment.base_profile_sha256,
        search_space=experiment.search_space,
        split=experiment.split,
        trials=list(experiment.trials) if trials is _KEEP else trials,
        selected_trial_id=experiment.selected_trial_id,
        proposal=experiment.proposal if proposal is _KEEP else proposal,
        holdout_locked=experiment.holdout_locked,
        holdout_observation_ids=list(experiment.holdout_observation_ids),
    )


def _rebuild_holdout(holdout: CalibrationHoldoutResult, **updates) -> CalibrationHoldoutResult:
    payload = holdout.model_dump(mode="json", warnings=False)
    payload.pop("content_sha256")
    for key, value in updates.items():
        payload[key] = value.isoformat() if isinstance(value, date) else value
    payload["content_sha256"] = hashlib.sha256(
        canonical_json_bytes(payload)
    ).hexdigest()
    return CalibrationHoldoutResult.model_validate(payload)


def _blocked_names(evaluation: ControlledEvolutionEvaluationV1) -> set[str]:
    return {check.name for check in evaluation.checks if check.state == "BLOCKED"}


def _evaluate(
    experiment,
    holdout,
    observations,
    *,
    base_profile_bytes: bytes | None = None,
    manifest: BacktestDatasetManifest | None = None,
    evidence_binding: CalibrationEvidenceBindingV1
    | None
    | object = _KEEP,
) -> ControlledEvolutionEvaluationV1:
    effective_manifest = manifest if manifest is not None else _manifest()
    if evidence_binding is _KEEP:
        # The honest binding for this chain, produced at the calibration/freeze
        # boundary from the canonical frozen manifest, the experiment and the
        # observation rows — never from a manifest substituted at evaluation
        # time (the builder itself fail-closes across mismatched manifests).
        evidence_binding = build_calibration_evidence_binding(
            manifest=_manifest(),
            experiment=experiment,
            observations=observations,
        )
    return evaluate_controlled_evolution(
        manifest=effective_manifest,
        experiment=experiment,
        holdout=holdout,
        observations=observations,
        base_profile_bytes=(
            base_profile_bytes
            if base_profile_bytes is not None
            else BASE_PROFILE_PATH.read_bytes()
        ),
        evidence_binding=evidence_binding,
    )


@pytest.fixture(scope="module")
def canonical_evidence():
    base_bytes = BASE_PROFILE_PATH.read_bytes()
    base_sha = hashlib.sha256(base_bytes).hexdigest()
    experiment, holdout, observations = _canonical_chain(base_profile_sha256=base_sha)
    binding = build_calibration_evidence_binding(
        manifest=_manifest(), experiment=experiment, observations=observations
    )
    return base_bytes, base_sha, experiment, holdout, observations, binding


def test_valid_canonical_proposal_is_ready_for_human_review(canonical_evidence):
    (
        base_bytes,
        base_sha,
        experiment,
        holdout,
        observations,
        binding,
    ) = canonical_evidence

    evaluation = _evaluate(experiment, holdout, observations)

    assert evaluation.admission_state == "READY_FOR_HUMAN_REVIEW"
    assert not _blocked_names(evaluation)
    assert len(evaluation.checks) == len(REQUIRED_EVALUATION_CHECK_NAMES) == 19
    assert [check.name for check in evaluation.checks] == list(
        REQUIRED_EVALUATION_CHECK_NAMES
    )
    assert evaluation.base_profile_sha256 == base_sha
    assert evaluation.evidence_binding_id == binding.binding_id
    assert evaluation.evidence_binding_sha256 == binding.content_sha256
    assert evaluation.requires_human_approval is True
    assert evaluation.automatic_application_allowed is False
    assert evaluation.proposal_payload_sha256 == proposal_payload_sha256(
        experiment.proposal
    )
    assert evaluation.observation_count == len(observations)


def test_base_profile_byte_hash_mismatch_blocks(canonical_evidence):
    _base_bytes, _base_sha, experiment, holdout, observations, _binding = canonical_evidence

    evaluation = _evaluate(
        experiment,
        holdout,
        observations,
        base_profile_bytes=b"tampered-profile-bytes",
    )

    assert evaluation.admission_state == "BLOCKED"
    assert CHECK_BASE_PROFILE_BYTES_HASH in _blocked_names(evaluation)


def test_manifest_substitution_blocks(canonical_evidence):
    _base_bytes, _base_sha, experiment, holdout, observations, _binding = canonical_evidence

    evaluation = _evaluate(
        experiment,
        holdout,
        observations,
        manifest=_manifest(dataset_id="another-frozen-dataset"),
    )

    assert evaluation.admission_state == "BLOCKED"
    assert CHECK_MANIFEST_IDENTITY in _blocked_names(evaluation)


def test_experiment_proposal_substitution_with_same_candidate_blocks(canonical_evidence):
    _base_bytes, _base_sha, experiment, holdout, observations, _binding = canonical_evidence
    proposal = experiment.proposal
    foreign = proposal.model_copy(
        update={
            "proposal_id": "foreign-proposal-id",
            "rationale": "pasted from another experiment",
        }
    )
    tampered = _rebuild_experiment(experiment, proposal=foreign)

    evaluation = _evaluate(tampered, holdout, observations)

    assert evaluation.admission_state == "BLOCKED"
    assert CHECK_PROPOSAL_EMBEDDING in _blocked_names(evaluation)


def test_selected_trial_parameter_mismatch_blocks(canonical_evidence):
    _base_bytes, _base_sha, experiment, holdout, observations, _binding = canonical_evidence
    proposal = experiment.proposal
    tampered = _rebuild_experiment(
        experiment,
        proposal=proposal.model_copy(
            update={"parameter_overrides": {"min_quality": 99.0}}
        ),
    )

    evaluation = _evaluate(tampered, holdout, observations)

    assert evaluation.admission_state == "BLOCKED"
    assert CHECK_SELECTED_TRIAL_AGREEMENT in _blocked_names(evaluation)


def test_search_trial_holdout_leakage_blocks(canonical_evidence):
    _base_bytes, _base_sha, experiment, holdout, observations, _binding = canonical_evidence
    trials = [
        trial.model_copy(
            update={
                "observation_ids": [
                    *trial.observation_ids,
                    observations[-1].observation_id,
                ]
            }
        )
        if trial.trial_id == experiment.selected_trial_id
        else trial
        for trial in experiment.trials
    ]
    tampered = _rebuild_experiment(experiment, trials=trials)

    evaluation = _evaluate(tampered, holdout, observations)

    assert evaluation.admission_state == "BLOCKED"
    assert CHECK_SEARCH_HOLDOUT_ISOLATION in _blocked_names(evaluation)


def test_evaluator_independently_catches_corrupt_chronology(canonical_evidence):
    _base_bytes, _base_sha, experiment, holdout, observations, _binding = canonical_evidence
    corrupt_split = ChronologicalSplit.model_construct(
        train_start=date(2020, 1, 2),
        train_end=date(2020, 1, 8),
        validation_start=date(2020, 1, 5),
        validation_end=date(2020, 1, 6),
        holdout_start=date(2020, 1, 7),
        holdout_end=date(2020, 1, 9),
    )
    corrupt = CalibrationExperiment.model_construct(
        contract="calibration_experiment_v1",
        experiment_id=experiment.experiment_id,
        manifest_id=experiment.manifest_id,
        base_profile_id=experiment.base_profile_id,
        base_profile_sha256=experiment.base_profile_sha256,
        search_space=experiment.search_space,
        split=corrupt_split,
        trials=experiment.trials,
        selected_trial_id=experiment.selected_trial_id,
        proposal=experiment.proposal,
        holdout_locked=True,
        holdout_observation_ids=[],
        content_sha256=experiment.content_sha256,
    )

    evaluation = _evaluate(corrupt, holdout, observations)

    assert evaluation.admission_state == "BLOCKED"
    assert CHECK_CHRONOLOGY_DISJOINT_ORDERED in _blocked_names(evaluation)


@pytest.mark.parametrize("status", ["HUMAN_APPROVED", "REJECTED"])
def test_non_proposal_only_status_blocks(canonical_evidence, status):
    _base_bytes, _base_sha, experiment, holdout, observations, _binding = canonical_evidence
    tampered = _rebuild_experiment(
        experiment,
        proposal=experiment.proposal.model_copy(update={"status": status}),
    )

    evaluation = _evaluate(tampered, holdout, observations)

    assert evaluation.admission_state == "BLOCKED"
    assert CHECK_PROPOSAL_STATUS_PROPOSAL_ONLY in _blocked_names(evaluation)


def test_automatic_application_true_rejected_by_existing_model(canonical_evidence):
    _base_bytes, _base_sha, experiment, _holdout, _observations, _binding = canonical_evidence

    with pytest.raises(ValueError, match="automatic application"):
        # model_copy deliberately skips validators; the persisted-contract
        # guard must be exercised through a validating round-trip.
        payload = experiment.proposal.model_dump(mode="json")
        payload["automatic_application_allowed"] = True
        CandidateProfileProposal.model_validate(payload)


def test_holdout_from_another_experiment_blocks(canonical_evidence):
    base_bytes, base_sha, experiment, _holdout, observations, _binding = canonical_evidence
    other_experiment, other_holdout, _other_observations = _canonical_chain(
        base_profile_sha256=base_sha, space_id="other-quality-thresholds-v1"
    )
    assert other_experiment.experiment_id != experiment.experiment_id

    evaluation = _evaluate(experiment, other_holdout, observations)

    assert evaluation.admission_state == "BLOCKED"
    assert CHECK_HOLDOUT_BINDING in _blocked_names(evaluation)


def test_holdout_for_another_proposal_blocks(canonical_evidence):
    _base_bytes, _base_sha, experiment, holdout, observations, _binding = canonical_evidence
    foreign = _rebuild_holdout(holdout, proposal_id="foreign-proposal-id")

    evaluation = _evaluate(experiment, foreign, observations)

    assert evaluation.admission_state == "BLOCKED"
    assert CHECK_HOLDOUT_BINDING in _blocked_names(evaluation)


def test_holdout_date_range_mismatch_blocks(canonical_evidence):
    _base_bytes, _base_sha, experiment, holdout, observations, _binding = canonical_evidence
    shifted = _rebuild_holdout(
        holdout,
        holdout_start=date(2020, 1, 8),
        holdout_end=date(2020, 1, 9),
    )

    evaluation = _evaluate(experiment, shifted, observations)

    assert evaluation.admission_state == "BLOCKED"
    assert CHECK_HOLDOUT_BINDING in _blocked_names(evaluation)


def test_frozen_observation_substitution_blocks(canonical_evidence):
    _base_bytes, _base_sha, experiment, holdout, observations, _binding = canonical_evidence
    substituted = [
        observation.model_copy(update={"target_return": observation.target_return + 1.0})
        for observation in observations
    ]

    evaluation = _evaluate(experiment, holdout, substituted)

    assert evaluation.admission_state == "BLOCKED"
    assert CHECK_CANONICAL_REPRODUCTION in _blocked_names(evaluation)


def test_duplicate_observation_ids_block(canonical_evidence):
    _base_bytes, _base_sha, experiment, holdout, observations, _binding = canonical_evidence
    duplicated = [
        observation.model_copy(update={"observation_id": "cal-duplicated"})
        for observation in observations
    ]

    evaluation = _evaluate(experiment, holdout, duplicated)

    assert evaluation.admission_state == "BLOCKED"
    assert CHECK_CANONICAL_REPRODUCTION in _blocked_names(evaluation)


def test_unrecorded_custom_scorer_experiment_is_blocked():
    base_bytes = BASE_PROFILE_PATH.read_bytes()
    base_sha = hashlib.sha256(base_bytes).hexdigest()
    inverted = lambda parameters, obs: -sum(  # noqa: E731 - test-only scorer
        item.target_return for item in obs if item.eligible
    )
    experiment, holdout, observations = _canonical_chain(
        base_profile_sha256=base_sha, scorer=inverted
    )

    evaluation = _evaluate(experiment, holdout, observations)

    assert evaluation.admission_state == "BLOCKED"
    assert CHECK_CANONICAL_REPRODUCTION in _blocked_names(evaluation)
    reproduction = next(
        check
        for check in evaluation.checks
        if check.name == CHECK_CANONICAL_REPRODUCTION
    )
    assert "custom scorer" in reproduction.detail


def test_experiment_without_selected_proposal_raises(canonical_evidence):
    _base_bytes, _base_sha, experiment, holdout, observations, _binding = canonical_evidence
    proposalless = _rebuild_experiment(experiment, proposal=None)

    with pytest.raises(EvolutionEvaluationError, match="selected proposal"):
        # A proposal-less experiment can never carry a calibration-time
        # evidence binding; evaluation must fail closed on its own boundary.
        _evaluate(proposalless, holdout, observations, evidence_binding=None)


def test_tampered_experiment_content_hash_blocks(canonical_evidence):
    _base_bytes, _base_sha, experiment, holdout, observations, _binding = canonical_evidence
    # A forged experiment that swapped its identity while keeping another
    # experiment's declared content hash is not the artifact it claims to be.
    forged = CalibrationExperiment.model_construct(
        contract="calibration_experiment_v1",
        experiment_id="forged-experiment-id",
        manifest_id=experiment.manifest_id,
        base_profile_id=experiment.base_profile_id,
        base_profile_sha256=experiment.base_profile_sha256,
        search_space=experiment.search_space,
        split=experiment.split,
        trials=experiment.trials,
        selected_trial_id=experiment.selected_trial_id,
        proposal=experiment.proposal,
        holdout_locked=True,
        holdout_observation_ids=[],
        content_sha256=experiment.content_sha256,
    )

    evaluation = _evaluate(forged, holdout, observations)

    assert evaluation.admission_state == "BLOCKED"
    assert CHECK_EXPERIMENT_CONTENT_HASH in _blocked_names(evaluation)


def test_deterministic_rerun_produces_byte_identical_dossier(canonical_evidence):
    _base_bytes, _base_sha, experiment, holdout, observations, _binding = canonical_evidence

    first = _evaluate(experiment, holdout, observations)
    second = _evaluate(experiment, holdout, observations)

    assert first == second
    assert first.content_sha256 == second.content_sha256
    assert (
        json.dumps(first.model_dump(mode="json"), sort_keys=True)
        == json.dumps(second.model_dump(mode="json"), sort_keys=True)
    )


def test_contract_carries_no_wall_clock_fields():
    schema = ControlledEvolutionEvaluationV1.model_json_schema()

    serialized = json.dumps(schema)

    assert "date-time" not in serialized
    assert "timestamp" not in serialized


def test_schema_parity_and_instance_validation(canonical_evidence):
    schema_path = ROOT / "schemas" / "controlled-evolution-evaluation.schema.json"
    checked_in = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(checked_in)
    assert checked_in == ControlledEvolutionEvaluationV1.model_json_schema()

    _base_bytes, _base_sha, experiment, holdout, observations, _binding = canonical_evidence
    evaluation = _evaluate(experiment, holdout, observations)
    Draft202012Validator(checked_in).validate(
        evaluation.model_dump(mode="json", warnings=False)
    )


def _write_evidence(tmp_path: Path, experiment, holdout, observations) -> dict[str, Path]:
    binding = build_calibration_evidence_binding(
        manifest=_manifest(), experiment=experiment, observations=observations
    )
    paths = {
        "manifest": tmp_path / "manifest.json",
        "experiment": tmp_path / "experiment.json",
        "holdout": tmp_path / "holdout.json",
        "observations": tmp_path / "observations.json",
        "base_profile": tmp_path / "strict-v1.yaml",
        "evidence_binding": tmp_path / "evidence-binding.json",
    }
    paths["manifest"].write_text(
        _manifest().model_dump_json(indent=2), encoding="utf-8"
    )
    paths["experiment"].write_text(
        experiment.model_dump_json(indent=2), encoding="utf-8"
    )
    paths["holdout"].write_text(holdout.model_dump_json(indent=2), encoding="utf-8")
    paths["observations"].write_text(
        json.dumps(
            [observation.model_dump(mode="json") for observation in observations],
            indent=2,
        ),
        encoding="utf-8",
    )
    paths["evidence_binding"].write_text(
        binding.model_dump_json(indent=2), encoding="utf-8"
    )
    paths["base_profile"].write_bytes(BASE_PROFILE_PATH.read_bytes())
    return paths


def _evaluate_arguments(paths: dict[str, Path], output: Path | None = None) -> list[str]:
    arguments = [
        "evolution",
        "evaluate",
        "--manifest",
        str(paths["manifest"]),
        "--experiment",
        str(paths["experiment"]),
        "--holdout",
        str(paths["holdout"]),
        "--observations",
        str(paths["observations"]),
        "--base-profile",
        str(paths["base_profile"]),
        "--evidence-binding",
        str(paths["evidence_binding"]),
    ]
    if output is not None:
        arguments.extend(["--output", str(output)])
    return arguments


def test_cli_happy_path_writes_admitted_dossier(
    tmp_path, capsys, canonical_evidence
):
    _base_bytes, _base_sha, experiment, holdout, observations, _binding = canonical_evidence
    paths = _write_evidence(tmp_path, experiment, holdout, observations)
    output = tmp_path / "evaluation.json"

    exit_code = main(_evaluate_arguments(paths, output))

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["admission_state"] == "READY_FOR_HUMAN_REVIEW"
    persisted = ControlledEvolutionEvaluationV1.model_validate(
        json.loads(output.read_text(encoding="utf-8"))
    )
    assert persisted.admission_state == "READY_FOR_HUMAN_REVIEW"
    assert persisted.contract == "controlled_evolution_evaluation_v1"


def test_cli_blocked_dossier_writes_output_and_exits_nonzero(
    tmp_path, capsys, canonical_evidence
):
    _base_bytes, _base_sha, experiment, holdout, observations, _binding = canonical_evidence
    paths = _write_evidence(tmp_path, experiment, holdout, observations)
    paths["base_profile"].write_bytes(b"tampered")
    output = tmp_path / "evaluation.json"

    exit_code = main(_evaluate_arguments(paths, output))

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["admission_state"] == "BLOCKED"
    persisted = ControlledEvolutionEvaluationV1.model_validate(
        json.loads(output.read_text(encoding="utf-8"))
    )
    assert persisted.admission_state == "BLOCKED"


def test_cli_evaluation_never_touches_network_or_input_bytes(
    tmp_path, monkeypatch, canonical_evidence
):
    _base_bytes, _base_sha, experiment, holdout, observations, _binding = canonical_evidence
    paths = _write_evidence(tmp_path, experiment, holdout, observations)
    output = tmp_path / "evaluation.json"

    def no_sockets(*args, **kwargs):
        raise AssertionError("evaluation constructed a network socket")

    monkeypatch.setattr(socket, "socket", no_sockets)
    monkeypatch.setattr(socket, "create_connection", no_sockets)

    before = {
        label: path.read_bytes() for label, path in paths.items()
    }
    strict_v1_before = BASE_PROFILE_PATH.read_bytes()

    exit_code = main(_evaluate_arguments(paths, output))

    assert exit_code == 0
    after = {label: path.read_bytes() for label, path in paths.items()}
    assert before == after
    assert BASE_PROFILE_PATH.read_bytes() == strict_v1_before
    assert output.exists()


def test_cli_refuses_output_overlapping_supplied_input(
    tmp_path, capsys, canonical_evidence
):
    _base_bytes, _base_sha, experiment, holdout, observations, _binding = canonical_evidence
    paths = _write_evidence(tmp_path, experiment, holdout, observations)
    binding_before = paths["evidence_binding"].read_bytes()

    exit_code = main(
        _evaluate_arguments(paths, paths["evidence_binding"])
    )

    assert exit_code == 2
    stderr = capsys.readouterr().err
    assert "must not overwrite" in stderr
    assert "evidence-binding" in stderr
    assert paths["evidence_binding"].read_bytes() == binding_before


def test_cli_fails_closed_on_corrupt_split_json(tmp_path, capsys):
    # Overlapping split ranges can never validate as a ChronologicalSplit, so
    # the command must fail closed without producing any dossier.
    experiment_payload = {
        "contract": "calibration_experiment_v1",
        "experiment_id": "corrupt",
        "manifest_id": "frozen-ah-mini-v1",
        "base_profile_id": "strict-v1",
        "base_profile_sha256": "a" * 64,
        "search_space": {
            "contract": "calibration_search_space_v1",
            "space_id": "s",
            "base_profile_id": "strict-v1",
            "parameters": {"min_quality": [0.0]},
        },
        "split": {
            "contract": "chronological_split_v1",
            "train_start": "2020-01-02",
            "train_end": "2020-01-08",
            "validation_start": "2020-01-05",
            "validation_end": "2020-01-06",
            "holdout_start": "2020-01-07",
            "holdout_end": "2020-01-09",
        },
        "trials": [],
        "selected_trial_id": None,
        "proposal": None,
        "holdout_locked": True,
        "holdout_observation_ids": [],
        "content_sha256": "0" * 64,
    }
    base_bytes = BASE_PROFILE_PATH.read_bytes()
    honest_experiment, _honest_holdout, honest_observations = _canonical_chain(
        base_profile_sha256=hashlib.sha256(base_bytes).hexdigest()
    )
    honest_binding = build_calibration_evidence_binding(
        manifest=_manifest(),
        experiment=honest_experiment,
        observations=honest_observations,
    )
    paths = {
        "experiment": tmp_path / "experiment.json",
        "manifest": tmp_path / "manifest.json",
        "holdout": tmp_path / "holdout.json",
        "observations": tmp_path / "observations.json",
        "base_profile": tmp_path / "strict-v1.yaml",
        "evidence_binding": tmp_path / "evidence-binding.json",
    }
    paths["experiment"].write_text(json.dumps(experiment_payload), encoding="utf-8")
    paths["manifest"].write_text(
        _manifest().model_dump_json(indent=2), encoding="utf-8"
    )
    paths["holdout"].write_text("{}", encoding="utf-8")
    paths["observations"].write_text("[]", encoding="utf-8")
    paths["evidence_binding"].write_text(
        honest_binding.model_dump_json(indent=2), encoding="utf-8"
    )
    paths["base_profile"].write_bytes(BASE_PROFILE_PATH.read_bytes())

    exit_code = main(
        [
            "evolution",
            "evaluate",
            "--manifest",
            str(paths["manifest"]),
            "--experiment",
            str(paths["experiment"]),
            "--holdout",
            str(paths["holdout"]),
            "--observations",
            str(paths["observations"]),
            "--base-profile",
            str(paths["base_profile"]),
            "--evidence-binding",
            str(paths["evidence_binding"]),
        ]
    )

    assert exit_code == 2
    assert "chronological" in capsys.readouterr().err
