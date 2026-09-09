import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from turtle_value_engine.models import Company
from turtle_value_engine.providers import (
    AKSHARE_MAPPING_VERSION,
    AKShareProvider,
    DataCategory,
    FilesystemRawResponseCache,
    ProviderNormalizationError,
    ProviderRequest,
    ProviderRequestError,
    ProviderResponseError,
    RetrievalMode,
    fetch_akshare_with_cache,
    normalize_akshare_records,
    normalize_listing_id,
)

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "providers" / "akshare"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "normalized-input.schema.json"
RETRIEVED_AT = datetime(2026, 9, 9, 16, 0, tzinfo=UTC)


def _fixture(name: str):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class FakeAKShare:
    __version__ = "fixture-akshare"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail = False

    def _return(self, endpoint: str, payload, **kwargs):
        self.calls.append((endpoint, kwargs))
        if self.fail:
            raise RuntimeError("network must not be used")
        return payload

    def stock_info_a_code_name(self):
        return self._return("stock_info_a_code_name", _fixture("a_code_name.json"))

    def stock_hk_company_profile_em(self, *, symbol: str):
        return self._return(
            "stock_hk_company_profile_em",
            _fixture("h_company_profile.json"),
            symbol=symbol,
        )

    def stock_hk_security_profile_em(self, *, symbol: str):
        return self._return(
            "stock_hk_security_profile_em",
            _fixture("h_security_profile.json"),
            symbol=symbol,
        )

    def stock_zh_a_st_em(self):
        return self._return("stock_zh_a_st_em", _fixture("a_risk_warning_status.json"))

    def stock_zh_a_spot_em(self):
        return self._return("stock_zh_a_spot_em", _fixture("a_quote.json"))

    def stock_hk_spot_em(self):
        return self._return("stock_hk_spot_em", _fixture("h_quote.json"))

    def stock_zh_a_hist(self, **kwargs):
        return self._return("stock_zh_a_hist", _fixture("a_history.json"), **kwargs)

    def stock_hk_daily(self, **kwargs):
        return self._return("stock_hk_daily", _fixture("h_history.json"), **kwargs)

    def stock_cash_flow_sheet_by_report_em(self, **kwargs):
        return self._return(
            "stock_cash_flow_sheet_by_report_em",
            _fixture("a_cash_flow.json"),
            **kwargs,
        )

    def stock_profit_sheet_by_report_em(self, **kwargs):
        return self._return(
            "stock_profit_sheet_by_report_em",
            _fixture("a_income_statement.json"),
            **kwargs,
        )

    def stock_yjyg_em(self, *, date: str):
        return self._return(
            "stock_yjyg_em",
            _fixture("a_earnings_forecast.json"),
            date=date,
        )

    def stock_yjkb_em(self, *, date: str):
        return self._return(
            "stock_yjkb_em",
            _fixture("a_earnings_quick_report.json"),
            date=date,
        )

    def stock_yjbb_em(self, *, date: str):
        return self._return(
            "stock_yjbb_em",
            _fixture("a_performance_report.json"),
            date=date,
        )

    def stock_zygc_em(self, *, symbol: str):
        return self._return(
            "stock_zygc_em",
            _fixture("a_business_composition.json"),
            symbol=symbol,
        )

    def stock_financial_abstract(self, *, symbol: str):
        return self._return(
            "stock_financial_abstract",
            _fixture("a_financial_abstract.json"),
            symbol=symbol,
        )

    def stock_financial_analysis_indicator_em(self, *, symbol: str, indicator: str):
        return self._return(
            "stock_financial_analysis_indicator_em",
            _fixture("a_financial_indicators.json"),
            symbol=symbol,
            indicator=indicator,
        )

    def stock_financial_hk_analysis_indicator_em(self, *, symbol: str, indicator: str):
        return self._return(
            "stock_financial_hk_analysis_indicator_em",
            _fixture("h_financial_indicators.json"),
            symbol=symbol,
            indicator=indicator,
        )

    def stock_hk_financial_indicator_em(self, *, symbol: str):
        return self._return(
            "stock_hk_financial_indicator_em",
            _fixture("h_latest_indicators.json"),
            symbol=symbol,
        )

    def stock_balance_sheet_by_report_em(self, **kwargs):
        return self._return(
            "stock_balance_sheet_by_report_em",
            _fixture("a_balance_sheet.json"),
            **kwargs,
        )

    def stock_zh_a_gbjg_em(self, *, symbol: str):
        return self._return(
            "stock_zh_a_gbjg_em",
            _fixture("a_share_capital.json"),
            symbol=symbol,
        )

    def stock_share_change_cninfo(self, **kwargs):
        return self._return(
            "stock_share_change_cninfo",
            _fixture("a_share_change_cninfo.json"),
            **kwargs,
        )

    def stock_financial_hk_report_em(self, **kwargs):
        return self._return(
            "stock_financial_hk_report_em",
            _fixture(
                "h_balance_sheet.json"
                if kwargs.get("symbol") == "资产负债表"
                else (
                    "h_income_statement.json"
                    if kwargs.get("symbol") == "利润表"
                    else "h_cash_flow.json"
                )
            ),
            **kwargs,
        )

    def stock_dividend_cninfo(self, **kwargs):
        return self._return(
            "stock_dividend_cninfo",
            _fixture("a_dividends.json"),
            **kwargs,
        )

    def stock_fhps_em(self, *, date: str):
        return self._return(
            "stock_fhps_em",
            _fixture("a_dividend_snapshot.json"),
            date=date,
        )

    def stock_hk_dividend_payout_em(self, **kwargs):
        return self._return(
            "stock_hk_dividend_payout_em",
            _fixture("h_dividends.json"),
            **kwargs,
        )

    def stock_hk_fhpx_detail_ths(self, *, symbol: str):
        return self._return(
            "stock_hk_fhpx_detail_ths",
            _fixture("h_dividend_detail_ths.json"),
            symbol=symbol,
        )

    def stock_zh_a_disclosure_report_cninfo(self, **kwargs):
        return self._return(
            "stock_zh_a_disclosure_report_cninfo",
            _fixture("a_disclosure_report.json"),
            **kwargs,
        )

    def stock_repurchase_em(self):
        return self._return("stock_repurchase_em", _fixture("a_repurchase.json"))

    def stock_allotment_cninfo(self, **kwargs):
        return self._return(
            "stock_allotment_cninfo",
            _fixture("a_allotment.json"),
            **kwargs,
        )

    def stock_gpzy_pledge_ratio_em(self, *, date: str):
        return self._return(
            "stock_gpzy_pledge_ratio_em",
            _fixture("a_ownership_pledge.json"),
            date=date,
        )

    def stock_share_hold_change_sse(self, *, symbol: str):
        return self._return(
            "stock_share_hold_change_sse",
            _fixture("a_insider_share_change.json"),
            symbol=symbol,
        )

    def stock_share_hold_change_szse(self, *, symbol: str):
        return self._return(
            "stock_share_hold_change_szse",
            _fixture("a_insider_share_change_szse.json"),
            symbol=symbol,
        )

    def stock_share_hold_change_bse(self, *, symbol: str):
        return self._return(
            "stock_share_hold_change_bse",
            _fixture("a_insider_share_change_bse.json"),
            symbol=symbol,
        )


class OfficialBalanceAKShare:
    __version__ = "fixture-akshare-official-balance"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def stock_zcfz_em(self, *, date: str):
        self.calls.append(("stock_zcfz_em", {"date": date}))
        return _fixture("a_balance_sheet_official.json")


def _request(category: DataCategory, entity_id: str, parameters: dict | None = None):
    return ProviderRequest(
        category=category,
        entity_id=entity_id,
        parameters={} if parameters is None else parameters,
    )


def _company(primary_listing: str = "SH600000") -> Company:
    return Company(
        name="Fixture company",
        primary_listing=primary_listing,
        sector="fixture-sector",
        reporting_currency="CNY" if primary_listing.startswith(("SH", "SZ", "BJ")) else "HKD",
    )


def _provider(fake: FakeAKShare | None = None) -> AKShareProvider:
    return AKShareProvider(
        fake or FakeAKShare(),
        clock=lambda: RETRIEVED_AT,
    )


def test_listing_id_normalization_accepts_common_a_and_h_forms():
    assert normalize_listing_id("600000") == "SH600000"
    assert normalize_listing_id("000001.SZ") == "SZ000001"
    assert normalize_listing_id("A:600000") == "SH600000"
    assert normalize_listing_id("700.HK") == "HK00700"
    assert normalize_listing_id("H:00700") == "HK00700"


def test_akshare_capabilities_are_exact_and_provider_import_is_lazy():
    provider = _provider()

    assert provider.capabilities.as_values() == (
        "balance_sheet",
        "business_composition",
        "cash_flow_statement",
        "company_metadata",
        "corporate_actions",
        "disclosure_notices",
        "dividends",
        "earnings_forecast",
        "earnings_quick_report",
        "financial_abstract",
        "financial_indicators",
        "income_statement",
        "insider_share_changes",
        "latest_indicators",
        "listing_metadata",
        "market_history",
        "market_quote",
        "ownership_pledge",
        "performance_report",
        "risk_warning_status",
        "share_capital",
    )
    assert provider.identity.provider_id == "akshare"
    assert provider.identity.provider_version == "26"
    assert AKSHARE_MAPPING_VERSION == "27"


def test_a_risk_warning_fetch_filters_the_documented_current_universe():
    fake = FakeAKShare()
    provider = _provider(fake)
    record = provider.fetch(_request(DataCategory.RISK_WARNING_STATUS, "SH600000"))

    fixture = _fixture("a_risk_warning_status.json")
    assert record.raw_payload == [row for row in fixture if row["代码"] == "600000"]
    assert fake.calls == [("stock_zh_a_st_em", {})]
    assert record.response_metadata["endpoint"] == "stock_zh_a_st_em"
    assert record.response_metadata["upstream_row_count"] == 2
    assert record.response_metadata["entity_row_count"] == 1
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is False
    assert record.response_metadata["row_filtering"] == "provider"
    assert record.response_metadata["snapshot_scope"] == "current_trading_day"
    assert record.source_uri == "https://quote.eastmoney.com/center/gridlist.html#st_board"


def test_risk_warning_request_is_a_share_only_and_accepts_no_parameters():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="does not accept request parameters"):
        provider.fetch(
            _request(
                DataCategory.RISK_WARNING_STATUS,
                "SH600000",
                {"date": "20241220"},
            )
        )
    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        provider.fetch(_request(DataCategory.RISK_WARNING_STATUS, "HK00700"))

    assert fake.calls == []


def test_risk_warning_response_rejects_a_universe_row_without_listing_code():
    class MissingListingCode(FakeAKShare):
        def stock_zh_a_st_em(self):
            return self._return(
                "stock_zh_a_st_em",
                [{"代码": None, "名称": "invalid"}],
            )

    with pytest.raises(ProviderResponseError, match="risk-warning-status row without"):
        _provider(MissingListingCode()).fetch(
            _request(DataCategory.RISK_WARNING_STATUS, "SH600000")
        )


def test_risk_warning_raw_record_is_not_promoted_to_special_treatment():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.RISK_WARNING_STATUS, "SH600000"))
    normalized = normalize_akshare_records(
        [record],
        analysis_id="risk-warning-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_RISK_WARNING_STATUS_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == ["special_treatment"]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "special_treatment=False" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_risk_warning_with_no_matching_listing_is_an_empty_raw_snapshot():
    class NoRiskWarning(FakeAKShare):
        def stock_zh_a_st_em(self):
            return self._return(
                "stock_zh_a_st_em",
                [{"代码": "000001", "名称": "*ST示例科技"}],
            )

    fake = NoRiskWarning()
    record = _provider(fake).fetch(
        _request(DataCategory.RISK_WARNING_STATUS, "SH600000")
    )

    assert record.raw_payload == []
    assert record.response_metadata["upstream_row_count"] == 1
    assert record.response_metadata["entity_row_count"] == 0


def test_risk_warning_normalizer_rejects_replayed_rows_for_another_listing():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.RISK_WARNING_STATUS, "SH600000"))
    mismatched_payload = [dict(row) for row in record.raw_payload]
    mismatched_payload[0]["代码"] = "000001"
    mismatched = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=mismatched_payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="risk-warning-status row entity"):
        normalize_akshare_records(
            [mismatched],
            analysis_id="mismatched-risk-warning-entity",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_risk_warning_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(DataCategory.RISK_WARNING_STATUS, "SH600000")

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [("stock_zh_a_st_em", {})]


def test_a_quote_is_selected_from_the_upstream_universe_and_kept_opaque():
    fake = FakeAKShare()
    provider = _provider(fake)
    record = provider.fetch(_request(DataCategory.MARKET_QUOTE, "SH600000"))

    assert record.request.entity_id == "SH600000"
    assert record.raw_payload["代码"] == "600000"
    assert record.raw_payload["最新价"] == 10.5
    assert record.response_metadata["endpoint"] == "stock_zh_a_spot_em"
    assert record.response_metadata["library_version"] == "fixture-akshare"
    assert fake.calls == [("stock_zh_a_spot_em", {})]


def test_h_history_uses_hk_symbol_and_keeps_range_parameters_in_cache_identity():
    fake = FakeAKShare()
    provider = _provider(fake)
    request = _request(
        DataCategory.MARKET_HISTORY,
        "HK00700",
        {"start_date": "2026-09-09", "end_date": "2026-09-09", "adjust": ""},
    )
    record = provider.fetch(request)

    assert record.raw_payload == _fixture("h_history.json")
    assert fake.calls == [("stock_hk_daily", {"symbol": "00700", "adjust": ""})]
    assert record.response_metadata["range_filtering"] == "normalizer"


def test_cash_flow_fetch_uses_market_specific_read_only_endpoints():
    fake = FakeAKShare()
    provider = _provider(fake)

    a_record = provider.fetch(_request(DataCategory.CASH_FLOW_STATEMENT, "SH600000"))
    h_record = provider.fetch(
        _request(DataCategory.CASH_FLOW_STATEMENT, "HK00700", {"indicator": "annual"})
    )

    assert a_record.raw_payload == _fixture("a_cash_flow.json")
    assert h_record.raw_payload == _fixture("h_cash_flow.json")
    assert fake.calls == [
        ("stock_cash_flow_sheet_by_report_em", {"symbol": "SH600000"}),
        (
            "stock_financial_hk_report_em",
            {"stock": "00700", "symbol": "现金流量表", "indicator": "年度"},
        ),
    ]


def test_income_statement_fetch_uses_market_specific_read_only_endpoints():
    fake = FakeAKShare()
    provider = _provider(fake)

    a_record = provider.fetch(_request(DataCategory.INCOME_STATEMENT, "SH600000"))
    h_record = provider.fetch(
        _request(DataCategory.INCOME_STATEMENT, "HK00700", {"indicator": "annual"})
    )

    assert a_record.raw_payload == _fixture("a_income_statement.json")
    assert h_record.raw_payload == _fixture("h_income_statement.json")
    assert fake.calls == [
        ("stock_profit_sheet_by_report_em", {"symbol": "SH600000"}),
        (
            "stock_financial_hk_report_em",
            {"stock": "00700", "symbol": "利润表", "indicator": "年度"},
        ),
    ]


def test_balance_sheet_fetch_uses_market_specific_read_only_endpoints():
    fake = FakeAKShare()
    provider = _provider(fake)

    a_record = provider.fetch(_request(DataCategory.BALANCE_SHEET, "SH600000"))
    h_record = provider.fetch(
        _request(DataCategory.BALANCE_SHEET, "HK00700", {"indicator": "annual"})
    )

    assert a_record.raw_payload == _fixture("a_balance_sheet.json")
    assert h_record.raw_payload == _fixture("h_balance_sheet.json")
    assert fake.calls == [
        ("stock_balance_sheet_by_report_em", {"symbol": "SH600000"}),
        (
            "stock_financial_hk_report_em",
            {"stock": "00700", "symbol": "资产负债表", "indicator": "年度"},
        ),
    ]


def test_a_share_capital_fetch_uses_documented_listing_scoped_history_endpoint():
    fake = FakeAKShare()
    provider = _provider(fake)
    record = provider.fetch(_request(DataCategory.SHARE_CAPITAL, "SH600000"))

    assert record.raw_payload == _fixture("a_share_capital.json")
    assert fake.calls == [
        ("stock_zh_a_gbjg_em", {"symbol": "600000"}),
    ]
    assert record.response_metadata["endpoint"] == "stock_zh_a_gbjg_em"
    assert record.response_metadata["upstream_row_count"] == 2
    assert record.response_metadata["listing_scoped_request"] is True
    assert record.source_uri == (
        "https://emweb.securities.eastmoney.com/pc_hsf10/pages/index.html#/gbjg"
    )


def test_share_capital_endpoint_rejects_parameters_and_h_share_requests_before_upstream_call():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="does not accept request parameters"):
        provider.fetch(
            _request(
                DataCategory.SHARE_CAPITAL,
                "SH600000",
                {"unexpected": "value"},
            )
        )
    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        provider.fetch(_request(DataCategory.SHARE_CAPITAL, "HK00700"))

    assert fake.calls == []


def test_a_share_change_fetch_uses_documented_listing_and_date_range_contract():
    fake = FakeAKShare()
    provider = _provider(fake)
    request = _request(
        DataCategory.SHARE_CAPITAL,
        "SH600000",
        {"start_date": "20180101", "end_date": "20241231"},
    )

    record = provider.fetch(request)

    assert record.raw_payload == _fixture("a_share_change_cninfo.json")
    assert fake.calls == [
        (
            "stock_share_change_cninfo",
            {"symbol": "600000", "start_date": "20180101", "end_date": "20241231"},
        )
    ]
    assert record.response_metadata["endpoint"] == "stock_share_change_cninfo"
    assert record.response_metadata["upstream_row_count"] == 2
    assert record.response_metadata["listing_scoped_request"] is True
    assert record.response_metadata["range_filtering"] == "provider"
    assert record.response_metadata["start_date"] == "20180101"
    assert record.response_metadata["end_date"] == "20241231"
    assert record.source_uri == "https://webapi.cninfo.com.cn/#/apiDoc"


def test_a_share_change_response_rejects_an_explicit_cross_listing_row():
    class WrongEntityAKShare(FakeAKShare):
        def stock_share_change_cninfo(self, **kwargs):
            payload = _fixture("a_share_change_cninfo.json")
            payload[0]["证券代码"] = "000001"
            return self._return("stock_share_change_cninfo", payload, **kwargs)

    fake = WrongEntityAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderResponseError, match="share-capital row entity"):
        provider.fetch(
            _request(
                DataCategory.SHARE_CAPITAL,
                "SH600000",
                {"start_date": "20180101", "end_date": "20241231"},
            )
        )
    assert fake.calls == [
        (
            "stock_share_change_cninfo",
            {"symbol": "600000", "start_date": "20180101", "end_date": "20241231"},
        )
    ]


def test_a_share_change_request_uses_documented_default_date_range_when_partly_omitted():
    fake = FakeAKShare()
    provider = _provider(fake)

    provider.fetch(
        _request(DataCategory.SHARE_CAPITAL, "SH600000", {"start_date": "20180101"})
    )

    assert fake.calls == [
        (
            "stock_share_change_cninfo",
            {"symbol": "600000", "start_date": "20180101", "end_date": "20241021"},
        )
    ]


def test_a_share_change_request_validates_date_range_and_parameters_before_upstream_call():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="share-capital start_date must be YYYYMMDD"):
        provider.fetch(
            _request(
                DataCategory.SHARE_CAPITAL,
                "SH600000",
                {"start_date": "2024-01-01"},
            )
        )
    with pytest.raises(ProviderRequestError, match="share-capital start_date must not be after"):
        provider.fetch(
            _request(
                DataCategory.SHARE_CAPITAL,
                "SH600000",
                {"start_date": "20250101", "end_date": "20240101"},
            )
        )
    with pytest.raises(ProviderRequestError, match="unsupported AKShare share-capital"):
        provider.fetch(
            _request(
                DataCategory.SHARE_CAPITAL,
                "SH600000",
                {"start_date": "20240101", "reason": "配股"},
            )
        )
    assert fake.calls == []


def test_share_capital_raw_record_is_not_promoted_to_a_canonical_diluted_share_fact():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.SHARE_CAPITAL, "SH600000"))
    normalized = normalize_akshare_records(
        [record],
        analysis_id="share-capital-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_SHARE_CAPITAL_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "normalized_diluted_economic_shares",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "canonical share-count fact" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_share_capital_raw_record_replays_offline_without_calling_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(DataCategory.SHARE_CAPITAL, "SH600000")

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [("stock_zh_a_gbjg_em", {"symbol": "600000"})]


def test_a_share_change_raw_record_is_not_promoted_to_a_canonical_share_fact():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.SHARE_CAPITAL,
            "SH600000",
            {"start_date": "20180101", "end_date": "20241231"},
        )
    )
    normalized = normalize_akshare_records(
        [record],
        analysis_id="share-change-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_SHARE_CAPITAL_CHANGE_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "normalized_diluted_economic_shares",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "canonical period, unit or diluted economic share scope" in (
        normalized.data_quality.notes
    )

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_a_share_change_normalizer_rejects_replayed_rows_for_another_listing():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.SHARE_CAPITAL,
            "SH600000",
            {"start_date": "20180101", "end_date": "20241231"},
        )
    )
    mismatched_payload = [dict(row) for row in record.raw_payload]
    mismatched_payload[0]["证券代码"] = "000001"
    mismatched = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=mismatched_payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="share-capital row entity"):
        normalize_akshare_records(
            [mismatched],
            analysis_id="mismatched-share-change-entity",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_a_share_change_raw_record_replays_offline_without_calling_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.SHARE_CAPITAL,
        "SH600000",
        {"start_date": "20180101", "end_date": "20241231"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        (
            "stock_share_change_cninfo",
            {"symbol": "600000", "start_date": "20180101", "end_date": "20241231"},
        )
    ]


def test_a_ownership_pledge_fetch_uses_exact_date_and_filters_the_universe():
    fake = FakeAKShare()
    provider = _provider(fake)
    request = _request(
        DataCategory.OWNERSHIP_PLEDGE,
        "SH600000",
        {"date": "20241220"},
    )

    record = provider.fetch(request)

    fixture = _fixture("a_ownership_pledge.json")
    assert record.raw_payload == [row for row in fixture if row["股票代码"] == "600000"]
    assert fake.calls == [
        ("stock_gpzy_pledge_ratio_em", {"date": "20241220"}),
    ]
    assert record.response_metadata["endpoint"] == "stock_gpzy_pledge_ratio_em"
    assert record.response_metadata["upstream_row_count"] == 2
    assert record.response_metadata["entity_row_count"] == 1
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is False
    assert record.response_metadata["row_filtering"] == "provider"
    assert record.response_metadata["requested_date"] == "20241220"
    assert record.response_metadata["observation_date"] == "2024-12-20"
    assert record.source_uri == "https://data.eastmoney.com/gpzy/pledgeRatio.aspx"


def test_ownership_pledge_request_requires_a_valid_date_and_a_share_listing():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="requires date"):
        provider.fetch(_request(DataCategory.OWNERSHIP_PLEDGE, "SH600000"))
    with pytest.raises(ProviderRequestError, match="must be YYYYMMDD"):
        provider.fetch(
            _request(
                DataCategory.OWNERSHIP_PLEDGE,
                "SH600000",
                {"date": "2024-12-20"},
            )
        )
    with pytest.raises(ProviderRequestError, match="must be a valid YYYYMMDD date"):
        provider.fetch(
            _request(
                DataCategory.OWNERSHIP_PLEDGE,
                "SH600000",
                {"date": "20241320"},
            )
        )
    with pytest.raises(ProviderRequestError, match="unsupported AKShare ownership-pledge"):
        provider.fetch(
            _request(
                DataCategory.OWNERSHIP_PLEDGE,
                "SH600000",
                {"date": "20241220", "market": "A"},
            )
        )
    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        provider.fetch(
            _request(
                DataCategory.OWNERSHIP_PLEDGE,
                "HK00700",
                {"date": "20241220"},
            )
        )

    assert fake.calls == []


def test_ownership_pledge_response_rejects_a_row_for_another_observation_date():
    class WrongDateAKShare(FakeAKShare):
        def stock_gpzy_pledge_ratio_em(self, *, date: str):
            payload = _fixture("a_ownership_pledge.json")
            payload[0]["交易日期"] = "2024-12-19"
            return self._return("stock_gpzy_pledge_ratio_em", payload, date=date)

    with pytest.raises(ProviderResponseError, match="ownership-pledge row date"):
        _provider(WrongDateAKShare()).fetch(
            _request(
                DataCategory.OWNERSHIP_PLEDGE,
                "SH600000",
                {"date": "20241220"},
            )
        )


def test_ownership_pledge_raw_record_is_not_promoted_to_governance_or_cash_facts():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.OWNERSHIP_PLEDGE,
            "SH600000",
            {"date": "20241220"},
        )
    )
    normalized = normalize_akshare_records(
        [record],
        analysis_id="ownership-pledge-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_OWNERSHIP_PLEDGE_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "governance_risk_level",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "governance-risk conclusion" in normalized.data_quality.notes
    assert "pledged cash amount" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_ownership_pledge_normalizer_rejects_replayed_rows_for_another_listing():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.OWNERSHIP_PLEDGE,
            "SH600000",
            {"date": "20241220"},
        )
    )
    mismatched_payload = [dict(row) for row in record.raw_payload]
    mismatched_payload[0]["股票代码"] = "000001"
    mismatched = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=mismatched_payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="ownership-pledge row entity"):
        normalize_akshare_records(
            [mismatched],
            analysis_id="mismatched-ownership-pledge",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_ownership_pledge_with_no_matching_listing_is_an_empty_raw_snapshot():
    class NoPledge(FakeAKShare):
        def stock_gpzy_pledge_ratio_em(self, *, date: str):
            return self._return(
                "stock_gpzy_pledge_ratio_em",
                [{"股票代码": "000001", "交易日期": "2024-12-20"}],
                date=date,
            )

    fake = NoPledge()
    record = _provider(fake).fetch(
        _request(
            DataCategory.OWNERSHIP_PLEDGE,
            "SH600000",
            {"date": "20241220"},
        )
    )

    assert record.raw_payload == []
    assert record.response_metadata["upstream_row_count"] == 1
    assert record.response_metadata["entity_row_count"] == 0


def test_ownership_pledge_rejects_a_universe_row_without_an_explicit_listing_code():
    class MissingListingCode(FakeAKShare):
        def stock_gpzy_pledge_ratio_em(self, *, date: str):
            return self._return(
                "stock_gpzy_pledge_ratio_em",
                [{"股票代码": None, "交易日期": "2024-12-20"}],
                date=date,
            )

    with pytest.raises(ProviderResponseError, match="ownership-pledge row without a listing code"):
        _provider(MissingListingCode()).fetch(
            _request(
                DataCategory.OWNERSHIP_PLEDGE,
                "SH600000",
                {"date": "20241220"},
            )
        )


def test_ownership_pledge_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.OWNERSHIP_PLEDGE,
        "SH600000",
        {"date": "20241220"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        ("stock_gpzy_pledge_ratio_em", {"date": "20241220"}),
    ]


def test_insider_share_change_fetch_uses_listing_scoped_sse_endpoint():
    fake = FakeAKShare()
    record = _provider(fake).fetch(
        _request(DataCategory.INSIDER_SHARE_CHANGES, "SH600000")
    )

    assert record.raw_payload == _fixture("a_insider_share_change.json")
    assert fake.calls == [
        ("stock_share_hold_change_sse", {"symbol": "600000"}),
    ]
    assert record.response_metadata["endpoint"] == "stock_share_hold_change_sse"
    assert record.response_metadata["upstream_row_count"] == 2
    assert record.response_metadata["entity_row_count"] == 2
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is True
    assert record.source_uri == (
        "http://www.sse.com.cn/disclosure/credibility/supervision/change/"
    )


def test_insider_share_change_fetch_uses_listing_scoped_szse_endpoint():
    fake = FakeAKShare()
    record = _provider(fake).fetch(
        _request(DataCategory.INSIDER_SHARE_CHANGES, "SZ000001")
    )

    assert record.raw_payload == _fixture("a_insider_share_change_szse.json")
    assert fake.calls == [
        ("stock_share_hold_change_szse", {"symbol": "000001"}),
    ]
    assert record.response_metadata["endpoint"] == "stock_share_hold_change_szse"
    assert record.response_metadata["upstream_row_count"] == 2
    assert record.response_metadata["entity_row_count"] == 2
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is True
    assert record.source_uri == (
        "http://www.szse.cn/disclosure/supervision/change/index.html"
    )


def test_insider_share_change_fetch_uses_listing_scoped_bse_endpoint():
    fake = FakeAKShare()
    record = _provider(fake).fetch(
        _request(DataCategory.INSIDER_SHARE_CHANGES, "BJ430489")
    )

    assert record.raw_payload == _fixture("a_insider_share_change_bse.json")
    assert fake.calls == [
        ("stock_share_hold_change_bse", {"symbol": "430489"}),
    ]
    assert record.response_metadata["endpoint"] == "stock_share_hold_change_bse"
    assert record.response_metadata["upstream_row_count"] == 2
    assert record.response_metadata["entity_row_count"] == 2
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is True
    assert record.source_uri == (
        "https://www.bse.cn/disclosure/djg_sharehold_change.html"
    )


def test_insider_share_change_request_supports_mainland_exchanges_and_has_no_parameters():
    fake = FakeAKShare()
    provider = _provider(fake)

    provider.fetch(_request(DataCategory.INSIDER_SHARE_CHANGES, "SZ000001"))
    provider.fetch(_request(DataCategory.INSIDER_SHARE_CHANGES, "BJ430489"))
    with pytest.raises(
        ProviderRequestError,
        match="Shanghai, Shenzhen and Beijing A-share listings only",
    ):
        provider.fetch(_request(DataCategory.INSIDER_SHARE_CHANGES, "HK00700"))
    with pytest.raises(ProviderRequestError, match="unsupported AKShare insider-share-change"):
        provider.fetch(
            _request(
                DataCategory.INSIDER_SHARE_CHANGES,
                "SH600000",
                {"start_date": "20240101"},
            )
        )

    assert fake.calls == [
        ("stock_share_hold_change_szse", {"symbol": "000001"}),
        ("stock_share_hold_change_bse", {"symbol": "430489"}),
    ]


def test_insider_share_change_response_rejects_missing_or_cross_listing_rows():
    class MissingListingCode(FakeAKShare):
        def stock_share_hold_change_sse(self, *, symbol: str):
            return self._return(
                "stock_share_hold_change_sse",
                [{"公司代码": None, "变动日期": "2021-07-15"}],
                symbol=symbol,
            )

    with pytest.raises(
        ProviderResponseError,
        match="insider-share-change row without a listing code",
    ):
        _provider(MissingListingCode()).fetch(
            _request(DataCategory.INSIDER_SHARE_CHANGES, "SH600000")
        )

    class WrongEntity(FakeAKShare):
        def stock_share_hold_change_sse(self, *, symbol: str):
            payload = _fixture("a_insider_share_change.json")
            payload[0]["公司代码"] = "600004"
            return self._return("stock_share_hold_change_sse", payload, symbol=symbol)

    with pytest.raises(ProviderResponseError, match="insider-share-change row entity"):
        _provider(WrongEntity()).fetch(
            _request(DataCategory.INSIDER_SHARE_CHANGES, "SH600000")
        )


def test_insider_share_change_response_rejects_invalid_event_dates():
    class InvalidDate(FakeAKShare):
        def stock_share_hold_change_sse(self, *, symbol: str):
            payload = _fixture("a_insider_share_change.json")
            payload[0]["变动日期"] = "not-a-date"
            return self._return("stock_share_hold_change_sse", payload, symbol=symbol)

    with pytest.raises(ProviderResponseError, match="invalid 变动日期"):
        _provider(InvalidDate()).fetch(
            _request(DataCategory.INSIDER_SHARE_CHANGES, "SH600000")
        )


def test_bse_insider_share_change_response_rejects_cross_listing_rows_and_invalid_dates():
    class WrongEntity(FakeAKShare):
        def stock_share_hold_change_bse(self, *, symbol: str):
            payload = _fixture("a_insider_share_change_bse.json")
            payload[0]["代码"] = "830000"
            return self._return("stock_share_hold_change_bse", payload, symbol=symbol)

    with pytest.raises(ProviderResponseError, match="insider-share-change row entity"):
        _provider(WrongEntity()).fetch(
            _request(DataCategory.INSIDER_SHARE_CHANGES, "BJ430489")
        )

    class InvalidDate(FakeAKShare):
        def stock_share_hold_change_bse(self, *, symbol: str):
            payload = _fixture("a_insider_share_change_bse.json")
            payload[0]["变动日期"] = "not-a-date"
            return self._return("stock_share_hold_change_bse", payload, symbol=symbol)

    with pytest.raises(ProviderResponseError, match="invalid 变动日期"):
        _provider(InvalidDate()).fetch(
            _request(DataCategory.INSIDER_SHARE_CHANGES, "BJ430489")
        )


def test_insider_share_change_raw_record_is_not_promoted_to_shares_or_governance():
    record = _provider().fetch(
        _request(DataCategory.INSIDER_SHARE_CHANGES, "SH600000")
    )
    normalized = normalize_akshare_records(
        [record],
        analysis_id="insider-share-change-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_INSIDER_SHARE_CHANGE_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "governance_risk_level",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "diluted-share series" in normalized.data_quality.notes
    assert "governance-risk judgment" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_szse_insider_share_change_raw_record_stays_outside_canonical_facts():
    record = _provider().fetch(
        _request(DataCategory.INSIDER_SHARE_CHANGES, "SZ000001")
    )
    normalized = normalize_akshare_records(
        [record],
        analysis_id="szse-insider-share-change-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company("SZ000001"),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_INSIDER_SHARE_CHANGE_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "governance_risk_level",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "SSE/SZSE/BSE insider-share-change" in normalized.data_quality.notes


def test_bse_insider_share_change_raw_record_stays_outside_canonical_facts():
    record = _provider().fetch(
        _request(DataCategory.INSIDER_SHARE_CHANGES, "BJ430489")
    )
    normalized = normalize_akshare_records(
        [record],
        analysis_id="bse-insider-share-change-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company("BJ430489"),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_INSIDER_SHARE_CHANGE_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "governance_risk_level",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "SSE/SZSE/BSE insider-share-change" in normalized.data_quality.notes
    assert "diluted-share series" in normalized.data_quality.notes


def test_insider_share_change_normalizer_rejects_replayed_rows_for_another_listing():
    record = _provider().fetch(
        _request(DataCategory.INSIDER_SHARE_CHANGES, "SH600000")
    )
    mismatched_payload = [dict(row) for row in record.raw_payload]
    mismatched_payload[0]["公司代码"] = "600004"
    mismatched = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=mismatched_payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="insider-share-change row entity"):
        normalize_akshare_records(
            [mismatched],
            analysis_id="mismatched-insider-share-change",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_insider_share_change_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(DataCategory.INSIDER_SHARE_CHANGES, "SH600000")

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        ("stock_share_hold_change_sse", {"symbol": "600000"}),
    ]


def test_bse_insider_share_change_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(DataCategory.INSIDER_SHARE_CHANGES, "BJ430489")

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        ("stock_share_hold_change_bse", {"symbol": "430489"}),
    ]


def test_a_rights_issue_fetch_uses_documented_listing_and_date_range_contract():
    fake = FakeAKShare()
    provider = _provider(fake)
    request = _request(
        DataCategory.CORPORATE_ACTIONS,
        "SH600000",
        {"start_date": "20180101", "end_date": "20241231"},
    )

    record = provider.fetch(request)

    assert record.raw_payload == _fixture("a_allotment.json")
    assert fake.calls == [
        (
            "stock_allotment_cninfo",
            {"symbol": "600000", "start_date": "20180101", "end_date": "20241231"},
        )
    ]
    assert record.response_metadata["endpoint"] == "stock_allotment_cninfo"
    assert record.response_metadata["upstream_row_count"] == 2
    assert record.response_metadata["listing_scoped_request"] is True
    assert record.response_metadata["action_type"] == "rights_issue"
    assert record.response_metadata["start_date"] == "20180101"
    assert record.response_metadata["end_date"] == "20241231"
    assert record.source_uri == "https://webapi.cninfo.com.cn/#/dataBrowse"


def test_rights_issue_response_rejects_an_explicit_cross_listing_row():
    class WrongEntityAKShare(FakeAKShare):
        def stock_allotment_cninfo(self, **kwargs):
            payload = _fixture("a_allotment.json")
            payload[0]["证券代码"] = "000001"
            return self._return("stock_allotment_cninfo", payload, **kwargs)

    fake = WrongEntityAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderResponseError, match="corporate-action row entity"):
        provider.fetch(
            _request(
                DataCategory.CORPORATE_ACTIONS,
                "SH600000",
                {"start_date": "20180101", "end_date": "20241231"},
            )
        )
    assert fake.calls == [
        (
            "stock_allotment_cninfo",
            {"symbol": "600000", "start_date": "20180101", "end_date": "20241231"},
        )
    ]


def test_rights_issue_request_uses_official_default_date_range_when_omitted():
    fake = FakeAKShare()
    provider = _provider(fake)

    provider.fetch(
        _request(
            DataCategory.CORPORATE_ACTIONS,
            "SH600000",
            {"start_date": "20180101"},
        )
    )

    assert fake.calls == [
        (
            "stock_allotment_cninfo",
            {"symbol": "600000", "start_date": "20180101", "end_date": "22220222"},
        )
    ]


def test_rights_issue_request_validates_date_range_and_parameters_before_upstream_call():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="start_date must be YYYYMMDD"):
        provider.fetch(
            _request(
                DataCategory.CORPORATE_ACTIONS,
                "SH600000",
                {"start_date": "2024-01-01"},
            )
        )
    with pytest.raises(ProviderRequestError, match="must not be after"):
        provider.fetch(
            _request(
                DataCategory.CORPORATE_ACTIONS,
                "SH600000",
                {"start_date": "20250101", "end_date": "20240101"},
            )
        )
    with pytest.raises(ProviderRequestError, match="unsupported AKShare corporate-action"):
        provider.fetch(
            _request(
                DataCategory.CORPORATE_ACTIONS,
                "SH600000",
                {"start_date": "20240101", "category": "配股"},
            )
        )
    assert fake.calls == []


def test_rights_issue_raw_record_is_not_promoted_to_issuance_or_dilution_facts():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.CORPORATE_ACTIONS,
            "SH600000",
            {"start_date": "20180101", "end_date": "20241231"},
        )
    )

    normalized = normalize_akshare_records(
        [record],
        analysis_id="rights-issue-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_ALLOTMENT_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == ["share_issuance_cash"]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "canonical issuance or dilution fact" in normalized.data_quality.notes
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(
        Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json"))
    ) == []


def test_rights_issue_raw_record_replays_offline_without_calling_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.CORPORATE_ACTIONS,
        "SH600000",
        {"start_date": "20180101", "end_date": "20241231"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        (
            "stock_allotment_cninfo",
            {"symbol": "600000", "start_date": "20180101", "end_date": "20241231"},
        )
    ]


def test_official_a_balance_endpoint_selects_listing_and_preserves_requested_period():
    fake = OfficialBalanceAKShare()
    provider = AKShareProvider(fake)
    record = provider.fetch(
        _request(
            DataCategory.BALANCE_SHEET,
            "SH600000",
            {"statement_date": "2024-12-31"},
        )
    )

    assert record.raw_payload == _fixture("a_balance_sheet_official.json")[0]
    assert fake.calls == [("stock_zcfz_em", {"date": "20241231"})]
    assert record.response_metadata["upstream_row_count"] == 2
    assert record.response_metadata["statement_date"] == "2024-12-31"

    normalized = normalize_akshare_records(
        [record],
        analysis_id="official-balance-sheet-fixture",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )
    values = {(fact.field, fact.period): fact for fact in normalized.facts}
    assert values[("book_cash", "2024-12-31")].value == 1600000000.0
    assert values[("total_equity", "2024-12-31")].value == 7350000000.0
    assert "reported_interest_bearing_debt" not in {fact.field for fact in normalized.facts}
    assert "parent_equity" not in {fact.field for fact in normalized.facts}
    assert "total_liabilities" not in {fact.field for fact in normalized.facts}
    assert normalized.data_quality.critical_missing_fields == [
        "parent_equity",
        "reported_interest_bearing_debt",
    ]


def test_official_a_balance_endpoint_requires_an_exact_statement_date():
    fake = OfficialBalanceAKShare()
    provider = AKShareProvider(fake)

    with pytest.raises(ProviderRequestError, match="requires statement_date"):
        provider.fetch(_request(DataCategory.BALANCE_SHEET, "SH600000"))
    with pytest.raises(ProviderRequestError, match="exact quarter-end"):
        provider.fetch(
            _request(
                DataCategory.BALANCE_SHEET,
                "SH600000",
                {"statement_date": "2024-12-30"},
            )
        )
    assert fake.calls == []


def test_dividend_fetch_uses_documented_market_specific_endpoints():
    fake = FakeAKShare()
    provider = _provider(fake)

    a_record = provider.fetch(_request(DataCategory.DIVIDENDS, "SH600000"))
    h_record = provider.fetch(_request(DataCategory.DIVIDENDS, "HK00700"))

    assert a_record.raw_payload == _fixture("a_dividends.json")
    assert h_record.raw_payload == _fixture("h_dividends.json")
    assert fake.calls == [
        ("stock_dividend_cninfo", {"symbol": "600000"}),
        ("stock_hk_dividend_payout_em", {"symbol": "00700"}),
    ]
    assert a_record.response_metadata["upstream_row_count"] == 2
    assert h_record.response_metadata["upstream_row_count"] == 2


def test_dividend_normalizer_keeps_plans_as_evidence_without_fabricating_cash():
    provider = _provider()
    records = [
        provider.fetch(_request(DataCategory.DIVIDENDS, "SH600000")),
        provider.fetch(_request(DataCategory.DIVIDENDS, "HK00700")),
    ]

    normalized = normalize_akshare_records(
        records,
        analysis_id="dividend-fixture",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert len(normalized.evidence_index) == 2
    assert normalized.data_quality.critical_missing_fields == [
        "ordinary_dividend_cash"
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_h_dividend_detail_fetch_uses_explicit_event_detail_view_and_keeps_scope():
    fake = FakeAKShare()
    provider = _provider(fake)
    request = _request(
        DataCategory.DIVIDENDS,
        "HK00700",
        {"view": "event_detail"},
    )

    record = provider.fetch(request)

    assert record.raw_payload == _fixture("h_dividend_detail_ths.json")
    assert fake.calls == [("stock_hk_fhpx_detail_ths", {"symbol": "00700"})]
    assert record.response_metadata["endpoint"] == "stock_hk_fhpx_detail_ths"
    assert record.response_metadata["upstream_row_count"] == 3
    assert record.response_metadata["entity_row_count"] == 3
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is True
    assert record.response_metadata["dividend_detail_view"] == "event_detail"
    assert record.source_uri == "https://stockpage.10jqka.com.cn/HK0700/bonus/"


def test_h_dividend_detail_request_rejects_unknown_view_before_upstream_call():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="view must be 'event_detail'"):
        provider.fetch(
            _request(
                DataCategory.DIVIDENDS,
                "HK00700",
                {"view": "not-a-documented-view"},
            )
        )

    assert fake.calls == []


def test_h_dividend_detail_response_rejects_invalid_event_dates():
    class InvalidDateAKShare(FakeAKShare):
        def stock_hk_fhpx_detail_ths(self, *, symbol: str):
            payload = _fixture("h_dividend_detail_ths.json")
            payload[0]["公告日期"] = "not-a-date"
            return self._return(
                "stock_hk_fhpx_detail_ths",
                payload,
                symbol=symbol,
            )

    with pytest.raises(ProviderResponseError, match="invalid H-share dividend-detail date"):
        _provider(InvalidDateAKShare()).fetch(
            _request(DataCategory.DIVIDENDS, "HK00700", {"view": "event_detail"})
        )


def test_h_dividend_detail_raw_record_is_not_promoted_to_dividend_or_filing_facts():
    provider = _provider()
    record = provider.fetch(
        _request(DataCategory.DIVIDENDS, "HK00700", {"view": "event_detail"})
    )

    normalized = normalize_akshare_records(
        [record],
        analysis_id="h-dividend-detail-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(primary_listing="HK00700"),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_HK_DIVIDEND_DETAIL_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "ordinary_dividend_cash",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "settled ordinary dividend cash" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(
        Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json"))
    ) == []


def test_h_dividend_detail_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(DataCategory.DIVIDENDS, "HK00700", {"view": "event_detail"})

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [("stock_hk_fhpx_detail_ths", {"symbol": "00700"})]


def test_dividend_endpoint_rejects_parameters_before_upstream_call():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="does not accept request parameters"):
        provider.fetch(
            _request(DataCategory.DIVIDENDS, "SH600000", {"indicator": "annual"})
        )
    assert fake.calls == []


def test_a_dividend_snapshot_fetch_uses_exact_report_date_and_filters_the_universe():
    fake = FakeAKShare()
    provider = _provider(fake)
    request = _request(
        DataCategory.DIVIDENDS,
        "SH600000",
        {"date": "20241231"},
    )

    record = provider.fetch(request)

    fixture = _fixture("a_dividend_snapshot.json")
    assert record.raw_payload == [row for row in fixture if row["代码"] == "600000"]
    assert fake.calls == [("stock_fhps_em", {"date": "20241231"})]
    assert record.response_metadata["endpoint"] == "stock_fhps_em"
    assert record.response_metadata["upstream_row_count"] == 2
    assert record.response_metadata["entity_row_count"] == 1
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is False
    assert record.response_metadata["row_filtering"] == "provider"
    assert record.response_metadata["requested_date"] == "20241231"
    assert record.response_metadata["report_period"] == "2024-12-31"
    assert record.source_uri == "https://data.eastmoney.com/yjfp/"


def test_a_dividend_snapshot_request_requires_a_documented_report_date():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="date must be YYYYMMDD"):
        provider.fetch(
            _request(DataCategory.DIVIDENDS, "SH600000", {"date": "2024-12-31"})
        )
    with pytest.raises(ProviderRequestError, match="date must be a valid YYYYMMDD"):
        provider.fetch(
            _request(DataCategory.DIVIDENDS, "SH600000", {"date": "20241331"})
        )
    with pytest.raises(ProviderRequestError, match="June 30 or December 31"):
        provider.fetch(
            _request(DataCategory.DIVIDENDS, "SH600000", {"date": "20240930"})
        )
    with pytest.raises(ProviderRequestError, match="on or after 19901231"):
        provider.fetch(
            _request(DataCategory.DIVIDENDS, "SH600000", {"date": "19891231"})
        )
    with pytest.raises(ProviderRequestError, match="unsupported AKShare dividend-snapshot"):
        provider.fetch(
            _request(
                DataCategory.DIVIDENDS,
                "SH600000",
                {"date": "20241231", "indicator": "annual"},
            )
        )

    assert fake.calls == []


def test_a_dividend_snapshot_raw_record_is_not_promoted_to_cash_or_payout_facts():
    provider = _provider()
    record = provider.fetch(
        _request(DataCategory.DIVIDENDS, "SH600000", {"date": "20241231"})
    )

    normalized = normalize_akshare_records(
        [record],
        analysis_id="dividend-snapshot-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_DIVIDEND_SNAPSHOT_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "ordinary_dividend_cash",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "canonical payout ratio" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_a_dividend_snapshot_normalizer_rejects_replayed_rows_for_another_listing():
    provider = _provider()
    record = provider.fetch(
        _request(DataCategory.DIVIDENDS, "SH600000", {"date": "20241231"})
    )
    mismatched_payload = [dict(row) for row in record.raw_payload]
    mismatched_payload[0]["代码"] = "000001"
    mismatched = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=mismatched_payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="dividend-snapshot row entity"):
        normalize_akshare_records(
            [mismatched],
            analysis_id="mismatched-dividend-snapshot",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_a_dividend_snapshot_with_no_matching_listing_is_an_empty_raw_snapshot():
    class NoSnapshot(FakeAKShare):
        def stock_fhps_em(self, *, date: str):
            return self._return(
                "stock_fhps_em",
                [{"代码": "000001", "名称": "平安银行"}],
                date=date,
            )

    fake = NoSnapshot()
    record = _provider(fake).fetch(
        _request(DataCategory.DIVIDENDS, "SH600000", {"date": "20241231"})
    )

    assert record.raw_payload == []
    assert record.response_metadata["upstream_row_count"] == 1
    assert record.response_metadata["entity_row_count"] == 0


def test_a_dividend_snapshot_rejects_a_universe_row_without_an_explicit_listing_code():
    class MissingListingCode(FakeAKShare):
        def stock_fhps_em(self, *, date: str):
            return self._return(
                "stock_fhps_em",
                [{"代码": None, "名称": "unresolved"}],
                date=date,
            )

    with pytest.raises(ProviderResponseError, match="dividend-snapshot row without a listing code"):
        _provider(MissingListingCode()).fetch(
            _request(DataCategory.DIVIDENDS, "SH600000", {"date": "20241231"})
        )


def test_a_dividend_snapshot_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(DataCategory.DIVIDENDS, "SH600000", {"date": "20241231"})

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [("stock_fhps_em", {"date": "20241231"})]


def test_a_disclosure_notice_fetch_uses_documented_listing_and_filter_contract():
    fake = FakeAKShare()
    provider = _provider(fake)
    request = _request(
        DataCategory.DISCLOSURE_NOTICES,
        "SH600000",
        {
            "market": "沪深京",
            "category": "公司治理",
            "start_date": "20240101",
            "end_date": "20241231",
        },
    )

    record = provider.fetch(request)

    assert record.raw_payload == _fixture("a_disclosure_report.json")
    assert fake.calls == [
        (
            "stock_zh_a_disclosure_report_cninfo",
            {
                "symbol": "600000",
                "market": "沪深京",
                "keyword": "",
                "category": "公司治理",
                "start_date": "20240101",
                "end_date": "20241231",
            },
        )
    ]
    assert record.response_metadata["endpoint"] == "stock_zh_a_disclosure_report_cninfo"
    assert record.response_metadata["upstream_row_count"] == 2
    assert record.response_metadata["entity_row_count"] == 2
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is True
    assert record.response_metadata["row_filtering"] == "provider"
    assert record.response_metadata["notice_category"] == "公司治理"
    assert record.response_metadata["start_date"] == "20240101"
    assert record.response_metadata["end_date"] == "20241231"
    assert record.source_uri == (
        "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search"
    )


def test_a_disclosure_notice_request_uses_documented_defaults_and_rejects_unsupported_scope():
    fake = FakeAKShare()
    provider = _provider(fake)

    provider.fetch(_request(DataCategory.DISCLOSURE_NOTICES, "SH600000"))
    assert fake.calls == [
        (
            "stock_zh_a_disclosure_report_cninfo",
            {
                "symbol": "600000",
                "market": "沪深京",
                "keyword": "",
                "category": "",
                "start_date": "20230618",
                "end_date": "20231219",
            },
        )
    ]

    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        provider.fetch(_request(DataCategory.DISCLOSURE_NOTICES, "HK00700"))
    with pytest.raises(ProviderRequestError, match="market must be"):
        provider.fetch(
            _request(DataCategory.DISCLOSURE_NOTICES, "SH600000", {"market": "港股"})
        )
    with pytest.raises(ProviderRequestError, match="category must be"):
        provider.fetch(
            _request(
                DataCategory.DISCLOSURE_NOTICES,
                "SH600000",
                {"category": "not-a-documented-category"},
            )
        )
    with pytest.raises(ProviderRequestError, match="start_date must not be after"):
        provider.fetch(
            _request(
                DataCategory.DISCLOSURE_NOTICES,
                "SH600000",
                {"start_date": "20250101", "end_date": "20240101"},
            )
        )


def test_disclosure_notice_response_rejects_cross_listing_missing_code_or_invalid_date():
    class WrongEntityAKShare(FakeAKShare):
        def stock_zh_a_disclosure_report_cninfo(self, **kwargs):
            payload = _fixture("a_disclosure_report.json")
            payload[0]["代码"] = "000001"
            return self._return("stock_zh_a_disclosure_report_cninfo", payload, **kwargs)

    with pytest.raises(ProviderResponseError, match="disclosure-notice row entity"):
        _provider(WrongEntityAKShare()).fetch(
            _request(DataCategory.DISCLOSURE_NOTICES, "SH600000")
        )

    class MissingCodeAKShare(FakeAKShare):
        def stock_zh_a_disclosure_report_cninfo(self, **kwargs):
            payload = _fixture("a_disclosure_report.json")
            payload[0].pop("代码")
            return self._return("stock_zh_a_disclosure_report_cninfo", payload, **kwargs)

    with pytest.raises(ProviderResponseError, match="without a listing code"):
        _provider(MissingCodeAKShare()).fetch(
            _request(DataCategory.DISCLOSURE_NOTICES, "SH600000")
        )

    class InvalidDateAKShare(FakeAKShare):
        def stock_zh_a_disclosure_report_cninfo(self, **kwargs):
            payload = _fixture("a_disclosure_report.json")
            payload[0]["公告时间"] = "not-a-date"
            return self._return("stock_zh_a_disclosure_report_cninfo", payload, **kwargs)

    with pytest.raises(ProviderResponseError, match="invalid disclosure-notice date"):
        _provider(InvalidDateAKShare()).fetch(
            _request(DataCategory.DISCLOSURE_NOTICES, "SH600000")
        )


def test_disclosure_notice_raw_record_is_not_promoted_to_filing_or_governance_facts():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.DISCLOSURE_NOTICES, "SH600000"))
    normalized = normalize_akshare_records(
        [record],
        analysis_id="disclosure-notices-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_DISCLOSURE_NOTICES_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "accounting_opinion",
        "governance_risk_level",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "filing contents" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(
        Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json"))
    ) == []


def test_disclosure_notice_normalizer_rejects_replayed_rows_for_another_listing():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.DISCLOSURE_NOTICES, "SH600000"))
    mismatched_payload = [dict(row) for row in record.raw_payload]
    mismatched_payload[0]["代码"] = "000001"
    mismatched = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=mismatched_payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="does not match requested listing"):
        normalize_akshare_records(
            [mismatched],
            analysis_id="mismatched-disclosure-notice-entity",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_disclosure_notice_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.DISCLOSURE_NOTICES,
        "SH600000",
        {"category": "公司治理", "start_date": "20240101", "end_date": "20241231"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        (
            "stock_zh_a_disclosure_report_cninfo",
            {
                "symbol": "600000",
                "market": "沪深京",
                "keyword": "",
                "category": "公司治理",
                "start_date": "20240101",
                "end_date": "20241231",
            },
        )
    ]


def test_a_earnings_forecast_fetch_uses_exact_report_date_and_filters_the_universe():
    fake = FakeAKShare()
    provider = _provider(fake)
    request = _request(
        DataCategory.EARNINGS_FORECAST,
        "SH600000",
        {"date": "20241231"},
    )

    record = provider.fetch(request)

    fixture = _fixture("a_earnings_forecast.json")
    assert record.raw_payload == [row for row in fixture if row["股票代码"] == "600000"]
    assert fake.calls == [("stock_yjyg_em", {"date": "20241231"})]
    assert record.response_metadata["endpoint"] == "stock_yjyg_em"
    assert record.response_metadata["upstream_row_count"] == 3
    assert record.response_metadata["entity_row_count"] == 2
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is False
    assert record.response_metadata["row_filtering"] == "provider"
    assert record.response_metadata["requested_date"] == "20241231"
    assert record.response_metadata["report_period"] == "2024-12-31"
    assert record.source_uri == "https://data.eastmoney.com/bbsj/202003/yjyg.html"


def test_earnings_forecast_request_requires_a_documented_quarter_end_date():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="requires date"):
        provider.fetch(_request(DataCategory.EARNINGS_FORECAST, "SH600000"))
    with pytest.raises(ProviderRequestError, match="date must be YYYYMMDD"):
        provider.fetch(
            _request(
                DataCategory.EARNINGS_FORECAST,
                "SH600000",
                {"date": "2024-12-31"},
            )
        )
    with pytest.raises(ProviderRequestError, match="date must be a valid YYYYMMDD"):
        provider.fetch(
            _request(
                DataCategory.EARNINGS_FORECAST,
                "SH600000",
                {"date": "20241331"},
            )
        )
    with pytest.raises(ProviderRequestError, match="on or after 20081231"):
        provider.fetch(
            _request(
                DataCategory.EARNINGS_FORECAST,
                "SH600000",
                {"date": "20080930"},
            )
        )
    with pytest.raises(ProviderRequestError, match="exact quarter-end"):
        provider.fetch(
            _request(
                DataCategory.EARNINGS_FORECAST,
                "SH600000",
                {"date": "20241230"},
            )
        )
    with pytest.raises(ProviderRequestError, match="unsupported AKShare earnings-forecast"):
        provider.fetch(
            _request(
                DataCategory.EARNINGS_FORECAST,
                "SH600000",
                {"date": "20241231", "indicator": "annual"},
            )
        )
    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        provider.fetch(
            _request(
                DataCategory.EARNINGS_FORECAST,
                "HK00700",
                {"date": "20241231"},
            )
        )

    assert fake.calls == []


def test_earnings_forecast_response_rejects_a_row_without_an_explicit_listing_code():
    class MissingListingCode(FakeAKShare):
        def stock_yjyg_em(self, *, date: str):
            return self._return(
                "stock_yjyg_em",
                [{"股票代码": None, "股票简称": "unresolved"}],
                date=date,
            )

    with pytest.raises(ProviderResponseError, match="earnings-forecast row without a listing code"):
        _provider(MissingListingCode()).fetch(
            _request(
                DataCategory.EARNINGS_FORECAST,
                "SH600000",
                {"date": "20241231"},
            )
        )


def test_earnings_forecast_response_rejects_an_explicit_wrong_report_period():
    class WrongPeriod(FakeAKShare):
        def stock_yjyg_em(self, *, date: str):
            payload = _fixture("a_earnings_forecast.json")
            payload[0]["报告日期"] = "2024-09-30"
            return self._return("stock_yjyg_em", payload, date=date)

    with pytest.raises(ProviderResponseError, match="earnings-forecast row period"):
        _provider(WrongPeriod()).fetch(
            _request(
                DataCategory.EARNINGS_FORECAST,
                "SH600000",
                {"date": "20241231"},
            )
        )


def test_earnings_forecast_raw_record_is_not_promoted_to_reported_profit_facts():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.EARNINGS_FORECAST,
            "SH600000",
            {"date": "20241231"},
        )
    )

    normalized = normalize_akshare_records(
        [record],
        analysis_id="earnings-forecast-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_EARNINGS_FORECAST_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "consolidated_net_profit",
        "parent_net_profit",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "reported parent or consolidated net profit" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_earnings_forecast_normalizer_rejects_replayed_rows_for_another_listing():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.EARNINGS_FORECAST,
            "SH600000",
            {"date": "20241231"},
        )
    )
    mismatched_payload = [dict(row) for row in record.raw_payload]
    mismatched_payload[0]["股票代码"] = "000001"
    mismatched = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=mismatched_payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="earnings-forecast row entity"):
        normalize_akshare_records(
            [mismatched],
            analysis_id="mismatched-earnings-forecast",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_earnings_forecast_with_no_matching_listing_is_an_empty_raw_snapshot():
    class NoForecast(FakeAKShare):
        def stock_yjyg_em(self, *, date: str):
            return self._return(
                "stock_yjyg_em",
                [{"股票代码": "000001", "股票简称": "平安银行"}],
                date=date,
            )

    fake = NoForecast()
    record = _provider(fake).fetch(
        _request(
            DataCategory.EARNINGS_FORECAST,
            "SH600000",
            {"date": "20241231"},
        )
    )

    assert record.raw_payload == []
    assert record.response_metadata["upstream_row_count"] == 1
    assert record.response_metadata["entity_row_count"] == 0


def test_earnings_forecast_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.EARNINGS_FORECAST,
        "SH600000",
        {"date": "20241231"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [("stock_yjyg_em", {"date": "20241231"})]


def test_a_earnings_quick_report_fetch_uses_exact_report_date_and_filters_the_universe():
    fake = FakeAKShare()
    provider = _provider(fake)
    request = _request(
        DataCategory.EARNINGS_QUICK_REPORT,
        "SH600000",
        {"date": "20241231"},
    )

    record = provider.fetch(request)

    fixture = _fixture("a_earnings_quick_report.json")
    assert record.raw_payload == [row for row in fixture if row["股票代码"] == "600000"]
    assert fake.calls == [("stock_yjkb_em", {"date": "20241231"})]
    assert record.response_metadata["endpoint"] == "stock_yjkb_em"
    assert record.response_metadata["upstream_row_count"] == 2
    assert record.response_metadata["entity_row_count"] == 1
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is False
    assert record.response_metadata["row_filtering"] == "provider"
    assert record.response_metadata["requested_date"] == "20241231"
    assert record.response_metadata["report_period"] == "2024-12-31"
    assert record.source_uri == "https://data.eastmoney.com/bbsj/202003/yjkb.html"


def test_earnings_quick_report_request_requires_a_documented_quarter_end_date():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="requires date"):
        provider.fetch(_request(DataCategory.EARNINGS_QUICK_REPORT, "SH600000"))
    with pytest.raises(ProviderRequestError, match="date must be YYYYMMDD"):
        provider.fetch(
            _request(
                DataCategory.EARNINGS_QUICK_REPORT,
                "SH600000",
                {"date": "2024-12-31"},
            )
        )
    with pytest.raises(ProviderRequestError, match="date must be a valid YYYYMMDD"):
        provider.fetch(
            _request(
                DataCategory.EARNINGS_QUICK_REPORT,
                "SH600000",
                {"date": "20241331"},
            )
        )
    with pytest.raises(ProviderRequestError, match="on or after 20100331"):
        provider.fetch(
            _request(
                DataCategory.EARNINGS_QUICK_REPORT,
                "SH600000",
                {"date": "20091231"},
            )
        )
    with pytest.raises(ProviderRequestError, match="exact quarter-end"):
        provider.fetch(
            _request(
                DataCategory.EARNINGS_QUICK_REPORT,
                "SH600000",
                {"date": "20241230"},
            )
        )
    with pytest.raises(ProviderRequestError, match="unsupported AKShare earnings-quick-report"):
        provider.fetch(
            _request(
                DataCategory.EARNINGS_QUICK_REPORT,
                "SH600000",
                {"date": "20241231", "indicator": "annual"},
            )
        )
    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        provider.fetch(
            _request(
                DataCategory.EARNINGS_QUICK_REPORT,
                "HK00700",
                {"date": "20241231"},
            )
        )

    assert fake.calls == []


def test_earnings_quick_report_response_rejects_a_row_without_an_explicit_listing_code():
    class MissingListingCode(FakeAKShare):
        def stock_yjkb_em(self, *, date: str):
            return self._return(
                "stock_yjkb_em",
                [{"股票代码": None, "股票简称": "unresolved"}],
                date=date,
            )

    with pytest.raises(
        ProviderResponseError,
        match="earnings-quick-report row without a listing code",
    ):
        _provider(MissingListingCode()).fetch(
            _request(
                DataCategory.EARNINGS_QUICK_REPORT,
                "SH600000",
                {"date": "20241231"},
            )
        )


def test_earnings_quick_report_response_rejects_an_explicit_wrong_report_period():
    class WrongPeriod(FakeAKShare):
        def stock_yjkb_em(self, *, date: str):
            return self._return(
                "stock_yjkb_em",
                [{"股票代码": "600000", "报告日期": "2024-09-30"}],
                date=date,
            )

    with pytest.raises(ProviderResponseError, match="earnings-quick-report row period"):
        _provider(WrongPeriod()).fetch(
            _request(
                DataCategory.EARNINGS_QUICK_REPORT,
                "SH600000",
                {"date": "20241231"},
            )
        )


def test_earnings_quick_report_raw_record_is_not_promoted_to_reported_profit_facts():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.EARNINGS_QUICK_REPORT,
            "SH600000",
            {"date": "20241231"},
        )
    )

    normalized = normalize_akshare_records(
        [record],
        analysis_id="earnings-quick-report-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_EARNINGS_QUICK_REPORT_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "consolidated_net_profit",
        "parent_net_profit",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "headline net profit" in normalized.data_quality.notes
    assert "per-share" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_earnings_quick_report_normalizer_rejects_replayed_rows_for_another_listing():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.EARNINGS_QUICK_REPORT,
            "SH600000",
            {"date": "20241231"},
        )
    )
    mismatched_payload = [dict(row) for row in record.raw_payload]
    mismatched_payload[0]["股票代码"] = "000001"
    mismatched = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=mismatched_payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="earnings-quick-report row entity"):
        normalize_akshare_records(
            [mismatched],
            analysis_id="mismatched-earnings-quick-report",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_earnings_quick_report_with_no_matching_listing_is_an_empty_raw_snapshot():
    class NoQuickReport(FakeAKShare):
        def stock_yjkb_em(self, *, date: str):
            return self._return(
                "stock_yjkb_em",
                [{"股票代码": "000001", "股票简称": "平安银行"}],
                date=date,
            )

    fake = NoQuickReport()
    record = _provider(fake).fetch(
        _request(
            DataCategory.EARNINGS_QUICK_REPORT,
            "SH600000",
            {"date": "20241231"},
        )
    )

    assert record.raw_payload == []
    assert record.response_metadata["upstream_row_count"] == 1
    assert record.response_metadata["entity_row_count"] == 0


def test_earnings_quick_report_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.EARNINGS_QUICK_REPORT,
        "SH600000",
        {"date": "20241231"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [("stock_yjkb_em", {"date": "20241231"})]


def test_a_performance_report_fetch_uses_exact_report_date_and_filters_the_universe():
    fake = FakeAKShare()
    provider = _provider(fake)
    request = _request(
        DataCategory.PERFORMANCE_REPORT,
        "SH600000",
        {"date": "20241231"},
    )

    record = provider.fetch(request)

    fixture = _fixture("a_performance_report.json")
    assert record.raw_payload == [row for row in fixture if row["股票代码"] == "600000"]
    assert fake.calls == [("stock_yjbb_em", {"date": "20241231"})]
    assert record.response_metadata["endpoint"] == "stock_yjbb_em"
    assert record.response_metadata["upstream_row_count"] == 2
    assert record.response_metadata["entity_row_count"] == 1
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is False
    assert record.response_metadata["row_filtering"] == "provider"
    assert record.response_metadata["requested_date"] == "20241231"
    assert record.response_metadata["report_period"] == "2024-12-31"
    assert record.source_uri == "https://data.eastmoney.com/bbsj/202003/yjbb.html"


def test_performance_report_request_requires_a_documented_quarter_end_date():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="requires date"):
        provider.fetch(_request(DataCategory.PERFORMANCE_REPORT, "SH600000"))
    with pytest.raises(ProviderRequestError, match="date must be YYYYMMDD"):
        provider.fetch(
            _request(
                DataCategory.PERFORMANCE_REPORT,
                "SH600000",
                {"date": "2024-12-31"},
            )
        )
    with pytest.raises(ProviderRequestError, match="date must be a valid YYYYMMDD"):
        provider.fetch(
            _request(
                DataCategory.PERFORMANCE_REPORT,
                "SH600000",
                {"date": "20241331"},
            )
        )
    with pytest.raises(ProviderRequestError, match="on or after 20100331"):
        provider.fetch(
            _request(
                DataCategory.PERFORMANCE_REPORT,
                "SH600000",
                {"date": "20091231"},
            )
        )
    with pytest.raises(ProviderRequestError, match="exact quarter-end"):
        provider.fetch(
            _request(
                DataCategory.PERFORMANCE_REPORT,
                "SH600000",
                {"date": "20241230"},
            )
        )
    with pytest.raises(ProviderRequestError, match="unsupported AKShare performance-report"):
        provider.fetch(
            _request(
                DataCategory.PERFORMANCE_REPORT,
                "SH600000",
                {"date": "20241231", "indicator": "annual"},
            )
        )
    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        provider.fetch(
            _request(
                DataCategory.PERFORMANCE_REPORT,
                "HK00700",
                {"date": "20241231"},
            )
        )

    assert fake.calls == []


def test_performance_report_response_rejects_a_row_without_an_explicit_listing_code():
    class MissingListingCode(FakeAKShare):
        def stock_yjbb_em(self, *, date: str):
            return self._return(
                "stock_yjbb_em",
                [{"股票代码": None, "股票简称": "unresolved"}],
                date=date,
            )

    with pytest.raises(
        ProviderResponseError,
        match="performance-report row without a listing code",
    ):
        _provider(MissingListingCode()).fetch(
            _request(
                DataCategory.PERFORMANCE_REPORT,
                "SH600000",
                {"date": "20241231"},
            )
        )


def test_performance_report_raw_record_is_not_promoted_to_reported_profit_or_cfo_facts():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.PERFORMANCE_REPORT,
            "SH600000",
            {"date": "20241231"},
        )
    )

    normalized = normalize_akshare_records(
        [record],
        analysis_id="performance-report-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_PERFORMANCE_REPORT_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "consolidated_net_profit",
        "parent_net_profit",
        "reported_cfo",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "headline net profit" in normalized.data_quality.notes
    assert "per share" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_performance_report_normalizer_rejects_replayed_rows_for_another_listing():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.PERFORMANCE_REPORT,
            "SH600000",
            {"date": "20241231"},
        )
    )
    mismatched_payload = [dict(row) for row in record.raw_payload]
    mismatched_payload[0]["股票代码"] = "000001"
    mismatched = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=mismatched_payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="performance-report row entity"):
        normalize_akshare_records(
            [mismatched],
            analysis_id="mismatched-performance-report",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_performance_report_with_no_matching_listing_is_an_empty_raw_snapshot():
    class NoPerformanceReport(FakeAKShare):
        def stock_yjbb_em(self, *, date: str):
            return self._return(
                "stock_yjbb_em",
                [{"股票代码": "000001", "股票简称": "平安银行"}],
                date=date,
            )

    fake = NoPerformanceReport()
    record = _provider(fake).fetch(
        _request(
            DataCategory.PERFORMANCE_REPORT,
            "SH600000",
            {"date": "20241231"},
        )
    )

    assert record.raw_payload == []
    assert record.response_metadata["upstream_row_count"] == 1
    assert record.response_metadata["entity_row_count"] == 0


def test_performance_report_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.PERFORMANCE_REPORT,
        "SH600000",
        {"date": "20241231"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [("stock_yjbb_em", {"date": "20241231"})]


def test_business_composition_fetch_preserves_listing_scoped_history_rows():
    fake = FakeAKShare()
    provider = _provider(fake)
    record = provider.fetch(_request(DataCategory.BUSINESS_COMPOSITION, "SH600000"))

    assert record.raw_payload == _fixture("a_business_composition.json")
    assert fake.calls == [("stock_zygc_em", {"symbol": "SH600000"})]
    assert record.response_metadata["endpoint"] == "stock_zygc_em"
    assert record.response_metadata["upstream_row_count"] == 3
    assert record.response_metadata["entity_row_count"] == 3
    assert record.response_metadata["listing_scoped_request"] is True
    assert record.response_metadata["report_period_count"] == 2
    assert record.source_uri == (
        "https://emweb.securities.eastmoney.com/PC_HSF10/BusinessAnalysis/"
        "Index?type=web&code=SH688041#"
    )


def test_business_composition_endpoint_rejects_parameters_and_h_share_requests_before_call():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="unsupported AKShare business-composition"):
        provider.fetch(
            _request(
                DataCategory.BUSINESS_COMPOSITION,
                "SH600000",
                {"start_date": "20240101"},
            )
        )
    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        provider.fetch(_request(DataCategory.BUSINESS_COMPOSITION, "HK00700"))

    assert fake.calls == []


def test_business_composition_response_rejects_rows_without_listing_identity():
    class MissingListingCode(FakeAKShare):
        def stock_zygc_em(self, *, symbol: str):
            return self._return(
                "stock_zygc_em",
                [{"股票代码": None, "报告日期": "2025-06-30"}],
                symbol=symbol,
            )

    with pytest.raises(
        ProviderResponseError,
        match="business-composition row without a listing code",
    ):
        _provider(MissingListingCode()).fetch(
            _request(DataCategory.BUSINESS_COMPOSITION, "SH600000")
        )


def test_business_composition_response_rejects_cross_listing_rows_and_invalid_dates():
    class WrongEntity(FakeAKShare):
        def stock_zygc_em(self, *, symbol: str):
            payload = _fixture("a_business_composition.json")
            payload[0]["股票代码"] = "000001"
            return self._return("stock_zygc_em", payload, symbol=symbol)

    with pytest.raises(ProviderResponseError, match="business-composition row entity"):
        _provider(WrongEntity()).fetch(
            _request(DataCategory.BUSINESS_COMPOSITION, "SH600000")
        )

    class WrongEntityWithoutDate(FakeAKShare):
        def stock_zygc_em(self, *, symbol: str):
            return self._return(
                "stock_zygc_em",
                [{"股票代码": "000001", "报告日期": None}],
                symbol=symbol,
            )

    with pytest.raises(ProviderResponseError, match="business-composition row entity"):
        _provider(WrongEntityWithoutDate()).fetch(
            _request(DataCategory.BUSINESS_COMPOSITION, "SH600000")
        )

    class InvalidDate(FakeAKShare):
        def stock_zygc_em(self, *, symbol: str):
            return self._return(
                "stock_zygc_em",
                [{"股票代码": "600000", "报告日期": "not-a-date"}],
                symbol=symbol,
            )

    with pytest.raises(ProviderResponseError, match="invalid report date"):
        _provider(InvalidDate()).fetch(
            _request(DataCategory.BUSINESS_COMPOSITION, "SH600000")
        )


def test_business_composition_raw_record_is_not_promoted_to_revenue_facts():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.BUSINESS_COMPOSITION, "SH600000"))

    normalized = normalize_akshare_records(
        [record],
        analysis_id="business-composition-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_BUSINESS_COMPOSITION_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "core_revenue",
        "revenue",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "canonical revenue" in normalized.data_quality.notes
    assert "core-revenue" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_business_composition_normalizer_rejects_replayed_rows_for_another_listing():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.BUSINESS_COMPOSITION, "SH600000"))
    mismatched_payload = [dict(row) for row in record.raw_payload]
    mismatched_payload[0]["股票代码"] = "000001"
    mismatched = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=mismatched_payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="business-composition row entity"):
        normalize_akshare_records(
            [mismatched],
            analysis_id="mismatched-business-composition",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_business_composition_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(DataCategory.BUSINESS_COMPOSITION, "SH600000")

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [("stock_zygc_em", {"symbol": "SH600000"})]


def test_corporate_actions_fetch_filters_universe_without_discarding_listing_history():
    fake = FakeAKShare()
    provider = _provider(fake)
    record = provider.fetch(_request(DataCategory.CORPORATE_ACTIONS, "SH600000"))

    fixture = _fixture("a_repurchase.json")
    assert record.raw_payload == [row for row in fixture if row["股票代码"] == "600000"]
    assert fake.calls == [("stock_repurchase_em", {})]
    assert record.response_metadata["endpoint"] == "stock_repurchase_em"
    assert record.response_metadata["upstream_row_count"] == 3
    assert record.response_metadata["entity_row_count"] == 2
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["row_filtering"] == "provider"
    assert record.source_uri == "https://data.eastmoney.com/gphg/hglist.html"


def test_corporate_actions_endpoint_rejects_parameters_and_h_share_requests_before_upstream_call():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="does not accept request parameters"):
        provider.fetch(
            _request(DataCategory.CORPORATE_ACTIONS, "SH600000", {"status": "completed"})
        )
    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        provider.fetch(_request(DataCategory.CORPORATE_ACTIONS, "HK00700"))

    assert fake.calls == []


def test_corporate_actions_normalizer_keeps_repurchase_rows_as_raw_evidence():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.CORPORATE_ACTIONS, "SH600000"))
    normalized = normalize_akshare_records(
        [record],
        analysis_id="repurchase-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert len(normalized.evidence_index) == 1
    assert normalized.flags == ["AKSHARE_CORPORATE_ACTIONS_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == ["buyback_cash"]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "settled annual buyback-cash fact" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_corporate_actions_normalizer_rejects_replayed_rows_for_another_listing():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.CORPORATE_ACTIONS, "SH600000"))
    mismatched_payload = [dict(row) for row in record.raw_payload]
    mismatched_payload[0]["股票代码"] = "000001"
    mismatched = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=mismatched_payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="does not match requested listing"):
        normalize_akshare_records(
            [mismatched],
            analysis_id="mismatched-repurchase-entity",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_corporate_actions_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(DataCategory.CORPORATE_ACTIONS, "SH600000")

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [("stock_repurchase_em", {})]


def test_corporate_actions_with_no_matching_listing_is_an_empty_raw_snapshot():
    class NoRepurchase(FakeAKShare):
        def stock_repurchase_em(self):
            return [{"股票代码": "000001", "股票简称": "平安银行"}]

    fake = NoRepurchase()
    record = _provider(fake).fetch(_request(DataCategory.CORPORATE_ACTIONS, "SH600000"))

    assert record.raw_payload == []
    assert record.response_metadata["upstream_row_count"] == 1
    assert record.response_metadata["entity_row_count"] == 0


def test_corporate_actions_rejects_a_universe_row_without_an_explicit_listing_code():
    class MissingListingCode(FakeAKShare):
        def stock_repurchase_em(self):
            return [{"股票代码": None, "股票简称": "unresolved"}]

    with pytest.raises(ProviderResponseError, match="without a listing code"):
        _provider(MissingListingCode()).fetch(
            _request(DataCategory.CORPORATE_ACTIONS, "SH600000")
        )


def test_missing_optional_dependency_is_reported_only_when_a_live_fetch_is_attempted(
    monkeypatch,
):
    imported = []

    def fail_import(name: str):
        imported.append(name)
        raise ImportError("not installed")

    monkeypatch.setattr(
        "turtle_value_engine.providers.akshare.importlib.import_module",
        fail_import,
    )
    provider = AKShareProvider(clock=lambda: RETRIEVED_AT)
    assert imported == []

    with pytest.raises(ProviderRequestError, match="optional dependency"):
        provider.fetch(_request(DataCategory.MARKET_QUOTE, "SH600000"))
    assert imported == ["akshare"]


def test_missing_corporate_action_endpoint_is_blocked_before_an_upstream_call():
    class NoCorporateActionEndpoint:
        __version__ = "fixture-akshare-without-repurchase"

    provider = _provider(NoCorporateActionEndpoint())

    with pytest.raises(ProviderRequestError, match="does not expose a supported endpoint"):
        provider.fetch(_request(DataCategory.CORPORATE_ACTIONS, "SH600000"))


def test_corporate_action_endpoint_is_a_share_only_and_rejects_h_share_before_upstream_call():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(
        ProviderRequestError,
        match="corporate-action endpoint.*A-share listings only",
    ):
        provider.fetch(_request(DataCategory.CORPORATE_ACTIONS, "HK00700"))
    assert fake.calls == []


def test_cache_replay_is_offline_and_preserves_raw_record(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(DataCategory.MARKET_QUOTE, "SH600000")

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [("stock_zh_a_spot_em", {})]


def test_normalizer_maps_metadata_quote_and_history_to_schema_valid_facts():
    provider = _provider()
    records = [
        provider.fetch(_request(DataCategory.COMPANY_METADATA, "SH600000")),
        provider.fetch(_request(DataCategory.LISTING_METADATA, "SH600000")),
        provider.fetch(_request(DataCategory.MARKET_QUOTE, "SH600000")),
        provider.fetch(
            _request(
                DataCategory.MARKET_HISTORY,
                "SH600000",
                {"start_date": "2026-09-08", "end_date": "2026-09-09"},
            )
        ),
    ]
    normalized = normalize_akshare_records(
        records,
        analysis_id="akshare-fixture",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    values = {(fact.field, fact.period): fact.value for fact in normalized.facts}
    assert values[("current_price", "AS_OF_2026-09-09")] == 10.5
    assert values[("historical_close", "2026-09-08")] == 10.3
    assert values[("historical_volume", "2026-09-09")] == 120000.0
    turnover = next(
        fact
        for fact in normalized.facts
        if fact.field == "historical_turnover" and fact.period == "2026-09-09"
    )
    change_percent = next(
        fact
        for fact in normalized.facts
        if fact.field == "historical_change_percent" and fact.period == "2026-09-09"
    )
    assert turnover.currency == "CNY"
    assert change_percent.currency is None
    assert values[("listing_name", "AS_OF_2026-09-09")] == "浦发银行"
    assert values[("company_name", "AS_OF_2026-09-09")] == "浦发银行"
    assert ("listing_years", "AS_OF_2026-09-09") not in values
    assert normalized.data_quality.critical_missing_fields == []
    assert normalized.company.legal_name == "浦发银行"
    assert all("最新价" not in fact.field for fact in normalized.facts)
    assert all("总市值" not in fact.field for fact in normalized.facts)
    assert not hasattr(normalized, "metrics")

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []
    assert all(
        evidence.source.type.value == "STRUCTURED_DATA_VENDOR"
        for evidence in normalized.evidence_index
    )


def test_normalizer_maps_explicit_cash_flow_lines_without_deriving_cdc():
    provider = _provider()
    records = [
        provider.fetch(_request(DataCategory.CASH_FLOW_STATEMENT, "SH600000")),
    ]
    normalized = normalize_akshare_records(
        records,
        analysis_id="cash-flow-fixture",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    values = {(fact.field, fact.period): fact for fact in normalized.facts}
    assert values[("reported_cfo", "2025-12-31")].value == 1200000000.0
    assert values[("acquisition_cash", "2025-12-31")].value == -250000000.0
    assert values[("reported_cfo", "2025-12-31")].currency == "CNY"
    assert values[("reported_cfo", "2025-12-31")].unit == "reported_currency_amount"
    assert "core_cdc" not in {fact.field for fact in normalized.facts}
    assert normalized.data_quality.critical_missing_fields == []


def test_h_cash_flow_long_rows_are_pivoted_and_keep_nulls():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.CASH_FLOW_STATEMENT,
            "HK00700",
            {"indicator": "annual"},
        )
    )
    normalized = normalize_akshare_records(
        [record],
        analysis_id="h-cash-flow-fixture",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company("HK00700"),
    )

    values = {(fact.field, fact.period): fact.value for fact in normalized.facts}
    assert values[("reported_cfo", "2024-12-31")] == 880000000.0
    assert values[("acquisition_cash", "2024-12-31")] is None
    assert values[("reported_cfo", "2023-12-31")] is None
    assert normalized.data_quality.critical_missing_fields == []


def test_normalizer_maps_only_explicit_income_statement_net_profit_lines():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.INCOME_STATEMENT, "SH600000"))
    normalized = normalize_akshare_records(
        [record],
        analysis_id="income-fixture",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    values = {(fact.field, fact.period): fact for fact in normalized.facts}
    assert values[("consolidated_net_profit", "2025-12-31")].value == 950000000.0
    assert values[("parent_net_profit", "2025-12-31")].value == 900000000.0
    assert values[("consolidated_net_profit", "2024-12-31")].value == 850000000.0
    assert values[("parent_net_profit", "2024-12-31")].value == 800000000.0
    assert values[("consolidated_net_profit", "2025-12-31")].currency == "CNY"
    assert values[("parent_net_profit", "2025-12-31")].unit == "reported_currency_amount"
    assert "revenue" not in {fact.field for fact in normalized.facts}
    assert "core_cdc" not in {fact.field for fact in normalized.facts}
    assert normalized.data_quality.critical_missing_fields == []

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_h_income_statement_long_rows_are_pivoted_and_keep_nulls():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.INCOME_STATEMENT,
            "HK00700",
            {"indicator": "annual"},
        )
    )
    normalized = normalize_akshare_records(
        [record],
        analysis_id="h-income-fixture",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company("HK00700"),
    )

    values = {(fact.field, fact.period): fact for fact in normalized.facts}
    assert values[("consolidated_net_profit", "2024-12-31")].value == 880000000.0
    assert values[("parent_net_profit", "2024-12-31")].value == 860000000.0
    assert values[("consolidated_net_profit", "2023-12-31")].value is None
    assert values[("parent_net_profit", "2023-12-31")].value is None
    assert values[("parent_net_profit", "2024-12-31")].currency == "HKD"
    assert normalized.data_quality.critical_missing_fields == []


def test_normalizer_maps_only_explicit_balance_sheet_totals():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.BALANCE_SHEET, "SH600000"))
    normalized = normalize_akshare_records(
        [record],
        analysis_id="balance-sheet-fixture",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    values = {(fact.field, fact.period): fact for fact in normalized.facts}
    assert values[("book_cash", "2025-12-31")].value == 1800000000.0
    assert values[("reported_interest_bearing_debt", "2025-12-31")].value == 700000000.0
    assert values[("parent_equity", "2025-12-31")].value == 7000000000.0
    assert values[("total_equity", "2025-12-31")].value == 7600000000.0
    assert values[("book_cash", "2024-12-31")].currency == "CNY"
    assert values[("total_equity", "2024-12-31")].unit == "reported_currency_amount"
    assert "total_liabilities" not in {fact.field for fact in normalized.facts}
    assert normalized.data_quality.critical_missing_fields == []

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_h_balance_sheet_long_rows_are_pivoted_and_keep_explicit_nulls():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.BALANCE_SHEET,
            "HK00700",
            {"indicator": "annual"},
        )
    )
    normalized = normalize_akshare_records(
        [record],
        analysis_id="h-balance-sheet-fixture",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company("HK00700"),
    )

    values = {(fact.field, fact.period): fact for fact in normalized.facts}
    assert values[("book_cash", "2024-12-31")].value == 420000000.0
    assert values[("reported_interest_bearing_debt", "2024-12-31")].value == 600000000.0
    assert values[("parent_equity", "2024-12-31")].value == 8800000000.0
    assert values[("total_equity", "2024-12-31")].value == 9000000000.0
    assert values[("book_cash", "2023-12-31")].value is None
    assert values[("book_cash", "2024-12-31")].currency == "HKD"
    assert normalized.data_quality.critical_missing_fields == []


def test_statement_currency_is_not_inferred_when_upstream_omits_it():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.INCOME_STATEMENT, "HK00700"))
    payload = [
        {key: value for key, value in row.items() if key != "CURRENCY"}
        for row in record.raw_payload
    ]
    without_currency = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    normalized = normalize_akshare_records(
        [without_currency],
        analysis_id="statement-currency-missing",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company("HK00700"),
    )

    statement_facts = [
        fact
        for fact in normalized.facts
        if fact.field in {"parent_net_profit", "consolidated_net_profit"}
    ]
    assert statement_facts
    assert {fact.currency for fact in statement_facts} == {None}
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(
        Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json"))
    ) == []


def test_statement_currency_conflicts_within_a_period_are_rejected():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.INCOME_STATEMENT, "HK00700"))
    conflicting = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=[
            {
                "SECURITY_CODE": "00700",
                "STD_REPORT_DATE": "2024-12-31",
                "STD_ITEM_NAME": "Profit for the year",
                "AMOUNT": 880000000,
                "CURRENCY": "CNY",
            },
            {
                "SECURITY_CODE": "00700",
                "STD_REPORT_DATE": "2024-12-31",
                "STD_ITEM_NAME": "Profit attributable to equity holders of the Company",
                "AMOUNT": 860000000,
                "CURRENCY": "HKD",
            },
        ],
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="conflicting income statement currency"):
        normalize_akshare_records(
            [conflicting],
            analysis_id="statement-currency-conflict",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company("HK00700"),
        )


def test_statement_currency_aliases_must_agree_on_one_row():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.INCOME_STATEMENT, "HK00700"))
    payload = [dict(row) for row in record.raw_payload]
    payload[0]["CURRENCY_NAME"] = "CNY"
    conflicting = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="conflicting income statement currency"):
        normalize_akshare_records(
            [conflicting],
            analysis_id="statement-currency-alias-conflict",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company("HK00700"),
        )


def test_invalid_explicit_statement_currency_is_rejected():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.INCOME_STATEMENT, "HK00700"))
    payload = [dict(row) for row in record.raw_payload]
    payload[0]["CURRENCY"] = "人民币"
    invalid = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="not an explicit three-letter code"):
        normalize_akshare_records(
            [invalid],
            analysis_id="statement-currency-invalid",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company("HK00700"),
        )


def test_statement_rows_for_a_different_listing_are_rejected():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.INCOME_STATEMENT, "HK00700"))
    payload = [dict(row) for row in record.raw_payload]
    payload[0]["SECURITY_CODE"] = "00005"
    mismatched = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="does not match requested listing"):
        normalize_akshare_records(
            [mismatched],
            analysis_id="mismatched-statement-entity",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company("HK00700"),
        )


def test_balance_sheet_ambiguous_long_items_are_rejected():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.BALANCE_SHEET, "HK00700"))
    duplicate = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=RETRIEVED_AT,
        raw_payload=[
            {
                "STD_REPORT_DATE": "2024-12-31",
                "STD_ITEM_NAME": "Cash and cash equivalents",
                "AMOUNT": 1,
            },
            {
                "STD_REPORT_DATE": "2024-12-31",
                "STD_ITEM_NAME": "Cash and cash equivalents",
                "AMOUNT": 2,
            },
        ],
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="duplicate balance-sheet item"):
        normalize_akshare_records(
            [duplicate],
            analysis_id="duplicate-balance-sheet",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company("HK00700"),
        )


def test_income_statement_ambiguous_long_items_are_rejected():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.INCOME_STATEMENT, "HK00700"))
    duplicate = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=RETRIEVED_AT,
        raw_payload=[
            {
                "STD_REPORT_DATE": "2024-12-31",
                "STD_ITEM_NAME": "Profit for the year",
                "AMOUNT": 1,
            },
            {
                "STD_REPORT_DATE": "2024-12-31",
                "STD_ITEM_NAME": "Profit for the year",
                "AMOUNT": 2,
            },
        ],
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="duplicate income item"):
        normalize_akshare_records(
            [duplicate],
            analysis_id="duplicate-income",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company("HK00700"),
        )


def test_cash_flow_ambiguous_period_or_item_is_rejected():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.CASH_FLOW_STATEMENT, "HK00700"))
    duplicate = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=RETRIEVED_AT,
        raw_payload=[
            {
                "STD_REPORT_DATE": "2024-12-31",
                "STD_ITEM_NAME": "经营活动产生的现金流量净额",
                "AMOUNT": 1,
            },
            {
                "STD_REPORT_DATE": "2024-12-31",
                "STD_ITEM_NAME": "经营活动产生的现金流量净额",
                "AMOUNT": 2,
            },
        ],
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="duplicate cash-flow item"):
        normalize_akshare_records(
            [duplicate],
            analysis_id="duplicate-cash-flow",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company("HK00700"),
        )


def test_h_history_range_is_applied_deterministically_during_normalization():
    provider = _provider()
    listing_metadata = provider.fetch(
        _request(DataCategory.LISTING_METADATA, "HK00700")
    )
    record = provider.fetch(
        _request(
            DataCategory.MARKET_HISTORY,
            "HK00700",
            {"start_date": "2026-09-09", "end_date": "2026-09-09"},
        )
    )
    normalized = normalize_akshare_records(
        [listing_metadata, record],
        analysis_id="h-history-fixture",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company("HK00700"),
    )

    periods = {fact.period for fact in normalized.facts if fact.field == "historical_close"}
    assert periods == {"2026-09-09"}
    listing_years = next(fact for fact in normalized.facts if fact.field == "listing_years")
    assert listing_years.value == pytest.approx(
        (date(2026, 9, 9) - date(2004, 6, 16)).days / 365.25
    )
    assert (
        next(fact for fact in normalized.facts if fact.field == "historical_close").currency
        == "HKD"
    )


def test_explicit_null_quote_is_not_zero_and_is_critical_missing():
    class NullQuote(FakeAKShare):
        def stock_zh_a_spot_em(self):
            return [{"代码": "600000", "最新价": None}]

    provider = _provider(NullQuote())
    record = provider.fetch(_request(DataCategory.MARKET_QUOTE, "SH600000"))
    normalized = normalize_akshare_records(
        [record],
        analysis_id="null-quote",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    price = next(fact for fact in normalized.facts if fact.field == "current_price")
    assert price.value is None
    assert price.value != 0
    assert normalized.data_quality.critical_missing_fields == ["current_price"]
    assert normalized.data_quality.confidence.value == "LOW"


def test_ambiguous_duplicate_history_periods_are_rejected():
    provider = _provider()
    request = _request(DataCategory.MARKET_HISTORY, "SH600000")
    record = provider.fetch(request)
    duplicate = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=RETRIEVED_AT,
        raw_payload=[
            {"日期": "2026-09-09", "收盘": 10.5},
            {"日期": "2026-09-09", "收盘": 10.6},
        ],
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="duplicate market history date"):
        normalize_akshare_records(
            [duplicate],
            analysis_id="duplicate-history",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_financial_abstract_fetch_preserves_matrix_and_records_period_metadata():
    fake = FakeAKShare()
    provider = _provider(fake)
    record = provider.fetch(_request(DataCategory.FINANCIAL_ABSTRACT, "SH600000"))

    assert record.raw_payload == _fixture("a_financial_abstract.json")
    assert record.raw_payload[2]["2024-09-30"] is None
    assert fake.calls == [
        ("stock_financial_abstract", {"symbol": "600000"}),
    ]
    assert record.response_metadata["endpoint"] == "stock_financial_abstract"
    assert record.response_metadata["upstream_row_count"] == 4
    assert record.response_metadata["entity_row_count"] == 4
    assert record.response_metadata["listing_scoped_request"] is True
    assert record.response_metadata["report_period_count"] == 2
    assert record.source_uri == (
        "https://vip.stock.finance.sina.com.cn/corp/go.php/"
        "vFD_FinanceSummary/stockid/600004.phtml"
    )


def test_financial_abstract_rejects_h_shares_and_request_parameters_before_upstream_call():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        provider.fetch(_request(DataCategory.FINANCIAL_ABSTRACT, "HK00700"))
    with pytest.raises(ProviderRequestError, match="unsupported AKShare financial-abstract"):
        provider.fetch(
            _request(
                DataCategory.FINANCIAL_ABSTRACT,
                "SH600000",
                {"start_year": "2024"},
            )
        )

    assert fake.calls == []


def test_financial_abstract_response_requires_explicit_metric_identity():
    class MissingMetric(FakeAKShare):
        def stock_financial_abstract(self, *, symbol: str):
            return self._return(
                "stock_financial_abstract",
                [{"选项": "常用指标", "20241231": 1.0}],
                symbol=symbol,
            )

    with pytest.raises(
        ProviderResponseError,
        match="financial-abstract row without explicit metric identity",
    ):
        _provider(MissingMetric()).fetch(
            _request(DataCategory.FINANCIAL_ABSTRACT, "SH600000")
        )


def test_financial_abstract_response_rejects_invalid_report_period_columns():
    class InvalidPeriod(FakeAKShare):
        def stock_financial_abstract(self, *, symbol: str):
            return self._return(
                "stock_financial_abstract",
                [
                    {
                        "选项": "常用指标",
                        "指标": "归母净利润",
                        "20241331": 1.0,
                    }
                ],
                symbol=symbol,
            )

    with pytest.raises(ProviderResponseError, match="invalid financial-abstract report-period"):
        _provider(InvalidPeriod()).fetch(
            _request(DataCategory.FINANCIAL_ABSTRACT, "SH600000")
        )


def test_financial_abstract_normalizer_keeps_matrix_as_raw_evidence_only():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.FINANCIAL_ABSTRACT, "SH600000"))
    normalized = normalize_akshare_records(
        [record],
        analysis_id="financial-abstract-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_FINANCIAL_ABSTRACT_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "consolidated_net_profit",
        "parent_net_profit",
        "reported_cfo",
        "revenue",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "wide amount, per-share and ratio" in normalized.data_quality.notes
    assert "canonical entity" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_financial_abstract_normalizer_rejects_replayed_rows_without_metric_identity():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.FINANCIAL_ABSTRACT, "SH600000"))
    payload = [dict(row) for row in record.raw_payload]
    del payload[0]["指标"]
    replayed = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="no explicit metric identity"):
        normalize_akshare_records(
            [replayed],
            analysis_id="invalid-financial-abstract-replay",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_financial_abstract_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(DataCategory.FINANCIAL_ABSTRACT, "SH600000")

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        ("stock_financial_abstract", {"symbol": "600000"}),
    ]


def test_financial_indicators_fetch_preserves_rows_and_period_metadata():
    fake = FakeAKShare()
    provider = _provider(fake)
    record = provider.fetch(_request(DataCategory.FINANCIAL_INDICATORS, "SH600000"))

    assert record.raw_payload == _fixture("a_financial_indicators.json")
    assert fake.calls == [
        (
            "stock_financial_analysis_indicator_em",
            {"symbol": "600000.SH", "indicator": "按报告期"},
        ),
    ]
    assert record.response_metadata["endpoint"] == (
        "stock_financial_analysis_indicator_em"
    )
    assert record.response_metadata["upstream_row_count"] == 2
    assert record.response_metadata["entity_row_count"] == 2
    assert record.response_metadata["listing_scoped_request"] is True
    assert record.response_metadata["report_period_count"] == 2
    assert record.response_metadata["indicator"] == "按报告期"
    assert record.source_uri == (
        "https://emweb.securities.eastmoney.com/pc_hsf10/pages/index.html?"
        "type=web&code=SZ301389&color=b#/cwfx"
    )


def test_h_financial_indicators_fetch_uses_documented_listing_and_mode():
    fake = FakeAKShare()
    provider = _provider(fake)
    record = provider.fetch(_request(DataCategory.FINANCIAL_INDICATORS, "HK00700"))

    assert record.raw_payload == _fixture("h_financial_indicators.json")
    assert fake.calls == [
        (
            "stock_financial_hk_analysis_indicator_em",
            {"symbol": "00700", "indicator": "年度"},
        ),
    ]
    assert record.response_metadata["endpoint"] == (
        "stock_financial_hk_analysis_indicator_em"
    )
    assert record.response_metadata["upstream_row_count"] == 2
    assert record.response_metadata["entity_row_count"] == 2
    assert record.response_metadata["listing_scoped_request"] is True
    assert record.response_metadata["report_period_count"] == 2
    assert record.response_metadata["indicator"] == "年度"
    assert record.response_metadata["market"] == "H"
    assert record.source_uri == (
        "https://emweb.securities.eastmoney.com/PC_HKF10/NewFinancialAnalysis/"
        "index?type=web&code=00700"
    )


def test_h_latest_indicators_fetch_uses_documented_symbol_and_keeps_snapshot_opaque():
    fake = FakeAKShare()
    provider = _provider(fake)
    record = provider.fetch(_request(DataCategory.LATEST_INDICATORS, "HK00700"))

    assert record.raw_payload == _fixture("h_latest_indicators.json")
    assert fake.calls == [
        ("stock_hk_financial_indicator_em", {"symbol": "00700"}),
    ]
    assert record.response_metadata["endpoint"] == "stock_hk_financial_indicator_em"
    assert record.response_metadata["upstream_row_count"] == 1
    assert record.response_metadata["entity_row_count"] == 1
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is True
    assert record.response_metadata["market"] == "H"
    assert record.source_uri == (
        "https://emweb.securities.eastmoney.com/PC_HKF10/pages/home/index.html"
    )


def test_h_latest_indicators_rejects_a_share_and_parameters_before_upstream_call():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="latest-indicator endpoint supports H-share"):
        provider.fetch(_request(DataCategory.LATEST_INDICATORS, "SH600000"))
    with pytest.raises(ProviderRequestError, match="unsupported AKShare latest-indicator"):
        provider.fetch(
            _request(DataCategory.LATEST_INDICATORS, "HK00700", {"indicator": "年度"})
        )

    assert fake.calls == []


def test_h_latest_indicators_response_rejects_ambiguous_rows():
    class AmbiguousRows(FakeAKShare):
        def stock_hk_financial_indicator_em(self, *, symbol: str):
            payload = _fixture("h_latest_indicators.json") * 2
            return self._return(
                "stock_hk_financial_indicator_em",
                payload,
                symbol=symbol,
            )

    with pytest.raises(ProviderResponseError, match="ambiguous latest-indicator rows"):
        _provider(AmbiguousRows()).fetch(
            _request(DataCategory.LATEST_INDICATORS, "HK00700")
        )


def test_h_latest_indicators_normalizer_keeps_mixed_snapshot_as_raw_evidence_only():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.LATEST_INDICATORS, "HK00700"))
    normalized = normalize_akshare_records(
        [record],
        analysis_id="h-latest-indicators-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company("HK00700"),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_LATEST_INDICATORS_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "consolidated_net_profit",
        "parent_net_profit",
        "reported_cfo",
        "revenue",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "latest-indicator response" in normalized.data_quality.notes
    assert "canonical period" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_h_latest_indicators_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(DataCategory.LATEST_INDICATORS, "HK00700")

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        ("stock_hk_financial_indicator_em", {"symbol": "00700"}),
    ]


def test_financial_indicators_accepts_quarterly_mode_and_rejects_unsupported_requests():
    fake = FakeAKShare()
    provider = _provider(fake)

    provider.fetch(
        _request(
            DataCategory.FINANCIAL_INDICATORS,
            "SH600000",
            {"indicator": "按单季度"},
        )
    )

    provider.fetch(
        _request(
            DataCategory.FINANCIAL_INDICATORS,
            "HK00700",
            {"indicator": "报告期"},
        )
    )
    with pytest.raises(ProviderRequestError, match="one of"):
        provider.fetch(
            _request(
                DataCategory.FINANCIAL_INDICATORS,
                "SH600000",
                {"indicator": "年度"},
            )
        )
    with pytest.raises(ProviderRequestError, match="unsupported AKShare financial-indicators"):
        provider.fetch(
            _request(
                DataCategory.FINANCIAL_INDICATORS,
                "SH600000",
                {"start_year": "2024"},
            )
        )

    assert fake.calls == [
        (
            "stock_financial_analysis_indicator_em",
            {"symbol": "600000.SH", "indicator": "按单季度"},
        ),
        (
            "stock_financial_hk_analysis_indicator_em",
            {"symbol": "00700", "indicator": "报告期"},
        ),
    ]


def test_h_financial_indicators_response_rejects_cross_listing_or_invalid_dates():
    class InvalidRows(FakeAKShare):
        def __init__(self, mode: str) -> None:
            super().__init__()
            self.mode = mode

        def stock_financial_hk_analysis_indicator_em(
            self,
            *,
            symbol: str,
            indicator: str,
        ):
            rows = [dict(row) for row in _fixture("h_financial_indicators.json")]
            if self.mode == "missing_code":
                rows[0].pop("SECUCODE")
                rows[0].pop("SECURITY_CODE")
            elif self.mode == "wrong_code":
                rows[0]["SECUCODE"] = "00001.HK"
                rows[0]["SECURITY_CODE"] = "00001"
            else:
                rows[0]["REPORT_DATE"] = "2024-13-31"
            return self._return(
                "stock_financial_hk_analysis_indicator_em",
                rows,
                symbol=symbol,
                indicator=indicator,
            )

    with pytest.raises(ProviderResponseError, match="without a listing code"):
        _provider(InvalidRows("missing_code")).fetch(
            _request(DataCategory.FINANCIAL_INDICATORS, "HK00700")
        )
    with pytest.raises(ProviderResponseError, match="financial-indicator row entity"):
        _provider(InvalidRows("wrong_code")).fetch(
            _request(DataCategory.FINANCIAL_INDICATORS, "HK00700")
        )
    with pytest.raises(ProviderResponseError, match="invalid financial-indicator report date"):
        _provider(InvalidRows("invalid_date")).fetch(
            _request(DataCategory.FINANCIAL_INDICATORS, "HK00700")
        )


def test_financial_indicators_response_requires_matching_listing_and_report_date():
    class InvalidRows(FakeAKShare):
        def __init__(self, mode: str) -> None:
            super().__init__()
            self.mode = mode

        def stock_financial_analysis_indicator_em(
            self,
            *,
            symbol: str,
            indicator: str,
        ):
            rows = [dict(row) for row in _fixture("a_financial_indicators.json")]
            if self.mode == "missing_code":
                rows[0].pop("SECUCODE")
                rows[0].pop("SECURITY_CODE")
            elif self.mode == "wrong_code":
                rows[0]["SECUCODE"] = "000001.SZ"
                rows[0]["SECURITY_CODE"] = "000001"
            elif self.mode == "invalid_date":
                rows[0]["REPORT_DATE"] = "2024-13-31"
            else:
                rows[0].pop("REPORT_DATE")
            return self._return(
                "stock_financial_analysis_indicator_em",
                rows,
                symbol=symbol,
                indicator=indicator,
            )

    with pytest.raises(ProviderResponseError, match="without a listing code"):
        _provider(InvalidRows("missing_code")).fetch(
            _request(DataCategory.FINANCIAL_INDICATORS, "SH600000")
        )
    with pytest.raises(ProviderResponseError, match="financial-indicator row entity"):
        _provider(InvalidRows("wrong_code")).fetch(
            _request(DataCategory.FINANCIAL_INDICATORS, "SH600000")
        )
    with pytest.raises(ProviderResponseError, match="invalid financial-indicator report date"):
        _provider(InvalidRows("invalid_date")).fetch(
            _request(DataCategory.FINANCIAL_INDICATORS, "SH600000")
        )
    with pytest.raises(ProviderResponseError, match="without a report date"):
        _provider(InvalidRows("missing_date")).fetch(
            _request(DataCategory.FINANCIAL_INDICATORS, "SH600000")
        )


def test_financial_indicators_normalizer_keeps_mixed_metrics_as_raw_evidence_only():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.FINANCIAL_INDICATORS, "SH600000"))
    normalized = normalize_akshare_records(
        [record],
        analysis_id="financial-indicators-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_FINANCIAL_INDICATORS_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "consolidated_net_profit",
        "parent_net_profit",
        "reported_cfo",
        "revenue",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "reported amounts, per-share values" in normalized.data_quality.notes
    assert "canonical entity" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_h_financial_indicators_normalizer_keeps_metrics_as_raw_evidence_only():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.FINANCIAL_INDICATORS, "HK00700"))
    normalized = normalize_akshare_records(
        [record],
        analysis_id="h-financial-indicators-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company("HK00700"),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_FINANCIAL_INDICATORS_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "consolidated_net_profit",
        "parent_net_profit",
        "reported_cfo",
        "revenue",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "A-share/H-share financial-indicator" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_financial_indicators_normalizer_rejects_replayed_rows_with_wrong_identity_or_mode():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.FINANCIAL_INDICATORS, "SH600000"))
    payload = [dict(row) for row in record.raw_payload]
    payload[0]["SECUCODE"] = "000001.SZ"
    payload[0]["SECURITY_CODE"] = "000001"
    replayed = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="financial-indicator row entity"):
        normalize_akshare_records(
            [replayed],
            analysis_id="invalid-financial-indicators-replay",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )

    invalid_mode = record.__class__(
        provider=record.provider,
        request=record.request.__class__(
            category=record.request.category,
            entity_id=record.request.entity_id,
            parameters={"indicator": "年度"},
        ),
        retrieved_at=record.retrieved_at,
        raw_payload=record.raw_payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )
    with pytest.raises(ProviderNormalizationError, match="one of"):
        normalize_akshare_records(
            [invalid_mode],
            analysis_id="invalid-financial-indicators-mode",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_financial_indicators_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(DataCategory.FINANCIAL_INDICATORS, "SH600000")

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        (
            "stock_financial_analysis_indicator_em",
            {"symbol": "600000.SH", "indicator": "按报告期"},
        )
    ]


def test_h_financial_indicators_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(DataCategory.FINANCIAL_INDICATORS, "HK00700")

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        (
            "stock_financial_hk_analysis_indicator_em",
            {"symbol": "00700", "indicator": "年度"},
        )
    ]
