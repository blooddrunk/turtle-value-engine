"""Phase 7-A-R2 fail-on-R1-main regression proofs.

The four tests below were first added and executed against the pristine R1
baseline ``cbcf4cab5f361eb45d5be83a846e74c3b7f085cd`` (see
``docs/status/phase-7-a-r2-2026-09-30.md`` for the recorded output).  On that
baseline each test fails by demonstrating one of the unsafe behaviors found by
the Phase 7-A-R1 post-closure review:

1. a separately valid manifest with the same ``dataset_id`` but different
   content is admitted as ``READY_FOR_HUMAN_REVIEW`` after rebuilding a fresh
   matching ``CalibrationEvidenceBindingV1`` over the substituted manifest;
2. changing only the non-scoring ``CalibrationObservation.source_hash``
   provenance is admitted the same way — with a fresh binding rebuilt over the
   substituted rows — while canonical experiment/holdout replay remains
   identical;
3. the checked-in Draft 2020-12 evaluation schema accepts a dossier whose
   canonical checks were reordered (schema-only validation);
4. the checked-in schema accepts a count-preserving duplicate/omission
   dossier (schema-only validation).

The tests intentionally use only Phase 7-A-R1 call surfaces — the evaluator is
called with ``evidence_binding`` exactly as R1 allows, and no R2 freeze-anchor
symbol is referenced — so the exact file runs on both the R1 baseline and the
hardened tree.  After R2 every test passes: an unanchored sidecar binding
fail-closes admission on the authoritative-freeze checks, and the generated
schema encodes the exact canonical check sequence (``prefixItems`` with
per-position ``const``), so reordering and count-preserving duplicate/omission
are rejected by schema-only validation as well.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError

from turtle_value_engine.backtest import (
    BacktestDatasetManifest,
    CalibrationObservation,
    CalibrationRunner,
    CalibrationSearchSpace,
    ChronologicalSplit,
    ListingLifecycle,
    Market,
    UniverseCoverage,
    build_calibration_evidence_binding,
)
from turtle_value_engine.evolution import (
    CHECK_CANONICAL_REPRODUCTION,
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
    binding = build_calibration_evidence_binding(
        manifest=_manifest(), experiment=experiment, observations=observations
    )
    return base_bytes, base_sha, experiment, holdout, observations, binding


def _blocked_names(evaluation) -> set[str]:
    return {check.name for check in evaluation.checks if check.state == "BLOCKED"}


def _content_hash(payload: dict) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
    ).hexdigest()


def _rehashed_payload(evaluation) -> dict:
    payload = evaluation.model_dump(mode="json", warnings=False)
    payload["content_sha256"] = _content_hash(payload)
    return payload


def test_proof_1_fresh_binding_manifest_substitution_must_not_be_admitted(
    canonical_evidence,
):
    base_bytes, _base_sha, experiment, holdout, observations, honest_binding = (
        canonical_evidence
    )

    substituted = _manifest(dataset_version="2")
    assert substituted.dataset_id == experiment.manifest_id
    assert substituted.content_sha256 != honest_binding.manifest_content_sha256

    # The attacker rebuilds a fresh internally valid binding over the
    # substituted manifest; because the R1 evaluator compares the supplied
    # binding only against the supplied evidence, the substitution is
    # self-consistent and R1 has no calibration-time authority left to
    # reject it.
    fresh_binding = build_calibration_evidence_binding(
        manifest=substituted, experiment=experiment, observations=observations
    )
    assert fresh_binding.manifest_content_sha256 == substituted.content_sha256

    evaluation = evaluate_controlled_evolution(
        manifest=substituted,
        experiment=experiment,
        holdout=holdout,
        observations=observations,
        base_profile_bytes=base_bytes,
        evidence_binding=fresh_binding,
    )

    assert evaluation.admission_state == "BLOCKED", (
        "a separately valid manifest with the same dataset_id but different "
        "content was admitted after rebuilding a fresh matching evidence "
        "binding over the substituted manifest"
    )


def test_proof_2_fresh_binding_provenance_substitution_must_not_be_admitted(
    canonical_evidence,
):
    base_bytes, _base_sha, experiment, holdout, observations, _honest_binding = (
        canonical_evidence
    )

    substituted = [
        observation.model_copy(update={"source_hash": "b" * 64})
        for observation in observations
    ]
    fresh_binding = build_calibration_evidence_binding(
        manifest=_manifest(), experiment=experiment, observations=substituted
    )
    assert fresh_binding.observations_content_sha256 != _honest_binding.observations_content_sha256

    evaluation = evaluate_controlled_evolution(
        manifest=_manifest(),
        experiment=experiment,
        holdout=holdout,
        observations=substituted,
        base_profile_bytes=base_bytes,
        evidence_binding=fresh_binding,
    )

    # The canonical replay itself stays blind to the provenance change: the
    # substitution is invisible to scoring, so blocking must come from the
    # authoritative-freeze boundary, not from the reproduction checks.
    assert CHECK_CANONICAL_REPRODUCTION not in _blocked_names(evaluation)
    assert evaluation.admission_state == "BLOCKED", (
        "a frozen-observation set differing only in non-scoring source_hash "
        "provenance was admitted after rebuilding a fresh matching evidence "
        "binding over the substituted rows"
    )


def test_proof_3_schema_only_reordered_checks_must_be_rejected(canonical_evidence):
    base_bytes, _base_sha, experiment, holdout, observations, binding = (
        canonical_evidence
    )

    evaluation = evaluate_controlled_evolution(
        manifest=_manifest(),
        experiment=experiment,
        holdout=holdout,
        observations=observations,
        base_profile_bytes=base_bytes,
        evidence_binding=binding,
    )
    payload = _rehashed_payload(evaluation)
    payload["checks"][0], payload["checks"][1] = (
        payload["checks"][1],
        payload["checks"][0],
    )
    payload["content_sha256"] = _content_hash(payload)

    schema = json.loads(
        (ROOT / "schemas" / "controlled-evolution-evaluation.schema.json").read_text(
            encoding="utf-8"
        )
    )
    # The checked-in schema itself, not only the in-memory model, must encode
    # the canonical per-position sequence: both swapped names stay valid
    # members of the check-name enum, so only an exact-sequence constraint
    # can reject this dossier.
    with pytest.raises(SchemaValidationError):
        Draft202012Validator(schema).validate(payload)


def test_proof_4_schema_only_duplicate_omission_must_be_rejected(canonical_evidence):
    base_bytes, _base_sha, experiment, holdout, observations, binding = (
        canonical_evidence
    )

    evaluation = evaluate_controlled_evolution(
        manifest=_manifest(),
        experiment=experiment,
        holdout=holdout,
        observations=observations,
        base_profile_bytes=base_bytes,
        evidence_binding=binding,
    )
    payload = _rehashed_payload(evaluation)
    # Replace one canonical check with a duplicate of another valid check so
    # the array keeps exactly the canonical item count and every name stays a
    # valid enum member; only an exact-sequence constraint can reject it.
    payload["checks"][0] = dict(payload["checks"][1])
    payload["content_sha256"] = _content_hash(payload)

    schema = json.loads(
        (ROOT / "schemas" / "controlled-evolution-evaluation.schema.json").read_text(
            encoding="utf-8"
        )
    )
    with pytest.raises(SchemaValidationError):
        Draft202012Validator(schema).validate(payload)
