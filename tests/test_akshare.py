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

    def stock_esg_rate_sina(self):
        return self._return("stock_esg_rate_sina", _fixture("esg_ratings.json"))

    def stock_margin_detail_sse(self, *, date: str):
        return self._return(
            "stock_margin_detail_sse",
            _fixture("a_margin_detail_sse.json"),
            date=date,
        )

    def stock_margin_detail_szse(self, *, date: str):
        return self._return(
            "stock_margin_detail_szse",
            _fixture("a_margin_detail_szse.json"),
            date=date,
        )

    def stock_margin_detail_bse(self, *, date: str):
        return self._return(
            "stock_margin_detail_bse",
            _fixture("a_margin_detail_bse.json"),
            date=date,
        )

    def stock_tfp_em(self, *, date: str):
        return self._return(
            "stock_tfp_em",
            _fixture("a_trading_suspensions.json"),
            date=date,
        )

    def stock_sy_jz_em(self, *, date: str):
        return self._return(
            "stock_sy_jz_em",
            _fixture("a_goodwill_impairment.json"),
            date=date,
        )

    def stock_zh_a_spot_em(self):
        return self._return("stock_zh_a_spot_em", _fixture("a_quote.json"))

    def stock_hk_spot_em(self):
        return self._return("stock_hk_spot_em", _fixture("h_quote.json"))

    def stock_zh_a_hist(self, **kwargs):
        return self._return("stock_zh_a_hist", _fixture("a_history.json"), **kwargs)

    def stock_hk_daily(self, **kwargs):
        return self._return("stock_hk_daily", _fixture("h_history.json"), **kwargs)

    def stock_individual_fund_flow(self, *, stock: str, market: str):
        return self._return(
            "stock_individual_fund_flow",
            _fixture("a_individual_fund_flow.json"),
            stock=stock,
            market=market,
        )

    def stock_lhb_detail_em(self, *, start_date: str, end_date: str):
        return self._return(
            "stock_lhb_detail_em",
            _fixture("a_lhb_detail.json"),
            start_date=start_date,
            end_date=end_date,
        )

    def stock_lhb_stock_statistic_em(self, *, symbol: str):
        return self._return(
            "stock_lhb_stock_statistic_em",
            _fixture("a_lhb_stock_statistic.json"),
            symbol=symbol,
        )

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

    def stock_individual_info_em(self, *, symbol: str):
        return self._return(
            "stock_individual_info_em",
            _fixture("a_individual_info.json"),
            symbol=symbol,
        )

    def stock_share_change_cninfo(self, **kwargs):
        return self._return(
            "stock_share_change_cninfo",
            _fixture("a_share_change_cninfo.json"),
            **kwargs,
        )

    def stock_restricted_release_queue_em(self, *, symbol: str):
        return self._return(
            "stock_restricted_release_queue_em",
            _fixture("a_restricted_release_queue.json"),
            symbol=symbol,
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

    def stock_cg_guarantee_cninfo(self, **kwargs):
        return self._return(
            "stock_cg_guarantee_cninfo",
            _fixture("a_external_guarantees.json"),
            **kwargs,
        )

    def stock_cg_lawsuit_cninfo(self, **kwargs):
        return self._return(
            "stock_cg_lawsuit_cninfo",
            _fixture("a_litigation.json"),
            **kwargs,
        )

    def stock_gpzy_pledge_ratio_em(self, *, date: str):
        return self._return(
            "stock_gpzy_pledge_ratio_em",
            _fixture("a_ownership_pledge.json"),
            date=date,
        )

    def stock_gpzy_individual_pledge_ratio_detail_em(self, *, symbol: str):
        return self._return(
            "stock_gpzy_individual_pledge_ratio_detail_em",
            _fixture("a_individual_pledge_detail.json"),
            symbol=symbol,
        )

    def stock_cg_equity_mortgage_cninfo(self, *, date: str):
        return self._return(
            "stock_cg_equity_mortgage_cninfo",
            _fixture("a_equity_mortgage.json"),
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

    def stock_hold_management_detail_em(self):
        return self._return(
            "stock_hold_management_detail_em",
            _fixture("a_management_holdings.json"),
        )

    def stock_main_stock_holder(self, *, stock: str):
        return self._return(
            "stock_main_stock_holder",
            _fixture("a_main_stock_holder.json"),
            stock=stock,
        )

    def stock_hold_num_cninfo(self, *, date: str):
        return self._return(
            "stock_hold_num_cninfo",
            _fixture("a_shareholder_counts.json"),
            date=date,
        )

    def stock_hold_control_cninfo(self, *, symbol: str):
        return self._return(
            "stock_hold_control_cninfo",
            _fixture("a_control_holdings.json"),
            symbol=symbol,
        )

    def stock_gdfx_top_10_em(self, *, symbol: str, date: str):
        return self._return(
            "stock_gdfx_top_10_em",
            _fixture("a_top_10_holders.json"),
            symbol=symbol,
            date=date,
        )

    def stock_gdfx_free_top_10_em(self, *, symbol: str, date: str):
        return self._return(
            "stock_gdfx_free_top_10_em",
            _fixture("a_free_top_10_holders.json"),
            symbol=symbol,
            date=date,
        )

    def stock_gdfx_free_holding_detail_em(self, *, date: str):
        return self._return(
            "stock_gdfx_free_holding_detail_em",
            _fixture("a_free_holding_detail.json"),
            date=date,
        )

    def stock_hsgt_individual_em(self, *, symbol: str):
        fixture = (
            "a_hsgt_individual_holdings.json"
            if len(symbol) == 6
            else "h_hsgt_individual_holdings.json"
        )
        return self._return(
            "stock_hsgt_individual_em",
            _fixture(fixture),
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
        "capital_flow",
        "cash_flow_statement",
        "company_metadata",
        "corporate_actions",
        "disclosure_notices",
        "dividends",
        "earnings_forecast",
        "earnings_quick_report",
        "esg_ratings",
        "external_guarantees",
        "financial_abstract",
        "financial_indicators",
        "goodwill_impairment",
        "income_statement",
        "insider_share_changes",
        "latest_indicators",
        "listing_metadata",
        "litigation",
        "margin_trading",
        "market_activity",
        "market_history",
        "market_quote",
        "ownership_pledge",
        "performance_report",
        "risk_warning_status",
        "share_capital",
        "shareholder_holdings",
        "trading_suspensions",
    )
    assert provider.identity.provider_id == "akshare"
    assert provider.identity.provider_version == "49"
    assert AKSHARE_MAPPING_VERSION == "50"


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


def test_trading_suspension_fetch_filters_the_documented_date_bound_universe():
    fake = FakeAKShare()
    record = _provider(fake).fetch(
        _request(
            DataCategory.TRADING_SUSPENSIONS,
            "SH600000",
            {"date": "20240426"},
        )
    )

    fixture = _fixture("a_trading_suspensions.json")
    assert record.raw_payload == [row for row in fixture if row["代码"] == "600000"]
    assert fake.calls == [("stock_tfp_em", {"date": "20240426"})]
    assert record.response_metadata["endpoint"] == "stock_tfp_em"
    assert record.response_metadata["upstream_row_count"] == 3
    assert record.response_metadata["entity_row_count"] == 2
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is False
    assert record.response_metadata["row_filtering"] == "provider"
    assert record.response_metadata["requested_date"] == "20240426"
    assert record.response_metadata["snapshot_scope"] == "requested_date"
    assert record.source_uri == "https://data.eastmoney.com/tfpxx/"


def test_trading_suspension_request_validates_date_and_market_before_upstream_call():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="requires date"):
        provider.fetch(_request(DataCategory.TRADING_SUSPENSIONS, "SH600000"))
    with pytest.raises(ProviderRequestError, match="date must be YYYYMMDD"):
        provider.fetch(
            _request(
                DataCategory.TRADING_SUSPENSIONS,
                "SH600000",
                {"date": "2024-04-26"},
            )
        )
    with pytest.raises(ProviderRequestError, match="date must be a valid YYYYMMDD"):
        provider.fetch(
            _request(
                DataCategory.TRADING_SUSPENSIONS,
                "SH600000",
                {"date": "20240230"},
            )
        )
    with pytest.raises(ProviderRequestError, match="unsupported AKShare trading-suspension"):
        provider.fetch(
            _request(
                DataCategory.TRADING_SUSPENSIONS,
                "SH600000",
                {"date": "20240426", "market": "沪深京"},
            )
        )
    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        provider.fetch(
            _request(
                DataCategory.TRADING_SUSPENSIONS,
                "HK00700",
                {"date": "20240426"},
            )
        )

    assert fake.calls == []


def test_trading_suspension_response_rejects_missing_codes_and_invalid_dates():
    class MissingCode(FakeAKShare):
        def stock_tfp_em(self, *, date: str):
            return self._return(
                "stock_tfp_em",
                [{"代码": None, "停牌时间": "2024-04-26"}],
                date=date,
            )

    with pytest.raises(ProviderResponseError, match="trading-suspension row without"):
        _provider(MissingCode()).fetch(
            _request(DataCategory.TRADING_SUSPENSIONS, "SH600000", {"date": "20240426"})
        )

    class InvalidDate(FakeAKShare):
        def stock_tfp_em(self, *, date: str):
            payload = _fixture("a_trading_suspensions.json")
            payload[0]["预计复牌时间"] = "not-a-date"
            return self._return("stock_tfp_em", payload, date=date)

    with pytest.raises(ProviderResponseError, match="invalid trading-suspension date"):
        _provider(InvalidDate()).fetch(
            _request(DataCategory.TRADING_SUSPENSIONS, "SH600000", {"date": "20240426"})
        )


def test_trading_suspension_with_no_matching_listing_is_an_empty_raw_snapshot():
    class NoSuspension(FakeAKShare):
        def stock_tfp_em(self, *, date: str):
            return self._return(
                "stock_tfp_em",
                [{"代码": "000001", "停牌时间": "2024-04-26"}],
                date=date,
            )

    record = _provider(NoSuspension()).fetch(
        _request(DataCategory.TRADING_SUSPENSIONS, "SH600000", {"date": "20240426"})
    )

    assert record.raw_payload == []
    assert record.response_metadata["upstream_row_count"] == 1
    assert record.response_metadata["entity_row_count"] == 0


def test_trading_suspension_raw_record_is_not_promoted_to_status_or_governance_facts():
    provider = _provider()
    record = provider.fetch(
        _request(DataCategory.TRADING_SUSPENSIONS, "SH600000", {"date": "20240426"})
    )
    normalized = normalize_akshare_records(
        [record],
        analysis_id="trading-suspension-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_TRADING_SUSPENSIONS_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "governance_risk_level",
        "special_treatment",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "complete special-treatment status" in normalized.data_quality.notes
    assert "governance conclusion" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_trading_suspension_normalizer_rejects_replayed_rows_for_another_listing():
    provider = _provider()
    record = provider.fetch(
        _request(DataCategory.TRADING_SUSPENSIONS, "SH600000", {"date": "20240426"})
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

    with pytest.raises(ProviderNormalizationError, match="trading-suspension row entity"):
        normalize_akshare_records(
            [mismatched],
            analysis_id="mismatched-trading-suspension",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_trading_suspension_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.TRADING_SUSPENSIONS,
        "SH600000",
        {"date": "20240426"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [("stock_tfp_em", {"date": "20240426"})]


def test_main_shareholder_fetch_uses_documented_listing_scoped_endpoint():
    fake = FakeAKShare()
    record = _provider(fake).fetch(
        _request(DataCategory.SHAREHOLDER_HOLDINGS, "SH600000")
    )

    assert record.raw_payload == _fixture("a_main_stock_holder.json")
    assert fake.calls == [
        ("stock_main_stock_holder", {"stock": "600000"}),
    ]
    assert record.response_metadata["endpoint"] == "stock_main_stock_holder"
    assert record.response_metadata["upstream_row_count"] == 3
    assert record.response_metadata["entity_row_count"] == 3
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is True
    assert record.source_uri == (
        "https://vip.stock.finance.sina.com.cn/corp/go.php/"
        "vCI_StockHolder/stockid/600004.phtml"
    )


def test_hsgt_individual_holdings_fetch_uses_explicit_view_for_a_and_h_listings():
    fake = FakeAKShare()
    provider = _provider(fake)
    a_record = provider.fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            "SH600000",
            {"view": "hsgt_individual"},
        )
    )
    h_record = provider.fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            "HK00700",
            {"view": "hsgt_individual"},
        )
    )

    assert a_record.raw_payload == _fixture("a_hsgt_individual_holdings.json")
    assert h_record.raw_payload == _fixture("h_hsgt_individual_holdings.json")
    assert fake.calls == [
        ("stock_hsgt_individual_em", {"symbol": "600000"}),
        ("stock_hsgt_individual_em", {"symbol": "00700"}),
    ]
    assert a_record.response_metadata["endpoint"] == "stock_hsgt_individual_em"
    assert a_record.response_metadata["upstream_row_count"] == 2
    assert a_record.response_metadata["entity_row_count"] == 2
    assert a_record.response_metadata["entity_rows_selected"] is True
    assert a_record.response_metadata["listing_scoped_request"] is True
    assert a_record.response_metadata["snapshot_scope"] == "historical_published_dataset"
    assert a_record.response_metadata["observation_date_field"] == "持股日期"
    assert h_record.response_metadata["market"] == "H"
    assert h_record.response_metadata["listing_code"] == "00700"
    assert h_record.source_uri == "https://data.eastmoney.com/hsgt/StockHdDetail/002008.html"


def test_hsgt_individual_holdings_request_requires_explicit_view_and_rejects_extra_parameters():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        provider.fetch(_request(DataCategory.SHAREHOLDER_HOLDINGS, "HK00700"))
    with pytest.raises(ProviderRequestError, match="requires view='hsgt_individual'"):
        provider.fetch(
            _request(
                DataCategory.SHAREHOLDER_HOLDINGS,
                "SH600000",
                {"view": "unknown"},
            )
        )
    with pytest.raises(
        ProviderRequestError,
        match="unsupported AKShare HSGT individual-holdings parameter",
    ):
        provider.fetch(
            _request(
                DataCategory.SHAREHOLDER_HOLDINGS,
                "HK00700",
                {"view": "hsgt_individual", "date": "20240816"},
            )
        )

    assert fake.calls == []


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("missing_date", "without a holding date"),
        ("invalid_date", "invalid HSGT individual-holdings date"),
        ("wrong_entity", "HSGT individual-holdings row entity"),
    ],
)
def test_hsgt_individual_holdings_response_validates_dates_and_optional_identity(
    mutation: str,
    match: str,
):
    class InvalidRows(FakeAKShare):
        def stock_hsgt_individual_em(self, *, symbol: str):
            rows = _fixture("a_hsgt_individual_holdings.json")
            if mutation == "missing_date":
                rows[0].pop("持股日期")
            elif mutation == "invalid_date":
                rows[0]["持股日期"] = "not-a-date"
            elif mutation == "wrong_entity":
                rows[0]["证券代码"] = "000001"
            return self._return("stock_hsgt_individual_em", rows, symbol=symbol)

    with pytest.raises(ProviderResponseError, match=match):
        _provider(InvalidRows()).fetch(
            _request(
                DataCategory.SHAREHOLDER_HOLDINGS,
                "SH600000",
                {"view": "hsgt_individual"},
            )
        )


@pytest.mark.parametrize(
    ("listing", "fixture", "analysis_id"),
    [
        ("SH600000", "a_hsgt_individual_holdings.json", "a-hsgt-raw-only"),
        ("HK00700", "h_hsgt_individual_holdings.json", "h-hsgt-raw-only"),
    ],
)
def test_hsgt_individual_holdings_are_retained_as_raw_evidence_without_canonical_facts(
    listing: str,
    fixture: str,
    analysis_id: str,
):
    record = _provider().fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            listing,
            {"view": "hsgt_individual"},
        )
    )

    normalized = normalize_akshare_records(
        [record],
        analysis_id=analysis_id,
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(listing),
    )

    assert record.raw_payload == _fixture(fixture)
    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_HSGT_INDIVIDUAL_HOLDINGS_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "governance_risk_level",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "investor holding quantities" in normalized.data_quality.notes
    assert "diluted-share series" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(
        Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json"))
    ) == []


def test_hsgt_individual_holdings_normalizer_rejects_invalid_replayed_dates():
    record = _provider().fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            "HK00700",
            {"view": "hsgt_individual"},
        )
    )
    payload = [dict(row) for row in record.raw_payload]
    payload[0]["持股日期"] = "not-a-date"
    replayed = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(
        ProviderNormalizationError,
        match="HSGT individual-holdings row has an invalid holding date",
    ):
        normalize_akshare_records(
            [replayed],
            analysis_id="invalid-hsgt-date",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company("HK00700"),
        )


def test_hsgt_individual_holdings_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.SHAREHOLDER_HOLDINGS,
        "HK00700",
        {"view": "hsgt_individual"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        ("stock_hsgt_individual_em", {"symbol": "00700"}),
    ]


def test_actual_controller_holding_changes_filter_the_documented_cninfo_universe():
    fake = FakeAKShare()
    record = _provider(fake).fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            "SH600000",
            {"view": "control_changes"},
        )
    )

    fixture = _fixture("a_control_holdings.json")
    assert record.raw_payload == [row for row in fixture if row["证券代码"] == "600000"]
    assert fake.calls == [
        ("stock_hold_control_cninfo", {"symbol": "全部"}),
    ]
    assert record.response_metadata["endpoint"] == "stock_hold_control_cninfo"
    assert record.response_metadata["upstream_row_count"] == 3
    assert record.response_metadata["entity_row_count"] == 2
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is False
    assert record.response_metadata["row_filtering"] == "provider"
    assert record.response_metadata["upstream_symbol"] == "全部"
    assert record.response_metadata["control_type"] == "全部"
    assert record.response_metadata["control_view"] == "control_changes"
    assert record.response_metadata["snapshot_scope"] == "historical_published_dataset"
    assert record.response_metadata["observation_date_field"] == "变动日期"
    assert record.source_uri == "https://webapi.cninfo.com.cn/#/thematicStatistics"


def test_actual_controller_holding_changes_pass_the_documented_control_scope():
    fake = FakeAKShare()
    record = _provider(fake).fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            "SH600000",
            {"view": "control_changes", "control_type": "实际控制人"},
        )
    )

    assert record.response_metadata["control_type"] == "实际控制人"
    assert fake.calls == [
        ("stock_hold_control_cninfo", {"symbol": "实际控制人"}),
    ]


@pytest.mark.parametrize(
    ("parameters", "match"),
    [
        ({"view": "control_changes", "unexpected": True}, "unsupported AKShare actual-controller"),
        ({"view": "control_changes", "control_type": "unknown"}, "control_type must be one of"),
    ],
)
def test_actual_controller_holding_change_request_validates_view_and_scope(
    parameters: dict,
    match: str,
):
    fake = FakeAKShare()

    with pytest.raises(ProviderRequestError, match=match):
        _provider(fake).fetch(
            _request(DataCategory.SHAREHOLDER_HOLDINGS, "SH600000", parameters)
        )

    assert fake.calls == []


def test_actual_controller_holding_change_request_is_a_share_only():
    fake = FakeAKShare()

    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        _provider(fake).fetch(
            _request(
                DataCategory.SHAREHOLDER_HOLDINGS,
                "HK00700",
                {"view": "control_changes"},
            )
        )

    assert fake.calls == []


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("missing_code", "actual-controller holding-change row without a listing code"),
        ("missing_date", "actual-controller holding-change row without a change date"),
        ("invalid_date", "invalid actual-controller holding-change date"),
    ],
)
def test_actual_controller_holding_change_response_validates_identity_and_dates(
    mutation: str,
    match: str,
):
    class InvalidRows(FakeAKShare):
        def stock_hold_control_cninfo(self, *, symbol: str):
            rows = _fixture("a_control_holdings.json")
            if mutation == "missing_code":
                rows[0].pop("证券代码")
            elif mutation == "missing_date":
                rows[0].pop("变动日期")
            else:
                rows[0]["变动日期"] = "not-a-date"
            return self._return("stock_hold_control_cninfo", rows, symbol=symbol)

    with pytest.raises(ProviderResponseError, match=match):
        _provider(InvalidRows()).fetch(
            _request(
                DataCategory.SHAREHOLDER_HOLDINGS,
                "SH600000",
                {"view": "control_changes"},
            )
        )


def test_actual_controller_holding_changes_are_raw_only_without_canonical_facts():
    record = _provider().fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            "SH600000",
            {"view": "control_changes"},
        )
    )
    normalized = normalize_akshare_records(
        [record],
        analysis_id="actual-controller-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_CONTROL_HOLDINGS_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "governance_risk_level",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "filing-backed control" in normalized.data_quality.notes
    assert "diluted-share conclusion" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(
        Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json"))
    ) == []


def test_actual_controller_holding_change_normalizer_rejects_replayed_scope_mismatches():
    record = _provider().fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            "SH600000",
            {"view": "control_changes"},
        )
    )
    payload = [dict(row) for row in record.raw_payload]
    payload[0]["证券代码"] = "000001"
    replayed = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(
        ProviderNormalizationError,
        match="actual-controller holding-change row entity",
    ):
        normalize_akshare_records(
            [replayed],
            analysis_id="invalid-actual-controller-entity",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_actual_controller_holding_changes_cache_replay_does_not_call_upstream(
    tmp_path: Path,
):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.SHAREHOLDER_HOLDINGS,
        "SH600000",
        {"view": "control_changes"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        ("stock_hold_control_cninfo", {"symbol": "全部"}),
    ]


def test_main_shareholder_request_is_a_share_only_and_accepts_no_parameters():
    fake = FakeAKShare()
    provider = _provider(fake)

    record = provider.fetch(_request(DataCategory.SHAREHOLDER_HOLDINGS, "SH600000"))
    assert record.response_metadata["endpoint"] == "stock_main_stock_holder"
    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        provider.fetch(_request(DataCategory.SHAREHOLDER_HOLDINGS, "HK00700"))

    assert fake.calls == [("stock_main_stock_holder", {"stock": "600000"})]


def test_main_shareholder_response_rejects_invalid_documented_dates():
    class InvalidDate(FakeAKShare):
        def stock_main_stock_holder(self, *, stock: str):
            payload = _fixture("a_main_stock_holder.json")
            payload[0]["公告日期"] = "not-a-date"
            return self._return("stock_main_stock_holder", payload, stock=stock)

    with pytest.raises(ProviderResponseError, match="invalid main-shareholder date"):
        _provider(InvalidDate()).fetch(
            _request(DataCategory.SHAREHOLDER_HOLDINGS, "SH600000")
        )


def test_main_shareholder_raw_record_is_not_promoted_to_ownership_or_share_facts():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.SHAREHOLDER_HOLDINGS, "SH600000"))
    normalized = normalize_akshare_records(
        [record],
        analysis_id="main-shareholder-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_MAIN_SHAREHOLDERS_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "governance_risk_level",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "beneficial control" in normalized.data_quality.notes
    assert "diluted-share series" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_main_shareholder_normalizer_rejects_invalid_replayed_dates():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.SHAREHOLDER_HOLDINGS, "SH600000"))
    mismatched_payload = [dict(row) for row in record.raw_payload]
    mismatched_payload[0]["截至日期"] = "not-a-date"
    mismatched = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=mismatched_payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="main-shareholder row has an invalid"):
        normalize_akshare_records(
            [mismatched],
            analysis_id="invalid-main-shareholder-date",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_main_shareholder_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(DataCategory.SHAREHOLDER_HOLDINGS, "SH600000")

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        ("stock_main_stock_holder", {"stock": "600000"}),
    ]


def test_shareholder_count_fetch_filters_the_documented_quarter_end_universe():
    fake = FakeAKShare()
    record = _provider(fake).fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            "SH600000",
            {"date": "20241231"},
        )
    )

    fixture = _fixture("a_shareholder_counts.json")
    assert record.raw_payload == [row for row in fixture if row["证券代码"] == "600000"]
    assert fake.calls == [("stock_hold_num_cninfo", {"date": "20241231"})]
    assert record.response_metadata["endpoint"] == "stock_hold_num_cninfo"
    assert record.response_metadata["upstream_row_count"] == 3
    assert record.response_metadata["entity_row_count"] == 1
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is False
    assert record.response_metadata["row_filtering"] == "provider"
    assert record.response_metadata["requested_date"] == "20241231"
    assert record.response_metadata["observation_date"] == "2024-12-31"
    assert record.response_metadata["date_binding"] == "row_and_request"
    assert record.response_metadata["snapshot_scope"] == "requested_quarter_end"
    assert record.source_uri == "https://webapi.cninfo.com.cn/#/thematicStatistics"


@pytest.mark.parametrize(
    ("parameters", "match"),
    [
        ({"date": "2024-12-31"}, "date must be YYYYMMDD"),
        ({"date": "20241331"}, "date must be a valid YYYYMMDD date"),
        ({"date": "20161231"}, "date must be on or after 20170331"),
        ({"date": "20241230"}, "date must be an exact quarter-end report date"),
        (
            {"date": "20241231", "market": "沪市"},
            "unsupported AKShare shareholder-count parameter",
        ),
    ],
)
def test_shareholder_count_request_requires_documented_quarter_end_date(
    parameters: dict,
    match: str,
):
    fake = FakeAKShare()

    with pytest.raises(ProviderRequestError, match=match):
        _provider(fake).fetch(
            _request(DataCategory.SHAREHOLDER_HOLDINGS, "SH600000", parameters)
        )

    assert fake.calls == []


def test_shareholder_count_request_is_a_share_only_before_upstream_call():
    fake = FakeAKShare()

    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        _provider(fake).fetch(
            _request(
                DataCategory.SHAREHOLDER_HOLDINGS,
                "HK00700",
                {"date": "20241231"},
            )
        )

    assert fake.calls == []


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("missing_code", "shareholder-count row without a listing code"),
        ("missing_date", "shareholder-count row without an observation date"),
        ("invalid_date", "invalid shareholder-count observation date"),
        ("wrong_date", "shareholder-count row date"),
    ],
)
def test_shareholder_count_response_requires_explicit_code_and_matching_date(
    mutation: str,
    match: str,
):
    class InvalidRows(FakeAKShare):
        def stock_hold_num_cninfo(self, *, date: str):
            rows = _fixture("a_shareholder_counts.json")
            if mutation == "missing_code":
                rows[0].pop("证券代码")
            elif mutation == "missing_date":
                rows[0].pop("变动日期")
            elif mutation == "invalid_date":
                rows[0]["变动日期"] = "not-a-date"
            elif mutation == "wrong_date":
                rows[0]["变动日期"] = "2024-09-30"
            return self._return("stock_hold_num_cninfo", rows, date=date)

    with pytest.raises(ProviderResponseError, match=match):
        _provider(InvalidRows()).fetch(
            _request(
                DataCategory.SHAREHOLDER_HOLDINGS,
                "SH600000",
                {"date": "20241231"},
            )
        )


def test_shareholder_count_with_no_matching_listing_is_an_empty_raw_snapshot():
    class NoMatchingShareholderCount(FakeAKShare):
        def stock_hold_num_cninfo(self, *, date: str):
            return self._return(
                "stock_hold_num_cninfo",
                [
                    row
                    for row in _fixture("a_shareholder_counts.json")
                    if row["证券代码"] == "000001"
                ],
                date=date,
            )

    record = _provider(NoMatchingShareholderCount()).fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            "SH600000",
            {"date": "20241231"},
        )
    )

    assert record.raw_payload == []
    assert record.response_metadata["upstream_row_count"] == 1
    assert record.response_metadata["entity_row_count"] == 0


def test_shareholder_count_raw_record_is_not_promoted_to_canonical_facts():
    record = _provider().fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            "SH600000",
            {"date": "20241231"},
        )
    )

    normalized = normalize_akshare_records(
        [record],
        analysis_id="shareholder-count-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_SHAREHOLDER_COUNTS_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "governance_risk_level",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "quarter-end shareholder counts" in normalized.data_quality.notes
    assert "canonical concentration metric" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("entity", "shareholder-count row entity"),
        ("date", "shareholder-count row date"),
        ("missing_date", "shareholder-count row has no exact observation date"),
    ],
)
def test_shareholder_count_normalizer_rejects_replayed_scope_mismatches(
    mutation: str,
    match: str,
):
    record = _provider().fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            "SH600000",
            {"date": "20241231"},
        )
    )
    payload = [dict(row) for row in record.raw_payload]
    if mutation == "entity":
        payload[0]["证券代码"] = "000001"
    elif mutation == "date":
        payload[0]["变动日期"] = "2024-09-30"
    else:
        payload[0].pop("变动日期")
    replayed = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match=match):
        normalize_akshare_records(
            [replayed],
            analysis_id="mismatched-shareholder-count",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_shareholder_count_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.SHAREHOLDER_HOLDINGS,
        "SH600000",
        {"date": "20241231"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [("stock_hold_num_cninfo", {"date": "20241231"})]


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


def test_individual_info_fetch_requires_explicit_view_and_preserves_snapshot_rows():
    fake = FakeAKShare()
    provider = _provider(fake)
    request = _request(
        DataCategory.SHARE_CAPITAL,
        "SH600000",
        {"view": "individual_info"},
    )

    record = provider.fetch(request)

    assert record.raw_payload == _fixture("a_individual_info.json")
    assert fake.calls == [
        ("stock_individual_info_em", {"symbol": "600000"}),
    ]
    assert record.response_metadata["endpoint"] == "stock_individual_info_em"
    assert record.response_metadata["upstream_row_count"] == 9
    assert record.response_metadata["entity_row_count"] == 9
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is True
    assert record.response_metadata["individual_info_view"] == "individual_info"
    assert record.response_metadata["snapshot_scope"] == "current_provider_snapshot"
    assert record.source_uri == "https://quote.eastmoney.com/concept/"


def test_individual_info_request_rejects_non_view_parameters_before_upstream_call():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="unsupported AKShare individual-info"):
        provider.fetch(
            _request(
                DataCategory.SHARE_CAPITAL,
                "SH600000",
                {"view": "individual_info", "date": "20240930"},
            )
        )

    assert fake.calls == []


def test_individual_info_response_rejects_wrong_identity_or_invalid_listing_date():
    class WrongEntityAKShare(FakeAKShare):
        def stock_individual_info_em(self, *, symbol: str):
            payload = _fixture("a_individual_info.json")
            next(row for row in payload if row["item"] == "股票代码")["value"] = "000001"
            return self._return("stock_individual_info_em", payload, symbol=symbol)

    class InvalidDateAKShare(FakeAKShare):
        def stock_individual_info_em(self, *, symbol: str):
            payload = _fixture("a_individual_info.json")
            next(row for row in payload if row["item"] == "上市时间")["value"] = "not-a-date"
            return self._return("stock_individual_info_em", payload, symbol=symbol)

    request = _request(
        DataCategory.SHARE_CAPITAL,
        "SH600000",
        {"view": "individual_info"},
    )
    with pytest.raises(ProviderResponseError, match="individual-info response entity"):
        _provider(WrongEntityAKShare()).fetch(request)
    with pytest.raises(ProviderResponseError, match="上市时间 is not a valid date"):
        _provider(InvalidDateAKShare()).fetch(request)


def test_individual_info_snapshot_is_raw_only_and_keeps_diluted_shares_missing():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.SHARE_CAPITAL,
            "SH600000",
            {"view": "individual_info"},
        )
    )
    normalized = normalize_akshare_records(
        [record],
        analysis_id="individual-info-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_INDIVIDUAL_INFO_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "normalized_diluted_economic_shares",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "canonical period, unit or diluted economic-share scope" in (
        normalized.data_quality.notes
    )

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_individual_info_normalizer_rejects_replayed_identity_mismatch():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.SHARE_CAPITAL,
            "SH600000",
            {"view": "individual_info"},
        )
    )
    mismatched_payload = [dict(row) for row in record.raw_payload]
    next(row for row in mismatched_payload if row["item"] == "股票代码")["value"] = "000001"
    mismatched = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=mismatched_payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="individual-info response entity"):
        normalize_akshare_records(
            [mismatched],
            analysis_id="mismatched-individual-info-entity",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_individual_info_raw_record_replays_offline_without_calling_upstream(
    tmp_path: Path,
):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.SHARE_CAPITAL,
        "SH600000",
        {"view": "individual_info"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [("stock_individual_info_em", {"symbol": "600000"})]


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


def test_restricted_release_fetch_requires_explicit_view_and_preserves_batches():
    fake = FakeAKShare()
    provider = _provider(fake)
    request = _request(
        DataCategory.SHARE_CAPITAL,
        "SH600000",
        {"view": "restricted_release_queue"},
    )

    record = provider.fetch(request)

    assert record.raw_payload == _fixture("a_restricted_release_queue.json")
    assert fake.calls == [
        ("stock_restricted_release_queue_em", {"symbol": "600000"}),
    ]
    assert record.response_metadata["endpoint"] == "stock_restricted_release_queue_em"
    assert record.response_metadata["upstream_row_count"] == 2
    assert record.response_metadata["entity_row_count"] == 2
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is True
    assert record.response_metadata["restricted_release_view"] == (
        "restricted_release_queue"
    )
    assert record.source_uri == "https://data.eastmoney.com/dxf/q/600000.html"


def test_restricted_release_request_validates_view_and_parameters_before_upstream_call():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="unsupported AKShare restricted-share-release"):
        provider.fetch(
            _request(
                DataCategory.SHARE_CAPITAL,
                "SH600000",
                {"view": "restricted_release_queue", "start_date": "20240101"},
            )
        )
    with pytest.raises(ProviderRequestError, match="does not accept request parameters"):
        provider.fetch(
            _request(DataCategory.SHARE_CAPITAL, "SH600000", {"view": "unknown"})
        )

    assert fake.calls == []


def test_restricted_release_response_rejects_cross_listing_and_invalid_dates():
    class WrongEntityAKShare(FakeAKShare):
        def stock_restricted_release_queue_em(self, *, symbol: str):
            payload = _fixture("a_restricted_release_queue.json")
            payload[0]["股票代码"] = "000001"
            return self._return(
                "stock_restricted_release_queue_em",
                payload,
                symbol=symbol,
            )

    class InvalidDateAKShare(FakeAKShare):
        def stock_restricted_release_queue_em(self, *, symbol: str):
            payload = _fixture("a_restricted_release_queue.json")
            payload[0]["解禁时间"] = "not-a-date"
            return self._return(
                "stock_restricted_release_queue_em",
                payload,
                symbol=symbol,
            )

    request = _request(
        DataCategory.SHARE_CAPITAL,
        "SH600000",
        {"view": "restricted_release_queue"},
    )
    with pytest.raises(ProviderResponseError, match="restricted-share-release row entity"):
        _provider(WrongEntityAKShare()).fetch(request)
    with pytest.raises(ProviderResponseError, match="invalid restricted-share-release date"):
        _provider(InvalidDateAKShare()).fetch(request)


def test_restricted_release_raw_record_is_not_promoted_to_a_canonical_share_fact():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.SHARE_CAPITAL,
            "SH600000",
            {"view": "restricted_release_queue"},
        )
    )
    normalized = normalize_akshare_records(
        [record],
        analysis_id="restricted-release-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_RESTRICTED_SHARE_RELEASES_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "normalized_diluted_economic_shares",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "canonical diluted-economic-share treatment" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_restricted_release_normalizer_rejects_replayed_cross_listing_rows():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.SHARE_CAPITAL,
            "SH600000",
            {"view": "restricted_release_queue"},
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

    with pytest.raises(ProviderNormalizationError, match="restricted-share-release row entity"):
        normalize_akshare_records(
            [mismatched],
            analysis_id="mismatched-restricted-release-entity",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_restricted_release_raw_record_replays_offline_without_calling_upstream(
    tmp_path: Path,
):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.SHARE_CAPITAL,
        "SH600000",
        {"view": "restricted_release_queue"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        ("stock_restricted_release_queue_em", {"symbol": "600000"}),
    ]


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


def test_a_individual_ownership_pledge_detail_fetch_uses_explicit_view_and_symbol():
    fake = FakeAKShare()
    record = _provider(fake).fetch(
        _request(
            DataCategory.OWNERSHIP_PLEDGE,
            "SH600000",
            {"view": "individual_pledge_detail"},
        )
    )

    assert record.raw_payload == _fixture("a_individual_pledge_detail.json")
    assert fake.calls == [
        (
            "stock_gpzy_individual_pledge_ratio_detail_em",
            {"symbol": "600000"},
        ),
    ]
    assert record.response_metadata["endpoint"] == (
        "stock_gpzy_individual_pledge_ratio_detail_em"
    )
    assert record.response_metadata["upstream_row_count"] == 2
    assert record.response_metadata["entity_row_count"] == 2
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is True
    assert record.response_metadata["ownership_pledge_view"] == (
        "individual_pledge_detail"
    )
    assert record.response_metadata["upstream_symbol"] == "600000"
    assert record.source_uri == "https://data.eastmoney.com/gpzy/detail/{symbol}.html"


def test_individual_ownership_pledge_detail_requires_its_explicit_view_and_a_share():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="unsupported AKShare .*ownership-pledge"):
        provider.fetch(
            _request(
                DataCategory.OWNERSHIP_PLEDGE,
                "SH600000",
                {"view": "individual_pledge_detail", "date": "20241220"},
            )
        )
    with pytest.raises(ProviderRequestError, match="unsupported AKShare .*ownership-pledge"):
        provider.fetch(
            _request(
                DataCategory.OWNERSHIP_PLEDGE,
                "SH600000",
                {"view": "other_pledge_view"},
            )
        )
    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        provider.fetch(
            _request(
                DataCategory.OWNERSHIP_PLEDGE,
                "HK00700",
                {"view": "individual_pledge_detail"},
            )
        )

    assert fake.calls == []


def test_individual_ownership_pledge_detail_response_rejects_another_listing():
    class WrongListingAKShare(FakeAKShare):
        def stock_gpzy_individual_pledge_ratio_detail_em(self, *, symbol: str):
            payload = _fixture("a_individual_pledge_detail.json")
            payload[0]["股票代码"] = "000001"
            return self._return(
                "stock_gpzy_individual_pledge_ratio_detail_em",
                payload,
                symbol=symbol,
            )

    with pytest.raises(ProviderResponseError, match="individual ownership-pledge row entity"):
        _provider(WrongListingAKShare()).fetch(
            _request(
                DataCategory.OWNERSHIP_PLEDGE,
                "SH600000",
                {"view": "individual_pledge_detail"},
            )
        )


def test_individual_ownership_pledge_detail_response_rejects_invalid_event_date():
    class InvalidDateAKShare(FakeAKShare):
        def stock_gpzy_individual_pledge_ratio_detail_em(self, *, symbol: str):
            payload = _fixture("a_individual_pledge_detail.json")
            payload[0]["公告日期"] = "not-a-date"
            return self._return(
                "stock_gpzy_individual_pledge_ratio_detail_em",
                payload,
                symbol=symbol,
            )

    with pytest.raises(ProviderResponseError, match="invalid date in '公告日期'"):
        _provider(InvalidDateAKShare()).fetch(
            _request(
                DataCategory.OWNERSHIP_PLEDGE,
                "SH600000",
                {"view": "individual_pledge_detail"},
            )
        )


def test_individual_ownership_pledge_detail_raw_record_is_not_promoted_to_facts():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.OWNERSHIP_PLEDGE,
            "SH600000",
            {"view": "individual_pledge_detail"},
        )
    )
    normalized = normalize_akshare_records(
        [record],
        analysis_id="individual-pledge-detail-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_INDIVIDUAL_PLEDGE_DETAIL_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "governance_risk_level",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "individual ownership-pledge detail" in normalized.data_quality.notes
    assert "canonical share" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_individual_ownership_pledge_detail_normalizer_rejects_replayed_rows_for_another_listing():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.OWNERSHIP_PLEDGE,
            "SH600000",
            {"view": "individual_pledge_detail"},
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

    with pytest.raises(ProviderNormalizationError, match="individual ownership-pledge row entity"):
        normalize_akshare_records(
            [mismatched],
            analysis_id="mismatched-individual-pledge-detail",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_individual_ownership_pledge_detail_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.OWNERSHIP_PLEDGE,
        "SH600000",
        {"view": "individual_pledge_detail"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        (
            "stock_gpzy_individual_pledge_ratio_detail_em",
            {"symbol": "600000"},
        ),
    ]


def test_a_equity_mortgage_fetch_filters_the_documented_date_universe():
    fake = FakeAKShare()
    provider = _provider(fake)
    request = _request(
        DataCategory.OWNERSHIP_PLEDGE,
        "SH600000",
        {"view": "equity_mortgage", "date": "20210930"},
    )

    record = provider.fetch(request)

    fixture = _fixture("a_equity_mortgage.json")
    assert record.raw_payload == [row for row in fixture if row["股票代码"] == "600000"]
    assert fake.calls == [
        ("stock_cg_equity_mortgage_cninfo", {"date": "20210930"}),
    ]
    assert record.response_metadata["endpoint"] == "stock_cg_equity_mortgage_cninfo"
    assert record.response_metadata["upstream_row_count"] == 3
    assert record.response_metadata["entity_row_count"] == 2
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is False
    assert record.response_metadata["row_filtering"] == "provider"
    assert record.response_metadata["ownership_pledge_view"] == "equity_mortgage"
    assert record.response_metadata["requested_date"] == "20210930"
    assert record.response_metadata["snapshot_scope"] == "requested_date_parameter"
    assert record.source_uri == "https://webapi.cninfo.com.cn/#/thematicStatistics"


def test_equity_mortgage_request_uses_documented_default_and_validates_scope():
    fake = FakeAKShare()
    provider = _provider(fake)

    record = provider.fetch(
        _request(
            DataCategory.OWNERSHIP_PLEDGE,
            "SH600000",
            {"view": "equity_mortgage"},
        )
    )
    assert record.response_metadata["requested_date"] == "20210930"
    assert fake.calls == [
        ("stock_cg_equity_mortgage_cninfo", {"date": "20210930"}),
    ]

    with pytest.raises(ProviderRequestError, match="must be YYYYMMDD"):
        provider.fetch(
            _request(
                DataCategory.OWNERSHIP_PLEDGE,
                "SH600000",
                {"view": "equity_mortgage", "date": "2021-09-30"},
            )
        )
    with pytest.raises(ProviderRequestError, match="must be a valid YYYYMMDD date"):
        provider.fetch(
            _request(
                DataCategory.OWNERSHIP_PLEDGE,
                "SH600000",
                {"view": "equity_mortgage", "date": "20210931"},
            )
        )
    with pytest.raises(ProviderRequestError, match="unsupported AKShare equity-mortgage"):
        provider.fetch(
            _request(
                DataCategory.OWNERSHIP_PLEDGE,
                "SH600000",
                {"view": "equity_mortgage", "date": "20210930", "market": "A"},
            )
        )
    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        provider.fetch(
            _request(
                DataCategory.OWNERSHIP_PLEDGE,
                "HK00700",
                {"view": "equity_mortgage", "date": "20210930"},
            )
        )

    assert fake.calls == [
        ("stock_cg_equity_mortgage_cninfo", {"date": "20210930"}),
    ]


def test_equity_mortgage_response_rejects_missing_code_or_invalid_announcement_date():
    class MissingListingCode(FakeAKShare):
        def stock_cg_equity_mortgage_cninfo(self, *, date: str):
            return self._return(
                "stock_cg_equity_mortgage_cninfo",
                [{"股票代码": None, "公告日期": "2021-09-30"}],
                date=date,
            )

    with pytest.raises(
        ProviderResponseError,
        match="equity-mortgage row without a listing code",
    ):
        _provider(MissingListingCode()).fetch(
            _request(
                DataCategory.OWNERSHIP_PLEDGE,
                "SH600000",
                {"view": "equity_mortgage", "date": "20210930"},
            )
        )

    class InvalidAnnouncementDate(FakeAKShare):
        def stock_cg_equity_mortgage_cninfo(self, *, date: str):
            payload = _fixture("a_equity_mortgage.json")
            payload[0]["公告日期"] = "not-a-date"
            return self._return(
                "stock_cg_equity_mortgage_cninfo",
                payload,
                date=date,
            )

    with pytest.raises(
        ProviderResponseError,
        match="equity-mortgage row with an invalid date in '公告日期'",
    ):
        _provider(InvalidAnnouncementDate()).fetch(
            _request(
                DataCategory.OWNERSHIP_PLEDGE,
                "SH600000",
                {"view": "equity_mortgage", "date": "20210930"},
            )
        )


def test_equity_mortgage_with_no_matching_listing_is_an_empty_raw_snapshot():
    class NoMatchingMortgage(FakeAKShare):
        def stock_cg_equity_mortgage_cninfo(self, *, date: str):
            return self._return(
                "stock_cg_equity_mortgage_cninfo",
                [
                    row
                    for row in _fixture("a_equity_mortgage.json")
                    if row["股票代码"] == "000001"
                ],
                date=date,
            )

    fake = NoMatchingMortgage()
    record = _provider(fake).fetch(
        _request(
            DataCategory.OWNERSHIP_PLEDGE,
            "SH600000",
            {"view": "equity_mortgage", "date": "20210930"},
        )
    )

    assert record.raw_payload == []
    assert record.response_metadata["upstream_row_count"] == 1
    assert record.response_metadata["entity_row_count"] == 0


def test_equity_mortgage_is_retained_as_raw_evidence_without_canonical_facts():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.OWNERSHIP_PLEDGE,
            "SH600000",
            {"view": "equity_mortgage", "date": "20210930"},
        )
    )
    normalized = normalize_akshare_records(
        [record],
        analysis_id="equity-mortgage-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_EQUITY_MORTGAGE_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "governance_risk_level",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "canonical pledge period" in normalized.data_quality.notes
    assert "governance judgment" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(
        Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json"))
    ) == []


def test_equity_mortgage_normalizer_rejects_replayed_rows_for_another_listing():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.OWNERSHIP_PLEDGE,
            "SH600000",
            {"view": "equity_mortgage", "date": "20210930"},
        )
    )
    payload = [dict(row) for row in record.raw_payload]
    payload[0]["股票代码"] = "000001"
    replayed = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="equity-mortgage row entity"):
        normalize_akshare_records(
            [replayed],
            analysis_id="mismatched-equity-mortgage-entity",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_equity_mortgage_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.OWNERSHIP_PLEDGE,
        "SH600000",
        {"view": "equity_mortgage", "date": "20210930"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        ("stock_cg_equity_mortgage_cninfo", {"date": "20210930"}),
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


def test_management_holdings_fetch_uses_explicit_view_and_filters_the_documented_universe():
    fake = FakeAKShare()
    record = _provider(fake).fetch(
        _request(
            DataCategory.INSIDER_SHARE_CHANGES,
            "SH600000",
            {"view": "management_detail"},
        )
    )

    fixture = _fixture("a_management_holdings.json")
    assert record.raw_payload == [row for row in fixture if row["代码"] == "600000"]
    assert fake.calls == [("stock_hold_management_detail_em", {})]
    assert record.response_metadata["endpoint"] == "stock_hold_management_detail_em"
    assert record.response_metadata["upstream_row_count"] == 3
    assert record.response_metadata["entity_row_count"] == 2
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is False
    assert record.response_metadata["row_filtering"] == "provider"
    assert record.response_metadata["management_view"] == "management_detail"
    assert record.response_metadata["snapshot_scope"] == "historical_published_dataset"
    assert record.response_metadata["observation_date_field"] == "日期"
    assert record.source_uri == "https://data.eastmoney.com/executive/list.html"


def test_management_holdings_request_validates_view_parameters_and_market():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="unsupported AKShare management-holdings"):
        provider.fetch(
            _request(
                DataCategory.INSIDER_SHARE_CHANGES,
                "SH600000",
                {"view": "management_detail", "date": "20240101"},
            )
        )
    with pytest.raises(ProviderRequestError, match="Shanghai, Shenzhen and Beijing A-share"):
        provider.fetch(
            _request(
                DataCategory.INSIDER_SHARE_CHANGES,
                "HK00700",
                {"view": "management_detail"},
            )
        )

    assert fake.calls == []


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("missing_code", "management-holding row without a listing code"),
        ("missing_date", "management-holding row without a change date"),
        ("invalid_date", "invalid management-holding date"),
    ],
)
def test_management_holdings_response_validates_identity_and_dates(
    mutation: str,
    match: str,
):
    class InvalidRows(FakeAKShare):
        def stock_hold_management_detail_em(self):
            rows = _fixture("a_management_holdings.json")
            if mutation == "missing_code":
                rows[0].pop("代码")
            elif mutation == "missing_date":
                rows[0].pop("日期")
            else:
                rows[0]["日期"] = "not-a-date"
            return self._return("stock_hold_management_detail_em", rows)

    with pytest.raises(ProviderResponseError, match=match):
        _provider(InvalidRows()).fetch(
            _request(
                DataCategory.INSIDER_SHARE_CHANGES,
                "SH600000",
                {"view": "management_detail"},
            )
        )


def test_management_holdings_raw_record_is_not_promoted_to_shares_or_governance():
    record = _provider().fetch(
        _request(
            DataCategory.INSIDER_SHARE_CHANGES,
            "SH600000",
            {"view": "management_detail"},
        )
    )
    normalized = normalize_akshare_records(
        [record],
        analysis_id="management-holdings-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_MANAGEMENT_HOLDINGS_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "governance_risk_level",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "management-holding response" in normalized.data_quality.notes
    assert "diluted-share series" in normalized.data_quality.notes
    assert "governance-risk judgment" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


@pytest.mark.parametrize(
    ("field", "match"),
    [
        ("代码", "management-holding row entity"),
        ("日期", "management-holding row has an invalid change date"),
    ],
)
def test_management_holdings_normalizer_rejects_replayed_identity_or_date_mismatches(
    field: str,
    match: str,
):
    record = _provider().fetch(
        _request(
            DataCategory.INSIDER_SHARE_CHANGES,
            "SH600000",
            {"view": "management_detail"},
        )
    )
    payload = [dict(row) for row in record.raw_payload]
    payload[0][field] = "000001" if field == "代码" else "not-a-date"
    replayed = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match=match):
        normalize_akshare_records(
            [replayed],
            analysis_id="mismatched-management-holdings",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_management_holdings_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.INSIDER_SHARE_CHANGES,
        "SH600000",
        {"view": "management_detail"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [("stock_hold_management_detail_em", {})]


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


def test_external_guarantees_fetch_filters_documented_all_universe_and_preserves_range():
    fake = FakeAKShare()
    provider = _provider(fake)
    record = provider.fetch(
        _request(
            DataCategory.EXTERNAL_GUARANTEES,
            "SH600000",
            {"start_date": "20180630", "end_date": "20210927"},
        )
    )

    fixture = _fixture("a_external_guarantees.json")
    assert record.raw_payload == [row for row in fixture if row["证券代码"] == "600000"]
    assert fake.calls == [
        (
            "stock_cg_guarantee_cninfo",
            {"symbol": "全部", "start_date": "20180630", "end_date": "20210927"},
        )
    ]
    assert record.response_metadata["endpoint"] == "stock_cg_guarantee_cninfo"
    assert record.response_metadata["upstream_row_count"] == 2
    assert record.response_metadata["entity_row_count"] == 1
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is False
    assert record.response_metadata["row_filtering"] == "provider"
    assert record.response_metadata["upstream_symbol"] == "全部"
    assert record.response_metadata["start_date"] == "20180630"
    assert record.response_metadata["end_date"] == "20210927"
    assert record.source_uri == "https://webapi.cninfo.com.cn/#/thematicStatistics"


def test_external_guarantee_request_uses_documented_defaults_and_validates_range():
    fake = FakeAKShare()
    provider = _provider(fake)

    provider.fetch(_request(DataCategory.EXTERNAL_GUARANTEES, "SH600000"))
    with pytest.raises(
        ProviderRequestError,
        match="external-guarantee start_date must be YYYYMMDD",
    ):
        provider.fetch(
            _request(
                DataCategory.EXTERNAL_GUARANTEES,
                "SH600000",
                {"start_date": "2018-06-30"},
            )
        )
    with pytest.raises(
        ProviderRequestError,
        match="external-guarantee end_date must be a valid YYYYMMDD date",
    ):
        provider.fetch(
            _request(
                DataCategory.EXTERNAL_GUARANTEES,
                "SH600000",
                {"end_date": "20210931"},
            )
        )
    with pytest.raises(
        ProviderRequestError,
        match="external-guarantee start_date must not be after end_date",
    ):
        provider.fetch(
            _request(
                DataCategory.EXTERNAL_GUARANTEES,
                "SH600000",
                {"start_date": "20220101", "end_date": "20210101"},
            )
        )
    with pytest.raises(ProviderRequestError, match="unsupported AKShare external-guarantee"):
        provider.fetch(
            _request(
                DataCategory.EXTERNAL_GUARANTEES,
                "SH600000",
                {"symbol": "全部"},
            )
        )
    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        provider.fetch(_request(DataCategory.EXTERNAL_GUARANTEES, "HK00700"))

    assert fake.calls == [
        (
            "stock_cg_guarantee_cninfo",
            {"symbol": "全部", "start_date": "20180630", "end_date": "20210927"},
        )
    ]


def test_external_guarantees_reject_a_universe_row_without_an_explicit_listing_code():
    class MissingListingCode(FakeAKShare):
        def stock_cg_guarantee_cninfo(self, **kwargs):
            return self._return(
                "stock_cg_guarantee_cninfo",
                [{"证券代码": None, "证券简称": "unresolved"}],
                **kwargs,
            )

    with pytest.raises(
        ProviderResponseError,
        match="external-guarantee row without a listing code",
    ):
        _provider(MissingListingCode()).fetch(
            _request(DataCategory.EXTERNAL_GUARANTEES, "SH600000")
        )


def test_external_guarantees_with_no_matching_listing_is_an_empty_raw_snapshot():
    class NoMatchingGuarantee(FakeAKShare):
        def stock_cg_guarantee_cninfo(self, **kwargs):
            return self._return(
                "stock_cg_guarantee_cninfo",
                [
                    row
                    for row in _fixture("a_external_guarantees.json")
                    if row["证券代码"] == "000001"
                ],
                **kwargs,
            )

    fake = NoMatchingGuarantee()
    record = _provider(fake).fetch(
        _request(DataCategory.EXTERNAL_GUARANTEES, "SH600000")
    )

    assert record.raw_payload == []
    assert record.response_metadata["upstream_row_count"] == 1
    assert record.response_metadata["entity_row_count"] == 0


def test_external_guarantees_are_retained_as_raw_evidence_without_canonical_facts():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.EXTERNAL_GUARANTEES, "SH600000"))
    normalized = normalize_akshare_records(
        [record],
        analysis_id="external-guarantees-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_EXTERNAL_GUARANTEES_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "governance_risk_level",
        "major_illegal_guarantee",
        "material_quasi_debt",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "canonical quasi-debt" in normalized.data_quality.notes
    assert "illegal-guarantee/governance judgment" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(
        Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json"))
    ) == []


def test_external_guarantees_normalizer_rejects_replayed_rows_for_another_listing():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.EXTERNAL_GUARANTEES, "SH600000"))
    payload = [dict(row) for row in record.raw_payload]
    payload[0]["证券代码"] = "000001"
    replayed = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="external-guarantee row entity"):
        normalize_akshare_records(
            [replayed],
            analysis_id="mismatched-external-guarantee-entity",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_external_guarantees_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.EXTERNAL_GUARANTEES,
        "SH600000",
        {"start_date": "20180630", "end_date": "20210927"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        (
            "stock_cg_guarantee_cninfo",
            {"symbol": "全部", "start_date": "20180630", "end_date": "20210927"},
        )
    ]


def test_litigation_fetch_filters_documented_all_universe_and_preserves_range():
    fake = FakeAKShare()
    provider = _provider(fake)
    record = provider.fetch(
        _request(
            DataCategory.LITIGATION,
            "SH600000",
            {"start_date": "20180630", "end_date": "20210927"},
        )
    )

    fixture = _fixture("a_litigation.json")
    assert record.raw_payload == [row for row in fixture if row["证券代码"] == "600000"]
    assert fake.calls == [
        (
            "stock_cg_lawsuit_cninfo",
            {"symbol": "全部", "start_date": "20180630", "end_date": "20210927"},
        )
    ]
    assert record.response_metadata["endpoint"] == "stock_cg_lawsuit_cninfo"
    assert record.response_metadata["upstream_row_count"] == 2
    assert record.response_metadata["entity_row_count"] == 1
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is False
    assert record.response_metadata["row_filtering"] == "provider"
    assert record.response_metadata["upstream_symbol"] == "全部"
    assert record.response_metadata["start_date"] == "20180630"
    assert record.response_metadata["end_date"] == "20210927"
    assert record.source_uri == "https://webapi.cninfo.com.cn/#/thematicStatistics"


def test_litigation_request_uses_documented_defaults_and_validates_range():
    fake = FakeAKShare()
    provider = _provider(fake)

    provider.fetch(_request(DataCategory.LITIGATION, "SH600000"))
    with pytest.raises(
        ProviderRequestError,
        match="litigation start_date must be YYYYMMDD",
    ):
        provider.fetch(
            _request(
                DataCategory.LITIGATION,
                "SH600000",
                {"start_date": "2018-06-30"},
            )
        )
    with pytest.raises(
        ProviderRequestError,
        match="litigation end_date must be a valid YYYYMMDD date",
    ):
        provider.fetch(
            _request(
                DataCategory.LITIGATION,
                "SH600000",
                {"end_date": "20210931"},
            )
        )
    with pytest.raises(
        ProviderRequestError,
        match="litigation start_date must not be after end_date",
    ):
        provider.fetch(
            _request(
                DataCategory.LITIGATION,
                "SH600000",
                {"start_date": "20220101", "end_date": "20210101"},
            )
        )
    with pytest.raises(ProviderRequestError, match="unsupported AKShare litigation"):
        provider.fetch(
            _request(
                DataCategory.LITIGATION,
                "SH600000",
                {"symbol": "全部"},
            )
        )
    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        provider.fetch(_request(DataCategory.LITIGATION, "HK00700"))

    assert fake.calls == [
        (
            "stock_cg_lawsuit_cninfo",
            {"symbol": "全部", "start_date": "20180630", "end_date": "20210927"},
        )
    ]


def test_litigation_rejects_a_universe_row_without_an_explicit_listing_code():
    class MissingListingCode(FakeAKShare):
        def stock_cg_lawsuit_cninfo(self, **kwargs):
            return self._return(
                "stock_cg_lawsuit_cninfo",
                [{"证券代码": None, "证券简称": "unresolved"}],
                **kwargs,
            )

    with pytest.raises(
        ProviderResponseError,
        match="litigation row without a listing code",
    ):
        _provider(MissingListingCode()).fetch(
            _request(DataCategory.LITIGATION, "SH600000")
        )


def test_litigation_with_no_matching_listing_is_an_empty_raw_snapshot():
    class NoMatchingLawsuit(FakeAKShare):
        def stock_cg_lawsuit_cninfo(self, **kwargs):
            return self._return(
                "stock_cg_lawsuit_cninfo",
                [
                    row
                    for row in _fixture("a_litigation.json")
                    if row["证券代码"] == "000001"
                ],
                **kwargs,
            )

    fake = NoMatchingLawsuit()
    record = _provider(fake).fetch(_request(DataCategory.LITIGATION, "SH600000"))

    assert record.raw_payload == []
    assert record.response_metadata["upstream_row_count"] == 1
    assert record.response_metadata["entity_row_count"] == 0


def test_litigation_is_retained_as_raw_evidence_without_canonical_facts():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.LITIGATION, "SH600000"))
    normalized = normalize_akshare_records(
        [record],
        analysis_id="litigation-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_LITIGATION_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "governance_risk_level",
        "material_quasi_debt",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "canonical quasi-debt" in normalized.data_quality.notes
    assert "governance judgment" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(
        Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json"))
    ) == []


def test_litigation_normalizer_rejects_replayed_rows_for_another_listing():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.LITIGATION, "SH600000"))
    payload = [dict(row) for row in record.raw_payload]
    payload[0]["证券代码"] = "000001"
    replayed = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="litigation row entity"):
        normalize_akshare_records(
            [replayed],
            analysis_id="mismatched-litigation-entity",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_litigation_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.LITIGATION,
        "SH600000",
        {"start_date": "20180630", "end_date": "20210927"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        (
            "stock_cg_lawsuit_cninfo",
            {"symbol": "全部", "start_date": "20180630", "end_date": "20210927"},
        )
    ]


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


def test_a_goodwill_impairment_fetch_filters_the_documented_report_date_universe():
    fake = FakeAKShare()
    provider = _provider(fake)
    record = provider.fetch(
        _request(
            DataCategory.GOODWILL_IMPAIRMENT,
            "SH600000",
            {"date": "20250630"},
        )
    )

    fixture = _fixture("a_goodwill_impairment.json")
    assert record.raw_payload == [row for row in fixture if row["股票代码"] == "600000"]
    assert fake.calls == [("stock_sy_jz_em", {"date": "20250630"})]
    assert record.response_metadata["endpoint"] == "stock_sy_jz_em"
    assert record.response_metadata["upstream_row_count"] == 2
    assert record.response_metadata["entity_row_count"] == 1
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is False
    assert record.response_metadata["row_filtering"] == "provider"
    assert record.response_metadata["requested_date"] == "20250630"
    assert record.response_metadata["report_period"] == "2025-06-30"
    assert record.response_metadata["snapshot_scope"] == "requested_report_date"
    assert record.source_uri == "https://data.eastmoney.com/sy/jzlist.html"


def test_a_goodwill_impairment_request_validates_date_and_market_before_upstream_call():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="requires date"):
        provider.fetch(_request(DataCategory.GOODWILL_IMPAIRMENT, "SH600000"))
    with pytest.raises(ProviderRequestError, match="date must be YYYYMMDD"):
        provider.fetch(
            _request(
                DataCategory.GOODWILL_IMPAIRMENT,
                "SH600000",
                {"date": "2025-06-30"},
            )
        )
    with pytest.raises(ProviderRequestError, match="date must be a valid YYYYMMDD"):
        provider.fetch(
            _request(
                DataCategory.GOODWILL_IMPAIRMENT,
                "SH600000",
                {"date": "20251331"},
            )
        )
    with pytest.raises(ProviderRequestError, match="unsupported AKShare goodwill-impairment"):
        provider.fetch(
            _request(
                DataCategory.GOODWILL_IMPAIRMENT,
                "SH600000",
                {"date": "20250630", "view": "detail"},
            )
        )
    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        provider.fetch(
            _request(
                DataCategory.GOODWILL_IMPAIRMENT,
                "HK00700",
                {"date": "20250630"},
            )
        )

    assert fake.calls == []


def test_goodwill_impairment_response_rejects_missing_code_or_invalid_announcement_date():
    class InvalidRows(FakeAKShare):
        def __init__(self, mode: str) -> None:
            super().__init__()
            self.mode = mode

        def stock_sy_jz_em(self, *, date: str):
            rows = [dict(row) for row in _fixture("a_goodwill_impairment.json")]
            if self.mode == "missing_code":
                rows[0].pop("股票代码")
            else:
                rows[0]["公告日期"] = "not-a-date"
            return self._return("stock_sy_jz_em", rows, date=date)

    with pytest.raises(ProviderResponseError, match="goodwill-impairment row without"):
        _provider(InvalidRows("missing_code")).fetch(
            _request(
                DataCategory.GOODWILL_IMPAIRMENT,
                "SH600000",
                {"date": "20250630"},
            )
        )
    with pytest.raises(
        ProviderResponseError,
        match="invalid goodwill-impairment announcement date",
    ):
        _provider(InvalidRows("invalid_date")).fetch(
            _request(
                DataCategory.GOODWILL_IMPAIRMENT,
                "SH600000",
                {"date": "20250630"},
            )
        )


def test_goodwill_impairment_with_no_matching_listing_is_an_empty_raw_snapshot():
    class NoGoodwillImpairment(FakeAKShare):
        def stock_sy_jz_em(self, *, date: str):
            return self._return(
                "stock_sy_jz_em",
                [{"股票代码": "000001", "股票简称": "平安银行"}],
                date=date,
            )

    fake = NoGoodwillImpairment()
    record = _provider(fake).fetch(
        _request(
            DataCategory.GOODWILL_IMPAIRMENT,
            "SH600000",
            {"date": "20250630"},
        )
    )

    assert record.raw_payload == []
    assert record.response_metadata["upstream_row_count"] == 1
    assert record.response_metadata["entity_row_count"] == 0


def test_goodwill_impairment_raw_record_is_not_promoted_to_canonical_facts():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.GOODWILL_IMPAIRMENT,
            "SH600000",
            {"date": "20250630"},
        )
    )

    normalized = normalize_akshare_records(
        [record],
        analysis_id="goodwill-impairment-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_GOODWILL_IMPAIRMENT_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "goodwill",
        "impairment",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "primary-filing scope" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(
        Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json"))
    ) == []


def test_goodwill_impairment_normalizer_rejects_replayed_rows_for_another_listing():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.GOODWILL_IMPAIRMENT,
            "SH600000",
            {"date": "20250630"},
        )
    )
    payload = [dict(row) for row in record.raw_payload]
    payload[0]["股票代码"] = "000001"
    replayed = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="goodwill-impairment row entity"):
        normalize_akshare_records(
            [replayed],
            analysis_id="mismatched-goodwill-impairment-entity",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_goodwill_impairment_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.GOODWILL_IMPAIRMENT,
        "SH600000",
        {"date": "20250630"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [("stock_sy_jz_em", {"date": "20250630"})]


def test_esg_rating_fetch_filters_all_matching_rows_from_the_documented_mixed_a_h_universe():
    fake = FakeAKShare()
    provider = _provider(fake)

    a_record = provider.fetch(_request(DataCategory.ESG_RATINGS, "SH600000"))
    h_record = provider.fetch(_request(DataCategory.ESG_RATINGS, "HK00700"))

    fixture = _fixture("esg_ratings.json")
    assert a_record.raw_payload == [
        row for row in fixture if row["成分股代码"] == "SH600000"
    ]
    assert h_record.raw_payload == [
        row for row in fixture if row["成分股代码"] == "HK00700"
    ]
    assert fake.calls == [
        ("stock_esg_rate_sina", {}),
        ("stock_esg_rate_sina", {}),
    ]
    assert a_record.response_metadata["endpoint"] == "stock_esg_rate_sina"
    assert a_record.response_metadata["upstream_row_count"] == 4
    assert a_record.response_metadata["entity_row_count"] == 2
    assert a_record.response_metadata["entity_rows_selected"] is True
    assert a_record.response_metadata["listing_scoped_request"] is False
    assert a_record.response_metadata["row_filtering"] == "provider"
    assert a_record.response_metadata["snapshot_scope"] == "current_published_dataset"
    assert a_record.source_uri == "https://finance.sina.com.cn/esg/grade.shtml"


def test_esg_rating_request_accepts_no_parameters_for_a_or_h_listings():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="does not accept request parameters"):
        provider.fetch(
            _request(
                DataCategory.ESG_RATINGS,
                "SH600000",
                {"date": "20250930"},
            )
        )

    provider.fetch(_request(DataCategory.ESG_RATINGS, "HK00700"))
    assert fake.calls == [("stock_esg_rate_sina", {})]


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (
            {"评级机构": "示例机构", "交易市场": "cn"},
            "without a listing code",
        ),
        (
            {"成分股代码": "600000", "评级机构": "示例机构"},
            "no explicit market",
        ),
        (
            {"成分股代码": "SH600000", "评级机构": "示例机构", "交易市场": "hk"},
            "conflicts with market",
        ),
    ],
)
def test_esg_rating_response_rejects_rows_without_unambiguous_a_h_identity(
    row: dict[str, str], message: str
):
    class InvalidRows(FakeAKShare):
        def stock_esg_rate_sina(self):
            return self._return("stock_esg_rate_sina", [row])

    with pytest.raises(ProviderResponseError, match=message):
        _provider(InvalidRows()).fetch(
            _request(DataCategory.ESG_RATINGS, "SH600000")
        )


def test_esg_rating_with_no_matching_listing_is_an_empty_raw_snapshot():
    class NoMatchingRating(FakeAKShare):
        def stock_esg_rate_sina(self):
            return self._return(
                "stock_esg_rate_sina",
                [
                    {
                        "成分股代码": "SZ000001",
                        "评级机构": "示例机构",
                        "评级": "A",
                        "评级季度": "2025 Q4",
                        "标识": None,
                        "交易市场": "cn",
                    }
                ],
            )

    fake = NoMatchingRating()
    record = _provider(fake).fetch(
        _request(DataCategory.ESG_RATINGS, "SH600000")
    )

    assert record.raw_payload == []
    assert record.response_metadata["upstream_row_count"] == 1
    assert record.response_metadata["entity_row_count"] == 0


def test_esg_rating_raw_record_is_not_promoted_to_canonical_facts():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.ESG_RATINGS, "SH600000"))

    normalized = normalize_akshare_records(
        [record],
        analysis_id="esg-rating-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_ESG_RATINGS_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == ["governance_risk_level"]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "agency-specific ratings" in normalized.data_quality.notes
    assert "Business Quality judgment" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json")))
    assert errors == []


def test_esg_rating_normalizer_rejects_replayed_rows_for_another_listing():
    provider = _provider()
    record = provider.fetch(_request(DataCategory.ESG_RATINGS, "SH600000"))
    mismatched_payload = [dict(row) for row in record.raw_payload]
    mismatched_payload[0]["成分股代码"] = "HK00700"
    mismatched_payload[0]["交易市场"] = "hk"
    mismatched = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=mismatched_payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="ESG-rating row entity"):
        normalize_akshare_records(
            [mismatched],
            analysis_id="mismatched-esg-rating-entity",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_esg_rating_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(DataCategory.ESG_RATINGS, "SH600000")

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [("stock_esg_rate_sina", {})]


def test_sse_margin_detail_fetch_filters_the_documented_date_bound_universe():
    fake = FakeAKShare()
    record = _provider(fake).fetch(
        _request(
            DataCategory.MARGIN_TRADING,
            "SH600000",
            {"date": "20230922"},
        )
    )

    fixture = _fixture("a_margin_detail_sse.json")
    assert record.raw_payload == [
        row for row in fixture if row["标的证券代码"] == "600000"
    ]
    assert fake.calls == [
        ("stock_margin_detail_sse", {"date": "20230922"}),
    ]
    assert record.response_metadata["endpoint"] == "stock_margin_detail_sse"
    assert record.response_metadata["upstream_row_count"] == 3
    assert record.response_metadata["entity_row_count"] == 1
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is False
    assert record.response_metadata["row_filtering"] == "provider"
    assert record.response_metadata["requested_date"] == "20230922"
    assert record.response_metadata["observation_date"] == "2023-09-22"
    assert record.response_metadata["snapshot_scope"] == "requested_date"
    assert record.source_uri == (
        "http://www.sse.com.cn/market/othersdata/margin/detail/"
    )


def test_margin_detail_request_requires_exact_date_and_supported_mainland_listing():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="requires date"):
        provider.fetch(_request(DataCategory.MARGIN_TRADING, "SH600000"))
    with pytest.raises(ProviderRequestError, match="date must be YYYYMMDD"):
        provider.fetch(
            _request(
                DataCategory.MARGIN_TRADING,
                "SH600000",
                {"date": "2023-09-22"},
            )
        )
    with pytest.raises(
        ProviderRequestError,
        match="date must be a valid YYYYMMDD date",
    ):
        provider.fetch(
            _request(
                DataCategory.MARGIN_TRADING,
                "SH600000",
                {"date": "20230230"},
            )
        )
    with pytest.raises(ProviderRequestError, match="unsupported AKShare margin-trading"):
        provider.fetch(
            _request(
                DataCategory.MARGIN_TRADING,
                "SH600000",
                {"date": "20230922", "market": "沪市"},
            )
        )
    with pytest.raises(
        ProviderRequestError,
        match="Shanghai, Shenzhen and Beijing A-share listings only",
    ):
        provider.fetch(
            _request(
                DataCategory.MARGIN_TRADING,
                "HK00700",
                {"date": "20230922"},
            )
        )

    assert fake.calls == []


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("missing_code", "margin-trading row without a listing code"),
        ("missing_date", "margin-trading row without an observation date"),
        ("invalid_date", "invalid margin-trading observation date"),
        ("wrong_date", "margin-trading row date"),
    ],
)
def test_sse_margin_detail_response_rejects_invalid_identity_or_date(
    mode: str, message: str
):
    class InvalidRows(FakeAKShare):
        def stock_margin_detail_sse(self, *, date: str):
            rows = [dict(row) for row in _fixture("a_margin_detail_sse.json")]
            if mode == "missing_code":
                rows[0].pop("标的证券代码")
            elif mode == "missing_date":
                rows[0].pop("信用交易日期")
            elif mode == "invalid_date":
                rows[0]["信用交易日期"] = "not-a-date"
            else:
                rows[0]["信用交易日期"] = "20230921"
            return self._return("stock_margin_detail_sse", rows, date=date)

    with pytest.raises(ProviderResponseError, match=message):
        _provider(InvalidRows()).fetch(
            _request(
                DataCategory.MARGIN_TRADING,
                "SH600000",
                {"date": "20230922"},
            )
        )


def test_sse_margin_detail_with_no_matching_listing_is_an_empty_raw_snapshot():
    class NoMatchingMarginDetail(FakeAKShare):
        def stock_margin_detail_sse(self, *, date: str):
            return self._return(
                "stock_margin_detail_sse",
                [
                    row
                    for row in _fixture("a_margin_detail_sse.json")
                    if row["标的证券代码"] == "600519"
                ],
                date=date,
            )

    fake = NoMatchingMarginDetail()
    record = _provider(fake).fetch(
        _request(
            DataCategory.MARGIN_TRADING,
            "SH600000",
            {"date": "20230922"},
        )
    )

    assert record.raw_payload == []
    assert record.response_metadata["upstream_row_count"] == 1
    assert record.response_metadata["entity_row_count"] == 0


def test_sse_margin_detail_raw_record_is_not_promoted_to_issuer_facts():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.MARGIN_TRADING,
            "SH600000",
            {"date": "20230922"},
        )
    )

    normalized = normalize_akshare_records(
        [record],
        analysis_id="margin-detail-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_MARGIN_TRADING_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == ["financial_debt"]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "security-level financing balances" in normalized.data_quality.notes
    assert "issuer financial debt, cash or leverage facts" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(
        Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json"))
    ) == []


def test_sse_margin_detail_normalizer_rejects_replayed_rows_for_another_listing():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.MARGIN_TRADING,
            "SH600000",
            {"date": "20230922"},
        )
    )
    payload = [dict(row) for row in record.raw_payload]
    payload[0]["标的证券代码"] = "600519"
    replayed = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="margin-trading row entity"):
        normalize_akshare_records(
            [replayed],
            analysis_id="mismatched-margin-detail-entity",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_sse_margin_detail_normalizer_rejects_replayed_rows_for_another_date():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.MARGIN_TRADING,
            "SH600000",
            {"date": "20230922"},
        )
    )
    payload = [dict(row) for row in record.raw_payload]
    payload[0]["信用交易日期"] = "20230921"
    replayed = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="margin-trading row date"):
        normalize_akshare_records(
            [replayed],
            analysis_id="mismatched-margin-detail-date",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_sse_margin_detail_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.MARGIN_TRADING,
        "SH600000",
        {"date": "20230922"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [("stock_margin_detail_sse", {"date": "20230922"})]


def test_szse_margin_detail_fetch_filters_the_documented_date_bound_universe():
    fake = FakeAKShare()
    record = _provider(fake).fetch(
        _request(
            DataCategory.MARGIN_TRADING,
            "SZ000001",
            {"date": "20230925"},
        )
    )

    fixture = _fixture("a_margin_detail_szse.json")
    assert record.raw_payload == [
        row for row in fixture if row["证券代码"] == "000001"
    ]
    assert fake.calls == [
        ("stock_margin_detail_szse", {"date": "20230925"}),
    ]
    assert record.response_metadata["endpoint"] == "stock_margin_detail_szse"
    assert record.response_metadata["upstream_row_count"] == 3
    assert record.response_metadata["entity_row_count"] == 1
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is False
    assert record.response_metadata["row_filtering"] == "provider"
    assert record.response_metadata["requested_date"] == "20230925"
    assert record.response_metadata["observation_date"] == "2023-09-25"
    assert record.response_metadata["date_binding"] == "request"
    assert record.response_metadata["snapshot_scope"] == "requested_date"
    assert record.source_uri == (
        "https://www.szse.cn/disclosure/margin/margin/index.html"
    )


def test_szse_margin_detail_response_allows_the_documented_rows_without_row_date():
    record = _provider().fetch(
        _request(
            DataCategory.MARGIN_TRADING,
            "SZ000001",
            {"date": "20230925"},
        )
    )

    assert all("信用交易日期" not in row for row in record.raw_payload)


def test_szse_margin_detail_response_rejects_a_row_without_listing_code():
    class InvalidRows(FakeAKShare):
        def stock_margin_detail_szse(self, *, date: str):
            rows = [dict(row) for row in _fixture("a_margin_detail_szse.json")]
            rows[0].pop("证券代码")
            return self._return("stock_margin_detail_szse", rows, date=date)

    with pytest.raises(ProviderResponseError, match="margin-trading row without a listing code"):
        _provider(InvalidRows()).fetch(
            _request(
                DataCategory.MARGIN_TRADING,
                "SZ000001",
                {"date": "20230925"},
            )
        )


def test_szse_margin_detail_with_no_matching_listing_is_an_empty_raw_snapshot():
    class NoMatchingMarginDetail(FakeAKShare):
        def stock_margin_detail_szse(self, *, date: str):
            return self._return(
                "stock_margin_detail_szse",
                [
                    row
                    for row in _fixture("a_margin_detail_szse.json")
                    if row["证券代码"] == "000002"
                ],
                date=date,
            )

    record = _provider(NoMatchingMarginDetail()).fetch(
        _request(
            DataCategory.MARGIN_TRADING,
            "SZ000001",
            {"date": "20230925"},
        )
    )

    assert record.raw_payload == []
    assert record.response_metadata["upstream_row_count"] == 1
    assert record.response_metadata["entity_row_count"] == 0


def test_szse_margin_detail_raw_record_is_not_promoted_to_issuer_facts():
    record = _provider().fetch(
        _request(
            DataCategory.MARGIN_TRADING,
            "SZ000001",
            {"date": "20230925"},
        )
    )

    normalized = normalize_akshare_records(
        [record],
        analysis_id="szse-margin-detail-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(primary_listing="SZ000001"),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_MARGIN_TRADING_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == ["financial_debt"]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "security-level financing balances" in normalized.data_quality.notes
    assert "issuer financial debt, cash or leverage facts" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(
        Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json"))
    ) == []


def test_szse_margin_detail_normalizer_rejects_replayed_rows_for_another_listing():
    provider = _provider()
    record = provider.fetch(
        _request(
            DataCategory.MARGIN_TRADING,
            "SZ000001",
            {"date": "20230925"},
        )
    )
    payload = [dict(row) for row in record.raw_payload]
    payload[0]["证券代码"] = "000002"
    replayed = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="margin-trading row entity"):
        normalize_akshare_records(
            [replayed],
            analysis_id="mismatched-szse-margin-detail-entity",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(primary_listing="SZ000001"),
        )


def test_szse_margin_detail_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.MARGIN_TRADING,
        "SZ000001",
        {"date": "20230925"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [("stock_margin_detail_szse", {"date": "20230925"})]


def test_bse_margin_detail_fetch_filters_the_documented_date_bound_universe():
    fake = FakeAKShare()
    record = _provider(fake).fetch(
        _request(
            DataCategory.MARGIN_TRADING,
            "BJ920000",
            {"date": "20260721"},
        )
    )

    fixture = _fixture("a_margin_detail_bse.json")
    assert record.raw_payload == [
        row for row in fixture if row["证券代码"] == "920000"
    ]
    assert fake.calls == [
        ("stock_margin_detail_bse", {"date": "20260721"}),
    ]
    assert record.response_metadata["endpoint"] == "stock_margin_detail_bse"
    assert record.response_metadata["upstream_row_count"] == 3
    assert record.response_metadata["entity_row_count"] == 1
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is False
    assert record.response_metadata["row_filtering"] == "provider"
    assert record.response_metadata["requested_date"] == "20260721"
    assert record.response_metadata["observation_date"] == "2026-07-21"
    assert record.response_metadata["date_binding"] == "request"
    assert record.response_metadata["snapshot_scope"] == "requested_date"
    assert record.source_uri == (
        "https://www.bse.cn/disclosure/rzrq_trans_list.html"
    )
    assert all("信用交易日期" not in row for row in record.raw_payload)


def test_bse_margin_detail_response_rejects_a_row_without_listing_code():
    class InvalidRows(FakeAKShare):
        def stock_margin_detail_bse(self, *, date: str):
            rows = [dict(row) for row in _fixture("a_margin_detail_bse.json")]
            rows[0].pop("证券代码")
            return self._return("stock_margin_detail_bse", rows, date=date)

    with pytest.raises(ProviderResponseError, match="margin-trading row without a listing code"):
        _provider(InvalidRows()).fetch(
            _request(
                DataCategory.MARGIN_TRADING,
                "BJ920000",
                {"date": "20260721"},
            )
        )


def test_bse_margin_detail_raw_record_is_not_promoted_to_issuer_facts():
    record = _provider().fetch(
        _request(
            DataCategory.MARGIN_TRADING,
            "BJ920000",
            {"date": "20260721"},
        )
    )

    normalized = normalize_akshare_records(
        [record],
        analysis_id="bse-margin-detail-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(primary_listing="BJ920000"),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_MARGIN_TRADING_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == ["financial_debt"]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "security-level financing balances" in normalized.data_quality.notes
    assert "issuer financial debt, cash or leverage facts" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(
        Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json"))
    ) == []


def test_bse_margin_detail_normalizer_rejects_replayed_rows_for_another_listing():
    record = _provider().fetch(
        _request(
            DataCategory.MARGIN_TRADING,
            "BJ920000",
            {"date": "20260721"},
        )
    )
    payload = [dict(row) for row in record.raw_payload]
    payload[0]["证券代码"] = "920001"
    replayed = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="margin-trading row entity"):
        normalize_akshare_records(
            [replayed],
            analysis_id="mismatched-bse-margin-detail-entity",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(primary_listing="BJ920000"),
        )


def test_bse_margin_detail_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.MARGIN_TRADING,
        "BJ920000",
        {"date": "20260721"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [("stock_margin_detail_bse", {"date": "20260721"})]


@pytest.mark.parametrize(
    ("listing", "market"),
    [("SH600000", "sh"), ("SZ000001", "sz"), ("BJ920000", "bj")],
)
def test_individual_fund_flow_fetch_uses_documented_listing_market_scope(
    listing: str,
    market: str,
):
    fake = FakeAKShare()
    record = _provider(fake).fetch(_request(DataCategory.CAPITAL_FLOW, listing))

    assert record.raw_payload == _fixture("a_individual_fund_flow.json")
    assert fake.calls == [
        ("stock_individual_fund_flow", {"stock": listing[-6:], "market": market}),
    ]
    assert record.response_metadata["endpoint"] == "stock_individual_fund_flow"
    assert record.response_metadata["upstream_row_count"] == 3
    assert record.response_metadata["entity_row_count"] == 3
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is True
    assert record.response_metadata["snapshot_scope"] == "recent_trading_days"
    assert record.response_metadata["observation_date_field"] == "日期"
    assert record.response_metadata["observation_start_date"] == "2026-08-26"
    assert record.response_metadata["observation_end_date"] == "2026-08-28"
    assert record.source_uri == "https://data.eastmoney.com/zjlx/detail.html"


def test_individual_fund_flow_request_rejects_h_shares_and_extra_parameters():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        provider.fetch(_request(DataCategory.CAPITAL_FLOW, "HK00700"))
    with pytest.raises(ProviderRequestError, match="unsupported AKShare capital-flow"):
        provider.fetch(
            _request(
                DataCategory.CAPITAL_FLOW,
                "SH600000",
                {"start_date": "20260101"},
            )
        )

    assert fake.calls == []


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("missing_date", "capital-flow row without an observation date"),
        ("invalid_date", "invalid capital-flow observation date"),
        ("wrong_identity", "capital-flow row entity"),
        ("duplicate_date", "duplicate capital-flow observation date"),
    ],
)
def test_individual_fund_flow_response_validates_dates_and_optional_identity(
    mutation: str,
    match: str,
):
    class InvalidRows(FakeAKShare):
        def stock_individual_fund_flow(self, *, stock: str, market: str):
            rows = _fixture("a_individual_fund_flow.json")
            if mutation == "missing_date":
                rows[0].pop("日期")
            elif mutation == "invalid_date":
                rows[0]["日期"] = "not-a-date"
            elif mutation == "wrong_identity":
                rows[0]["代码"] = "000001"
            else:
                rows[1]["日期"] = rows[0]["日期"]
            return self._return(
                "stock_individual_fund_flow",
                rows,
                stock=stock,
                market=market,
            )

    with pytest.raises(ProviderResponseError, match=match):
        _provider(InvalidRows()).fetch(_request(DataCategory.CAPITAL_FLOW, "SH600000"))


def test_individual_fund_flow_is_retained_as_raw_evidence_without_canonical_facts():
    record = _provider().fetch(_request(DataCategory.CAPITAL_FLOW, "SH600000"))
    normalized = normalize_akshare_records(
        [record],
        analysis_id="individual-fund-flow-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_INDIVIDUAL_FUND_FLOW_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == []
    assert normalized.data_quality.confidence.value == "LOW"
    assert "investor-flow amounts and percentages" in normalized.data_quality.notes
    assert "issuer cash flow" in normalized.data_quality.notes
    assert "valuation fact" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(
        Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json"))
    ) == []


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("日期", "not-a-date", "capital-flow row has an invalid observation date"),
        ("代码", "000001", "capital-flow row entity"),
    ],
)
def test_individual_fund_flow_normalizer_rejects_replayed_scope_mismatches(
    field: str,
    value: str,
    match: str,
):
    record = _provider().fetch(_request(DataCategory.CAPITAL_FLOW, "SH600000"))
    payload = [dict(row) for row in record.raw_payload]
    payload[0][field] = value
    replayed = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match=match):
        normalize_akshare_records(
            [replayed],
            analysis_id="mismatched-individual-fund-flow",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_individual_fund_flow_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(DataCategory.CAPITAL_FLOW, "SH600000")

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        ("stock_individual_fund_flow", {"stock": "600000", "market": "sh"}),
    ]


def test_top_10_shareholders_fetch_uses_explicit_view_and_report_date():
    fake = FakeAKShare()
    record = _provider(fake).fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            "SH600000",
            {"view": "top_10", "date": "20240930"},
        )
    )

    assert record.raw_payload == _fixture("a_top_10_holders.json")
    assert fake.calls == [
        (
            "stock_gdfx_top_10_em",
            {"symbol": "SH600000", "date": "20240930"},
        )
    ]
    assert record.response_metadata["endpoint"] == "stock_gdfx_top_10_em"
    assert record.response_metadata["upstream_row_count"] == 3
    assert record.response_metadata["entity_row_count"] == 3
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is True
    assert record.response_metadata["top10_view"] == "top_10"
    assert record.response_metadata["requested_date"] == "20240930"
    assert record.response_metadata["report_period"] == "2024-09-30"
    assert record.response_metadata["snapshot_scope"] == "requested_report_period"
    assert record.response_metadata["observation_date_field"] == "request.date"
    assert record.source_uri == (
        "https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/"
        "Index?type=web&code=SH688686#sdgd-0"
    )


@pytest.mark.parametrize(
    ("parameters", "match"),
    [
        ({"view": "top_10"}, "requires date"),
        (
            {"view": "top_10", "date": "2024-09-30"},
            "date must be YYYYMMDD",
        ),
        (
            {"view": "top_10", "date": "20240931"},
            "date must be a valid YYYYMMDD date",
        ),
        (
            {"view": "top_10", "date": "20240929"},
            "date must be an exact quarter-end report date",
        ),
        (
            {"view": "top_10", "date": "20240930", "market": "A"},
            "unsupported AKShare top-ten-shareholder parameter",
        ),
    ],
)
def test_top_10_shareholders_request_validates_explicit_scope(
    parameters: dict,
    match: str,
):
    fake = FakeAKShare()

    with pytest.raises(ProviderRequestError, match=match):
        _provider(fake).fetch(
            _request(DataCategory.SHAREHOLDER_HOLDINGS, "SH600000", parameters)
        )

    assert fake.calls == []


def test_top_10_shareholders_request_is_a_share_only_before_upstream_call():
    fake = FakeAKShare()

    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        _provider(fake).fetch(
            _request(
                DataCategory.SHAREHOLDER_HOLDINGS,
                "HK00700",
                {"view": "top_10", "date": "20240930"},
            )
        )

    assert fake.calls == []


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("missing_rank", "top-ten-shareholder row without a valid rank"),
        ("missing_holder", "top-ten-shareholder row without a holder name"),
        ("wrong_identity", "top-ten-shareholder row entity"),
        ("duplicate_rank", "duplicate top-ten-shareholder rank"),
    ],
)
def test_top_10_shareholders_response_validates_rank_holder_and_identity(
    mutation: str,
    match: str,
):
    class InvalidRows(FakeAKShare):
        def stock_gdfx_top_10_em(self, *, symbol: str, date: str):
            rows = _fixture("a_top_10_holders.json")
            if mutation == "missing_rank":
                rows[0].pop("名次")
            elif mutation == "missing_holder":
                rows[0]["股东名称"] = None
            elif mutation == "wrong_identity":
                rows[0]["证券代码"] = "000001"
            else:
                rows[1]["名次"] = rows[0]["名次"]
            return self._return(
                "stock_gdfx_top_10_em",
                rows,
                symbol=symbol,
                date=date,
            )

    with pytest.raises(ProviderResponseError, match=match):
        _provider(InvalidRows()).fetch(
            _request(
                DataCategory.SHAREHOLDER_HOLDINGS,
                "SH600000",
                {"view": "top_10", "date": "20240930"},
            )
        )


def test_top_10_shareholders_empty_response_is_a_valid_scoped_raw_snapshot():
    class EmptyRows(FakeAKShare):
        def stock_gdfx_top_10_em(self, *, symbol: str, date: str):
            return self._return(
                "stock_gdfx_top_10_em",
                [],
                symbol=symbol,
                date=date,
            )

    record = _provider(EmptyRows()).fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            "SH600000",
            {"view": "top_10", "date": "20240930"},
        )
    )

    assert record.raw_payload == []
    assert record.response_metadata["upstream_row_count"] == 0
    assert record.response_metadata["entity_row_count"] == 0
    assert record.response_metadata["listing_scoped_request"] is True


def test_top_10_shareholders_are_retained_as_raw_evidence_without_canonical_facts():
    record = _provider().fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            "SH600000",
            {"view": "top_10", "date": "20240930"},
        )
    )
    normalized = normalize_akshare_records(
        [record],
        analysis_id="top-10-shareholders-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_TOP_10_SHAREHOLDERS_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "governance_risk_level",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "report-period rank" in normalized.data_quality.notes
    assert "canonical concentration metric" in normalized.data_quality.notes
    assert "diluted-share series" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(
        Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json"))
    ) == []


def test_top_10_shareholders_normalizer_rejects_replayed_scope_mismatches():
    record = _provider().fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            "SH600000",
            {"view": "top_10", "date": "20240930"},
        )
    )
    payload = [dict(row) for row in record.raw_payload]
    payload[0]["证券代码"] = "000001"
    replayed = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match="top-ten-shareholder row entity"):
        normalize_akshare_records(
            [replayed],
            analysis_id="mismatched-top-10-shareholders",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_top_10_shareholders_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.SHAREHOLDER_HOLDINGS,
        "SH600000",
        {"view": "top_10", "date": "20240930"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        (
            "stock_gdfx_top_10_em",
            {"symbol": "SH600000", "date": "20240930"},
        )
    ]


def test_free_top_10_shareholders_fetch_uses_explicit_view_and_report_date():
    fake = FakeAKShare()
    record = _provider(fake).fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            "SH600000",
            {"view": "free_top_10", "date": "20240930"},
        )
    )

    assert record.raw_payload == _fixture("a_free_top_10_holders.json")
    assert fake.calls == [
        (
            "stock_gdfx_free_top_10_em",
            {"symbol": "SH600000", "date": "20240930"},
        )
    ]
    assert record.response_metadata["endpoint"] == "stock_gdfx_free_top_10_em"
    assert record.response_metadata["upstream_row_count"] == 3
    assert record.response_metadata["entity_row_count"] == 3
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is True
    assert record.response_metadata["top10_view"] == "free_top_10"
    assert record.response_metadata["requested_date"] == "20240930"
    assert record.response_metadata["report_period"] == "2024-09-30"
    assert record.response_metadata["snapshot_scope"] == "requested_report_period"
    assert record.response_metadata["observation_date_field"] == "request.date"
    assert record.source_uri == (
        "https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/"
        "Index?type=web&code=SH688686#sdltgd-0"
    )


@pytest.mark.parametrize(
    ("parameters", "match"),
    [
        ({"view": "free_top_10"}, "requires date"),
        (
            {"view": "free_top_10", "date": "2024-09-30"},
            "date must be YYYYMMDD",
        ),
        (
            {"view": "free_top_10", "date": "20240931"},
            "date must be a valid YYYYMMDD date",
        ),
        (
            {"view": "free_top_10", "date": "20240929"},
            "date must be an exact quarter-end report date",
        ),
        (
            {"view": "free_top_10", "date": "20240930", "market": "A"},
            "unsupported AKShare free-top-ten-shareholder parameter",
        ),
    ],
)
def test_free_top_10_shareholders_request_validates_explicit_scope(
    parameters: dict,
    match: str,
):
    fake = FakeAKShare()

    with pytest.raises(ProviderRequestError, match=match):
        _provider(fake).fetch(
            _request(DataCategory.SHAREHOLDER_HOLDINGS, "SH600000", parameters)
        )

    assert fake.calls == []


def test_free_top_10_shareholders_request_is_a_share_only_before_upstream_call():
    fake = FakeAKShare()

    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        _provider(fake).fetch(
            _request(
                DataCategory.SHAREHOLDER_HOLDINGS,
                "HK00700",
                {"view": "free_top_10", "date": "20240930"},
            )
        )

    assert fake.calls == []


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (
            "missing_rank",
            "free-top-ten-shareholder row without a valid rank",
        ),
        (
            "missing_holder",
            "free-top-ten-shareholder row without a holder name",
        ),
        ("wrong_identity", "free-top-ten-shareholder row entity"),
        ("duplicate_rank", "duplicate free-top-ten-shareholder rank"),
    ],
)
def test_free_top_10_shareholders_response_validates_rank_holder_and_identity(
    mutation: str,
    match: str,
):
    class InvalidRows(FakeAKShare):
        def stock_gdfx_free_top_10_em(self, *, symbol: str, date: str):
            rows = _fixture("a_free_top_10_holders.json")
            if mutation == "missing_rank":
                rows[0].pop("名次")
            elif mutation == "missing_holder":
                rows[0]["股东名称"] = None
            elif mutation == "wrong_identity":
                rows[0]["证券代码"] = "000001"
            else:
                rows[1]["名次"] = rows[0]["名次"]
            return self._return(
                "stock_gdfx_free_top_10_em",
                rows,
                symbol=symbol,
                date=date,
            )

    with pytest.raises(ProviderResponseError, match=match):
        _provider(InvalidRows()).fetch(
            _request(
                DataCategory.SHAREHOLDER_HOLDINGS,
                "SH600000",
                {"view": "free_top_10", "date": "20240930"},
            )
        )


def test_free_top_10_shareholders_empty_response_is_a_valid_scoped_raw_snapshot():
    class EmptyRows(FakeAKShare):
        def stock_gdfx_free_top_10_em(self, *, symbol: str, date: str):
            return self._return(
                "stock_gdfx_free_top_10_em",
                [],
                symbol=symbol,
                date=date,
            )

    record = _provider(EmptyRows()).fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            "SH600000",
            {"view": "free_top_10", "date": "20240930"},
        )
    )

    assert record.raw_payload == []
    assert record.response_metadata["upstream_row_count"] == 0
    assert record.response_metadata["entity_row_count"] == 0
    assert record.response_metadata["listing_scoped_request"] is True


def test_free_top_10_shareholders_are_retained_as_raw_evidence_without_canonical_facts():
    record = _provider().fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            "SH600000",
            {"view": "free_top_10", "date": "20240930"},
        )
    )
    normalized = normalize_akshare_records(
        [record],
        analysis_id="free-top-10-shareholders-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_FREE_TOP_10_SHAREHOLDERS_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "governance_risk_level",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "top-ten-tradable-shareholder" in normalized.data_quality.notes
    assert "float-share ratio" in normalized.data_quality.notes
    assert "canonical concentration metric" in normalized.data_quality.notes
    assert "diluted-share series" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(
        Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json"))
    ) == []


def test_free_top_10_shareholders_normalizer_rejects_replayed_scope_mismatches():
    record = _provider().fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            "SH600000",
            {"view": "free_top_10", "date": "20240930"},
        )
    )
    payload = [dict(row) for row in record.raw_payload]
    payload[0]["证券代码"] = "000001"
    replayed = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(
        ProviderNormalizationError,
        match="free-top-ten-shareholder row entity",
    ):
        normalize_akshare_records(
            [replayed],
            analysis_id="mismatched-free-top-10-shareholders",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_free_top_10_shareholders_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.SHAREHOLDER_HOLDINGS,
        "SH600000",
        {"view": "free_top_10", "date": "20240930"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        (
            "stock_gdfx_free_top_10_em",
            {"symbol": "SH600000", "date": "20240930"},
        )
    ]


def test_free_holding_detail_fetch_filters_the_documented_report_period_universe():
    fake = FakeAKShare()
    record = _provider(fake).fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            "SH600000",
            {"view": "free_holding_detail", "date": "20240930"},
        )
    )

    fixture = _fixture("a_free_holding_detail.json")
    assert record.raw_payload == [row for row in fixture if row["股票代码"] == "600000"]
    assert fake.calls == [
        ("stock_gdfx_free_holding_detail_em", {"date": "20240930"}),
    ]
    assert record.response_metadata["endpoint"] == "stock_gdfx_free_holding_detail_em"
    assert record.response_metadata["upstream_row_count"] == 3
    assert record.response_metadata["entity_row_count"] == 2
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is False
    assert record.response_metadata["row_filtering"] == "provider"
    assert record.response_metadata["free_holding_detail_view"] == "free_holding_detail"
    assert record.response_metadata["requested_date"] == "20240930"
    assert record.response_metadata["report_period"] == "2024-09-30"
    assert record.response_metadata["date_binding"] == "row_and_request"
    assert record.response_metadata["snapshot_scope"] == "requested_quarter_end"
    assert record.response_metadata["observation_date_field"] == "报告期"
    assert record.source_uri == "https://data.eastmoney.com/gdfx/HoldingAnalyse.html"


@pytest.mark.parametrize(
    ("parameters", "match"),
    [
        (
            {"view": "free_holding_detail"},
            "requires date",
        ),
        (
            {"view": "free_holding_detail", "date": "2024-09-30"},
            "date must be YYYYMMDD",
        ),
        (
            {"view": "free_holding_detail", "date": "20240931"},
            "date must be a valid YYYYMMDD date",
        ),
        (
            {"view": "free_holding_detail", "date": "20240929"},
            "date must be an exact quarter-end report date",
        ),
        (
            {
                "view": "free_holding_detail",
                "date": "20240930",
                "market": "A",
            },
            "unsupported AKShare free-holding-detail parameter",
        ),
    ],
)
def test_free_holding_detail_request_validates_explicit_scope(
    parameters: dict,
    match: str,
):
    fake = FakeAKShare()

    with pytest.raises(ProviderRequestError, match=match):
        _provider(fake).fetch(
            _request(DataCategory.SHAREHOLDER_HOLDINGS, "SH600000", parameters)
        )

    assert fake.calls == []


def test_free_holding_detail_request_is_a_share_only_before_upstream_call():
    fake = FakeAKShare()

    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        _provider(fake).fetch(
            _request(
                DataCategory.SHAREHOLDER_HOLDINGS,
                "HK00700",
                {"view": "free_holding_detail", "date": "20240930"},
            )
        )

    assert fake.calls == []


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("missing_code", "free-holding-detail row without a listing code"),
        ("missing_holder", "free-holding-detail row without a holder name"),
        ("missing_period", "free-holding-detail row without a report period"),
        ("invalid_period", "invalid free-holding-detail report period"),
        ("wrong_period", "free-holding-detail row period"),
        (
            "invalid_announcement",
            "invalid free-holding-detail announcement date",
        ),
    ],
)
def test_free_holding_detail_response_validates_identity_and_report_period(
    mutation: str,
    match: str,
):
    class InvalidRows(FakeAKShare):
        def stock_gdfx_free_holding_detail_em(self, *, date: str):
            rows = _fixture("a_free_holding_detail.json")
            if mutation == "missing_code":
                rows[0].pop("股票代码")
            elif mutation == "missing_holder":
                rows[0]["股东名称"] = None
            elif mutation == "missing_period":
                rows[0].pop("报告期")
            elif mutation == "invalid_period":
                rows[0]["报告期"] = "not-a-date"
            elif mutation == "wrong_period":
                rows[0]["报告期"] = "2024-06-30"
            else:
                rows[0]["公告日"] = "not-a-date"
            return self._return(
                "stock_gdfx_free_holding_detail_em",
                rows,
                date=date,
            )

    with pytest.raises(ProviderResponseError, match=match):
        _provider(InvalidRows()).fetch(
            _request(
                DataCategory.SHAREHOLDER_HOLDINGS,
                "SH600000",
                {"view": "free_holding_detail", "date": "20240930"},
            )
        )


def test_free_holding_detail_with_no_matching_listing_is_an_empty_raw_snapshot():
    class NoMatchingFreeHoldingDetail(FakeAKShare):
        def stock_gdfx_free_holding_detail_em(self, *, date: str):
            return self._return(
                "stock_gdfx_free_holding_detail_em",
                [
                    row
                    for row in _fixture("a_free_holding_detail.json")
                    if row["股票代码"] == "000001"
                ],
                date=date,
            )

    record = _provider(NoMatchingFreeHoldingDetail()).fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            "SH600000",
            {"view": "free_holding_detail", "date": "20240930"},
        )
    )

    assert record.raw_payload == []
    assert record.response_metadata["upstream_row_count"] == 1
    assert record.response_metadata["entity_row_count"] == 0


def test_free_holding_detail_is_retained_as_raw_evidence_without_canonical_facts():
    record = _provider().fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            "SH600000",
            {"view": "free_holding_detail", "date": "20240930"},
        )
    )
    normalized = normalize_akshare_records(
        [record],
        analysis_id="free-holding-detail-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_FREE_HOLDING_DETAIL_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == [
        "governance_risk_level",
    ]
    assert normalized.data_quality.confidence.value == "LOW"
    assert "top-ten-tradable-shareholder detail universe" in normalized.data_quality.notes
    assert "canonical concentration metric" in normalized.data_quality.notes
    assert "diluted-share series" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(
        Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json"))
    ) == []


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("entity", "free-holding-detail row entity"),
        ("period", "free-holding-detail row period"),
        ("missing_period", "free-holding-detail row has no exact report period"),
        ("invalid_announcement", "free-holding-detail row has an invalid announcement date"),
    ],
)
def test_free_holding_detail_normalizer_rejects_replayed_scope_mismatches(
    mutation: str,
    match: str,
):
    record = _provider().fetch(
        _request(
            DataCategory.SHAREHOLDER_HOLDINGS,
            "SH600000",
            {"view": "free_holding_detail", "date": "20240930"},
        )
    )
    payload = [dict(row) for row in record.raw_payload]
    if mutation == "entity":
        payload[0]["股票代码"] = "000001"
    elif mutation == "period":
        payload[0]["报告期"] = "2024-06-30"
    elif mutation == "missing_period":
        payload[0].pop("报告期")
    else:
        payload[0]["公告日"] = "not-a-date"
    replayed = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match=match):
        normalize_akshare_records(
            [replayed],
            analysis_id="mismatched-free-holding-detail",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_free_holding_detail_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.SHAREHOLDER_HOLDINGS,
        "SH600000",
        {"view": "free_holding_detail", "date": "20240930"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        ("stock_gdfx_free_holding_detail_em", {"date": "20240930"}),
    ]


def test_market_activity_fetch_filters_the_documented_date_range_universe():
    fake = FakeAKShare()
    request = _request(
        DataCategory.MARKET_ACTIVITY,
        "SH600000",
        {"start_date": "20240927", "end_date": "20240930"},
    )
    record = _provider(fake).fetch(request)

    fixture = _fixture("a_lhb_detail.json")
    assert record.raw_payload == [row for row in fixture if row["代码"] == "600000"]
    assert fake.calls == [
        (
            "stock_lhb_detail_em",
            {"start_date": "20240927", "end_date": "20240930"},
        )
    ]
    assert record.response_metadata["endpoint"] == "stock_lhb_detail_em"
    assert record.response_metadata["upstream_row_count"] == 3
    assert record.response_metadata["entity_row_count"] == 2
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is False
    assert record.response_metadata["row_filtering"] == "provider"
    assert record.response_metadata["start_date"] == "20240927"
    assert record.response_metadata["end_date"] == "20240930"
    assert record.response_metadata["date_binding"] == "row_and_request"
    assert record.response_metadata["snapshot_scope"] == "requested_date_range"
    assert record.response_metadata["observation_date_field"] == "上榜日"
    assert record.response_metadata["observed_start_date"] == "2024-09-27"
    assert record.response_metadata["observed_end_date"] == "2024-09-30"
    assert record.source_uri == "https://data.eastmoney.com/stock/tradedetail.html"


@pytest.mark.parametrize(
    ("parameters", "match"),
    [
        ({"end_date": "20240930"}, "requires start_date and end_date"),
        ({"start_date": "20240927"}, "requires start_date and end_date"),
        (
            {"start_date": "2024-09-27", "end_date": "20240930"},
            "start_date must be YYYYMMDD",
        ),
        (
            {"start_date": "20240931", "end_date": "20240930"},
            "start_date must be a valid YYYYMMDD date",
        ),
        (
            {"start_date": "20241001", "end_date": "20240930"},
            "start_date must not be after end_date",
        ),
        (
            {
                "start_date": "20240927",
                "end_date": "20240930",
                "market": "A",
            },
            "unsupported AKShare market-activity parameter",
        ),
    ],
)
def test_market_activity_request_validates_explicit_date_range(
    parameters: dict,
    match: str,
):
    fake = FakeAKShare()

    with pytest.raises(ProviderRequestError, match=match):
        _provider(fake).fetch(
            _request(DataCategory.MARKET_ACTIVITY, "SH600000", parameters)
        )

    assert fake.calls == []


def test_market_activity_request_is_a_share_only_before_upstream_call():
    fake = FakeAKShare()

    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        _provider(fake).fetch(
            _request(
                DataCategory.MARKET_ACTIVITY,
                "HK00700",
                {"start_date": "20240927", "end_date": "20240930"},
            )
        )

    assert fake.calls == []


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("missing_code", "market-activity row without a listing code"),
        ("missing_date", "market-activity row without an activity date"),
        ("invalid_date", "invalid market-activity date"),
        ("outside_range", "market-activity row date .*outside requested range"),
    ],
)
def test_market_activity_response_validates_identity_and_date_range(
    mutation: str,
    match: str,
):
    class InvalidRows(FakeAKShare):
        def stock_lhb_detail_em(self, *, start_date: str, end_date: str):
            rows = _fixture("a_lhb_detail.json")
            if mutation == "missing_code":
                rows[0].pop("代码")
            elif mutation == "missing_date":
                rows[0].pop("上榜日")
            elif mutation == "invalid_date":
                rows[0]["上榜日"] = "not-a-date"
            else:
                rows[0]["上榜日"] = "2024-09-26"
            return self._return(
                "stock_lhb_detail_em",
                rows,
                start_date=start_date,
                end_date=end_date,
            )

    with pytest.raises(ProviderResponseError, match=match):
        _provider(InvalidRows()).fetch(
            _request(
                DataCategory.MARKET_ACTIVITY,
                "SH600000",
                {"start_date": "20240927", "end_date": "20240930"},
            )
        )


def test_market_activity_with_no_matching_listing_is_an_empty_raw_snapshot():
    class NoMatchingMarketActivity(FakeAKShare):
        def stock_lhb_detail_em(self, *, start_date: str, end_date: str):
            return self._return(
                "stock_lhb_detail_em",
                [
                    row
                    for row in _fixture("a_lhb_detail.json")
                    if row["代码"] == "000001"
                ],
                start_date=start_date,
                end_date=end_date,
            )

    record = _provider(NoMatchingMarketActivity()).fetch(
        _request(
            DataCategory.MARKET_ACTIVITY,
            "SH600000",
            {"start_date": "20240927", "end_date": "20240930"},
        )
    )

    assert record.raw_payload == []
    assert record.response_metadata["upstream_row_count"] == 1
    assert record.response_metadata["entity_row_count"] == 0


def test_market_activity_is_retained_as_raw_evidence_without_canonical_facts():
    record = _provider().fetch(
        _request(
            DataCategory.MARKET_ACTIVITY,
            "SH600000",
            {"start_date": "20240927", "end_date": "20240930"},
        )
    )
    normalized = normalize_akshare_records(
        [record],
        analysis_id="market-activity-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_MARKET_ACTIVITY_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == []
    assert normalized.data_quality.confidence.value == "LOW"
    assert "Dragon-Tiger-board" in normalized.data_quality.notes
    assert "forward-looking post-listing returns" in normalized.data_quality.notes
    assert "issuer cash flow" in normalized.data_quality.notes
    assert "canonical market metric" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(
        Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json"))
    ) == []


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("entity", "market-activity row entity"),
        ("outside_range", "market-activity row date .*outside requested range"),
        ("missing_date", "market-activity row has no exact activity date"),
        ("invalid_date", "market-activity row has an invalid activity date"),
    ],
)
def test_market_activity_normalizer_rejects_replayed_scope_mismatches(
    mutation: str,
    match: str,
):
    record = _provider().fetch(
        _request(
            DataCategory.MARKET_ACTIVITY,
            "SH600000",
            {"start_date": "20240927", "end_date": "20240930"},
        )
    )
    payload = [dict(row) for row in record.raw_payload]
    if mutation == "entity":
        payload[0]["代码"] = "000001"
    elif mutation == "outside_range":
        payload[0]["上榜日"] = "2024-09-26"
    elif mutation == "missing_date":
        payload[0].pop("上榜日")
    else:
        payload[0]["上榜日"] = "not-a-date"
    replayed = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=record.response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match=match):
        normalize_akshare_records(
            [replayed],
            analysis_id="mismatched-market-activity",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_market_activity_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.MARKET_ACTIVITY,
        "SH600000",
        {"start_date": "20240927", "end_date": "20240930"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        (
            "stock_lhb_detail_em",
            {"start_date": "20240927", "end_date": "20240930"},
        )
    ]


def test_market_activity_statistic_fetch_uses_explicit_view_and_period_and_filters_universe():
    fake = FakeAKShare()
    request = _request(
        DataCategory.MARKET_ACTIVITY,
        "SH600000",
        {"view": "stock_statistic", "period": "近三月"},
    )
    record = _provider(fake).fetch(request)

    fixture = _fixture("a_lhb_stock_statistic.json")
    assert record.raw_payload == [row for row in fixture if row["代码"] == "600000"]
    assert fake.calls == [
        ("stock_lhb_stock_statistic_em", {"symbol": "近三月"}),
    ]
    assert record.response_metadata["endpoint"] == "stock_lhb_stock_statistic_em"
    assert record.response_metadata["upstream_row_count"] == 3
    assert record.response_metadata["entity_row_count"] == 1
    assert record.response_metadata["entity_rows_selected"] is True
    assert record.response_metadata["listing_scoped_request"] is False
    assert record.response_metadata["row_filtering"] == "provider"
    assert record.response_metadata["market_activity_view"] == "stock_statistic"
    assert record.response_metadata["statistic_period"] == "近三月"
    assert record.response_metadata["upstream_symbol"] == "近三月"
    assert record.response_metadata["date_binding"] == "request_period"
    assert record.response_metadata["snapshot_scope"] == "requested_statistic_period"
    assert record.response_metadata["observation_date_field"] == "最近上榜日"
    assert record.response_metadata["observed_earliest_recent_listing_date"] == (
        "2024-09-27"
    )
    assert record.response_metadata["observed_latest_recent_listing_date"] == (
        "2024-09-30"
    )
    assert record.source_uri == "https://data.eastmoney.com/stock/tradedetail.html"


@pytest.mark.parametrize(
    ("parameters", "match"),
    [
        (
            {"period": "近三月"},
            "requires view='stock_statistic'",
        ),
        (
            {"view": "stock_statistic"},
            "requires period",
        ),
        (
            {"view": "not-a-view", "period": "近三月"},
            "requires view='stock_statistic'",
        ),
        (
            {"view": "stock_statistic", "period": "近二月"},
            "period must be one of",
        ),
        (
            {
                "view": "stock_statistic",
                "period": "近三月",
                "start_date": "20240927",
            },
            "unsupported AKShare market-activity-statistic parameter",
        ),
    ],
)
def test_market_activity_statistic_request_validates_view_period_and_parameters(
    parameters: dict,
    match: str,
):
    fake = FakeAKShare()

    with pytest.raises(ProviderRequestError, match=match):
        _provider(fake).fetch(
            _request(DataCategory.MARKET_ACTIVITY, "SH600000", parameters)
        )

    assert fake.calls == []


def test_market_activity_statistic_request_is_a_share_only_before_upstream_call():
    fake = FakeAKShare()

    with pytest.raises(ProviderRequestError, match="A-share listings only"):
        _provider(fake).fetch(
            _request(
                DataCategory.MARKET_ACTIVITY,
                "HK00700",
                {"view": "stock_statistic", "period": "近一月"},
            )
        )

    assert fake.calls == []


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (
            "missing_code",
            "market-activity-statistic row without a listing code",
        ),
        (
            "missing_date",
            "market-activity-statistic row without a recent listing date",
        ),
        (
            "invalid_date",
            "invalid market-activity-statistic recent listing date",
        ),
        (
            "duplicate_code",
            "duplicate market-activity-statistic row",
        ),
    ],
)
def test_market_activity_statistic_response_validates_identity_and_dates(
    mutation: str,
    match: str,
):
    class InvalidRows(FakeAKShare):
        def stock_lhb_stock_statistic_em(self, *, symbol: str):
            rows = _fixture("a_lhb_stock_statistic.json")
            if mutation == "missing_code":
                rows[0].pop("代码")
            elif mutation == "missing_date":
                rows[0].pop("最近上榜日")
            elif mutation == "invalid_date":
                rows[0]["最近上榜日"] = "not-a-date"
            else:
                rows.append(dict(rows[0]))
            return self._return(
                "stock_lhb_stock_statistic_em",
                rows,
                symbol=symbol,
            )

    with pytest.raises(ProviderResponseError, match=match):
        _provider(InvalidRows()).fetch(
            _request(
                DataCategory.MARKET_ACTIVITY,
                "SH600000",
                {"view": "stock_statistic", "period": "近三月"},
            )
        )


def test_market_activity_statistic_with_no_matching_listing_is_an_empty_raw_snapshot():
    class NoMatchingMarketActivityStatistic(FakeAKShare):
        def stock_lhb_stock_statistic_em(self, *, symbol: str):
            return self._return(
                "stock_lhb_stock_statistic_em",
                [
                    row
                    for row in _fixture("a_lhb_stock_statistic.json")
                    if row["代码"] == "000001"
                ],
                symbol=symbol,
            )

    record = _provider(NoMatchingMarketActivityStatistic()).fetch(
        _request(
            DataCategory.MARKET_ACTIVITY,
            "SH600000",
            {"view": "stock_statistic", "period": "近三月"},
        )
    )

    assert record.raw_payload == []
    assert record.response_metadata["upstream_row_count"] == 1
    assert record.response_metadata["entity_row_count"] == 0


def test_market_activity_statistic_is_retained_as_raw_evidence_without_canonical_facts():
    record = _provider().fetch(
        _request(
            DataCategory.MARKET_ACTIVITY,
            "SH600000",
            {"view": "stock_statistic", "period": "近三月"},
        )
    )
    normalized = normalize_akshare_records(
        [record],
        analysis_id="market-activity-statistic-raw-only",
        as_of=date(2026, 9, 9),
        profile_id="strict-v1",
        company=_company(),
    )

    assert normalized.facts == []
    assert normalized.evidence_index
    assert normalized.flags == ["AKSHARE_MARKET_ACTIVITY_STATISTICS_RAW_ONLY"]
    assert normalized.data_quality.critical_missing_fields == []
    assert normalized.data_quality.confidence.value == "LOW"
    assert "Dragon-Tiger stock-statistic" in normalized.data_quality.notes
    assert "aggregate" in normalized.data_quality.notes
    assert "issuer cash flow" in normalized.data_quality.notes
    assert "canonical market metric" in normalized.data_quality.notes

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(
        Draft202012Validator(schema).iter_errors(normalized.model_dump(mode="json"))
    ) == []


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (
            "entity",
            "market-activity-statistic row entity",
        ),
        (
            "missing_date",
            "market-activity-statistic row has no exact recent listing date",
        ),
        (
            "invalid_date",
            "market-activity-statistic row has an invalid recent listing date",
        ),
        (
            "duplicate_code",
            "market-activity-statistic row has duplicate listing code",
        ),
        (
            "metadata_period",
            "market-activity-statistic response period does not match",
        ),
    ],
)
def test_market_activity_statistic_normalizer_rejects_replayed_scope_mismatches(
    mutation: str,
    match: str,
):
    record = _provider().fetch(
        _request(
            DataCategory.MARKET_ACTIVITY,
            "SH600000",
            {"view": "stock_statistic", "period": "近三月"},
        )
    )
    payload = [dict(row) for row in record.raw_payload]
    response_metadata = dict(record.response_metadata)
    if mutation == "entity":
        payload[0]["代码"] = "000001"
    elif mutation == "missing_date":
        payload[0].pop("最近上榜日")
    elif mutation == "invalid_date":
        payload[0]["最近上榜日"] = "not-a-date"
    elif mutation == "duplicate_code":
        payload.append(dict(payload[0]))
    else:
        response_metadata["statistic_period"] = "近一年"
    replayed = record.__class__(
        provider=record.provider,
        request=record.request,
        retrieved_at=record.retrieved_at,
        raw_payload=payload,
        source_uri=record.source_uri,
        response_metadata=response_metadata,
    )

    with pytest.raises(ProviderNormalizationError, match=match):
        normalize_akshare_records(
            [replayed],
            analysis_id="mismatched-market-activity-statistic",
            as_of=date(2026, 9, 9),
            profile_id="strict-v1",
            company=_company(),
        )


def test_market_activity_statistic_cache_replay_does_not_call_upstream(tmp_path: Path):
    fake = FakeAKShare()
    provider = _provider(fake)
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request(
        DataCategory.MARKET_ACTIVITY,
        "SH600000",
        {"view": "stock_statistic", "period": "近三月"},
    )

    live = fetch_akshare_with_cache(provider, request, cache)
    fake.fail = True
    replay = fetch_akshare_with_cache(provider, request, cache, offline=True)

    assert live.mode is RetrievalMode.LIVE
    assert replay.mode is RetrievalMode.CACHE_REPLAY
    assert replay.record == live.record
    assert fake.calls == [
        ("stock_lhb_stock_statistic_em", {"symbol": "近三月"}),
    ]
