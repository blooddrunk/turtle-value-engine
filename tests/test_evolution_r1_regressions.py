"""Phase 7-A-R1 fail-on-pre-R1-main regression proofs.

The four tests below were first added and executed against the pristine
pre-R1 baseline ``32f77c57a58f1b350d5871165958bd0de443bd4c`` (see
``docs/status/phase-7-a-r1-2026-09-30.md`` for the recorded output).  On that
baseline each test fails by demonstrating one of the unsafe behaviors found by
the Phase 7-A post-closure review:

1. a separately valid manifest with the same ``dataset_id`` but changed
   content and a recomputed valid ``content_sha256`` is admitted as
   ``READY_FOR_HUMAN_REVIEW``;
2. changing only the non-scoring ``CalibrationObservation.source_hash``
   provenance is admitted while canonical experiment/holdout replay remains
   identical;
3. a ``READY_FOR_HUMAN_REVIEW`` dossier with a required check removed still
   model/schema-validates after recomputing ``content_sha256``;
4. a dossier carrying a wrong/non-canonical ``evaluation_id`` still
   model-validates after recomputing ``content_sha256``.

The tests intentionally use only the Phase 7-A (pre-R1) call signature —
no evidence binding is supplied — so the exact file runs on both the
baseline and the hardened tree.  After R1 every test passes because the
missing prior evidence binding alone fail-closes admission, and the
persisted dossier contract rejects incomplete check sets and non-canonical
evaluation ids.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from turtle_value_engine.backtest import (
    BacktestDatasetManifest,
    CalibrationObservation,
    CalibrationRunner,
    CalibrationSearchSpace,
    ChronologicalSplit,
    ListingLifecycle,
    Market,
    UniverseCoverage,
)
from turtle_value_engine.evolution import (
    CHECK_CANONICAL_REPRODUCTION,
    ControlledEvolutionEvaluationV1,
    evaluate_controlled_evolution,
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


def _search_space() -> CalibrationSearchSpace:
    return CalibrationSearchSpace(
        space_id="quality-thresholds-v1",
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
def canonical_evidence():
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
    return base_bytes, base_sha, experiment, holdout, observations


def _evaluate_without_binding(
    manifest: BacktestDatasetManifest,
    experiment,
    holdout,
    observations,
    *,
    base_profile_bytes: bytes,
) -> ControlledEvolutionEvaluationV1:
    """Call the evaluator exactly as Phase 7-A (pre-R1) allowed: no binding."""

    return evaluate_controlled_evolution(
        manifest=manifest,
        experiment=experiment,
        holdout=holdout,
        observations=observations,
        base_profile_bytes=base_profile_bytes,
    )


def _blocked_names(evaluation: ControlledEvolutionEvaluationV1) -> set[str]:
    return {check.name for check in evaluation.checks if check.state == "BLOCKED"}


def _rehashed_payload(evaluation: ControlledEvolutionEvaluationV1) -> dict:
    payload = evaluation.model_dump(mode="json", warnings=False)
    payload["content_sha256"] = hashlib.sha256(
        canonical_json_bytes(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
    ).hexdigest()
    return payload


def test_proof_1_same_id_manifest_content_substitution_must_not_be_admitted(
    canonical_evidence,
):
    base_bytes, _base_sha, experiment, holdout, observations = canonical_evidence

    substituted = _manifest(dataset_version="2")
    assert substituted.dataset_id == experiment.manifest_id
    honest = _manifest()
    assert substituted.content_sha256 != honest.content_sha256

    evaluation = _evaluate_without_binding(
        substituted, experiment, holdout, observations, base_profile_bytes=base_bytes
    )

    assert evaluation.admission_state == "BLOCKED", (
        "a separately valid manifest with the same dataset_id but different "
        "content and a recomputed valid content_sha256 was admitted without "
        "any calibration-time manifest binding"
    )


def test_proof_2_source_hash_observation_substitution_must_not_be_admitted(
    canonical_evidence,
):
    base_bytes, _base_sha, experiment, holdout, observations = canonical_evidence

    substituted = [
        observation.model_copy(update={"source_hash": "b" * 64})
        for observation in observations
    ]

    evaluation = _evaluate_without_binding(
        _manifest(),
        experiment,
        holdout,
        substituted,
        base_profile_bytes=base_bytes,
    )

    # The canonical replay itself stays blind to the provenance change: the
    # substitution is invisible to scoring, so blocking must come from the
    # frozen-evidence identity boundary, not from the reproduction checks.
    assert CHECK_CANONICAL_REPRODUCTION not in _blocked_names(evaluation)
    assert evaluation.admission_state == "BLOCKED", (
        "a frozen-observation set differing only in non-scoring source_hash "
        "provenance was admitted even though it is not the calibrated "
        "observation set"
    )


def test_proof_3_dossier_missing_required_checks_must_not_validate(canonical_evidence):
    base_bytes, _base_sha, experiment, holdout, observations = canonical_evidence

    evaluation = _evaluate_without_binding(
        _manifest(),
        experiment,
        holdout,
        observations,
        base_profile_bytes=base_bytes,
    )
    payload = _rehashed_payload(evaluation)
    names = [check["name"] for check in payload["checks"]]
    assert "MANIFEST_IDENTITY" in names
    payload["checks"] = [
        check for check in payload["checks"] if check["name"] != "MANIFEST_IDENTITY"
    ]
    payload["content_sha256"] = hashlib.sha256(
        canonical_json_bytes(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
    ).hexdigest()

    # Either layer of the hardened contract rejects the truncation: the
    # canonical-set field constraint (exactly 19 checks) or the canonical
    # required-check-set sequence validator.
    with pytest.raises(
        ValidationError, match="at least 19 items|canonical required check set"
    ):
        ControlledEvolutionEvaluationV1.model_validate(payload)

    schema = json.loads(
        (ROOT / "schemas" / "controlled-evolution-evaluation.schema.json").read_text(
            encoding="utf-8"
        )
    )
    # The checked-in schema must reject the truncated dossier as well: the
    # persisted contract itself, not only the in-memory model, carries the
    # canonical required-check-set constraint.
    with pytest.raises(SchemaValidationError):
        Draft202012Validator(schema).validate(payload)


def test_proof_4_non_canonical_evaluation_id_must_not_validate(canonical_evidence):
    base_bytes, _base_sha, experiment, holdout, observations = canonical_evidence

    evaluation = _evaluate_without_binding(
        _manifest(),
        experiment,
        holdout,
        observations,
        base_profile_bytes=base_bytes,
    )
    payload = _rehashed_payload(evaluation)
    payload["evaluation_id"] = "attacker-chosen-evaluation-id"
    payload["content_sha256"] = hashlib.sha256(
        canonical_json_bytes(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
    ).hexdigest()

    with pytest.raises(ValidationError, match="evaluation_id"):
        ControlledEvolutionEvaluationV1.model_validate(payload)
