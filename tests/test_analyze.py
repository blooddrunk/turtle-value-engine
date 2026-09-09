import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from turtle_value_engine import load_normalized_input
from turtle_value_engine.cli import main
from turtle_value_engine.models import CompanyAnalysis, GateStatus
from turtle_value_engine.pipeline import run_analyze

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


def _company_analysis_validator() -> Draft202012Validator:
    schema_dir = Path("schemas").resolve()
    schema = json.loads((schema_dir / "company-analysis.schema.json").read_text(encoding="utf-8"))
    valuation = json.loads(
        (schema_dir / "valuation-result.schema.json").read_text(encoding="utf-8")
    )
    evidence = json.loads((schema_dir / "evidence.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resources(
        [
            (schema["$id"], Resource.from_contents(schema)),
            (valuation["$id"], Resource.from_contents(valuation)),
            (evidence["$id"], Resource.from_contents(evidence)),
        ]
    )
    return Draft202012Validator(schema, registry=registry)


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_analyze_assembles_schema_valid_offline_company_analysis(fixture_name: str):
    normalized_input = load_normalized_input(Path("fixtures") / f"{fixture_name}.json")

    analysis = run_analyze(normalized_input)

    _company_analysis_validator().validate(analysis.model_dump(mode="json"))
    assert isinstance(analysis, CompanyAnalysis)
    assert analysis.analysis_id == normalized_input.analysis_id
    assert analysis.gates.cdc.rules
    assert analysis.gates.balance_sheet.rules
    assert analysis.valuation.tiers.observation


def test_analyze_preserves_lineage_and_does_not_infer_business_quality():
    normalized_input = load_normalized_input(Path("fixtures/healthy_cash_cow.json"))

    analysis = run_analyze(normalized_input)
    cdc_payload = analysis.metrics.cdc.model_dump(mode="json")

    assert analysis.facts == normalized_input.facts
    assert analysis.adjustments == normalized_input.adjustments
    assert analysis.evidence_index == normalized_input.evidence_index
    assert cdc_payload["source_evidence_ids"]["reported_cfo@FY2021"] == [
        "ev-healthy_cash_cow-cdc"
    ]
    assert analysis.business_quality is None
    assert analysis.gates.business_quality.status is GateStatus.NOT_EVALUATED
    assert analysis.valuation.current_valuation_state.value == "SPECIAL_REVIEW"
    assert analysis.decision.auto_decision_allowed is False
    assert analysis.decision.state.value == "SPECIAL_REVIEW"


def test_analyze_honors_declared_cyclical_special_model():
    normalized_input = load_normalized_input(Path("fixtures/cyclical_peak_false_cheap.json"))

    analysis = run_analyze(normalized_input)

    assert analysis.metrics.cdc.model_dump(mode="json")["normalized_parent_core_cdc"] == 75.0
    assert "CYCLICAL_VALUATION_UNAVAILABLE" not in analysis.valuation.flags


def test_analyze_cli_emits_complete_company_analysis(capsys):
    exit_code = main(
        [
            "analyze",
            "--input",
            "fixtures/healthy_cash_cow.json",
            "--profile",
            "strict-v1",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    CompanyAnalysis.model_validate(output)
    assert output["gates"]["business_quality"]["status"] == "NOT_EVALUATED"
    assert output["decision"]["auto_decision_allowed"] is False
