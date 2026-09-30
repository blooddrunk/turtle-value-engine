"""Phase 7-A-R2 authoritative calibration-freeze anchor and schema parity.

Focused R2 coverage: the immutable ``CalibrationFreezeRecordV1`` contract, the
experiment-keyed authoritative workspace slot (idempotent byte-identical
repeat, conflicting re-freeze rejection with original bytes preserved, anchor
published last), the fail-closed workspace resolution boundary (missing,
corrupt, foreign, mismatched anchor/binding), the evaluator's authoritative
anchor checks (an unanchored sidecar binding can never be READY), the real
``calibrate --workspace -> evolution evaluate --calibration-workspace`` CLI
chain, Draft 2020-12 exact-sequence schema parity for the canonical check
set, socket-guarded offline execution and ``strict-v1`` byte identity.
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
    BacktestWorkspaceError,
    CalibrationExperiment,
    CalibrationFreezeRecordV1,
    CalibrationObservation,
    CalibrationRunner,
    CalibrationSearchSpace,
    ChronologicalSplit,
    ListingLifecycle,
    Market,
    UniverseCoverage,
    build_calibration_evidence_binding,
    commit_calibration_freeze,
    resolve_anchored_calibration_evidence,
)
from turtle_value_engine.backtest.calibration_freeze import CalibrationFreezeError
from turtle_value_engine.cli import main
from turtle_value_engine.evolution import (
    CHECK_FREEZE_ANCHOR_BINDING_IDENTITY,
    CHECK_FREEZE_ANCHOR_EXPERIMENT_IDENTITY,
    CHECK_FREEZE_ANCHOR_PRESENT,
    REQUIRED_EVALUATION_CHECK_NAMES,
    ControlledEvolutionEvaluationV1,
    evaluate_controlled_evolution,
)
from turtle_value_engine.historical import (
    HistoricalArtifactStore,
    HistoricalDatasetManifest,
    compile_backtest_manifest,
)
from turtle_value_engine.providers.models import canonical_json_bytes

ROOT = Path(__file__).parents[1]
SOURCE_HASH = "a" * 64
BASE_PROFILE_PATH = ROOT / "rules" / "strict-v1.yaml"
HISTORICAL_FIXTURE_ROOT = ROOT / "fixtures" / "historical" / "phase5r-compact-v1"
STRICT_V1_SHA256 = "e3618f78b2f8e4d1e8e81ce3065da977685ad5256bd0ab3332b3a8054e0b6333"


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


def _manifest(dataset_version: str = "1") -> BacktestDatasetManifest:
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
        dataset_id="frozen-ah-mini-v1",
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
    record = CalibrationFreezeRecordV1.build(
        experiment_id=experiment.experiment_id,
        experiment_content_sha256=experiment.content_sha256,
        binding_id=binding.binding_id,
        binding_content_sha256=binding.content_sha256,
    )
    return base_bytes, base_sha, experiment, holdout, observations, binding, record


def _blocked_names(evaluation) -> set[str]:
    return {check.name for check in evaluation.checks if check.state == "BLOCKED"}


def _workspace_snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(item.relative_to(root)): item.read_bytes()
        for item in sorted(root.rglob("*"))
        if item.is_file()
    }


def _record_path(root: Path, experiment_id: str) -> Path:
    return root / "calibration-freeze-records" / f"{experiment_id}.json"


# --------------------------------------------------------------------------
# Freeze record contract
# --------------------------------------------------------------------------


def test_freeze_record_build_is_deterministic(chain):
    _base, _sha, _experiment, _holdout, _obs, binding, record = chain
    rebuilt = CalibrationFreezeRecordV1.build(
        experiment_id=record.experiment_id,
        experiment_content_sha256=record.experiment_content_sha256,
        binding_id=record.binding_id,
        binding_content_sha256=record.binding_content_sha256,
    )
    assert rebuilt == record
    assert rebuilt.contract == "calibration_freeze_record_v1"
    assert rebuilt.freeze_id == record.freeze_id
    assert rebuilt.binding_id == binding.binding_id


def test_freeze_record_rejects_tampered_content_sha256(chain):
    *_, record = chain
    payload = record.model_dump(mode="json", warnings=False)
    payload["content_sha256"] = "e" * 64
    with pytest.raises(ValidationError, match="content_sha256"):
        CalibrationFreezeRecordV1.model_validate(payload)


def test_freeze_record_rejects_tampered_bound_field(chain):
    *_, record = chain
    payload = record.model_dump(mode="json", warnings=False)
    payload["binding_id"] = "foreign-binding-id"
    with pytest.raises(ValidationError, match="freeze_id"):
        CalibrationFreezeRecordV1.model_validate(payload)


def test_freeze_record_schema_parity_and_instance_validation(chain):
    schema_path = ROOT / "schemas" / "calibration-freeze-record.schema.json"
    checked_in = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(checked_in)
    assert checked_in == CalibrationFreezeRecordV1.model_json_schema()

    *_, record = chain
    Draft202012Validator(checked_in).validate(
        record.model_dump(mode="json", warnings=False)
    )


# --------------------------------------------------------------------------
# Authoritative workspace freeze: commit, idempotency, conflict
# --------------------------------------------------------------------------


def test_commit_persists_prerequisites_and_anchor_keyed_by_experiment_id(
    tmp_path, chain
):
    base, _sha, experiment, holdout, observations, binding, record = chain
    workspace = BacktestWorkspace(tmp_path)

    committed_binding, committed_record = commit_calibration_freeze(
        workspace,
        manifest=_manifest(),
        experiment=experiment,
        observations=observations,
    )

    assert committed_binding == binding
    assert committed_record == record
    assert workspace.load_calibration_experiment(experiment.experiment_id) == experiment
    assert workspace.load_calibration_evidence_binding(binding.binding_id) == binding
    assert (
        workspace.load_calibration_freeze_record(experiment.experiment_id) == record
    )
    # The authoritative slot is keyed by experiment_id, not binding_id.
    assert _record_path(tmp_path, experiment.experiment_id).is_file()


def test_repeated_byte_identical_freeze_is_idempotent(tmp_path, chain):
    base, _sha, experiment, _holdout, observations, _binding, _record = chain
    workspace = BacktestWorkspace(tmp_path)
    commit_calibration_freeze(
        workspace, manifest=_manifest(), experiment=experiment, observations=observations
    )
    before = _workspace_snapshot(tmp_path)

    commit_calibration_freeze(
        workspace, manifest=_manifest(), experiment=experiment, observations=observations
    )

    assert _workspace_snapshot(tmp_path) == before


def test_conflicting_second_freeze_fails_closed_and_preserves_original_bytes(
    tmp_path, chain
):
    base, _sha, experiment, _holdout, observations, binding, record = chain
    workspace = BacktestWorkspace(tmp_path)
    commit_calibration_freeze(
        workspace, manifest=_manifest(), experiment=experiment, observations=observations
    )
    before = _workspace_snapshot(tmp_path)

    # A re-freeze over substituted non-scoring observation provenance produces
    # a different binding for the same experiment identity: the authoritative
    # experiment-keyed slot must reject it without altering any frozen byte.
    substituted = [
        observation.model_copy(update={"source_hash": "b" * 64})
        for observation in observations
    ]
    fresh_binding = build_calibration_evidence_binding(
        manifest=_manifest(), experiment=experiment, observations=substituted
    )
    workspace.save_calibration_evidence_binding(fresh_binding)
    conflicting_record = CalibrationFreezeRecordV1.build(
        experiment_id=experiment.experiment_id,
        experiment_content_sha256=experiment.content_sha256,
        binding_id=fresh_binding.binding_id,
        binding_content_sha256=fresh_binding.content_sha256,
    )
    with pytest.raises(BacktestWorkspaceError, match="conflicting"):
        workspace.save_calibration_freeze_record(conflicting_record)

    snapshot = _workspace_snapshot(tmp_path)
    assert {
        path: bytes_
        for path, bytes_ in snapshot.items()
        if path in before or not path.startswith("calibration-evidence-bindings/")
    } == {
        path: bytes_
        for path, bytes_ in before.items()
    }
    # The original authoritative record still binds the original binding.
    assert workspace.load_calibration_freeze_record(
        experiment.experiment_id
    ) == record


def test_conflicting_manifest_content_fails_closed(tmp_path, chain):
    base, _sha, experiment, _holdout, observations, _binding, _record = chain
    workspace = BacktestWorkspace(tmp_path)
    commit_calibration_freeze(
        workspace, manifest=_manifest(), experiment=experiment, observations=observations
    )
    before = _workspace_snapshot(tmp_path)

    # Same dataset_id, different valid manifest content: the same-experiment
    # rerun must fail closed (the manifest slot conflicts first).
    with pytest.raises(BacktestWorkspaceError, match="conflicting"):
        commit_calibration_freeze(
            workspace,
            manifest=_manifest(dataset_version="2"),
            experiment=experiment,
            observations=observations,
        )
    assert _workspace_snapshot(tmp_path) == before


def test_anchor_is_published_last_on_crash_during_prerequisites(tmp_path, chain):
    base, _sha, experiment, _holdout, observations, _binding, _record = chain
    workspace = BacktestWorkspace(tmp_path)

    def fail_binding_save(*args, **kwargs):
        raise BacktestWorkspaceError(
            "simulated crash while persisting the binding prerequisite"
        )

    original_save_binding = BacktestWorkspace.save_calibration_evidence_binding
    BacktestWorkspace.save_calibration_evidence_binding = fail_binding_save
    try:
        with pytest.raises(BacktestWorkspaceError):
            commit_calibration_freeze(
                workspace,
                manifest=_manifest(),
                experiment=experiment,
                observations=observations,
            )
    finally:
        BacktestWorkspace.save_calibration_evidence_binding = original_save_binding

    # A crash before the prerequisites are committed can leave unreferenced
    # preparatory artifacts, but must never publish an authoritative anchor.
    assert not _record_path(tmp_path, experiment.experiment_id).exists()


# --------------------------------------------------------------------------
# Fail-closed workspace resolution
# --------------------------------------------------------------------------


def test_resolve_returns_the_anchored_chain(tmp_path, chain):
    base, _sha, experiment, _holdout, observations, binding, record = chain
    workspace = BacktestWorkspace(tmp_path)
    commit_calibration_freeze(
        workspace, manifest=_manifest(), experiment=experiment, observations=observations
    )

    anchored = resolve_anchored_calibration_evidence(
        workspace, experiment_id=experiment.experiment_id
    )

    assert anchored.freeze_record == record
    assert anchored.experiment == experiment
    assert anchored.binding == binding


def test_resolve_fails_closed_when_anchor_is_missing(tmp_path, chain):
    _base, _sha, experiment, *_rest = chain
    workspace = BacktestWorkspace(tmp_path)

    with pytest.raises(CalibrationFreezeError, match="no authoritative"):
        resolve_anchored_calibration_evidence(
            workspace, experiment_id=experiment.experiment_id
        )


def test_resolve_fails_closed_on_corrupt_anchor(tmp_path, chain):
    _base, _sha, experiment, _holdout, observations, _binding, _record = chain
    workspace = BacktestWorkspace(tmp_path)
    commit_calibration_freeze(
        workspace, manifest=_manifest(), experiment=experiment, observations=observations
    )
    record_file = _record_path(tmp_path, experiment.experiment_id)
    record_file.write_text("not a freeze record", encoding="utf-8")

    with pytest.raises(CalibrationFreezeError, match="no authoritative"):
        resolve_anchored_calibration_evidence(
            workspace, experiment_id=experiment.experiment_id
        )


def test_resolve_fails_closed_on_foreign_experiment_anchor(tmp_path, chain):
    base, _sha, experiment, _holdout, observations, _binding, _record = chain
    other_runner = CalibrationRunner(
        manifest_id="frozen-ah-mini-v1",
        base_profile_id="strict-v1",
        base_profile_sha256=hashlib.sha256(base).hexdigest(),
        search_space=_search_space("other-quality-thresholds-v1"),
        split=_split(),
    )
    other_experiment = other_runner.run(observations)
    assert other_experiment.experiment_id != experiment.experiment_id
    workspace = BacktestWorkspace(tmp_path)
    commit_calibration_freeze(
        workspace,
        manifest=_manifest(),
        experiment=other_experiment,
        observations=observations,
    )

    # The workspace froze a foreign experiment; the requested identity has no
    # anchor at all and resolution fails closed.
    with pytest.raises(CalibrationFreezeError, match="no authoritative"):
        resolve_anchored_calibration_evidence(
            workspace, experiment_id=experiment.experiment_id
        )


def test_resolve_fails_closed_when_anchor_references_missing_binding(tmp_path, chain):
    _base, _sha, experiment, _holdout, observations, binding, _record = chain
    workspace = BacktestWorkspace(tmp_path)
    commit_calibration_freeze(
        workspace, manifest=_manifest(), experiment=experiment, observations=observations
    )
    (tmp_path / "calibration-evidence-bindings" / f"{binding.binding_id}.json").unlink()

    with pytest.raises(CalibrationFreezeError, match="missing or corrupt"):
        resolve_anchored_calibration_evidence(
            workspace, experiment_id=experiment.experiment_id
        )


def test_resolve_fails_closed_when_anchor_binding_hash_mismatches(tmp_path, chain):
    _base, _sha, experiment, _holdout, observations, binding, _record = chain
    workspace = BacktestWorkspace(tmp_path)
    workspace.save_calibration_experiment(experiment)
    workspace.save_calibration_evidence_binding(binding)
    forged = CalibrationFreezeRecordV1.build(
        experiment_id=experiment.experiment_id,
        experiment_content_sha256=experiment.content_sha256,
        binding_id=binding.binding_id,
        binding_content_sha256="f" * 64,
    )
    workspace.save_calibration_freeze_record(forged)

    with pytest.raises(CalibrationFreezeError, match="does not bind the referenced"):
        resolve_anchored_calibration_evidence(
            workspace, experiment_id=experiment.experiment_id
        )


def test_resolve_fails_closed_when_anchor_experiment_hash_mismatches(tmp_path, chain):
    _base, _sha, experiment, _holdout, observations, binding, _record = chain
    workspace = BacktestWorkspace(tmp_path)
    workspace.save_calibration_experiment(experiment)
    workspace.save_calibration_evidence_binding(binding)
    forged = CalibrationFreezeRecordV1.build(
        experiment_id=experiment.experiment_id,
        experiment_content_sha256="d" * 64,
        binding_id=binding.binding_id,
        binding_content_sha256=binding.content_sha256,
    )
    workspace.save_calibration_freeze_record(forged)

    with pytest.raises(CalibrationFreezeError, match="does not bind the committed"):
        resolve_anchored_calibration_evidence(
            workspace, experiment_id=experiment.experiment_id
        )


def test_resolve_fails_closed_when_anchored_binding_is_foreign(tmp_path, chain):
    base, _sha, experiment, _holdout, observations, _binding, _record = chain
    other_runner = CalibrationRunner(
        manifest_id="frozen-ah-mini-v1",
        base_profile_id="strict-v1",
        base_profile_sha256=hashlib.sha256(base).hexdigest(),
        search_space=_search_space("other-quality-thresholds-v1"),
        split=_split(),
    )
    other_experiment = other_runner.run(observations)
    other_binding = build_calibration_evidence_binding(
        manifest=_manifest(), experiment=other_experiment, observations=observations
    )
    workspace = BacktestWorkspace(tmp_path)
    workspace.save_calibration_experiment(experiment)
    workspace.save_calibration_evidence_binding(other_binding)
    foreign_anchor = CalibrationFreezeRecordV1.build(
        experiment_id=experiment.experiment_id,
        experiment_content_sha256=experiment.content_sha256,
        binding_id=other_binding.binding_id,
        binding_content_sha256=other_binding.content_sha256,
    )
    workspace.save_calibration_freeze_record(foreign_anchor)

    with pytest.raises(CalibrationFreezeError, match="does not bind that experiment"):
        resolve_anchored_calibration_evidence(
            workspace, experiment_id=experiment.experiment_id
        )


# --------------------------------------------------------------------------
# Evaluator authoritative-anchor checks
# --------------------------------------------------------------------------


def test_anchored_honest_chain_is_ready_and_records_anchor_identity(chain):
    base, _sha, experiment, holdout, observations, binding, record = chain

    evaluation = evaluate_controlled_evolution(
        manifest=_manifest(),
        experiment=experiment,
        holdout=holdout,
        observations=observations,
        base_profile_bytes=base,
        evidence_binding=binding,
        freeze_record=record,
    )

    assert evaluation.admission_state == "READY_FOR_HUMAN_REVIEW"
    assert not _blocked_names(evaluation)
    assert evaluation.freeze_anchor_id == record.freeze_id
    assert evaluation.freeze_anchor_sha256 == record.content_sha256
    assert len(evaluation.checks) == len(REQUIRED_EVALUATION_CHECK_NAMES) == 22


def test_sidecar_binding_alone_blocks_on_authoritative_anchor(chain):
    base, _sha, experiment, holdout, observations, binding, _record = chain

    evaluation = evaluate_controlled_evolution(
        manifest=_manifest(),
        experiment=experiment,
        holdout=holdout,
        observations=observations,
        base_profile_bytes=base,
        evidence_binding=binding,
    )

    assert evaluation.admission_state == "BLOCKED"
    assert _blocked_names(evaluation) == {
        CHECK_FREEZE_ANCHOR_PRESENT,
        CHECK_FREEZE_ANCHOR_EXPERIMENT_IDENTITY,
        CHECK_FREEZE_ANCHOR_BINDING_IDENTITY,
    }
    assert evaluation.freeze_anchor_id is None
    assert evaluation.freeze_anchor_sha256 is None


def test_anchor_experiment_mismatch_blocks_precisely(chain):
    base, _sha, experiment, holdout, observations, binding, record = chain
    # An internally valid anchor for a DIFFERENT experiment identity.
    foreign_anchor = CalibrationFreezeRecordV1.build(
        experiment_id="another-experiment-id",
        experiment_content_sha256="c" * 64,
        binding_id=binding.binding_id,
        binding_content_sha256=binding.content_sha256,
    )

    evaluation = evaluate_controlled_evolution(
        manifest=_manifest(),
        experiment=experiment,
        holdout=holdout,
        observations=observations,
        base_profile_bytes=base,
        evidence_binding=binding,
        freeze_record=foreign_anchor,
    )

    assert evaluation.admission_state == "BLOCKED"
    assert _blocked_names(evaluation) == {CHECK_FREEZE_ANCHOR_EXPERIMENT_IDENTITY}


def test_anchor_binding_mismatch_blocks_precisely(chain):
    base, _sha, experiment, holdout, observations, binding, _record = chain
    # An internally valid anchor referencing a different binding identity.
    mismatched_anchor = CalibrationFreezeRecordV1.build(
        experiment_id=experiment.experiment_id,
        experiment_content_sha256=experiment.content_sha256,
        binding_id="another-binding-id",
        binding_content_sha256="d" * 64,
    )

    evaluation = evaluate_controlled_evolution(
        manifest=_manifest(),
        experiment=experiment,
        holdout=holdout,
        observations=observations,
        base_profile_bytes=base,
        evidence_binding=binding,
        freeze_record=mismatched_anchor,
    )

    assert evaluation.admission_state == "BLOCKED"
    assert _blocked_names(evaluation) == {CHECK_FREEZE_ANCHOR_BINDING_IDENTITY}


def test_ready_dossier_requires_anchor_identity_fields(chain):
    base, _sha, experiment, holdout, observations, binding, record = chain
    evaluation = evaluate_controlled_evolution(
        manifest=_manifest(),
        experiment=experiment,
        holdout=holdout,
        observations=observations,
        base_profile_bytes=base,
        evidence_binding=binding,
        freeze_record=record,
    )
    assert evaluation.admission_state == "READY_FOR_HUMAN_REVIEW"

    payload = evaluation.model_dump(mode="json", warnings=False)
    payload["freeze_anchor_id"] = None
    payload["freeze_anchor_sha256"] = None
    payload["evaluation_id"] = _evaluation_id_for(payload)
    payload["content_sha256"] = _content_hash(payload)

    with pytest.raises(
        ValidationError, match="READY_FOR_HUMAN_REVIEW requires an authoritative"
    ):
        ControlledEvolutionEvaluationV1.model_validate(payload)


def test_anchor_identity_fields_must_be_supplied_together(chain):
    base, _sha, experiment, holdout, observations, binding, record = chain
    evaluation = evaluate_controlled_evolution(
        manifest=_manifest(),
        experiment=experiment,
        holdout=holdout,
        observations=observations,
        base_profile_bytes=base,
        evidence_binding=binding,
        freeze_record=record,
    )

    payload = evaluation.model_dump(mode="json", warnings=False)
    payload["freeze_anchor_sha256"] = None
    payload["evaluation_id"] = _evaluation_id_for(payload)
    payload["content_sha256"] = _content_hash(payload)

    with pytest.raises(ValidationError, match="supplied together"):
        ControlledEvolutionEvaluationV1.model_validate(payload)


def _evaluation_id_for(payload: dict) -> str:
    from turtle_value_engine.providers.normalization import deterministic_id

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
        payload.get("freeze_anchor_id"),
        payload.get("freeze_anchor_sha256"),
    )


def _content_hash(payload: dict) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
    ).hexdigest()


# --------------------------------------------------------------------------
# Draft 2020-12 exact-sequence schema parity
# --------------------------------------------------------------------------


def _anchored_ready_payload(chain) -> dict:
    base, _sha, experiment, holdout, observations, binding, record = chain
    evaluation = evaluate_controlled_evolution(
        manifest=_manifest(),
        experiment=experiment,
        holdout=holdout,
        observations=observations,
        base_profile_bytes=base,
        evidence_binding=binding,
        freeze_record=record,
    )
    assert evaluation.admission_state == "READY_FOR_HUMAN_REVIEW"
    return evaluation.model_dump(mode="json", warnings=False)


def _checked_in_schema() -> dict:
    return json.loads(
        (ROOT / "schemas" / "controlled-evolution-evaluation.schema.json").read_text(
            encoding="utf-8"
        )
    )


def test_schema_is_generated_from_the_canonical_check_sequence():
    schema = _checked_in_schema()
    Draft202012Validator.check_schema(schema)
    assert schema == ControlledEvolutionEvaluationV1.model_json_schema()

    checks = schema["properties"]["checks"]
    assert checks["items"] is False
    assert checks["minItems"] == checks["maxItems"] == len(REQUIRED_EVALUATION_CHECK_NAMES)
    assert [
        position["properties"]["name"]["const"]
        for position in checks["prefixItems"]
    ] == list(REQUIRED_EVALUATION_CHECK_NAMES)


def test_canonical_dossier_validates_in_model_and_schema(chain):
    payload = _anchored_ready_payload(chain)
    schema = _checked_in_schema()

    ControlledEvolutionEvaluationV1.model_validate(payload)
    Draft202012Validator(schema).validate(payload)


def test_reordered_checks_rejected_in_model_and_schema(chain):
    payload = _anchored_ready_payload(chain)
    payload["checks"][0], payload["checks"][1] = (
        payload["checks"][1],
        payload["checks"][0],
    )
    payload["content_sha256"] = _content_hash(payload)
    schema = _checked_in_schema()

    with pytest.raises(ValidationError, match="canonical required check set"):
        ControlledEvolutionEvaluationV1.model_validate(payload)
    with pytest.raises(Exception):  # noqa: B017 - jsonschema ValidationError
        Draft202012Validator(schema).validate(payload)


def test_count_preserving_duplicate_omission_rejected_in_model_and_schema(chain):
    payload = _anchored_ready_payload(chain)
    payload["checks"][0] = dict(payload["checks"][1])
    payload["content_sha256"] = _content_hash(payload)
    schema = _checked_in_schema()

    with pytest.raises(ValidationError, match="canonical required check set"):
        ControlledEvolutionEvaluationV1.model_validate(payload)
    with pytest.raises(Exception):  # noqa: B017 - jsonschema ValidationError
        Draft202012Validator(schema).validate(payload)


def test_truncated_checks_rejected_in_model_and_schema(chain):
    payload = _anchored_ready_payload(chain)
    payload["checks"] = payload["checks"][:-1]
    payload["content_sha256"] = _content_hash(payload)
    schema = _checked_in_schema()

    with pytest.raises(ValidationError):
        ControlledEvolutionEvaluationV1.model_validate(payload)
    with pytest.raises(Exception):  # noqa: B017 - jsonschema ValidationError
        Draft202012Validator(schema).validate(payload)


def test_unknown_check_name_rejected_in_model_and_schema(chain):
    payload = _anchored_ready_payload(chain)
    payload["checks"][0] = dict(payload["checks"][0], name="FAKE_SUBSTITUTED_CHECK")
    payload["content_sha256"] = _content_hash(payload)
    schema = _checked_in_schema()

    with pytest.raises(ValidationError):
        ControlledEvolutionEvaluationV1.model_validate(payload)
    with pytest.raises(Exception):  # noqa: B017 - jsonschema ValidationError
        Draft202012Validator(schema).validate(payload)


def test_extra_check_beyond_sequence_rejected_by_schema(chain):
    payload = _anchored_ready_payload(chain)
    payload["checks"] = [*payload["checks"], dict(payload["checks"][-1])]
    payload["content_sha256"] = _content_hash(payload)
    schema = _checked_in_schema()

    with pytest.raises(Exception):  # noqa: B017 - jsonschema ValidationError
        Draft202012Validator(schema).validate(payload)


# --------------------------------------------------------------------------
# CLI: authoritative chain, unanchored sidecar, fail-closed resolution
# --------------------------------------------------------------------------


def _cli_chain(tmp_path: Path):
    """Run a real calibrate -> workspace freeze and return the CLI inputs."""

    base_bytes = BASE_PROFILE_PATH.read_bytes()
    base_sha = hashlib.sha256(base_bytes).hexdigest()
    search_space = CalibrationSearchSpace(
        space_id="r2-cli-space",
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
            observation_id=f"r2-cli-observation-{index}",
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
    workspace_root = tmp_path / "calibration-workspace"

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
                "--workspace",
                str(workspace_root),
            ]
        )
        == 0
    )
    experiment = CalibrationExperiment.model_validate(
        json.loads(experiment_path.read_text(encoding="utf-8"))
    )
    compiled_manifest = compile_backtest_manifest(
        HistoricalDatasetManifest.model_validate(
            json.loads(
                (HISTORICAL_FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8")
            )
        ),
        HistoricalArtifactStore(HISTORICAL_FIXTURE_ROOT / "store"),
    )
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
    return {
        "manifest": manifest_path,
        "experiment": experiment_path,
        "holdout": holdout_path,
        "observations": observations_path,
        "evidence_binding": binding_path,
        "calibration_workspace": workspace_root,
        "experiment_model": experiment,
    }


def _evaluate_arguments(paths: dict, anchor: str, output: Path | None = None):
    anchor_key = anchor.removeprefix("--").replace("-", "_")
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
        str(BASE_PROFILE_PATH),
        anchor,
        str(paths[anchor_key]),
    ]
    if output is not None:
        arguments.extend(["--output", str(output)])
    return arguments


def test_cli_workspace_chain_reaches_ready(tmp_path, capsys):
    paths = _cli_chain(tmp_path)
    capsys.readouterr()  # discard the calibrate output before asserting on evaluate
    output = tmp_path / "evaluation.json"

    exit_code = main(_evaluate_arguments(paths, "--calibration-workspace", output))

    assert exit_code == 0
    evaluation = ControlledEvolutionEvaluationV1.model_validate(
        json.loads(capsys.readouterr().out)
    )
    assert evaluation.admission_state == "READY_FOR_HUMAN_REVIEW"
    workspace = BacktestWorkspace(paths["calibration_workspace"])
    record = workspace.load_calibration_freeze_record(
        paths["experiment_model"].experiment_id
    )
    assert evaluation.freeze_anchor_id == record.freeze_id


def test_cli_sidecar_only_binding_is_blocked_never_ready(tmp_path, capsys):
    paths = _cli_chain(tmp_path)
    capsys.readouterr()  # discard the calibrate output before asserting on evaluate
    output = tmp_path / "evaluation-sidecar.json"

    exit_code = main(_evaluate_arguments(paths, "--evidence-binding", output))

    assert exit_code == 1
    evaluation = ControlledEvolutionEvaluationV1.model_validate(
        json.loads(capsys.readouterr().out)
    )
    assert evaluation.admission_state == "BLOCKED"
    assert CHECK_FREEZE_ANCHOR_PRESENT in _blocked_names(evaluation)


def test_cli_fails_closed_when_workspace_anchor_is_missing(tmp_path, capsys):
    paths = _cli_chain(tmp_path)
    # A workspace without any committed freeze for this experiment.
    empty_workspace = tmp_path / "empty-workspace"
    empty_workspace.mkdir()
    paths["calibration_workspace"] = empty_workspace

    exit_code = main(_evaluate_arguments(paths, "--calibration-workspace"))

    assert exit_code == 2
    assert "no authoritative calibration freeze record" in capsys.readouterr().err


def test_cli_fails_closed_on_corrupt_workspace_anchor(tmp_path, capsys):
    paths = _cli_chain(tmp_path)
    experiment_id = paths["experiment_model"].experiment_id
    record_file = _record_path(paths["calibration_workspace"], experiment_id)
    record_file.write_text("corrupt", encoding="utf-8")

    exit_code = main(_evaluate_arguments(paths, "--calibration-workspace"))

    assert exit_code == 2
    assert "no authoritative calibration freeze record" in capsys.readouterr().err


def test_cli_fails_closed_on_substituted_manifest_with_workspace(tmp_path, capsys):
    # The R2 regression scenario through the authoritative CLI path: a
    # separately valid manifest with the same dataset_id cannot be admitted
    # because the anchored binding pins the original manifest content.
    paths = _cli_chain(tmp_path)
    capsys.readouterr()  # discard the calibrate output before asserting on evaluate
    compiled = BacktestDatasetManifest.model_validate(
        json.loads(paths["manifest"].read_text(encoding="utf-8"))
    )
    payload = compiled.model_dump(mode="json", warnings=False)
    payload["dataset_version"] = "tampered"
    payload.pop("content_sha256")
    payload["content_sha256"] = hashlib.sha256(
        canonical_json_bytes(payload)
    ).hexdigest()
    substituted = BacktestDatasetManifest.model_validate(payload)
    assert substituted.dataset_id == compiled.dataset_id
    assert substituted.content_sha256 != compiled.content_sha256
    substituted_path = paths["manifest"].with_name("substituted-manifest.json")
    substituted_path.write_text(
        json.dumps(substituted.model_dump(mode="json"), indent=2), encoding="utf-8"
    )
    paths["manifest"] = substituted_path

    exit_code = main(_evaluate_arguments(paths, "--calibration-workspace"))

    assert exit_code == 1
    persisted = ControlledEvolutionEvaluationV1.model_validate(
        json.loads(capsys.readouterr().out)
    )
    assert persisted.admission_state == "BLOCKED"
    assert "EVIDENCE_BINDING_MANIFEST_IDENTITY" in _blocked_names(persisted)


def test_cli_conflicting_calibrate_rerun_fails_closed_and_preserves_bytes(
    tmp_path, capsys
):
    paths = _cli_chain(tmp_path)
    workspace_root = paths["calibration_workspace"]
    before = _workspace_snapshot(workspace_root)

    # Same experiment identity, substituted non-scoring observation
    # provenance: the conflicting re-freeze must fail closed with every
    # pre-existing authoritative byte preserved.
    substituted_observations = tmp_path / "substituted-observations.json"
    rows = json.loads(paths["observations"].read_text(encoding="utf-8"))
    for row in rows:
        row["source_hash"] = "b" * 64
    substituted_observations.write_text(json.dumps(rows), encoding="utf-8")

    exit_code = main(
        [
            "calibrate",
            "--manifest",
            str(HISTORICAL_FIXTURE_ROOT / "manifest.json"),
            "--store",
            str(HISTORICAL_FIXTURE_ROOT / "store"),
            "--search-space",
            str(tmp_path / "search-space.json"),
            "--split",
            str(tmp_path / "split.json"),
            "--observations",
            str(substituted_observations),
            "--base-profile-sha256",
            hashlib.sha256(BASE_PROFILE_PATH.read_bytes()).hexdigest(),
            "--workspace",
            str(workspace_root),
        ]
    )

    assert exit_code == 2
    assert "conflicting" in capsys.readouterr().err
    snapshot = _workspace_snapshot(workspace_root)
    assert {
        path: data for path, data in snapshot.items() if path in before
    } == before


def test_cli_calibrate_exports_are_non_destructive(tmp_path):
    paths = _cli_chain(tmp_path)
    binding_before = paths["evidence_binding"].read_bytes()
    experiment_before = paths["experiment"].read_bytes()
    base_sha = hashlib.sha256(BASE_PROFILE_PATH.read_bytes()).hexdigest()

    # A rerun whose sidecar export would overwrite a supplied input fails.
    exit_code = main(
        [
            "calibrate",
            "--manifest",
            str(HISTORICAL_FIXTURE_ROOT / "manifest.json"),
            "--store",
            str(HISTORICAL_FIXTURE_ROOT / "store"),
            "--search-space",
            str(tmp_path / "search-space.json"),
            "--split",
            str(tmp_path / "split.json"),
            "--observations",
            str(paths["observations"]),
            "--base-profile-sha256",
            base_sha,
            "--evidence-binding-output",
            str(paths["observations"]),
        ]
    )
    assert exit_code == 2

    # A rerun whose sidecar export would collide with the primary output
    # fails before either export is written.
    exit_code = main(
        [
            "calibrate",
            "--manifest",
            str(HISTORICAL_FIXTURE_ROOT / "manifest.json"),
            "--store",
            str(HISTORICAL_FIXTURE_ROOT / "store"),
            "--search-space",
            str(tmp_path / "search-space.json"),
            "--split",
            str(tmp_path / "split.json"),
            "--observations",
            str(paths["observations"]),
            "--base-profile-sha256",
            base_sha,
            "--output",
            str(paths["evidence_binding"]),
            "--evidence-binding-output",
            str(paths["evidence_binding"]),
        ]
    )
    assert exit_code == 2
    assert paths["evidence_binding"].read_bytes() == binding_before

    # A rerun whose export would overwrite an existing DIFFERENT frozen
    # artifact fails; byte-identical content stays idempotent.
    conflicting_target = tmp_path / "occupied.json"
    conflicting_target.write_text("different frozen bytes", encoding="utf-8")
    exit_code = main(
        [
            "calibrate",
            "--manifest",
            str(HISTORICAL_FIXTURE_ROOT / "manifest.json"),
            "--store",
            str(HISTORICAL_FIXTURE_ROOT / "store"),
            "--search-space",
            str(tmp_path / "search-space.json"),
            "--split",
            str(tmp_path / "split.json"),
            "--observations",
            str(paths["observations"]),
            "--base-profile-sha256",
            base_sha,
            "--evidence-binding-output",
            str(conflicting_target),
        ]
    )
    assert exit_code == 2
    assert conflicting_target.read_text(encoding="utf-8") == "different frozen bytes"
    assert paths["experiment"].read_bytes() == experiment_before

    exit_code = main(
        [
            "calibrate",
            "--manifest",
            str(HISTORICAL_FIXTURE_ROOT / "manifest.json"),
            "--store",
            str(HISTORICAL_FIXTURE_ROOT / "store"),
            "--search-space",
            str(tmp_path / "search-space.json"),
            "--split",
            str(tmp_path / "split.json"),
            "--observations",
            str(paths["observations"]),
            "--base-profile-sha256",
            base_sha,
            "--evidence-binding-output",
            str(paths["evidence_binding"]),
        ]
    )
    assert exit_code == 0
    assert paths["evidence_binding"].read_bytes() == binding_before


def test_cli_evaluate_refuses_output_inside_calibration_workspace(tmp_path, capsys):
    paths = _cli_chain(tmp_path)
    output = paths["calibration_workspace"] / "evaluation.json"

    exit_code = main(_evaluate_arguments(paths, "--calibration-workspace", output))

    assert exit_code == 2
    assert "calibration workspace" in capsys.readouterr().err
    assert not output.exists()


def test_cli_requires_exactly_one_anchor_source(tmp_path, capsys):
    paths = _cli_chain(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        main(
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
                str(BASE_PROFILE_PATH),
            ]
        )
    assert exc_info.value.code == 2
    assert "--evidence-binding" in capsys.readouterr().err

    capsys.readouterr()
    with pytest.raises(SystemExit) as exc_info:
        main(
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
                str(BASE_PROFILE_PATH),
                "--evidence-binding",
                str(paths["evidence_binding"]),
                "--calibration-workspace",
                str(paths["calibration_workspace"]),
            ]
        )
    assert exc_info.value.code == 2
    assert "not allowed with" in capsys.readouterr().err


# --------------------------------------------------------------------------
# Offline / no-network execution and rule-profile byte identity
# --------------------------------------------------------------------------


def test_freeze_commit_resolve_and_evaluation_construct_no_network(
    tmp_path, monkeypatch, chain
):
    def no_sockets(*args, **kwargs):
        raise AssertionError("calibration freeze or evaluation constructed a socket")

    monkeypatch.setattr(socket, "socket", no_sockets)
    monkeypatch.setattr(socket, "create_connection", no_sockets)

    base, _sha, experiment, holdout, observations, binding, record = chain
    workspace = BacktestWorkspace(tmp_path)
    committed_binding, committed_record = commit_calibration_freeze(
        workspace, manifest=_manifest(), experiment=experiment, observations=observations
    )
    anchored = resolve_anchored_calibration_evidence(
        workspace, experiment_id=experiment.experiment_id
    )
    evaluation = evaluate_controlled_evolution(
        manifest=_manifest(),
        experiment=experiment,
        holdout=holdout,
        observations=observations,
        base_profile_bytes=base,
        evidence_binding=anchored.binding,
        freeze_record=anchored.freeze_record,
    )
    assert committed_binding == binding
    assert committed_record == record
    assert evaluation.admission_state == "READY_FOR_HUMAN_REVIEW"


def test_cli_calibration_freeze_and_evaluation_construct_no_network(
    tmp_path, monkeypatch
):
    def no_sockets(*args, **kwargs):
        raise AssertionError("calibration-freeze CLI path constructed a socket")

    monkeypatch.setattr(socket, "socket", no_sockets)
    monkeypatch.setattr(socket, "create_connection", no_sockets)

    paths = _cli_chain(tmp_path)
    output = tmp_path / "evaluation.json"
    assert main(_evaluate_arguments(paths, "--calibration-workspace", output)) == 0


def test_strict_v1_bytes_remain_identical(tmp_path, chain):
    # The full R2 chain never touches the rule profile: the byte identity
    # recorded through the Phase 7-A/R1 closures must hold unchanged.
    assert (
        hashlib.sha256(BASE_PROFILE_PATH.read_bytes()).hexdigest() == STRICT_V1_SHA256
    )
    base, _sha, experiment, holdout, observations, binding, record = chain
    workspace = BacktestWorkspace(tmp_path)
    commit_calibration_freeze(
        workspace, manifest=_manifest(), experiment=experiment, observations=observations
    )
    anchored = resolve_anchored_calibration_evidence(
        workspace, experiment_id=experiment.experiment_id
    )
    evaluation = evaluate_controlled_evolution(
        manifest=_manifest(),
        experiment=experiment,
        holdout=holdout,
        observations=observations,
        base_profile_bytes=base,
        evidence_binding=anchored.binding,
        freeze_record=anchored.freeze_record,
    )
    assert evaluation.base_profile_sha256 == STRICT_V1_SHA256
    assert hashlib.sha256(BASE_PROFILE_PATH.read_bytes()).hexdigest() == STRICT_V1_SHA256
