import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from turtle_value_engine.providers import (
    CacheCorruptionError,
    CacheKey,
    CacheMissError,
    CacheWriteError,
    DataCategory,
    FilesystemRawResponseCache,
    ProviderCapabilities,
    ProviderCapabilityError,
    ProviderIdentity,
    ProviderRequest,
    ProviderRequestError,
    RawProviderRecord,
    StructuredDataProvider,
    deterministic_id,
    fetch_with_cache,
)

IDENTITY = ProviderIdentity(
    provider_id="test-provider",
    provider_version="adapter-1",
    source_name="Synthetic structured source",
)


def _request(
    *,
    category: DataCategory = DataCategory.MARKET_QUOTE,
    entity_id: str = "SH600000",
    parameters: dict | None = None,
) -> ProviderRequest:
    return ProviderRequest(
        category=category,
        entity_id=entity_id,
        parameters={} if parameters is None else parameters,
    )


def _record(
    request: ProviderRequest | None = None,
    *,
    payload: object = None,
    retrieved_at: datetime | None = None,
) -> RawProviderRecord:
    return RawProviderRecord(
        provider=IDENTITY,
        request=request or _request(),
        retrieved_at=retrieved_at or datetime(2026, 9, 9, 2, 0, tzinfo=UTC),
        raw_payload=payload,
        source_uri="https://structured.example.test/quote",
        response_metadata={"status_code": 200},
    )


class StubProvider(StructuredDataProvider):
    def __init__(self, record: RawProviderRecord | None = None, error: Exception | None = None):
        self.record = record
        self.error = error
        self.calls = 0

    @property
    def identity(self) -> ProviderIdentity:
        return IDENTITY

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities({DataCategory.MARKET_QUOTE})

    def fetch_raw(self, request: ProviderRequest) -> RawProviderRecord:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.record is not None
        return self.record


def test_filesystem_cache_round_trip_preserves_raw_record(tmp_path: Path):
    cache = FilesystemRawResponseCache(tmp_path)
    record = _record(payload={"upstream_column": None, "price": 12.5})
    key = CacheKey.from_record(record)

    cache.write(record)
    loaded = cache.read(key)

    assert loaded == record
    assert loaded is not None
    assert loaded.provider == IDENTITY
    assert loaded.request.entity_id == "SH600000"
    assert loaded.retrieved_at == record.retrieved_at
    assert loaded.raw_payload == {"upstream_column": None, "price": 12.5}
    assert cache.path_for(key).is_file()


def test_cache_key_is_stable_for_parameter_order_and_separates_identity():
    first = CacheKey(
        provider="test-provider",
        provider_version="adapter-1",
        category="market_history",
        entity_id="SH600000",
        parameters={"period": "FY2025", "fields": {"b": 2, "a": 1}},
    )
    second = CacheKey(
        provider="test-provider",
        provider_version="adapter-1",
        category="market_history",
        entity_id="SH600000",
        parameters={"fields": {"a": 1, "b": 2}, "period": "FY2025"},
    )

    assert first.digest == second.digest
    assert first.relative_path == second.relative_path
    assert first.digest != CacheKey(
        provider="other-provider",
        provider_version="adapter-1",
        category="market_history",
        entity_id="SH600000",
    ).digest
    assert first.digest != CacheKey(
        provider="test-provider",
        provider_version="adapter-1",
        category="market_history",
        entity_id="HK000000",
    ).digest
    equivalent_request = _request(
        category="market_history",
        parameters={"fields": {"a": 1, "b": 2}, "period": "FY2025"},
    )
    assert first.digest == CacheKey.from_request(IDENTITY, equivalent_request).digest


def test_deterministic_ids_ignore_mapping_order_and_use_explicit_namespaces():
    first = deterministic_id("fact", "SH600000", "reported_cfo", "FY2025", {"b": 2, "a": 1})
    second = deterministic_id("fact", "SH600000", "reported_cfo", "FY2025", {"a": 1, "b": 2})

    assert first == second
    assert first.startswith("fact-")
    assert first != deterministic_id("evidence", "SH600000", "reported_cfo", "FY2025")


def test_provider_capabilities_are_discoverable_and_block_unsupported_fetches():
    provider = StubProvider(record=_record())

    assert provider.capabilities.supports(DataCategory.MARKET_QUOTE)
    assert not provider.capabilities.supports(DataCategory.BALANCE_SHEET)
    with pytest.raises(ProviderCapabilityError):
        provider.fetch_category(DataCategory.BALANCE_SHEET, "SH600000")
    assert provider.calls == 0


def test_corrupt_and_incomplete_cache_entries_are_explicit_errors(tmp_path: Path):
    cache = FilesystemRawResponseCache(tmp_path)
    record = _record(payload={"price": 12.5})
    key = CacheKey.from_record(record)
    cache.write(record)
    path = cache.path_for(key)

    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(CacheCorruptionError):
        cache.read(key)

    path.write_text(
        json.dumps(
            {
                "cache_format_version": 1,
                "provider": IDENTITY.as_dict(),
                "request": _request().as_dict(),
                "retrieved_at": "2026-09-09T02:00:00Z",
                "source_uri": None,
                "response_metadata": {},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CacheCorruptionError, match="raw_payload"):
        cache.read(key)


def test_provider_failure_does_not_create_or_replace_a_snapshot(tmp_path: Path):
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request()
    good_record = _record(request, payload={"price": 10})
    cache.write(good_record)
    key = CacheKey.from_record(good_record)
    before = cache.path_for(key).read_bytes()
    provider = StubProvider(error=RuntimeError("upstream unavailable"))

    with pytest.raises(ProviderRequestError):
        fetch_with_cache(provider, request, cache)

    assert cache.path_for(key).read_bytes() == before


def test_cache_replace_failure_preserves_previous_snapshot(monkeypatch, tmp_path: Path):
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request()
    original = _record(request, payload={"price": 10})
    replacement = _record(request, payload={"price": 11})
    key = CacheKey.from_record(original)
    cache.write(original)
    before = cache.path_for(key).read_bytes()

    def fail_replace(source: str | Path, destination: str | Path) -> None:
        raise OSError("simulated atomic replace failure")

    monkeypatch.setattr("turtle_value_engine.providers.cache.os.replace", fail_replace)
    with pytest.raises(CacheWriteError):
        cache.write(replacement)

    assert cache.path_for(key).read_bytes() == before


def test_offline_replay_never_calls_provider_and_requires_a_cache_entry(tmp_path: Path):
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request()
    record = _record(request, payload={"price": 10})
    cache.write(record)
    provider = StubProvider(error=RuntimeError("network must not be used"))

    replay = fetch_with_cache(provider, request, cache, offline=True)

    assert replay.mode == "CACHE_REPLAY"
    assert replay.record == record
    assert provider.calls == 0

    with pytest.raises(CacheMissError):
        fetch_with_cache(provider, _request(entity_id="SH600001"), cache, offline=True)


def test_missing_raw_data_remains_null_in_cache_and_is_not_zero(tmp_path: Path):
    cache = FilesystemRawResponseCache(tmp_path)
    record = _record(payload={"reported_cfo": None})

    cache.write(record)
    loaded = cache.read(CacheKey.from_record(record))

    assert loaded is not None
    assert loaded.raw_payload["reported_cfo"] is None
    assert loaded.raw_payload["reported_cfo"] != 0


def test_stale_provider_failure_fallback_is_explicit(tmp_path: Path):
    cache = FilesystemRawResponseCache(tmp_path)
    request = _request()
    record = _record(
        request,
        payload={"price": 10},
        retrieved_at=datetime.now(UTC) - timedelta(days=3),
    )
    cache.write(record)
    provider = StubProvider(error=RuntimeError("quota exceeded"))

    replay = fetch_with_cache(
        provider,
        request,
        cache,
        max_age=timedelta(days=1),
        allow_stale=True,
    )

    assert replay.mode == "STALE_CACHE_REPLAY"
    assert replay.record == record
