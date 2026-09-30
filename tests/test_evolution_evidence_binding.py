"""Phase 7-A-R1 frozen-evidence binding and dossier-integrity tests.

Focused R1 coverage: the calibration-time ``CalibrationEvidenceBindingV1``
contract and its freeze-boundary builder, the evaluator's binding identity
checks (each with its precise blocked reason), the persisted dossier's
semantic integrity (canonical check set, deterministic ``evaluation_id``,
binding identity fields), workspace persistence, the additive CLI paths and
offline/no-network execution.
"""

from __future__ import annotations

import hashlib
import json
import socket
from datetime import date
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from turtle_value_engine.backtest import (
    BacktestDatasetManifest,
    BacktestWorkspace,
    CalibrationEvidenceBindingV1,
    CalibrationObservation,
    CalibrationRunner,
    CalibrationSearchSpace,
    ChronologicalSplit,
    EvidenceBindingError,
    ListingLifecycle,
    Market,
    UniverseCoverage,
    build_calibration_evidence_binding,
    canonical_observations_sha256,
)
from turtle_value_engine.cli import main
from turtle_value_engine.evolution import (
    CHECK_CANONICAL_REPRODUCTION,
    CHECK_EVIDENCE_BINDING_BASE_PROFILE_IDENTITY,
    CHECK_EVIDENCE_BINDING_EXPERIMENT_IDENTITY,
    CHECK_EVIDENCE_BINDING_MANIFEST_IDENTITY,
    CHECK_EVIDENCE_BINDING_OBSERVATIONS_IDENTITY,
    CHECK_EVIDENCE_BINDING_PRESENT,
    CHECK_EVIDENCE_BINDING_PROPOSAL_IDENTITY,
    REQUIRED_EVALUATION_CHECK_NAMES,
    ControlledEvolutionEvaluationV1,
    evaluate_controlled_evolution,
    frozen_observations_sha256,
    proposal_payload_sha256,
)
from turtle_value_engine.historical import (
    HistoricalArtifactStore,
    HistoricalDatasetManifest,
    compile_backtest_manifest,
)
from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.providers.normalization import deterministic_id

ROOT = Path(__file__).parents[1]
SOURCE_HASH = "a" * 64
BASE_PROFILE_PATH = ROOT / "rules" / "strict-v1.yaml"
HISTORICAL_FIXTURE_ROOT = ROOT / "fixtures" / "historical" / "phase5r-compact-v1"
_HONEST = object()


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


def _manifest(
    dataset_id: str = "frozen-ah-mini-v1", dataset_version: str = "1"
) -> BacktestDatasetManifest:
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
        dataset_version=dataset_version,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 2, 1),
        calendar_id="frozen-mini-ah-v1",
        universe_id="frozen-ah",
        universe_coverage=UniverseCoverage.FIXED_RESEARCH_UNIVERSE,
        listing_lifecycles=[lifecycle],
    )


@pytest.fixture(scope="module")
def chain():
    base_bytes = BASE_PROFILE_PATH.read_bytes()
    base_sha = hashlib.sha256(base_bytes).hexdigest()
    observations = _observations()
    runner = CalibrationRunner(
        manifest_id="frozen-ah-mini-v1",
        base_profile_id="strict-v1",
        base_profile_sha256=base_sha,
        search_space=_search_space(),
        split=_split(),
    )
    experiment = runner.run(observations)
    holdout = runner.evaluate_holdout(experiment, observations)
    binding = build_calibration_evidence_binding(
        manifest=_manifest(), experiment=experiment, observations=observations
    )
    return base_bytes, base_sha, experiment, holdout, observations, binding


def _evaluate(
    chain_tuple,
    *,
    manifest: BacktestDatasetManifest | None = None,
    observations: list[CalibrationObservation] | None = None,
    base_profile_bytes: bytes | None = None,
    evidence_binding: CalibrationEvidenceBindingV1 | None | object = _HONEST,
):
    base_bytes, _sha, experiment, holdout, chain_observations, binding = chain_tuple
    return evaluate_controlled_evolution(
        manifest=manifest if manifest is not None else _manifest(),
        experiment=experiment,
        holdout=holdout,
        observations=observations if observations is not None else chain_observations,
        base_profile_bytes=(
            base_profile_bytes if base_profile_bytes is not None else base_bytes
        ),
        evidence_binding=(
            binding if evidence_binding is _HONEST else evidence_binding
        ),
    )


def _blocked_names(evaluation) -> set[str]:
    return {check.name for check in evaluation.checks if check.state == "BLOCKED"}


def _forged_binding(honest: CalibrationEvidenceBindingV1, **overrides):
    """Rebuild an internally consistent binding with tampered bound fields.

    The forgery recomputes ``binding_id`` and ``content_sha256`` so the model
    itself stays valid; only the bound identities differ.  This is exactly
    the attacker model the evaluator's binding-identity checks must catch.
    """

    payload = honest.model_dump(mode="json", warnings=False)
    for key, value in overrides.items():
        payload[key] = value
    payload.pop("binding_id", None)
    payload.pop("content_sha256", None)
    return CalibrationEvidenceBindingV1.build(
        manifest_id=payload["manifest_id"],
        manifest_content_sha256=payload["manifest_content_sha256"],
        experiment_id=payload["experiment_id"],
        experiment_content_sha256=payload["experiment_content_sha256"],
        observations_content_sha256=payload["observations_content_sha256"],
        observation_count=payload["observation_count"],
        base_profile_id=payload["base_profile_id"],
        base_profile_sha256=payload["base_profile_sha256"],
        proposal_id=payload["proposal_id"],
        proposal_payload_sha256=payload["proposal_payload_sha256"],
    )


# --------------------------------------------------------------------------
# Binding contract and freeze-boundary builder
# --------------------------------------------------------------------------


def test_builder_binds_every_required_identity(chain):
    (
        _base_bytes,
        base_sha,
        experiment,
        _holdout,
        observations,
        binding,
    ) = chain

    assert binding.manifest_id == experiment.manifest_id == "frozen-ah-mini-v1"
    assert binding.manifest_content_sha256 == _manifest().content_sha256
    assert binding.experiment_id == experiment.experiment_id
    assert binding.experiment_content_sha256 == experiment.content_sha256
    assert binding.observations_content_sha256 == frozen_observations_sha256(observations)
    assert binding.observations_content_sha256 == canonical_observations_sha256(observations)
    assert binding.observation_count == len(observations)
    assert binding.base_profile_id == experiment.base_profile_id
    assert binding.base_profile_sha256 == base_sha
    assert binding.proposal_id == experiment.proposal.proposal_id
    assert (
        binding.proposal_payload_sha256
        == proposal_payload_sha256(experiment.proposal)
    )
    assert binding.contract == "calibration_evidence_binding_v1"


def test_binding_build_is_deterministic(chain):
    _base_bytes, _sha, experiment, _holdout, observations, binding = chain

    rebuilt = build_calibration_evidence_binding(
        manifest=_manifest(), experiment=experiment, observations=observations
    )

    assert rebuilt == binding
    assert rebuilt.binding_id == binding.binding_id
    assert rebuilt.content_sha256 == binding.content_sha256


def test_binding_contract_rejects_tampered_content_sha256(chain):
    *_, binding = chain
    payload = binding.model_dump(mode="json", warnings=False)
    payload["content_sha256"] = "e" * 64

    with pytest.raises(ValidationError, match="content_sha256"):
        CalibrationEvidenceBindingV1.model_validate(payload)


def test_binding_contract_rejects_tampered_bound_field(chain):
    *_, binding = chain
    payload = binding.model_dump(mode="json", warnings=False)
    payload["manifest_content_sha256"] = "f" * 64

    # Any bound-field tamper breaks the deterministic binding_id first.
    with pytest.raises(ValidationError, match="binding_id"):
        CalibrationEvidenceBindingV1.model_validate(payload)


def test_binding_contract_rejects_non_canonical_binding_id(chain):
    *_, binding = chain
    payload = binding.model_dump(mode="json", warnings=False)
    payload["binding_id"] = "attacker-chosen-binding-id"

    with pytest.raises(ValidationError, match="binding_id"):
        CalibrationEvidenceBindingV1.model_validate(payload)


def test_binding_builder_fails_closed_on_foreign_manifest(chain):
    _base_bytes, _sha, experiment, _holdout, observations, _binding = chain

    with pytest.raises(EvidenceBindingError, match="manifest"):
        build_calibration_evidence_binding(
            manifest=_manifest(dataset_id="another-frozen-dataset"),
            experiment=experiment,
            observations=observations,
        )


def test_binding_builder_fails_closed_without_selected_proposal(chain):
    from tests.test_evolution_evaluation import _rebuild_experiment

    _base_bytes, _sha, experiment, _holdout, observations, _binding = chain
    proposalless = _rebuild_experiment(experiment, proposal=None)

    with pytest.raises(EvidenceBindingError, match="selected proposal"):
        build_calibration_evidence_binding(
            manifest=_manifest(),
            experiment=proposalless,
            observations=observations,
        )


def test_binding_schema_parity_and_instance_validation(chain):
    schema_path = ROOT / "schemas" / "calibration-evidence-binding.schema.json"
    checked_in = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(checked_in)
    assert checked_in == CalibrationEvidenceBindingV1.model_json_schema()

    *_, binding = chain
    Draft202012Validator(checked_in).validate(
        binding.model_dump(mode="json", warnings=False)
    )


# --------------------------------------------------------------------------
# Evaluator binding-identity checks (precise fail-closed reasons)
# --------------------------------------------------------------------------


def test_honest_binding_admits_canonical_chain(chain):
    evaluation = _evaluate(chain)
    assert evaluation.admission_state == "READY_FOR_HUMAN_REVIEW"
    assert not _blocked_names(evaluation)


def test_same_id_manifest_substitution_blocks_on_binding_manifest_identity(chain):
    evaluation = _evaluate(chain, manifest=_manifest(dataset_version="2"))

    assert evaluation.admission_state == "BLOCKED"
    assert _blocked_names(evaluation) == {CHECK_EVIDENCE_BINDING_MANIFEST_IDENTITY}


def test_source_hash_substitution_blocks_on_binding_observation_identity(chain):
    substituted = [
        observation.model_copy(update={"source_hash": "b" * 64})
        for observation in chain[4]
    ]

    evaluation = _evaluate(chain, observations=substituted)

    # Canonical replay alone stays blind to the provenance change; only the
    # frozen-evidence binding catches it.
    assert CHECK_CANONICAL_REPRODUCTION not in _blocked_names(evaluation)
    assert evaluation.admission_state == "BLOCKED"
    assert _blocked_names(evaluation) == {CHECK_EVIDENCE_BINDING_OBSERVATIONS_IDENTITY}


def test_foreign_binding_experiment_blocks_on_binding_experiment_identity(chain):
    base_bytes = chain[0]
    other_experiment, _other_holdout, other_observations = _other_chain(base_bytes)
    foreign_binding = build_calibration_evidence_binding(
        manifest=_manifest(),
        experiment=other_experiment,
        observations=other_observations,
    )

    evaluation = _evaluate(chain, evidence_binding=foreign_binding)

    # The other chain selects a different trial, so its proposal identity
    # differs as well; every other binding identity (manifest, observations,
    # base profile) is shared and stays PASS.
    assert evaluation.admission_state == "BLOCKED"
    assert _blocked_names(evaluation) == {
        CHECK_EVIDENCE_BINDING_EXPERIMENT_IDENTITY,
        CHECK_EVIDENCE_BINDING_PROPOSAL_IDENTITY,
    }


def _other_chain(base_bytes: bytes):
    base_sha = hashlib.sha256(base_bytes).hexdigest()
    observations = _observations()
    runner = CalibrationRunner(
        manifest_id="frozen-ah-mini-v1",
        base_profile_id="strict-v1",
        base_profile_sha256=base_sha,
        search_space=_search_space("other-quality-thresholds-v1"),
        split=_split(),
    )
    experiment = runner.run(observations)
    holdout = runner.evaluate_holdout(experiment, observations)
    return experiment, holdout, observations


def test_observation_count_mismatch_blocks_on_binding_observation_identity(chain):
    *_, binding = chain

    forged = _forged_binding(binding, observation_count=binding.observation_count - 1)

    evaluation = _evaluate(chain, evidence_binding=forged)

    assert evaluation.admission_state == "BLOCKED"
    assert _blocked_names(evaluation) == {CHECK_EVIDENCE_BINDING_OBSERVATIONS_IDENTITY}


def test_binding_base_profile_mismatch_blocks(chain):
    *_, binding = chain

    forged = _forged_binding(
        binding,
        base_profile_id="strict-v9-forged",
        base_profile_sha256="c" * 64,
    )

    evaluation = _evaluate(chain, evidence_binding=forged)

    assert evaluation.admission_state == "BLOCKED"
    assert _blocked_names(evaluation) == {CHECK_EVIDENCE_BINDING_BASE_PROFILE_IDENTITY}


def test_binding_proposal_mismatch_blocks(chain):
    *_, binding = chain

    forged = _forged_binding(
        binding,
        proposal_id="foreign-proposal-id",
        proposal_payload_sha256="d" * 64,
    )

    evaluation = _evaluate(chain, evidence_binding=forged)

    assert evaluation.admission_state == "BLOCKED"
    assert _blocked_names(evaluation) == {CHECK_EVIDENCE_BINDING_PROPOSAL_IDENTITY}


def test_missing_binding_fail_closes_every_binding_check_and_never_ready(chain):
    evaluation = _evaluate(chain, evidence_binding=None)

    assert evaluation.admission_state == "BLOCKED"
    assert _blocked_names(evaluation) == {
        CHECK_EVIDENCE_BINDING_PRESENT,
        CHECK_EVIDENCE_BINDING_MANIFEST_IDENTITY,
        CHECK_EVIDENCE_BINDING_EXPERIMENT_IDENTITY,
        CHECK_EVIDENCE_BINDING_OBSERVATIONS_IDENTITY,
        CHECK_EVIDENCE_BINDING_BASE_PROFILE_IDENTITY,
        CHECK_EVIDENCE_BINDING_PROPOSAL_IDENTITY,
    }


def test_binding_mismatch_dossier_still_records_supplied_binding_identity(chain):
    evaluation = _evaluate(chain, manifest=_manifest(dataset_version="2"))
    *_, binding = chain

    assert evaluation.evidence_binding_id == binding.binding_id
    assert evaluation.evidence_binding_sha256 == binding.content_sha256
    assert evaluation.admission_state == "BLOCKED"


# --------------------------------------------------------------------------
# Persisted dossier semantic integrity
# --------------------------------------------------------------------------


def _rehashed_payload(evaluation) -> dict:
    payload = evaluation.model_dump(mode="json", warnings=False)
    payload["content_sha256"] = _content_hash(payload)
    return payload


def _content_hash(payload: dict) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
    ).hexdigest()


def test_ready_dossier_without_binding_identity_is_rejected(chain):
    evaluation = _evaluate(chain)
    assert evaluation.admission_state == "READY_FOR_HUMAN_REVIEW"

    payload = _rehashed_payload(evaluation)
    payload["evidence_binding_id"] = None
    payload["evidence_binding_sha256"] = None
    payload["evaluation_id"] = deterministic_evaluation_id(payload)
    payload["content_sha256"] = _content_hash(payload)

    with pytest.raises(
        ValidationError, match="READY_FOR_HUMAN_REVIEW requires a bound"
    ):
        ControlledEvolutionEvaluationV1.model_validate(payload)


def test_binding_identity_fields_must_be_supplied_together(chain):
    evaluation = _evaluate(chain)

    payload = _rehashed_payload(evaluation)
    payload["evidence_binding_sha256"] = None
    payload["evaluation_id"] = deterministic_evaluation_id(payload)
    payload["content_sha256"] = _content_hash(payload)

    with pytest.raises(ValidationError, match="supplied together"):
        ControlledEvolutionEvaluationV1.model_validate(payload)


def deterministic_evaluation_id(payload: dict) -> str:
    return deterministic_id(
        "controlled-evolution-evaluation",
        payload["base_profile_id"],
        payload["base_profile_sha256"],
        payload["dataset_id"],
        payload["manifest_content_sha256"],
        payload["experiment_id"],
        payload["experiment_content_sha256"],
        payload["proposal_id"],
        payload["proposal_payload_sha256"],
        payload["holdout_content_sha256"],
        payload["observations_content_sha256"],
        payload["evidence_binding_id"],
        payload["evidence_binding_sha256"],
    )


def test_reordered_checks_are_rejected(chain):
    evaluation = _evaluate(chain)

    payload = _rehashed_payload(evaluation)
    payload["checks"][0], payload["checks"][1] = (
        payload["checks"][1],
        payload["checks"][0],
    )
    payload["content_sha256"] = _content_hash(payload)

    with pytest.raises(ValidationError, match="canonical required check set"):
        ControlledEvolutionEvaluationV1.model_validate(payload)


def test_unknown_check_name_is_rejected(chain):
    evaluation = _evaluate(chain)

    payload = _rehashed_payload(evaluation)
    payload["checks"][0]["name"] = "FAKE_SUBSTITUTED_CHECK"
    payload["content_sha256"] = _content_hash(payload)

    with pytest.raises(ValidationError):
        ControlledEvolutionEvaluationV1.model_validate(payload)


def test_duplicate_check_is_rejected(chain):
    evaluation = _evaluate(chain)

    payload = _rehashed_payload(evaluation)
    payload["checks"].append(dict(payload["checks"][0]))
    payload["content_sha256"] = _content_hash(payload)

    with pytest.raises(ValidationError):
        ControlledEvolutionEvaluationV1.model_validate(payload)


def test_canonical_required_check_set_matches_evaluator_output(chain):
    evaluation = _evaluate(chain)

    assert len(REQUIRED_EVALUATION_CHECK_NAMES) == 19
    assert [check.name for check in evaluation.checks] == list(
        REQUIRED_EVALUATION_CHECK_NAMES
    )


def test_evaluation_schema_rejects_truncated_check_list(chain):
    schema = json.loads(
        (ROOT / "schemas" / "controlled-evolution-evaluation.schema.json").read_text(
            encoding="utf-8"
        )
    )
    payload = _rehashed_payload(_evaluate(chain))
    payload["checks"] = payload["checks"][:-1]

    with pytest.raises(Exception):  # noqa: B017 - jsonschema ValidationError
        Draft202012Validator(schema).validate(payload)


# --------------------------------------------------------------------------
# Workspace persistence
# --------------------------------------------------------------------------


def test_workspace_round_trips_evidence_binding(tmp_path, chain):
    *_, binding = chain
    workspace = BacktestWorkspace(tmp_path)

    path = workspace.save_calibration_evidence_binding(binding)

    assert path.exists()
    assert workspace.load_calibration_evidence_binding(binding.binding_id) == binding


def test_workspace_rejects_conflicting_binding_content(tmp_path, chain):
    from turtle_value_engine.backtest import BacktestWorkspaceError

    *_, binding = chain
    workspace = BacktestWorkspace(tmp_path)
    workspace.save_calibration_evidence_binding(binding)

    # A binding_id is derived from its bound content, so a legitimately built
    # binding can never collide; simulate foreign bytes already occupying the
    # artifact path to prove the store stays immutable.
    conflicting_path = (
        tmp_path / "calibration-evidence-bindings" / f"{binding.binding_id}.json"
    )
    conflicting_path.write_text("not the persisted binding", encoding="utf-8")
    with pytest.raises(BacktestWorkspaceError, match="conflicting"):
        workspace.save_calibration_evidence_binding(binding)


# --------------------------------------------------------------------------
# CLI paths
# --------------------------------------------------------------------------


def test_evolution_cli_requires_evidence_binding_argument(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["evolution", "evaluate"])

    assert exc_info.value.code == 2
    assert "--evidence-binding" in capsys.readouterr().err


def test_calibrate_cli_produces_evidence_binding_and_full_chain_admits(tmp_path):
    base_bytes = BASE_PROFILE_PATH.read_bytes()
    base_sha = hashlib.sha256(base_bytes).hexdigest()
    search_space = CalibrationSearchSpace(
        space_id="r1-cli-space",
        base_profile_id="strict-v1",
        parameters={"min_quality": [0.0]},
        objective="MEAN_RETURN",
    )
    split = ChronologicalSplit(
        train_start=date(2020, 1, 1),
        train_end=date(2020, 1, 1),
        validation_start=date(2020, 1, 2),
        validation_end=date(2020, 1, 2),
        holdout_start=date(2020, 1, 3),
        holdout_end=date(2020, 1, 3),
    )
    observations = [
        CalibrationObservation(
            observation_id=f"r1-cli-observation-{index}",
            observed_at=observed_at,
            target_return=float(index),
            feature_values={"quality": float(index)},
            source_hash=SOURCE_HASH,
        )
        for index, observed_at in enumerate(
            (date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3)),
            start=1,
        )
    ]
    search_space_path = tmp_path / "search-space.json"
    split_path = tmp_path / "split.json"
    observations_path = tmp_path / "observations.json"
    search_space_path.write_text(search_space.model_dump_json(), encoding="utf-8")
    split_path.write_text(split.model_dump_json(), encoding="utf-8")
    observations_path.write_text(
        json.dumps([item.model_dump(mode="json") for item in observations]),
        encoding="utf-8",
    )
    experiment_path = tmp_path / "calibration.json"
    binding_path = tmp_path / "evidence-binding.json"

    assert (
        main(
            [
                "calibrate",
                "--manifest",
                str(HISTORICAL_FIXTURE_ROOT / "manifest.json"),
                "--store",
                str(HISTORICAL_FIXTURE_ROOT / "store"),
                "--search-space",
                str(search_space_path),
                "--split",
                str(split_path),
                "--observations",
                str(observations_path),
                "--base-profile-sha256",
                base_sha,
                "--output",
                str(experiment_path),
                "--evidence-binding-output",
                str(binding_path),
            ]
        )
        == 0
    )

    binding = CalibrationEvidenceBindingV1.model_validate(
        json.loads(binding_path.read_text(encoding="utf-8"))
    )
    from turtle_value_engine.backtest import CalibrationExperiment

    experiment = CalibrationExperiment.model_validate(
        json.loads(experiment_path.read_text(encoding="utf-8"))
    )
    # The CLI produced the binding at the calibration/freeze boundary from the
    # exact compiled manifest, the exact observation rows and the experiment.
    assert binding.experiment_id == experiment.experiment_id
    assert binding.experiment_content_sha256 == experiment.content_sha256
    assert binding.observations_content_sha256 == canonical_observations_sha256(
        observations
    )

    # Full production chain: the same binding admits the frozen chain through
    # the offline evaluation CLI.
    historical_manifest = HistoricalDatasetManifest.model_validate(
        json.loads(
            (HISTORICAL_FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8")
        )
    )
    compiled_manifest = compile_backtest_manifest(
        historical_manifest, HistoricalArtifactStore(HISTORICAL_FIXTURE_ROOT / "store")
    )
    assert compiled_manifest.content_sha256 == binding.manifest_content_sha256
    manifest_path = tmp_path / "backtest-manifest.json"
    manifest_path.write_text(compiled_manifest.model_dump_json(indent=2), "utf-8")

    holdout = CalibrationRunner(
        manifest_id=experiment.manifest_id,
        base_profile_id=experiment.base_profile_id,
        base_profile_sha256=experiment.base_profile_sha256,
        search_space=experiment.search_space,
        split=experiment.split,
    ).evaluate_holdout(experiment, observations)
    holdout_path = tmp_path / "holdout.json"
    holdout_path.write_text(holdout.model_dump_json(indent=2), "utf-8")

    output_path = tmp_path / "evaluation.json"
    assert (
        main(
            [
                "evolution",
                "evaluate",
                "--manifest",
                str(manifest_path),
                "--experiment",
                str(experiment_path),
                "--holdout",
                str(holdout_path),
                "--observations",
                str(observations_path),
                "--base-profile",
                str(BASE_PROFILE_PATH),
                "--evidence-binding",
                str(binding_path),
                "--output",
                str(output_path),
            ]
        )
        == 0
    )
    evaluation = ControlledEvolutionEvaluationV1.model_validate(
        json.loads(output_path.read_text(encoding="utf-8"))
    )
    assert evaluation.admission_state == "READY_FOR_HUMAN_REVIEW"
    assert evaluation.evidence_binding_id == binding.binding_id


# --------------------------------------------------------------------------
# Offline / no-network execution
# --------------------------------------------------------------------------


def test_binding_and_evaluation_paths_construct_no_network(tmp_path, monkeypatch, chain):
    def no_sockets(*args, **kwargs):
        raise AssertionError("evidence binding or evaluation constructed a socket")

    monkeypatch.setattr(socket, "socket", no_sockets)
    monkeypatch.setattr(socket, "create_connection", no_sockets)

    evaluation = _evaluate(chain)
    assert evaluation.admission_state == "READY_FOR_HUMAN_REVIEW"

    _base_bytes, _sha, experiment, _holdout, observations, _binding = chain
    rebuilt = build_calibration_evidence_binding(
        manifest=_manifest(), experiment=experiment, observations=observations
    )
    assert rebuilt == chain[5]
