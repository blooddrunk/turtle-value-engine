import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from referencing import Registry, Resource

from turtle_value_engine.models import (
    CompanyAnalysis,
    Fact,
    NormalizedCompanyInput,
)


def test_fact_requires_at_least_one_evidence_id():
    with pytest.raises(ValidationError):
        Fact(
            id="fact-1",
            field="reported_cfo",
            value=100,
            period="FY2025",
            source_evidence_ids=[],
            confidence=1,
        )


def test_normalized_input_preserves_null_and_contract_fields():
    input_data = NormalizedCompanyInput(
        schema_version="1.0.0",
        analysis_id="analysis-1",
        as_of="2026-09-08",
        profile_id="strict-v1",
        company={
            "name": "Synthetic Co",
            "primary_listing": "SH600000",
            "sector": "industrials",
            "reporting_currency": "CNY",
        },
        data_quality={
            "confidence": "HIGH",
            "evidence_coverage": 1,
            "critical_missing_fields": [],
        },
        facts=[
            {
                "id": "fact-1",
                "field": "lease_principal_outside_cfo",
                "value": None,
                "period": "FY2025",
                "source_evidence_ids": ["evidence-1"],
                "confidence": 0.5,
            }
        ],
        evidence_index=[
            {
                "id": "evidence-1",
                "direction": "CONTEXT",
                "strength": "E0",
                "statement": "Synthetic model-validation evidence.",
                "source": {
                    "type": "OTHER",
                    "title": "Synthetic model-validation source",
                },
                "confidence": 1,
            }
        ],
        adjustments=[],
    )

    assert input_data.facts[0].value is None
    assert input_data.model_dump(mode="json")["schema_version"] == "1.0.0"


def test_company_analysis_serialization_validates_against_repository_schema():
    gate = {"status": "PASS", "rules": []}
    tier = {
        "cdc_hurdle": 0.10,
        "return_hurdle": 0.05,
        "market_cap": 100.0,
        "price": 10.0,
    }
    analysis = CompanyAnalysis(
        analysis_id="analysis-1",
        as_of="2026-09-08",
        profile_id="strict-v1",
        company={
            "name": "Synthetic Co",
            "primary_listing": "SH600000",
            "sector": "industrials",
            "reporting_currency": "CNY",
        },
        data_quality={
            "confidence": "HIGH",
            "evidence_coverage": 1,
            "critical_missing_fields": [],
        },
        facts=[],
        adjustments=[],
        metrics={
            "cdc": {},
            "net_cash": {},
            "through_return": {},
        },
        gates={
            "universe": gate,
            "balance_sheet": gate,
            "cdc": gate,
            "through_return": gate,
            "business_quality": gate,
            "governance_data_quality": gate,
        },
        valuation={
            "as_of": "2026-09-08",
            "valuation_currency": "CNY",
            "listing": "SH600000",
            "normalized_parent_core_cdc": 10,
            "distributable_base": 9,
            "recurring_shareholder_cash": 5.4,
            "tiers": {
                "observation": tier,
                "acceptable": tier,
                "turtle_entry": tier,
                "extreme_safety": tier,
            },
            "current_valuation_state": "TURTLE_ENTRY",
            "confidence": "HIGH",
        },
        decision={
            "state": "TURTLE_ENTRY",
            "auto_decision_allowed": True,
            "summary": "synthetic",
            "blocking_reasons": [],
        },
    )

    schema_dir = Path("schemas").resolve()
    schema = json.loads((schema_dir / "company-analysis.schema.json").read_text())
    valuation_schema = json.loads((schema_dir / "valuation-result.schema.json").read_text())
    evidence_schema = json.loads((schema_dir / "evidence.schema.json").read_text())
    registry = Registry().with_resources(
        [
            (schema["$id"], Resource.from_contents(schema)),
            (valuation_schema["$id"], Resource.from_contents(valuation_schema)),
            (evidence_schema["$id"], Resource.from_contents(evidence_schema)),
        ]
    )

    Draft202012Validator(schema, registry=registry).validate(analysis.model_dump(mode="json"))
