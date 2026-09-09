import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from turtle_value_engine.models import Company
from turtle_value_engine.providers import (
    AKShareProvider,
    DataCategory,
    FilesystemRawResponseCache,
    ProviderCapabilityError,
    ProviderNormalizationError,
    ProviderRequest,
    ProviderRequestError,
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

    def stock_financial_hk_report_em(self, **kwargs):
        return self._return(
            "stock_financial_hk_report_em",
            _fixture(
                "h_income_statement.json"
                if kwargs.get("symbol") == "利润表"
                else "h_cash_flow.json"
            ),
            **kwargs,
        )


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
        "cash_flow_statement",
        "company_metadata",
        "income_statement",
        "listing_metadata",
        "market_history",
        "market_quote",
    )
    assert provider.identity.provider_id == "akshare"
    assert provider.identity.provider_version == "3"


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


def test_unsupported_category_is_blocked_before_the_fake_provider_is_called():
    fake = FakeAKShare()
    provider = _provider(fake)

    with pytest.raises(ProviderCapabilityError):
        provider.fetch(_request(DataCategory.BALANCE_SHEET, "SH600000"))
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
