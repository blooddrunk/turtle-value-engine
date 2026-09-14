"""Frozen acceptance coverage for the Phase 2/3 closure goal."""

import base64
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from turtle_value_engine import (
    build_decision_trace,
    load_normalized_input,
    materialize_effective_input,
)
from turtle_value_engine.adjustments import AdjustmentProposalWorkflow
from turtle_value_engine.models import Company, NormalizedCompanyInput
from turtle_value_engine.models.common import AdjustmentStatus, AdjustmentType
from turtle_value_engine.pipeline import run_analyze, run_analyze_with_accepted_adjustments
from turtle_value_engine.preparation import (
    AcquisitionRequest,
    NormalizedCompanyInputBuilder,
    PreparationNormalizationError,
)
from turtle_value_engine.providers import (
    AKShareNormalizer,
    AKShareProvider,
    FilesystemFilingDocumentCache,
    FilesystemRawResponseCache,
    FilingDiscoveryQuery,
    FilingDiscoverySourceClient,
    FilingDocumentDownloader,
    FilingDocumentSourceClient,
    FilingDocumentTextParser,
    FilingDownloadPayload,
    FilingEvidenceStore,
    FilingReportExtractor,
    FilingSource,
    OfficialFilingDiscoveryProvider,
    fetch_filing_discovery_with_cache,
    fetch_filing_document_with_cache,
    parse_filing_discovery_record,
)

ROOT = Path(__file__).parents[1]
RETRIEVED_AT = datetime(2026, 9, 12, 5, 6, 7, tzinfo=UTC)


def _provider_fixture(name: str):
    return json.loads(
        (ROOT / "fixtures/providers/akshare" / name).read_text(encoding="utf-8")
    )


class FrozenAKShare:
    """Minimal injected AKShare client backed only by repository fixtures."""

    __version__ = "phase-2-frozen-akshare"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail = False

    def _return(self, endpoint: str, payload: object, **kwargs: object):
        self.calls.append((endpoint, dict(kwargs)))
        if self.fail:
            raise RuntimeError("frozen provider must not be called during replay")
        return deepcopy(payload)

    def stock_info_a_code_name(self):
        return self._return("stock_info_a_code_name", _provider_fixture("a_code_name.json"))

    def stock_hk_company_profile_em(self, *, symbol: str):
        return self._return(
            "stock_hk_company_profile_em",
            _provider_fixture("h_company_profile.json"),
            symbol=symbol,
        )

    def stock_hk_security_profile_em(self, *, symbol: str):
        return self._return(
            "stock_hk_security_profile_em",
            _provider_fixture("h_security_profile.json"),
            symbol=symbol,
        )

    def stock_zh_a_spot_em(self):
        return self._return("stock_zh_a_spot_em", _provider_fixture("a_quote.json"))

    def stock_hk_spot_em(self):
        return self._return("stock_hk_spot_em", _provider_fixture("h_quote.json"))

    def stock_cash_flow_sheet_by_report_em(self, **kwargs: object):
        return self._return(
            "stock_cash_flow_sheet_by_report_em",
            _provider_fixture("a_cash_flow.json"),
            **kwargs,
        )

    def stock_profit_sheet_by_report_em(self, **kwargs: object):
        return self._return(
            "stock_profit_sheet_by_report_em",
            _provider_fixture("a_income_statement.json"),
            **kwargs,
        )

    def stock_balance_sheet_by_report_em(self, **kwargs: object):
        return self._return(
            "stock_balance_sheet_by_report_em",
            _provider_fixture("a_balance_sheet.json"),
            **kwargs,
        )

    def stock_financial_hk_report_em(self, **kwargs: object):
        symbol = str(kwargs["symbol"])
        filename = (
            "h_cash_flow.json"
            if "现金流" in symbol
            else "h_income_statement.json"
            if "利润" in symbol
            else "h_balance_sheet.json"
        )
        return self._return(
            "stock_financial_hk_report_em",
            _provider_fixture(filename),
            **kwargs,
        )


def akshare_provider(fake: FrozenAKShare) -> AKShareProvider:
    return AKShareProvider(fake, clock=lambda: RETRIEVED_AT)


def _validate_normalized(value: NormalizedCompanyInput) -> None:
    schema = json.loads((ROOT / "schemas" / "normalized-input.schema.json").read_text())
    Draft202012Validator(schema).validate(value.model_dump(mode="json"))


def _validate_analysis(value: object) -> None:
    schema = json.loads((ROOT / "schemas" / "company-analysis.schema.json").read_text())
    valuation = json.loads((ROOT / "schemas" / "valuation-result.schema.json").read_text())
    evidence = json.loads((ROOT / "schemas" / "evidence.schema.json").read_text())
    registry = Registry().with_resources(
        [
            (schema["$id"], Resource.from_contents(schema)),
            (valuation["$id"], Resource.from_contents(valuation)),
            (evidence["$id"], Resource.from_contents(evidence)),
        ]
    )
    Draft202012Validator(schema, registry=registry).validate(value.model_dump(mode="json"))


@pytest.mark.parametrize(
    ("listing_id", "reporting_currency"),
    [("SH600000", "CNY"), ("HK00700", "HKD")],
)
def test_phase2_frozen_provider_cache_normalization_and_analysis(
    tmp_path: Path,
    listing_id: str,
    reporting_currency: str,
):
    fake = FrozenAKShare()
    provider = akshare_provider(fake)
    company = Company(
        name="Frozen acceptance company",
        primary_listing=listing_id,
        sector="frozen-sector",
        reporting_currency=reporting_currency,
    )
    request = AcquisitionRequest(
        listing_id=listing_id,
        as_of=RETRIEVED_AT.date(),
        provider="akshare",
        company=company,
    )
    cache = FilesystemRawResponseCache(tmp_path / "raw")
    builder = NormalizedCompanyInputBuilder(provider, cache)

    live_bundle, normalized = builder.prepare(request)
    assert len(live_bundle.records) == 6
    assert all(mode.value == "LIVE" for mode in live_bundle.retrieval_modes)
    assert len(fake.calls) == 6
    _validate_normalized(normalized)

    replay_fake = FrozenAKShare()
    replay_fake.fail = True
    replay_bundle, replayed = NormalizedCompanyInputBuilder(
        akshare_provider(replay_fake), cache
    ).prepare(request, offline=True)
    assert all(mode.value == "CACHE_REPLAY" for mode in replay_bundle.retrieval_modes)
    assert replay_fake.calls == []
    assert replayed.model_dump(mode="json") == normalized.model_dump(mode="json")

    analysis = run_analyze(replayed)
    _validate_analysis(analysis)
    assert analysis.company.primary_listing == listing_id
    assert all("报告日期" not in fact.field for fact in replayed.facts)


def test_phase2_preparation_requires_explicit_company_context_without_guessing(tmp_path: Path):
    request = AcquisitionRequest(
        listing_id="SH600000",
        as_of=RETRIEVED_AT.date(),
    )
    builder = NormalizedCompanyInputBuilder(
        akshare_provider(FrozenAKShare()),
        FilesystemRawResponseCache(tmp_path / "raw"),
    )
    with pytest.raises(ValueError, match="company context is required"):
        builder.prepare(request)


def test_phase2_preparation_rejects_future_normalized_period(tmp_path: Path):
    class FuturePeriodNormalizer:
        def normalize(self, records, *, analysis_id, as_of, profile_id, company):
            normalized = AKShareNormalizer().normalize(
                records,
                analysis_id=analysis_id,
                as_of=as_of,
                profile_id=profile_id,
                company=company,
            )
            first_fact = normalized.facts[0].model_copy(update={"period": "AS_OF_2026-09-15"})
            return normalized.model_copy(update={"facts": [first_fact, *normalized.facts[1:]]})

    request = AcquisitionRequest(
        listing_id="SH600000",
        as_of=RETRIEVED_AT.date(),
        company=Company(
            name="Frozen point-in-time company",
            primary_listing="SH600000",
            sector="frozen-sector",
            reporting_currency="CNY",
        ),
    )
    builder = NormalizedCompanyInputBuilder(
        akshare_provider(FrozenAKShare()),
        FilesystemRawResponseCache(tmp_path / "raw"),
        normalizer=FuturePeriodNormalizer(),
    )
    with pytest.raises(PreparationNormalizationError, match="after as_of"):
        builder.prepare(request)


def test_tve_prepare_cli_writes_replayable_normalized_input(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    import turtle_value_engine.cli as cli

    fake = FrozenAKShare()
    monkeypatch.setattr(cli, "AKShareProvider", lambda: akshare_provider(fake))
    output = tmp_path / "normalized.json"
    assert (
        cli.main(
            [
                "prepare",
                "600000.SH",
                "--as-of",
                RETRIEVED_AT.date().isoformat(),
                "--provider",
                "akshare",
                "--name",
                "Frozen CLI company",
                "--sector",
                "frozen-sector",
                "--reporting-currency",
                "CNY",
                "--cache-dir",
                str(tmp_path / "cache"),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    prepared = load_normalized_input(output)
    _validate_normalized(prepared)
    assert prepared.company.primary_listing == "SH600000"

    replay_fake = FrozenAKShare()
    replay_fake.fail = True
    monkeypatch.setattr(cli, "AKShareProvider", lambda: akshare_provider(replay_fake))
    replay_output = tmp_path / "normalized-replay.json"
    assert (
        cli.main(
            [
                "prepare",
                "600000.SH",
                "--as-of",
                RETRIEVED_AT.date().isoformat(),
                "--provider",
                "akshare",
                "--offline",
                "--name",
                "Frozen CLI company",
                "--sector",
                "frozen-sector",
                "--reporting-currency",
                "CNY",
                "--cache-dir",
                str(tmp_path / "cache"),
                "--output",
                str(replay_output),
            ]
        )
        == 0
    )
    assert replay_fake.calls == []
    assert load_normalized_input(replay_output) == prepared


def _base_without_adjustments() -> NormalizedCompanyInput:
    original = load_normalized_input(ROOT / "fixtures" / "healthy_cash_cow.json")
    payload = original.model_dump(mode="python", warnings=False)
    payload["adjustments"] = []
    return NormalizedCompanyInput.model_validate(payload)


@pytest.mark.parametrize("adjustment_type", [item.value for item in AdjustmentType])
def test_accepted_adjustment_materializes_each_supported_type(adjustment_type: str):
    normalized = _base_without_adjustments()
    evidence_id = normalized.evidence_index[0].id
    adjustment = {
        "id": f"accepted-{adjustment_type.lower()}",
        "target_field": "restricted_cash",
        "target_period": "AS_OF_2026-09-08",
        "adjustment_type": adjustment_type,
        "input_value": 0.0,
        "proposed_adjusted_value": 10.0,
        "status": "ACCEPTED",
        "reason": "Frozen acceptance adjustment.",
        "source_evidence_ids": [evidence_id],
        "proposed_by": "LLM",
        "approved_by": "HUMAN",
        "confidence": 0.9,
    }
    payload = normalized.model_dump(mode="python", warnings=False)
    payload["adjustments"] = [adjustment]
    normalized_with_adjustment = NormalizedCompanyInput.model_validate(payload)

    effective = materialize_effective_input(normalized_with_adjustment)
    source = next(
        fact
        for fact in normalized_with_adjustment.facts
        if fact.field == "restricted_cash" and fact.period == "AS_OF_2026-09-08"
    )
    result = next(
        fact
        for fact in effective.facts
        if fact.field == "restricted_cash" and fact.period == "AS_OF_2026-09-08"
    )
    assert source.value == 0
    assert result.value == 10.0
    assert result.source_fact_id == source.id
    assert result.source_value == source.value
    assert result.applied_adjustment_ids == [normalized_with_adjustment.adjustments[0].id]
    assert source.id != result.id
    assert normalized_with_adjustment.facts == _base_without_adjustments().facts


def test_adjustment_materialization_is_explicit_stale_safe_and_idempotent():
    normalized = _base_without_adjustments()
    evidence_id = normalized.evidence_index[0].id
    proposed = {
        "id": "proposal-is-not-effective",
        "target_field": "restricted_cash",
        "target_period": "AS_OF_2026-09-08",
        "adjustment_type": "HAIRCUT",
        "input_value": 0.0,
        "proposed_adjusted_value": 10.0,
        "status": "PROPOSED",
        "reason": "Review only.",
        "source_evidence_ids": [evidence_id],
        "proposed_by": "LLM",
    }
    payload = normalized.model_dump(mode="python", warnings=False)
    payload["adjustments"] = [proposed]
    proposed_input = NormalizedCompanyInput.model_validate(payload)
    assert materialize_effective_input(proposed_input).facts == proposed_input.facts

    stale = deepcopy(proposed)
    stale["id"] = "stale-accepted"
    stale["status"] = "ACCEPTED"
    stale["approved_by"] = "RULE_ENGINE"
    stale["input_value"] = 99.0
    payload["adjustments"] = [stale]
    with pytest.raises(ValueError, match="stale"):
        materialize_effective_input(NormalizedCompanyInput.model_validate(payload))

    accepted = dict(proposed)
    accepted["id"] = "accepted-idempotent"
    accepted["status"] = "ACCEPTED"
    accepted["approved_by"] = "HUMAN"
    payload["adjustments"] = [accepted]
    once = materialize_effective_input(NormalizedCompanyInput.model_validate(payload))
    twice = materialize_effective_input(once)
    assert twice == once


def test_adjustment_materialization_fails_closed_on_evidence_conflicts_and_targets():
    normalized = _base_without_adjustments()
    evidence_id = normalized.evidence_index[0].id
    common = {
        "target_field": "restricted_cash",
        "target_period": "AS_OF_2026-09-08",
        "adjustment_type": "INCLUDE",
        "input_value": 0.0,
        "status": "ACCEPTED",
        "reason": "Frozen adversarial adjustment.",
        "source_evidence_ids": [evidence_id],
        "proposed_by": "HUMAN",
        "approved_by": "HUMAN",
    }
    missing_evidence = {**common, "id": "missing-evidence", "proposed_adjusted_value": 10.0}
    with pytest.raises(ValueError, match="undefined evidence"):
        materialize_effective_input(
            normalized,
            [missing_evidence | {"source_evidence_ids": ["missing"]}],
        )

    conflicting = [
        {**common, "id": "conflict-a", "proposed_adjusted_value": 10.0},
        {**common, "id": "conflict-b", "proposed_adjusted_value": 20.0},
    ]
    with pytest.raises(ValueError, match="conflicting accepted adjustments"):
        materialize_effective_input(normalized, conflicting)

    unsupported = {
        **common,
        "id": "unsupported-target",
        "target_field": "through_return",
        "proposed_adjusted_value": 10.0,
    }
    with pytest.raises(ValueError, match="not an allowed source-side numeric fact"):
        materialize_effective_input(normalized, [unsupported])


def _filing_fixture() -> tuple[dict, dict, dict, dict]:
    discovery = json.loads((ROOT / "fixtures/filings/discovery_a_h.json").read_text())
    document = json.loads((ROOT / "fixtures/filings/document_payloads.json").read_text())
    extraction = json.loads((ROOT / "fixtures/filings/extraction_payloads.json").read_text())
    evidence = json.loads((ROOT / "fixtures/filings/evidence_store_payloads.json").read_text())
    return discovery["a_cninfo"], document["a_cninfo"], extraction["a_annual_pdf"], evidence[
        "a_annual_support"
    ]


def test_phase3_official_filing_to_accepted_adjustment_to_decision_trace(tmp_path: Path):
    discovery, document_payload, extraction_payload, evidence_payload = _filing_fixture()
    discovery_calls: list[FilingDiscoveryQuery] = []

    def discover(query: FilingDiscoveryQuery) -> list[dict]:
        discovery_calls.append(query)
        return deepcopy(discovery["filings"])

    discovery_provider = OfficialFilingDiscoveryProvider(
        {
            FilingSource.CNINFO: FilingDiscoverySourceClient(
                source=FilingSource.CNINFO,
                source_uri=discovery["source_uri"],
                discover=discover,
            )
        },
        clock=lambda: RETRIEVED_AT,
    )
    discovery_query = FilingDiscoveryQuery(
        listing_id="SH600000",
        source=FilingSource.CNINFO,
        as_of="2026-09-08",
    )
    raw_cache = FilesystemRawResponseCache(tmp_path / "filing-raw")
    live_discovery = fetch_filing_discovery_with_cache(
        discovery_provider,
        discovery_query.to_provider_request(),
        raw_cache,
    )
    replay_discovery = fetch_filing_discovery_with_cache(
        discovery_provider,
        discovery_query.to_provider_request(),
        raw_cache,
        offline=True,
    )
    assert live_discovery.record == replay_discovery.record
    assert len(discovery_calls) == 1
    filing = parse_filing_discovery_record(replay_discovery.record).filings[0]

    content = base64.b64decode(document_payload["content_base64"])
    download_calls: list[str] = []

    def download(received):
        download_calls.append(received.filing_id)
        return FilingDownloadPayload(
            content=content,
            media_type=document_payload["media_type"],
            response_metadata=document_payload["response_metadata"],
        )

    downloader = FilingDocumentDownloader(
        {
            filing.source: FilingDocumentSourceClient(
                source=filing.source,
                download=download,
            )
        },
        clock=lambda: RETRIEVED_AT,
    )
    document_cache = FilesystemFilingDocumentCache(tmp_path / "documents")
    live_document = fetch_filing_document_with_cache(downloader, filing, document_cache)
    replay_document = fetch_filing_document_with_cache(
        downloader,
        filing,
        document_cache,
        offline=True,
    )
    assert live_document.document == replay_document.document
    assert download_calls == [filing.filing_id]

    parser = FilingDocumentTextParser(
        media_type="application/pdf",
        parser_id="phase-3-frozen-parser",
        parser_version="1",
        parse=lambda _document: deepcopy(extraction_payload["blocks"]),
    )
    extraction = FilingReportExtractor({"application/pdf": parser}).extract(
        replay_document.document
    )
    evidence_store = FilingEvidenceStore(tmp_path / "evidence")
    evidence = evidence_store.append(
        extraction,
        deepcopy(evidence_payload["evidence"]),
        block_sequence=evidence_payload["block_sequence"],
        document=replay_document.document,
    )

    workflow = AdjustmentProposalWorkflow(tmp_path / "adjustments")
    proposal = {
        "target_field": "restricted_cash",
        "target_period": "AS_OF_2026-09-08",
        "adjustment_type": "INCLUDE",
        "input_value": 0.0,
        "proposed_adjusted_value": 20.0,
        "status": "PROPOSED",
        "reason": "Frozen official filing adjustment proposal.",
        "source_evidence_ids": [evidence.id],
        "proposed_by": "LLM",
        "confidence": 0.9,
    }
    proposed_adjustment = workflow.append(proposal, evidence_store=evidence_store)
    accepted_adjustment = workflow.accept(
        proposed_adjustment.id,
        actor="HUMAN",
        evidence_store=evidence_store,
    )
    assert accepted_adjustment.status is AdjustmentStatus.ACCEPTED
    assert accepted_adjustment.approved_by.value == "HUMAN"

    base = _base_without_adjustments()
    input_payload = base.model_dump(mode="python", warnings=False)
    input_payload["evidence_index"] = [*input_payload["evidence_index"], evidence]
    input_payload["adjustments"] = [accepted_adjustment]
    normalized = NormalizedCompanyInput.model_validate(input_payload)
    source = next(
        fact
        for fact in normalized.facts
        if fact.field == "restricted_cash" and fact.period == "AS_OF_2026-09-08"
    )
    analysis = run_analyze_with_accepted_adjustments(normalized)
    _validate_normalized(materialize_effective_input(normalized))
    _validate_analysis(analysis)
    effective = next(
        fact
        for fact in analysis.facts
        if fact.field == "restricted_cash" and fact.period == "AS_OF_2026-09-08"
    )
    assert source.value == 0
    assert effective.value == 20.0
    assert effective.source_fact_id == source.id
    assert effective.applied_adjustment_ids == [accepted_adjustment.id]

    trace = build_decision_trace(analysis)
    assert any(filing_node.filing_id == filing.filing_id for filing_node in trace.filings)
    assert any(
        link.fact_id == effective.id
        and accepted_adjustment.id in link.adjustment_ids
        and link.filing_id == filing.filing_id
        and link.metric == "net_cash"
        for link in trace.links
    )
    assert trace.decision_state == analysis.decision.state.value
