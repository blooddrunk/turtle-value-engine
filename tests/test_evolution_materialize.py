"""Phase 7-B1 materializable candidate semantics, projection and PIT replay.

Focused B1 coverage: the versioned materializable-parameter semantics frozen
inside the calibration search space BEFORE selection; legacy/unbound
``min_quality`` proposals classified NON_MATERIALIZABLE with zero candidate
output; deterministic candidate-only ``RuleProfile`` projection from the exact
base-profile bytes (exact rule diff, no hidden semantic change); the immutable
materialization record binding the re-admitted R2 evidence, parameter
semantics, diff and profile-aware frozen PIT replay; authoritative
re-admission through the calibration workspace (dossier/sidecar-only attempts
fail); replay determinism, chronological/holdout isolation and explicit
missing-input blockers; non-destructive create-only CLI outputs with refusal
under active ``rules/``; schema drift parity; socket-guarded offline
execution; and ``strict-v1`` byte identity.
"""

from __future__ import annotations

import hashlib
import json
import socket
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from turtle_value_engine import load_normalized_input
from turtle_value_engine.backtest import (
    INSTALLED_MATERIALIZATION_SEMANTICS,
    BacktestDatasetManifest,
    BacktestWorkspace,
    CalibrationObservation,
    CalibrationRunner,
    CalibrationSearchSpace,
    ChronologicalSplit,
    HistoricalDecisionArtifact,
    ListingLifecycle,
    Market,
    MaterializableParameterSemanticsSetV1,
    MaterializableParameterSemanticsV1,
    MaterializationSemanticsError,
    MaterializationSemanticsReferenceV1,
    RegisteredRuleTargetV1,
    UniverseCoverage,
    commit_calibration_freeze,
    resolve_anchored_calibration_evidence,
    resolve_materialization_semantics,
)
from turtle_value_engine.backtest.calibration import _default_scorer
from turtle_value_engine.cli import main
from turtle_value_engine.evolution import (
    REASON_NO_FROZEN_MATERIALIZATION_SEMANTICS,
    CandidateMaterializationError,
    CandidateProfileMaterializationV1,
    CandidateProfileReplayV1,
    CandidateProjectionError,
    CandidateReplayError,
    classify_proposal_materializability,
    evaluate_controlled_evolution,
    materialize_candidate_profile,
    project_candidate_profile,
    replay_candidate_profile,
)

ROOT = Path(__file__).parents[1]
BASE_PROFILE_PATH = ROOT / "rules" / "strict-v1.yaml"
STRICT_V1_SHA256 = "e3618f78b2f8e4d1e8e81ce3065da977685ad5256bd0ab3332b3a8054e0b6333"
SOURCE_HASH = "a" * 64
UTC = UTC
INSTALLED = INSTALLED_MATERIALIZATION_SEMANTICS[0]


def _base_bytes() -> bytes:
    return BASE_PROFILE_PATH.read_bytes()


def _normalized_input():
    return load_normalized_input(ROOT / "fixtures" / "healthy_cash_cow.json")


def _artifacts(with_inputs: bool = True) -> list[HistoricalDecisionArtifact]:
    normalized = _normalized_input()
    artifacts = []
    for index, day in enumerate(range(8, 16), start=1):
        payload = dict(
            artifact_id=f"art-{index}",
            listing_id="SH600001",
            decision_time=datetime(2026, 9, day, 15, tzinfo=UTC),
            as_of=date(2026, 9, 8),
            available_at=datetime(2026, 9, day, 15, tzinfo=UTC),
            source_hash=SOURCE_HASH,
        )
        if with_inputs:
            payload["normalized_input"] = normalized.model_dump(mode="python")
        else:
            payload["analysis"] = None
        artifacts.append(HistoricalDecisionArtifact.model_validate(payload))
    return artifacts


def _lifecycle() -> ListingLifecycle:
    return ListingLifecycle(
        listing_id="SH600001",
        company_id="economic-company-1",
        economic_company_id="economic-company-1",
        market=Market.A,
        currency="CNY",
        listing_date=date(2026, 9, 1),
        terminal_status="ACTIVE",
        trading_calendar="frozen-mini-ah-v1",
        timezone="Asia/Shanghai",
        sector="consumer",
    )


def _manifest(with_artifacts: bool = True) -> BacktestDatasetManifest:
    return BacktestDatasetManifest.build(
        dataset_id="frozen-ah-mini-v1",
        dataset_version="1",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
        calendar_id="frozen-mini-ah-v1",
        universe_id="frozen-ah",
        universe_coverage=UniverseCoverage.FIXED_RESEARCH_UNIVERSE,
        listing_lifecycles=[_lifecycle()],
        decision_artifacts=_artifacts(with_artifacts) if with_artifacts else [],
    )


def _observations(with_sources: bool = True) -> list[CalibrationObservation]:
    rows = []
    for index in range(8):
        rows.append(
            CalibrationObservation(
                observation_id=f"cal-{index}",
                observed_at=date(2026, 9, 8 + index),
                target_return=0.5 if index % 2 == 0 else -0.3,
                feature_values={
                    "cdc_yield": 0.16 if index % 2 == 0 else 0.05,
                },
                source_observation_id=f"art-{index + 1}" if with_sources else None,
                source_hash=SOURCE_HASH,
            )
        )
    return rows


def _split() -> ChronologicalSplit:
    return ChronologicalSplit(
        train_start=date(2026, 9, 8),
        train_end=date(2026, 9, 11),
        validation_start=date(2026, 9, 12),
        validation_end=date(2026, 9, 13),
        holdout_start=date(2026, 9, 14),
        holdout_end=date(2026, 9, 15),
    )


def _b1_search_space(values: list[float] | None = None) -> CalibrationSearchSpace:
    return CalibrationSearchSpace(
        space_id="b1-cdc-thresholds-v1",
        base_profile_id="strict-v1",
        parameters={"min_cdc_yield": values or [0.02, 0.14]},
        objective="MEAN_RETURN",
        materialization_semantics=INSTALLED.reference(),
    )


class _Chain:
    """One honestly frozen materializable calibration chain."""

    def __init__(self, root: Path, *, values: list[float] | None = None) -> None:
        self.root = root
        base_bytes = _base_bytes()
        base_sha256 = hashlib.sha256(base_bytes).hexdigest()
        self.base_bytes = base_bytes
        self.base_sha256 = base_sha256
        self.manifest = _manifest()
        self.observations = _observations()
        search_space = _b1_search_space(values)
        runner = CalibrationRunner(
            manifest_id=self.manifest.dataset_id,
            base_profile_id="strict-v1",
            base_profile_sha256=base_sha256,
            search_space=search_space,
            split=_split(),
        )
        self.experiment = runner.run(self.observations)
        self.holdout = runner.evaluate_holdout(self.experiment, self.observations)
        self.workspace = BacktestWorkspace(root / "workspace")
        commit_calibration_freeze(
            self.workspace,
            manifest=self.manifest,
            experiment=self.experiment,
            observations=self.observations,
        )
        self.anchored = resolve_anchored_calibration_evidence(
            self.workspace, experiment_id=self.experiment.experiment_id
        )
        self.evaluation = evaluate_controlled_evolution(
            manifest=self.manifest,
            experiment=self.experiment,
            holdout=self.holdout,
            observations=self.observations,
            base_profile_bytes=base_bytes,
            evidence_binding=self.anchored.binding,
            freeze_record=self.anchored.freeze_record,
        )

    def materialize(self) -> object:
        return materialize_candidate_profile(
            manifest=self.manifest,
            experiment=self.experiment,
            holdout=self.holdout,
            observations=self.observations,
            base_profile_bytes=self.base_bytes,
            evaluation=self.evaluation,
            freeze_record=self.anchored.freeze_record,
            evidence_binding=self.anchored.binding,
        )

    def dump_inputs(self, directory: Path) -> dict[str, Path]:
        directory.mkdir(parents=True, exist_ok=True)

        def dump(name: str, model) -> Path:
            path = directory / name
            path.write_text(
                json.dumps(model.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
            )
            return path

        paths = {
            "manifest": dump("manifest.json", self.manifest),
            "experiment": dump("experiment.json", self.experiment),
            "holdout": dump("holdout.json", self.holdout),
        }
        paths["observations"] = directory / "observations.json"
        paths["observations"].write_text(
            json.dumps(
                [item.model_dump(mode="json") for item in self.observations],
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        return paths


@pytest.fixture(scope="module")
def chain(tmp_path_factory) -> _Chain:
    return _Chain(tmp_path_factory.mktemp("b1-chain"))


@pytest.fixture(scope="module")
def legacy_chain(tmp_path_factory):
    """The R2-era ``min_quality`` chain: evaluable history, no semantics."""

    root = tmp_path_factory.mktemp("b1-legacy")
    base_bytes = _base_bytes()
    base_sha256 = hashlib.sha256(base_bytes).hexdigest()
    observations = [
        CalibrationObservation(
            observation_id=f"cal-{index}",
            observed_at=date(2020, 1, index + 1),
            target_return=float(index - 2),
            feature_values={"quality": float(index)},
            source_hash=SOURCE_HASH,
        )
        for index in range(1, 9)
    ]
    split = ChronologicalSplit(
        train_start=date(2020, 1, 2),
        train_end=date(2020, 1, 4),
        validation_start=date(2020, 1, 5),
        validation_end=date(2020, 1, 6),
        holdout_start=date(2020, 1, 7),
        holdout_end=date(2020, 1, 9),
    )
    search_space = CalibrationSearchSpace(
        space_id="quality-thresholds-v1",
        base_profile_id="strict-v1",
        parameters={"min_quality": [0.0, 4.0]},
        objective="MEAN_RETURN",
    )
    runner = CalibrationRunner(
        manifest_id="frozen-ah-mini-v1",
        base_profile_id="strict-v1",
        base_profile_sha256=base_sha256,
        search_space=search_space,
        split=split,
    )
    experiment = runner.run(observations)
    holdout = runner.evaluate_holdout(experiment, observations)
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
    manifest = BacktestDatasetManifest.build(
        dataset_id="frozen-ah-mini-v1",
        dataset_version="1",
        start_date=date(2020, 1, 1),
        end_date=date(2020, 2, 1),
        calendar_id="frozen-mini-ah-v1",
        universe_id="frozen-ah",
        universe_coverage=UniverseCoverage.FIXED_RESEARCH_UNIVERSE,
        listing_lifecycles=[lifecycle],
    )
    workspace = BacktestWorkspace(root / "workspace")
    commit_calibration_freeze(
        workspace, manifest=manifest, experiment=experiment, observations=observations
    )
    anchored = resolve_anchored_calibration_evidence(
        workspace, experiment_id=experiment.experiment_id
    )
    evaluation = evaluate_controlled_evolution(
        manifest=manifest,
        experiment=experiment,
        holdout=holdout,
        observations=observations,
        base_profile_bytes=base_bytes,
        evidence_binding=anchored.binding,
        freeze_record=anchored.freeze_record,
    )
    return {
        "root": root,
        "base_bytes": base_bytes,
        "manifest": manifest,
        "experiment": experiment,
        "holdout": holdout,
        "observations": observations,
        "evaluation": evaluation,
    }


def _deep_diff(before: dict, after: dict, prefix: str = "") -> list[str]:
    changed: list[str] = []
    for key in sorted(set(before) | set(after)):
        left, right = before.get(key), after.get(key)
        if isinstance(left, dict) and isinstance(right, dict):
            changed.extend(_deep_diff(left, right, f"{prefix}{key}."))
        elif left != right:
            changed.append(f"{prefix}{key}")
    return changed


def _run_cli(argv: list[str]) -> tuple[int, object, str]:
    import contextlib
    import io

    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(argv)
    payload = None
    text = stdout.getvalue().strip() or stderr.getvalue().strip()
    if stdout.getvalue().strip():
        try:
            payload = json.loads(stdout.getvalue().strip())
        except json.JSONDecodeError:
            payload = None
    return code, payload, text


# --------------------------------------------------------------------------
# Baseline structural evidence (goal §9.1) — ongoing guards, not fabricated
# missing-symbol regressions
# --------------------------------------------------------------------------


def test_baseline_default_scorer_does_not_interpret_strict_v1():
    assert "without interpreting strict-v1" in (_default_scorer.__doc__ or "")


def test_baseline_builtin_parameter_behavior_is_generic_feature_filters_only():
    # A prefix-less parameter name is ignored by the generic filter: the
    # built-in scorer defines behavior only for min_/max_/equals_ prefixes.
    observations = _observations()
    untouched = _default_scorer({"unrelated_name": 1.0}, tuple(observations))
    everything = _default_scorer({}, tuple(observations))
    assert untouched == everything


def test_baseline_min_quality_is_not_a_rule_profile_field():
    profile_text = BASE_PROFILE_PATH.read_text(encoding="utf-8")
    assert "min_quality" not in profile_text


# --------------------------------------------------------------------------
# 1. Legacy min_quality proposal is explicitly non-materializable
# --------------------------------------------------------------------------


def test_legacy_min_quality_proposal_is_non_materializable(legacy_chain):
    with pytest.raises(CandidateMaterializationError) as raised:
        classify_proposal_materializability(experiment=legacy_chain["experiment"])
    assert raised.value.classification == "NON_MATERIALIZABLE"
    assert raised.value.reason_code == REASON_NO_FROZEN_MATERIALIZATION_SEMANTICS


def test_legacy_chain_still_evaluates_ready_but_materializes_nothing(
    legacy_chain, tmp_path
):
    # Legacy R2 history remains evaluable: the honest chain is READY.
    assert legacy_chain["evaluation"].admission_state == "READY_FOR_HUMAN_REVIEW"
    with pytest.raises(CandidateMaterializationError):
        materialize_candidate_profile(
            manifest=legacy_chain["manifest"],
            experiment=legacy_chain["experiment"],
            holdout=legacy_chain["holdout"],
            observations=legacy_chain["observations"],
            base_profile_bytes=legacy_chain["base_bytes"],
            evaluation=legacy_chain["evaluation"],
            freeze_record=(
                resolve_anchored_calibration_evidence(
                    BacktestWorkspace(legacy_chain["root"] / "workspace"),
                    experiment_id=legacy_chain["experiment"].experiment_id,
                ).freeze_record
            ),
            evidence_binding=(
                resolve_anchored_calibration_evidence(
                    BacktestWorkspace(legacy_chain["root"] / "workspace"),
                    experiment_id=legacy_chain["experiment"].experiment_id,
                ).binding
            ),
        )

    root = legacy_chain["root"]
    inputs = {
        "manifest": root / "manifest.json",
        "experiment": root / "experiment.json",
        "holdout": root / "holdout.json",
        "observations": root / "observations.json",
    }
    for name, model in (
        ("manifest", legacy_chain["manifest"]),
        ("experiment", legacy_chain["experiment"]),
        ("holdout", legacy_chain["holdout"]),
    ):
        inputs[name].write_text(
            json.dumps(model.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        )
    inputs["observations"].write_text(
        json.dumps(
            [item.model_dump(mode="json") for item in legacy_chain["observations"]],
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    candidate_output = tmp_path / "candidate.yaml"
    code, payload, _text = _run_cli(
        [
            "evolution",
            "materialize-candidate",
            "--calibration-workspace",
            str(root / "workspace"),
            "--manifest",
            str(inputs["manifest"]),
            "--experiment",
            str(inputs["experiment"]),
            "--holdout",
            str(inputs["holdout"]),
            "--observations",
            str(inputs["observations"]),
            "--base-profile",
            str(BASE_PROFILE_PATH),
            "--candidate-output",
            str(candidate_output),
            "--materialization-output",
            str(tmp_path / "materialization.json"),
        ]
    )
    assert code == 1
    assert payload["classification"] == "NON_MATERIALIZABLE"
    assert payload["reason_code"] == REASON_NO_FROZEN_MATERIALIZATION_SEMANTICS
    assert not candidate_output.exists()
    assert not (tmp_path / "materialization.json").exists()


# --------------------------------------------------------------------------
# 2. One real registered scalar end-to-end
# --------------------------------------------------------------------------


def test_registered_scalar_end_to_end_chain(chain):
    assert chain.evaluation.admission_state == "READY_FOR_HUMAN_REVIEW"
    assert chain.experiment.proposal.parameter_overrides == {"min_cdc_yield": 0.14}
    outcome = chain.materialize()
    projected = outcome.projected

    assert projected.profile.profile.id == chain.experiment.proposal.candidate_profile_id
    assert projected.profile.cdc.yield_bands.pass_ == 0.14
    assert [(c.profile_path, c.before, c.after) for c in projected.rule_changes] == [
        ("cdc.yield_bands.pass", 0.08, 0.14)
    ]

    replay = outcome.replay
    assert replay.replay_scope == "SEARCH_STAGE_TRAIN_VALIDATION"
    assert replay.replayed_observation_count == 6
    assert replay.changed_row_count == 6
    holdout_ids = {"cal-6", "cal-7"}
    assert not holdout_ids.intersection(row.observation_id for row in replay.rows)

    record = outcome.record
    assert record.requires_human_approval is True
    assert record.automatic_application_allowed is False
    assert record.semantics_id == INSTALLED.semantics_id
    assert record.candidate_profile_id == projected.profile.profile.id
    assert record.candidate_content_sha256 == projected.candidate_content_sha256


def test_candidate_diff_contains_exactly_registered_leaves_plus_metadata(chain):
    outcome = chain.materialize()
    before = yaml.safe_load(chain.base_bytes)
    after = yaml.safe_load(outcome.projected.candidate_bytes)
    assert _deep_diff(before, after) == [
        "cdc.yield_bands.pass",
        "profile.description",
        "profile.id",
        "profile.name",
        "profile.status",
    ]
    metadata_fields = {change.field for change in outcome.projected.metadata_changes}
    assert metadata_fields == {"id", "name", "status", "description"}


# --------------------------------------------------------------------------
# 3. Semantics frozen before selection
# --------------------------------------------------------------------------


def test_semantics_reference_is_part_of_the_experiment_identity():
    with_ref = _b1_search_space()
    without_ref = with_ref.model_copy(update={"materialization_semantics": None})
    experiment_ids = []
    runner_inputs = dict(
        manifest_id="frozen-ah-mini-v1",
        base_profile_id="strict-v1",
        base_profile_sha256=hashlib.sha256(_base_bytes()).hexdigest(),
        split=_split(),
    )
    for space in (with_ref, without_ref):
        experiment = CalibrationRunner(search_space=space, **runner_inputs).run(
            _observations()
        )
        experiment_ids.append(experiment.experiment_id)
    assert experiment_ids[0] != experiment_ids[1]


def test_mutated_registry_changes_identity_and_breaks_old_references():
    original = INSTALLED
    parameter = original.parameters["min_cdc_yield"]
    drifted = MaterializableParameterSemanticsSetV1.build(
        semantics_version=original.semantics_version,
        parameters={
            **original.parameters,
            "min_cdc_yield": MaterializableParameterSemanticsV1(
                parameter_key="min_cdc_yield",
                operator=parameter.operator,
                observation_feature=parameter.observation_feature,
                target=RegisteredRuleTargetV1(
                    target_key="some-other-target",
                    profile_path="cdc.yield_bands.watch",
                    leaf_type="FLOAT",
                ),
            ),
        },
    )
    assert drifted.semantics_id != original.semantics_id
    assert drifted.content_sha256 != original.content_sha256
    with pytest.raises(MaterializationSemanticsError):
        # The drifted set is not installed, so its reference cannot resolve
        # against the installed registry.
        resolve_materialization_semantics(drifted.reference())


def test_runner_rejects_unregistered_parameter_in_semantics_space():
    space = CalibrationSearchSpace(
        space_id="mixed",
        base_profile_id="strict-v1",
        parameters={"min_quality": [4.0]},
        materialization_semantics=INSTALLED.reference(),
    )
    with pytest.raises(MaterializationSemanticsError, match="not registered"):
        CalibrationRunner(
            manifest_id="frozen-ah-mini-v1",
            base_profile_id="strict-v1",
            base_profile_sha256=hashlib.sha256(_base_bytes()).hexdigest(),
            search_space=space,
            split=_split(),
        )


def test_runner_rejects_out_of_contract_search_values():
    for parameters in (
        {"min_cdc_yield": [0.0, 0.14]},  # violates exclusive minimum 0
        {"min_business_quality_score": [28.5]},  # INT target, float value
    ):
        space = CalibrationSearchSpace(
            space_id="ooc",
            base_profile_id="strict-v1",
            parameters=parameters,
            materialization_semantics=INSTALLED.reference(),
        )
        with pytest.raises(MaterializationSemanticsError):
            CalibrationRunner(
                manifest_id="frozen-ah-mini-v1",
                base_profile_id="strict-v1",
                base_profile_sha256=hashlib.sha256(_base_bytes()).hexdigest(),
                search_space=space,
                split=_split(),
            )


def test_post_hoc_registry_drift_blocks_re_admission_and_materialization(
    chain, monkeypatch, tmp_path
):
    import turtle_value_engine.backtest.materialization_semantics as semantics_module

    drifted = MaterializableParameterSemanticsSetV1.build(
        semantics_version=INSTALLED.semantics_version + "-drifted",
        parameters=INSTALLED.parameters,
    )
    monkeypatch.setattr(
        semantics_module,
        "INSTALLED_MATERIALIZATION_SEMANTICS",
        (drifted,),
    )
    inputs = chain.dump_inputs(tmp_path / "inputs")
    candidate_output = tmp_path / "candidate.yaml"
    code, payload, _text = _run_cli(
        [
            "evolution",
            "materialize-candidate",
            "--calibration-workspace",
            str(chain.root / "workspace"),
            "--manifest",
            str(inputs["manifest"]),
            "--experiment",
            str(inputs["experiment"]),
            "--holdout",
            str(inputs["holdout"]),
            "--observations",
            str(inputs["observations"]),
            "--base-profile",
            str(BASE_PROFILE_PATH),
            "--candidate-output",
            str(candidate_output),
            "--materialization-output",
            str(tmp_path / "materialization.json"),
        ]
    )
    assert code == 1
    assert payload["classification"] == "MATERIALIZATION_BLOCKED"
    assert "CANONICAL_REPRODUCTION" in payload["blocked_checks"]
    assert not candidate_output.exists()


def test_unresolvable_reference_classifies_non_materializable(chain):
    tampered = MaterializationSemanticsReferenceV1(
        semantics_id=INSTALLED.semantics_id,
        semantics_version=INSTALLED.semantics_version,
        content_sha256="b" * 64,
    )
    experiment = chain.experiment.model_copy(
        update={
            "search_space": chain.experiment.search_space.model_copy(
                update={"materialization_semantics": tampered}
            )
        }
    )
    with pytest.raises(CandidateMaterializationError) as raised:
        classify_proposal_materializability(experiment=experiment)
    assert raised.value.reason_code == "SEMANTICS_REFERENCE_UNRESOLVED"


# --------------------------------------------------------------------------
# 4./5. Projection fail-closed boundaries
# --------------------------------------------------------------------------


def _hand_proposal(base_sha256: str, overrides: dict):
    from turtle_value_engine.backtest.contracts import CandidateProfileProposal

    return CandidateProfileProposal(
        proposal_id="candidate-profile-proposal-fixed",
        base_profile_id="strict-v1",
        base_profile_sha256=base_sha256,
        candidate_profile_id="candidate-profile-fixed",
        parameter_overrides=overrides,
        rationale="focused B1 projection fixture",
    )


def test_projection_rejects_wrong_base_profile_hash():
    proposal = _hand_proposal("c" * 64, {"min_cdc_yield": 0.14})
    with pytest.raises(CandidateProjectionError, match="hash to"):
        project_candidate_profile(
            base_profile_bytes=_base_bytes(),
            proposal=proposal,
            semantics=INSTALLED,
        )


def test_projection_rejects_wrong_base_profile_identity():
    # Valid RuleProfile bytes whose declared id is not the proposal's base.
    payload = yaml.safe_load(_base_bytes())
    payload["profile"]["id"] = "other-profile"
    other_bytes = yaml.safe_dump(payload).encode("utf-8")
    proposal = _hand_proposal(hashlib.sha256(other_bytes).hexdigest(), {"min_cdc_yield": 0.14})
    with pytest.raises(CandidateProjectionError, match="base profile id disagrees"):
        project_candidate_profile(
            base_profile_bytes=other_bytes,
            proposal=proposal,
            semantics=INSTALLED,
        )


def test_projection_rejects_unknown_parameter_and_bad_values():
    base_sha256 = hashlib.sha256(_base_bytes()).hexdigest()
    for overrides, pattern in (
        ({"min_quality": 4.0}, "not registered"),
        ({"min_cdc_yield": True}, "numeric candidate"),
        ({"min_cdc_yield": 0.0}, "must be above"),
        ({"min_business_quality_score": 28.5}, "integer candidate"),
        ({"min_business_quality_score": 99}, "at or below"),
    ):
        with pytest.raises((CandidateProjectionError, MaterializationSemanticsError)):
            project_candidate_profile(
                base_profile_bytes=_base_bytes(),
                proposal=_hand_proposal(base_sha256, overrides),
                semantics=INSTALLED,
            )


def test_projection_rejects_structural_and_unregistered_target_paths():
    structural = MaterializableParameterSemanticsSetV1.build(
        semantics_version="structural-test",
        parameters={
            "min_special_models": MaterializableParameterSemanticsV1(
                parameter_key="min_special_models",
                operator="MIN_FEATURE_THRESHOLD",
                observation_feature="special_models",
                target=RegisteredRuleTargetV1(
                    target_key="universe-special-models",
                    profile_path="universe.special_models",
                    leaf_type="FLOAT",
                ),
            )
        },
    )
    base_sha256 = hashlib.sha256(_base_bytes()).hexdigest()
    with pytest.raises(CandidateProjectionError, match="structural"):
        project_candidate_profile(
            base_profile_bytes=_base_bytes(),
            proposal=_hand_proposal(base_sha256, {"min_special_models": 1.0}),
            semantics=structural,
        )

    absent = MaterializableParameterSemanticsSetV1.build(
        semantics_version="absent-test",
        parameters={
            "min_missing": MaterializableParameterSemanticsV1(
                parameter_key="min_missing",
                operator="MIN_FEATURE_THRESHOLD",
                observation_feature="missing",
                target=RegisteredRuleTargetV1(
                    target_key="no-such-leaf",
                    profile_path="cdc.yield_bands.nonexistent",
                    leaf_type="FLOAT",
                ),
            )
        },
    )
    with pytest.raises(CandidateProjectionError, match="absent from the base profile"):
        project_candidate_profile(
            base_profile_bytes=_base_bytes(),
            proposal=_hand_proposal(base_sha256, {"min_missing": 1.0}),
            semantics=absent,
        )


def test_projection_rejects_type_mismatched_override_values():
    base_sha256 = hashlib.sha256(_base_bytes()).hexdigest()
    with pytest.raises((CandidateProjectionError, MaterializationSemanticsError)):
        project_candidate_profile(
            base_profile_bytes=_base_bytes(),
            proposal=_hand_proposal(base_sha256, {"min_cdc_yield": "high"}),
            semantics=INSTALLED,
        )


# --------------------------------------------------------------------------
# 6./7./8. Determinism and byte identity
# --------------------------------------------------------------------------


def test_repeated_materialization_is_byte_identical(chain):
    first = chain.materialize()
    second = chain.materialize()
    assert first.projected.candidate_bytes == second.projected.candidate_bytes
    assert first.record.materialization_id == second.record.materialization_id
    assert first.record.content_sha256 == second.record.content_sha256


def test_replay_is_deterministic_and_search_stage_only(chain):
    outcome = chain.materialize()
    again = replay_candidate_profile(
        manifest=chain.manifest,
        observations=chain.observations,
        split=chain.experiment.split,
        base_profile=outcome.projected.base_profile,
        candidate_profile=outcome.projected.profile,
        base_profile_sha256=chain.base_sha256,
        candidate_profile_sha256=outcome.projected.candidate_content_sha256,
    )
    assert again == outcome.replay
    train_validation_ids = {f"cal-{index}" for index in range(6)}
    assert {row.observation_id for row in again.rows} == train_validation_ids


def test_replay_proves_engine_semantic_change_not_feature_filtering(chain):
    outcome = chain.materialize()
    assert outcome.replay.changed_row_count == outcome.replay.replayed_observation_count
    for row in outcome.replay.rows:
        assert row.baseline_analysis_sha256 != row.candidate_analysis_sha256
        # Generic feature filtering never executes the engine; these digests
        # are full deterministic engine analyses under the two profiles.
        assert row.baseline_decision_state == "SPECIAL_REVIEW"


# --------------------------------------------------------------------------
# 9./10./11. Authority boundaries
# --------------------------------------------------------------------------


def test_dossier_only_authorization_fails_without_anchor_binding(tmp_path):
    # A READY evaluation from a foreign anchored chain is not authority for
    # this chain's anchored evidence.
    chain = _Chain(tmp_path / "honest")
    foreign = _Chain(tmp_path / "foreign", values=[0.02, 0.12])
    assert foreign.experiment.experiment_id != chain.experiment.experiment_id
    assert foreign.evaluation.admission_state == "READY_FOR_HUMAN_REVIEW"
    with pytest.raises(CandidateMaterializationError) as raised:
        materialize_candidate_profile(
            manifest=chain.manifest,
            experiment=chain.experiment,
            holdout=chain.holdout,
            observations=chain.observations,
            base_profile_bytes=chain.base_bytes,
            evaluation=foreign.evaluation,
            freeze_record=chain.anchored.freeze_record,
            evidence_binding=chain.anchored.binding,
        )
    assert raised.value.reason_code == "ANCHORED_IDENTITY_MISMATCH"


def test_blocked_admission_never_materializes(tmp_path):
    chain = _Chain(tmp_path)
    # Same dataset_id, different valid content: re-admission fails closed on
    # the R2 binding checks before any candidate output exists.
    substituted = BacktestDatasetManifest.build(
        dataset_id=chain.manifest.dataset_id,
        dataset_version="2",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
        calendar_id="frozen-mini-ah-v1",
        universe_id="frozen-ah",
        universe_coverage=UniverseCoverage.FIXED_RESEARCH_UNIVERSE,
        listing_lifecycles=[_lifecycle()],
        decision_artifacts=_artifacts(),
    )
    assert substituted.content_sha256 != chain.manifest.content_sha256
    evaluation = evaluate_controlled_evolution(
        manifest=substituted,
        experiment=chain.experiment,
        holdout=chain.holdout,
        observations=chain.observations,
        base_profile_bytes=chain.base_bytes,
        evidence_binding=chain.anchored.binding,
        freeze_record=chain.anchored.freeze_record,
    )
    assert evaluation.admission_state == "BLOCKED"
    with pytest.raises(CandidateMaterializationError) as raised:
        materialize_candidate_profile(
            manifest=substituted,
            experiment=chain.experiment,
            holdout=chain.holdout,
            observations=chain.observations,
            base_profile_bytes=chain.base_bytes,
            evaluation=evaluation,
            freeze_record=chain.anchored.freeze_record,
            evidence_binding=chain.anchored.binding,
        )
    assert raised.value.reason_code == "ADMISSION_NOT_READY"


def test_materialize_cli_requires_authoritative_workspace_argument(tmp_path, chain):
    inputs = chain.dump_inputs(tmp_path / "inputs")
    import contextlib
    import io

    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr), pytest.raises(SystemExit) as raised:
        main(
            [
                "evolution",
                "materialize-candidate",
                "--manifest",
                str(inputs["manifest"]),
                "--experiment",
                str(inputs["experiment"]),
                "--holdout",
                str(inputs["holdout"]),
                "--observations",
                str(inputs["observations"]),
                "--base-profile",
                str(BASE_PROFILE_PATH),
                "--candidate-output",
                str(tmp_path / "candidate.yaml"),
                "--materialization-output",
                str(tmp_path / "materialization.json"),
            ]
        )
    assert raised.value.code == 2  # argparse: --calibration-workspace is required


def test_corrupt_workspace_fails_closed_before_candidate_output(tmp_path, chain):
    root = tmp_path / "ws"
    root.mkdir()
    record_path = chain.root / "workspace" / "calibration-freeze-records" / (
        chain.experiment.experiment_id + ".json"
    )
    (root / "calibration-freeze-records").mkdir(parents=True)
    (root / "calibration-freeze-records" / record_path.name).write_text("{corrupt")
    inputs = chain.dump_inputs(tmp_path / "inputs")
    code, _payload, text = _run_cli(
        [
            "evolution",
            "materialize-candidate",
            "--calibration-workspace",
            str(root),
            "--manifest",
            str(inputs["manifest"]),
            "--experiment",
            str(inputs["experiment"]),
            "--holdout",
            str(inputs["holdout"]),
            "--observations",
            str(inputs["observations"]),
            "--base-profile",
            str(BASE_PROFILE_PATH),
            "--candidate-output",
            str(tmp_path / "candidate.yaml"),
            "--materialization-output",
            str(tmp_path / "materialization.json"),
        ]
    )
    assert code == 2
    assert not (tmp_path / "candidate.yaml").exists()


# --------------------------------------------------------------------------
# 12. Missing frozen replay inputs are an explicit blocker
# --------------------------------------------------------------------------


class _NoReplayChain(_Chain):
    """Honest chain whose manifest froze no replayable decision artifacts."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.base_bytes = _base_bytes()
        self.base_sha256 = hashlib.sha256(self.base_bytes).hexdigest()
        self.manifest = _manifest(with_artifacts=False)
        self.observations = _observations()
        runner = CalibrationRunner(
            manifest_id=self.manifest.dataset_id,
            base_profile_id="strict-v1",
            base_profile_sha256=self.base_sha256,
            search_space=_b1_search_space(),
            split=_split(),
        )
        self.experiment = runner.run(self.observations)
        self.holdout = runner.evaluate_holdout(self.experiment, self.observations)
        self.workspace = BacktestWorkspace(root / "workspace")
        commit_calibration_freeze(
            self.workspace,
            manifest=self.manifest,
            experiment=self.experiment,
            observations=self.observations,
        )
        self.anchored = resolve_anchored_calibration_evidence(
            self.workspace, experiment_id=self.experiment.experiment_id
        )
        self.evaluation = evaluate_controlled_evolution(
            manifest=self.manifest,
            experiment=self.experiment,
            holdout=self.holdout,
            observations=self.observations,
            base_profile_bytes=self.base_bytes,
            evidence_binding=self.anchored.binding,
            freeze_record=self.anchored.freeze_record,
        )
        assert self.evaluation.admission_state == "READY_FOR_HUMAN_REVIEW"


def test_missing_frozen_replay_input_is_explicit_blocker(tmp_path):
    chain = _NoReplayChain(tmp_path)
    with pytest.raises(CandidateReplayError, match="MISSING_FROZEN_NORMALIZED_INPUT"):
        chain.materialize()
    inputs = chain.dump_inputs(tmp_path / "inputs")
    candidate_output = tmp_path / "candidate.yaml"
    code, payload, _text = _run_cli(
        [
            "evolution",
            "materialize-candidate",
            "--calibration-workspace",
            str(chain.root / "workspace"),
            "--manifest",
            str(inputs["manifest"]),
            "--experiment",
            str(inputs["experiment"]),
            "--holdout",
            str(inputs["holdout"]),
            "--observations",
            str(inputs["observations"]),
            "--base-profile",
            str(BASE_PROFILE_PATH),
            "--candidate-output",
            str(candidate_output),
            "--materialization-output",
            str(tmp_path / "materialization.json"),
        ]
    )
    assert code == 1
    assert payload["classification"] == "MATERIALIZATION_BLOCKED"
    assert "MISSING_FROZEN_NORMALIZED_INPUT" in payload["message"]
    assert not candidate_output.exists()


def test_replay_rejects_future_and_provenance_mismatched_inputs(tmp_path):
    chain = _Chain(tmp_path)
    outcome = chain.materialize()
    # cal-0 (2026-09-08, train scope) references a later-frozen artifact.
    future = [
        item.model_copy(update={"source_observation_id": "art-8"})
        if index == 0
        else item
        for index, item in enumerate(chain.observations)
    ]
    with pytest.raises(CandidateReplayError, match="FUTURE_FROZEN_INPUT"):
        replay_candidate_profile(
            manifest=chain.manifest,
            observations=future,
            split=chain.experiment.split,
            base_profile=outcome.projected.base_profile,
            candidate_profile=outcome.projected.profile,
            base_profile_sha256=chain.base_sha256,
            candidate_profile_sha256=outcome.projected.candidate_content_sha256,
        )
    mismatched = [
        item if index != 0 else item.model_copy(update={"source_hash": "c" * 64})
        for index, item in enumerate(chain.observations)
    ]
    with pytest.raises(CandidateReplayError, match="OBSERVATION_PROVENANCE_MISMATCH"):
        replay_candidate_profile(
            manifest=chain.manifest,
            observations=mismatched,
            split=chain.experiment.split,
            base_profile=outcome.projected.base_profile,
            candidate_profile=outcome.projected.profile,
            base_profile_sha256=chain.base_sha256,
            candidate_profile_sha256=outcome.projected.candidate_content_sha256,
        )


# --------------------------------------------------------------------------
# 13. CLI output guards
# --------------------------------------------------------------------------


def _cli_argv(chain, tmp_path, candidate: Path, materialization: Path) -> list[str]:
    inputs = chain.dump_inputs(tmp_path / "inputs")
    return [
        "evolution",
        "materialize-candidate",
        "--calibration-workspace",
        str(chain.root / "workspace"),
        "--manifest",
        str(inputs["manifest"]),
        "--experiment",
        str(inputs["experiment"]),
        "--holdout",
        str(inputs["holdout"]),
        "--observations",
        str(inputs["observations"]),
        "--base-profile",
        str(BASE_PROFILE_PATH),
        "--candidate-output",
        str(candidate),
        "--materialization-output",
        str(materialization),
    ]


def test_cli_success_idempotence_and_byte_identity(tmp_path, chain):
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    code, _payload, _text = _run_cli(
        _cli_argv(chain, tmp_path, first_dir / "candidate.yaml", first_dir / "m.json")
    )
    assert code == 0
    code, _payload, _text = _run_cli(
        _cli_argv(chain, tmp_path, second_dir / "candidate.yaml", second_dir / "m.json")
    )
    assert code == 0
    assert (first_dir / "candidate.yaml").read_bytes() == (
        second_dir / "candidate.yaml"
    ).read_bytes()
    assert (first_dir / "m.json").read_bytes() == (second_dir / "m.json").read_bytes()
    # Identical rerun onto occupied paths is idempotent.
    code, _payload, _text = _run_cli(
        _cli_argv(chain, tmp_path, first_dir / "candidate.yaml", first_dir / "m.json")
    )
    assert code == 0


def test_cli_output_collision_paths_fail_closed(tmp_path, chain):
    inputs_dir = tmp_path / "inputs"
    inputs = chain.dump_inputs(inputs_dir)
    same = tmp_path / "same.yaml"
    code, _payload, text = _run_cli(
        _cli_argv(chain, tmp_path, same, same)
    )
    assert code == 2 and "distinct paths" in text
    code, _payload, text = _run_cli(
        _cli_argv(chain, tmp_path, inputs["manifest"], tmp_path / "m.json")
    )
    assert code == 2 and "must not overwrite" in text
    code, _payload, text = _run_cli(
        _cli_argv(
            chain,
            tmp_path,
            chain.root / "workspace" / "candidate.yaml",
            tmp_path / "m.json",
        )
    )
    assert code == 2 and "calibration workspace" in text
    code, _payload, text = _run_cli(
        _cli_argv(chain, tmp_path, ROOT / "rules" / "candidate.yaml", tmp_path / "m.json")
    )
    assert code == 2 and "rules" in text


def test_cli_refuses_occupied_output_with_different_bytes(tmp_path, chain):
    candidate = tmp_path / "candidate.yaml"
    materialization = tmp_path / "m.json"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(b"different bytes\n")
    code, _payload, text = _run_cli(_cli_argv(chain, tmp_path, candidate, materialization))
    assert code == 2 and "different content" in text
    assert candidate.read_bytes() == b"different bytes\n"
    assert not materialization.exists()


def test_cli_wrong_base_profile_bytes_block_admission(tmp_path, chain):
    mutated = yaml.safe_load(chain.base_bytes)
    mutated["cdc"]["yield_bands"]["watch"] = 0.07
    wrong = Path(tmp_path / "wrong-profile.yaml")
    wrong.write_bytes(yaml.safe_dump(mutated).encode("utf-8"))
    inputs = chain.dump_inputs(tmp_path / "inputs")
    candidate = tmp_path / "candidate.yaml"
    code, payload, _text = _run_cli(
        [
            "evolution",
            "materialize-candidate",
            "--calibration-workspace",
            str(chain.root / "workspace"),
            "--manifest",
            str(inputs["manifest"]),
            "--experiment",
            str(inputs["experiment"]),
            "--holdout",
            str(inputs["holdout"]),
            "--observations",
            str(inputs["observations"]),
            "--base-profile",
            str(wrong),
            "--candidate-output",
            str(candidate),
            "--materialization-output",
            str(tmp_path / "m.json"),
        ]
    )
    assert code == 1
    assert payload["classification"] == "MATERIALIZATION_BLOCKED"
    assert "BASE_PROFILE_BYTES_HASH" in payload["blocked_checks"]
    assert not candidate.exists()


# --------------------------------------------------------------------------
# 14. Schema drift parity
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("schema_name", "model"),
    [
        ("materializable-parameter-semantics.schema.json", MaterializableParameterSemanticsSetV1),
        ("materialization-semantics-reference.schema.json", MaterializationSemanticsReferenceV1),
        ("candidate-profile-materialization.schema.json", CandidateProfileMaterializationV1),
        ("candidate-profile-replay.schema.json", CandidateProfileReplayV1),
        ("calibration-search-space.schema.json", CalibrationSearchSpace),
    ],
)
def test_checked_in_schemas_have_drift_parity(schema_name, model):
    schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema == model.model_json_schema()


def test_materialization_and_semantics_validate_against_checked_in_schemas(chain):
    semantics_schema = Draft202012Validator(
        json.loads(
            (ROOT / "schemas" / "materializable-parameter-semantics.schema.json").read_text(
                encoding="utf-8"
            )
        )
    )
    semantics_schema.validate(INSTALLED.model_dump(mode="json"))
    outcome = chain.materialize()
    materialization_schema = Draft202012Validator(
        json.loads(
            (ROOT / "schemas" / "candidate-profile-materialization.schema.json").read_text(
                encoding="utf-8"
            )
        )
    )
    materialization_schema.validate(outcome.record.model_dump(mode="json"))
    tampered = outcome.record.model_dump(mode="json")
    tampered["automatic_application_allowed"] = True
    with pytest.raises(ValidationError):
        CandidateProfileMaterializationV1.model_validate(tampered)


# --------------------------------------------------------------------------
# 15. Socket-guarded offline execution
# --------------------------------------------------------------------------


def test_full_b1_library_path_constructs_no_socket(chain, monkeypatch):
    def no_sockets(*args, **kwargs):
        raise AssertionError("B1 materialization constructed a socket")

    monkeypatch.setattr(socket, "socket", no_sockets)
    monkeypatch.setattr(socket, "create_connection", no_sockets)
    outcome = chain.materialize()
    assert outcome.record.materialization_id


def test_full_b1_cli_path_constructs_no_socket(chain, monkeypatch, tmp_path):
    def no_sockets(*args, **kwargs):
        raise AssertionError("B1 CLI materialization constructed a socket")

    monkeypatch.setattr(socket, "socket", no_sockets)
    monkeypatch.setattr(socket, "create_connection", no_sockets)
    code, _payload, _text = _run_cli(
        _cli_argv(chain, tmp_path, tmp_path / "candidate.yaml", tmp_path / "m.json")
    )
    assert code == 0


# --------------------------------------------------------------------------
# 16. strict-v1 byte identity across the B1 path
# --------------------------------------------------------------------------


def test_strict_v1_bytes_unchanged_across_b1_execution(chain, tmp_path):
    before = BASE_PROFILE_PATH.read_bytes()
    _run_cli(_cli_argv(chain, tmp_path, tmp_path / "candidate.yaml", tmp_path / "m.json"))
    after = BASE_PROFILE_PATH.read_bytes()
    assert hashlib.sha256(before).hexdigest() == STRICT_V1_SHA256
    assert before == after
    committed = subprocess.check_output(["git", "show", "HEAD:rules/strict-v1.yaml"], cwd=ROOT)
    assert hashlib.sha256(committed).hexdigest() == STRICT_V1_SHA256
