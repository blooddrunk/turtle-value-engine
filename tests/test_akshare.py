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
        "cash_flow_statement",
        "company_metadata",
        "corporate_actions",
        "dividends",
        "income_statement",
        "listing_metadata",
        "market_history",
        "market_quote",
        "ownership_pledge",
        "share_capital",
    )
    assert provider.identity.provider_id == "akshare"
    assert provider.identity.provider_version == "12"
    assert AKSHARE_MAPPING_VERSION == "13"


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
