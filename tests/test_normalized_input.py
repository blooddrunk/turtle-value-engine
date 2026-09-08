import json
import socket
import urllib.request
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as JsonSchemaValidationError

from turtle_value_engine import NormalizedInputLoadError, load_normalized_input
from turtle_value_engine.calculations import build_cdc_input_from_normalized_input, calculate_cdc
from turtle_value_engine.config import load_profile

FIXTURE_NAMES = (
    "healthy_cash_cow",
    "high_dividend_bad_cashflow",
    "cash_rich_dying_business",
    "excellent_business_too_expensive",
    "leveraged_dividend_trap",
    "negative_ev_governance_risk",
    "cyclical_peak_false_cheap",
    "share_dilution_offsets_buyback",
)
FIXTURE_DIR = Path("fixtures")
SCHEMA_DIR = Path("schemas")


def _raw_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _normalized_schema() -> dict:
    return json.loads((SCHEMA_DIR / "normalized-input.schema.json").read_text(encoding="utf-8"))


def _schema_validator() -> Draft202012Validator:
    schema = _normalized_schema()
    return Draft202012Validator(schema)


def _fact(raw: dict, field: str, period: str | None = None) -> dict:
    matches = [fact for fact in raw["facts"] if fact["field"] == field]
    if period is not None:
        matches = [fact for fact in matches if fact["period"] == period]
    assert len(matches) == 1, (field, period)
    return matches[0]


def test_normalized_schema_is_valid_and_all_eight_fixtures_validate():
    schema = _normalized_schema()
    Draft202012Validator.check_schema(schema)
    validator = _schema_validator()

    for name in FIXTURE_NAMES:
        validator.validate(_raw_fixture(name))


def test_all_repository_schemas_pass_draft_2020_12_schema_checks():
    for path in SCHEMA_DIR.glob("*.schema.json"):
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def test_normalized_schema_rejects_known_field_type_and_output_field():
    validator = _schema_validator()
    wrong_type = _raw_fixture("healthy_cash_cow")
    _fact(wrong_type, "current_market_cap")["value"] = "650"
    with pytest.raises(JsonSchemaValidationError):
        validator.validate(wrong_type)

    output_mixed_in = _raw_fixture("healthy_cash_cow")
    output_mixed_in["valuation"] = {}
    with pytest.raises(JsonSchemaValidationError):
        validator.validate(output_mixed_in)


def test_pydantic_serialization_validates_against_normalized_schema():
    validator = _schema_validator()

    for name in FIXTURE_NAMES:
        normalized_input = load_normalized_input(FIXTURE_DIR / f"{name}.json")
        serialized = normalized_input.model_dump(mode="json")
        validator.validate(serialized)


def test_fixture_evidence_also_validates_against_canonical_evidence_schema():
    evidence_schema = json.loads((SCHEMA_DIR / "evidence.schema.json").read_text(encoding="utf-8"))
    evidence_validator = Draft202012Validator(evidence_schema)

    for name in FIXTURE_NAMES:
        for evidence in _raw_fixture(name)["evidence_index"]:
            evidence_validator.validate(evidence)


def test_fixture_directory_contains_only_the_eight_inputs_and_separate_expectations():
    input_names = {
        path.stem for path in FIXTURE_DIR.glob("*.json") if path.name != "expectations.json"
    }
    assert input_names == set(FIXTURE_NAMES)

    expectations = json.loads((FIXTURE_DIR / "expectations.json").read_text(encoding="utf-8"))
    assert {item["fixture"] for item in expectations["fixtures"]} == set(FIXTURE_NAMES)
    assert all("engine_validation_status" in item for item in expectations["fixtures"])


def test_loader_rejects_unknown_top_level_output_field(tmp_path: Path):
    raw = _raw_fixture("healthy_cash_cow")
    raw["metrics"] = {}
    path = tmp_path / "unknown-output-field.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(NormalizedInputLoadError, match="Extra inputs are not permitted"):
        load_normalized_input(path)


def test_loader_rejects_unknown_nested_field(tmp_path: Path):
    raw = _raw_fixture("healthy_cash_cow")
    raw["company"]["unexpected"] = "not part of the contract"
    path = tmp_path / "unknown-nested-field.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(NormalizedInputLoadError, match="Extra inputs are not permitted"):
        load_normalized_input(path)


def test_loader_rejects_wrong_type_for_known_numeric_fact(tmp_path: Path):
    raw = _raw_fixture("healthy_cash_cow")
    _fact(raw, "current_market_cap")["value"] = "650"
    path = tmp_path / "wrong-type.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(NormalizedInputLoadError, match="requires a numeric value or null"):
        load_normalized_input(path)


def test_loader_rejects_illegal_enum_value(tmp_path: Path):
    raw = _raw_fixture("cyclical_peak_false_cheap")
    _fact(raw, "cycle_phase")["value"] = "BOOM"
    path = tmp_path / "wrong-enum.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(NormalizedInputLoadError, match="requires one of"):
        load_normalized_input(path)


def test_loader_rejects_accepted_adjustment_without_approval(tmp_path: Path):
    raw = _raw_fixture("healthy_cash_cow")
    raw["adjustments"][0].pop("approved_by")
    path = tmp_path / "unapproved-adjustment.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(NormalizedInputLoadError, match="accepted adjustments require approved_by"):
        load_normalized_input(path)


def test_missing_numeric_fact_stays_null_and_is_not_filled_with_zero(tmp_path: Path):
    raw = _raw_fixture("healthy_cash_cow")
    missing = _fact(raw, "lease_principal_outside_cfo", "FY2025")
    missing["value"] = None
    raw["data_quality"]["critical_missing_fields"] = ["lease_principal_outside_cfo"]
    path = tmp_path / "missing-value.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    loaded = load_normalized_input(path)
    assert (
        _fact(loaded.model_dump(mode="json"), "lease_principal_outside_cfo", "FY2025")["value"]
        is None
    )
    assert missing["value"] is None


def test_fixture_declared_critical_missing_fields_are_explicit_nulls():
    normalized_input = load_normalized_input(FIXTURE_DIR / "cash_rich_dying_business.json")
    facts_by_field = {}
    for fact in normalized_input.facts:
        if fact.period.startswith("AS_OF_"):
            facts_by_field[fact.field] = fact

    for field in normalized_input.data_quality.critical_missing_fields:
        assert field in facts_by_field
        assert facts_by_field[field].value is None


def test_all_fact_and_adjustment_evidence_references_are_defined():
    for name in FIXTURE_NAMES:
        normalized_input = load_normalized_input(FIXTURE_DIR / f"{name}.json")
        evidence_ids = {evidence.id for evidence in normalized_input.evidence_index}
        references = {
            evidence_id
            for fact in normalized_input.facts
            for evidence_id in fact.source_evidence_ids
        }
        references.update(
            evidence_id
            for adjustment in normalized_input.adjustments
            for evidence_id in adjustment.source_evidence_ids
        )
        assert references <= evidence_ids


def test_undefined_evidence_reference_is_rejected(tmp_path: Path):
    raw = _raw_fixture("healthy_cash_cow")
    raw["facts"][0]["source_evidence_ids"] = ["ev-does-not-exist"]
    path = tmp_path / "undefined-evidence.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(NormalizedInputLoadError, match="undefined evidence ID"):
        load_normalized_input(path)


def test_fixtures_project_to_existing_cdc_calculation_without_network():
    profile = load_profile("strict-v1")

    for name in FIXTURE_NAMES:
        normalized_input = load_normalized_input(FIXTURE_DIR / f"{name}.json")
        cdc_input = build_cdc_input_from_normalized_input(
            normalized_input,
            cyclical=name == "cyclical_peak_false_cheap",
        )
        result = calculate_cdc(cdc_input, profile)
        assert result.year_results
        assert all(year.core_cdc is not None for year in result.year_results)


def test_loading_fixtures_makes_no_network_requests(monkeypatch):
    def fail_network(*args, **kwargs):
        raise AssertionError("normalized-input loading must remain offline")

    monkeypatch.setattr(socket, "socket", fail_network)
    monkeypatch.setattr(urllib.request, "urlopen", fail_network)

    for name in FIXTURE_NAMES:
        load_normalized_input(FIXTURE_DIR / f"{name}.json")


def test_normalized_input_does_not_accept_output_sections(tmp_path: Path):
    raw = _raw_fixture("healthy_cash_cow")
    for output_field in ("business_quality", "gates", "valuation", "decision"):
        candidate = deepcopy(raw)
        candidate[output_field] = {}
        path = tmp_path / f"{output_field}.json"
        path.write_text(json.dumps(candidate), encoding="utf-8")
        with pytest.raises(NormalizedInputLoadError):
            load_normalized_input(path)
