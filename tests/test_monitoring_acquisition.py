"""Deterministic Phase 6-B acquisition service and mapping tests.

These tests prove the goal's acquisition semantics end-to-end at the
provider-neutral boundary: deny-by-default networking, explicit allow,
deterministic canonicalization and replay, PIT filtering, duplicate and
conflict handling, and the rule that acquisition never advances a committed
cursor.  All source responses come from an injected fake discovery client;
no test touches the network.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from turtle_value_engine.monitoring import (
    MonitoringConflictError,
    MonitoringWorkspace,
    WatchlistEntryV1,
    WatchlistSpecV1,
    build_event_batch,
    run_monitoring,
)
from turtle_value_engine.monitoring.canonical import canonical_json_bytes, to_utc_datetime
from turtle_value_engine.monitoring_acquisition import (
    MAX_LISTINGS_PER_ACQUISITION,
    MAX_WINDOW_DAYS,
    AcquisitionError,
    AcquisitionWindow,
    NetworkDeniedError,
    acquire_filing_events,
    batch_for_events,
    derive_window_start_from_state,
)
from turtle_value_engine.monitoring_acquisition.mapping import (
    FILING_EVENT_CLASSIFICATION,
    classification_rule_for,
    conservative_available_at,
    map_filing_record_to_event,
)
from turtle_value_engine.providers.cache import FilesystemRawResponseCache
from turtle_value_engine.providers.filings import (
    FilingDescriptor,
    FilingDiscoverySourceClient,
    FilingMarket,
    FilingRecord,
    FilingSource,
    OfficialFilingDiscoveryProvider,
    filing_id_for,
)

ADAPTER_VERSION = "filing-discovery-v1+cninfo-disclosure-v1"
UTC = UTC


def _filing(
    listing_id: str,
    document_id: str,
    title: str,
    document_type: str,
    published: date,
    market: FilingMarket = FilingMarket.A,
    source: FilingSource = FilingSource.CNINFO,
    url: str | None = None,
) -> FilingRecord:
    document_url = url or (
        f"https://static.cninfo.com.cn/finalpage/{published.isoformat()}/{document_id}.PDF"
    )
    return FilingRecord(
        filing_id=filing_id_for(
            listing_id=listing_id,
            market=market,
            source=source,
            source_document_id=document_id,
            url=document_url,
        ),
        listing_id=listing_id,
        market=market,
        source=source,
        title=title,
        document_type=document_type,
        published_date=published,
        url=document_url,
        source_document_id=document_id,
        report_period=None,
        issuer_name="示例公司",
    )


class FakeDiscoveryClient:
    """Scripted ``FilingDiscoverySourceClient`` returning frozen descriptors."""

    def __init__(self, results: dict[str, list[FilingDescriptor]] | None = None):
        self.results = results or {}
        self.calls: list[str] = []

    def discover(self, query):
        self.calls.append(query.listing_id)
        if isinstance(self.results.get(query.listing_id), Exception):
            raise self.results[query.listing_id]
        return self.results.get(query.listing_id, [])


def _provider(client: FakeDiscoveryClient) -> OfficialFilingDiscoveryProvider:
    return OfficialFilingDiscoveryProvider(
        {FilingSource.CNINFO: FilingDiscoverySourceClient(
            source=FilingSource.CNINFO,
            source_uri="https://www.cninfo.com.cn/new/hisAnnouncement/query",
            discover=client.discover,
        )},
        provider_version=ADAPTER_VERSION,
    )


def _acquire(client, cache, *, listings=("SH600519",), network_allowed=True,
             offline=False, window=None, as_of=None, limit=30):
    return acquire_filing_events(
        provider=_provider(client),
        listings=list(listings),
        window=window or AcquisitionWindow(date(2026, 4, 10), date(2026, 4, 30)),
        source_id="CNINFO",
        adapter_version=ADAPTER_VERSION,
        cache=cache,
        limit=limit,
        as_of=as_of,
        network_allowed=network_allowed and not offline,
        offline=offline,
    )


class TestNetworkGating:
    def test_deny_by_default_never_touches_the_source_client(self, tmp_path):
        client = FakeDiscoveryClient()
        with pytest.raises(NetworkDeniedError, match="network is denied"):
            _acquire(client, FilesystemRawResponseCache(tmp_path / "c"),
                     network_allowed=False)
        assert client.calls == []

    def test_offline_and_allow_are_mutually_exclusive(self, tmp_path):
        client = FakeDiscoveryClient()
        with pytest.raises(AcquisitionError, match="mutually exclusive"):
            acquire_filing_events(
                provider=_provider(client),
                listings=["SH600519"],
                window=AcquisitionWindow(date(2026, 4, 10), date(2026, 4, 30)),
                source_id="CNINFO",
                adapter_version=ADAPTER_VERSION,
                cache=FilesystemRawResponseCache(tmp_path / "c"),
                network_allowed=True,
                offline=True,
            )
        assert client.calls == []

    def test_offline_replay_calls_no_source_client(self, tmp_path):
        client = FakeDiscoveryClient({
            "SH600519": [FilingDescriptor(
                title="2025年年度报告", document_type="010301",
                published_date=date(2026, 4, 17),
                url="https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF",
                source_document_id="1225114741", issuer_name="贵州茅台",
            )],
        })
        cache = FilesystemRawResponseCache(tmp_path / "c")
        first = _acquire(client, cache)
        assert first.summary.network_allowed is True
        assert client.calls == ["SH600519"]
        client.calls.clear()
        second = _acquire(client, cache, offline=True)
        assert client.calls == []  # replay served entirely from the raw cache
        assert second.batch_id == first.batch_id


class TestCanonicalization:
    def _live(self, tmp_path):
        client = FakeDiscoveryClient({
            "SH600519": [
                FilingDescriptor(
                    title="贵州茅台2025年年度报告", document_type="010301",
                    published_date=date(2026, 4, 17),
                    url="https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF",
                    source_document_id="1225114741", issuer_name="贵州茅台",
                ),
                FilingDescriptor(
                    title="贵州茅台2025年半年度报告", document_type="010303",
                    published_date=date(2026, 4, 18),
                    url="https://static.cninfo.com.cn/finalpage/2026-04-18/9000000001.PDF",
                    source_document_id="9000000001", issuer_name="贵州茅台",
                ),
                FilingDescriptor(
                    title="贵州茅台关于回购股份实施进展的公告", document_type="011513",
                    published_date=date(2026, 4, 19),
                    url="https://static.cninfo.com.cn/finalpage/2026-04-19/9000000002.PDF",
                    source_document_id="9000000002", issuer_name="贵州茅台",
                ),
            ],
        })
        return client, FilesystemRawResponseCache(tmp_path / "c")

    def test_exact_classification_and_provenance(self, tmp_path):
        client, cache = self._live(tmp_path)
        outcome = _acquire(client, cache)
        events = {e.event_id: e for e in outcome.batch.events}
        assert len(events) == 3
        by_source_id = {e.source_event_id: e for e in events.values()}
        assert by_source_id["1225114741"].event_type == "ANNUAL_REPORT"
        assert by_source_id["9000000001"].event_type == "INTERIM_REPORT"
        assert by_source_id["9000000002"].event_type == "INFORMATIONAL_DISCLOSURE"
        for event in events.values():
            assert event.source_id == "CNINFO"
            assert event.source_artifact_id.startswith("filing-")
            assert event.published_at is None

    def test_available_at_is_conservative_end_of_beijing_day(self, tmp_path):
        client, cache = self._live(tmp_path)
        outcome = _acquire(client, cache)
        by_source = {e.source_event_id: e for e in outcome.batch.events}
        # End of the Beijing publication date, expressed in UTC.
        assert by_source["1225114741"].available_at == datetime(
            2026, 4, 17, 15, 59, 59, 999999, tzinfo=UTC
        )
        assert by_source["9000000001"].available_at == datetime(
            2026, 4, 18, 15, 59, 59, 999999, tzinfo=UTC
        )
        assert by_source["9000000002"].available_at == datetime(
            2026, 4, 19, 15, 59, 59, 999999, tzinfo=UTC
        )

    def test_pit_boundary_excludes_future_unavailable_events(self, tmp_path):
        client, cache = self._live(tmp_path)
        outcome = _acquire(client, cache, as_of="2026-04-17T23:59:59Z")
        source_ids = {e.source_event_id for e in outcome.batch.events}
        assert source_ids == {"1225114741"}  # only 2026-04-17 is fully available
        assert outcome.summary.listings[0].deferred_future_count == 2
        assert outcome.summary.as_of == to_utc_datetime("2026-04-17T23:59:59Z")

    def test_no_as_of_keeps_all_events(self, tmp_path):
        client, cache = self._live(tmp_path)
        outcome = _acquire(client, cache)
        assert outcome.summary.listings[0].deferred_future_count == 0
        assert outcome.summary.event_count == 3

    def test_live_and_offline_replay_are_byte_identical(self, tmp_path):
        client, cache = self._live(tmp_path)
        first = _acquire(client, cache)
        live_bytes = canonical_json_bytes(first.batch.model_dump(mode="json"))
        second = _acquire(client, cache, offline=True)
        replay_bytes = canonical_json_bytes(second.batch.model_dump(mode="json"))
        assert live_bytes == replay_bytes
        assert second.summary.listings[0].retrieval_mode == "CACHE_REPLAY"
        assert first.summary.listings[0].retrieval_mode == "LIVE"

    def test_restart_from_persisted_raw_cache_is_deterministic(self, tmp_path):
        client, cache = self._live(tmp_path)
        first = _acquire(client, cache)
        # Simulate a restart: brand-new process objects over the same cache dir.
        fresh_client = FakeDiscoveryClient()
        fresh_cache = FilesystemRawResponseCache(tmp_path / "c")
        second = _acquire(fresh_client, fresh_cache, offline=True)
        assert fresh_client.calls == []
        assert second.batch_id == first.batch_id
        assert second.batch.events == first.batch.events

    def test_raw_cache_artifact_persists_replayable_provenance(self, tmp_path):
        client, cache = self._live(tmp_path)
        outcome = _acquire(client, cache)
        digest = outcome.summary.listings[0].raw_cache_digest
        artifact = (
            tmp_path / "c" / "official-filing-discovery" / "filing_discovery"
            / f"{digest}.json"
        )
        assert artifact.is_file()
        envelope = json.loads(artifact.read_text(encoding="utf-8"))
        assert envelope["provider"]["version"] == ADAPTER_VERSION
        assert envelope["request"]["parameters"]["source"] == "CNINFO"
        assert envelope["raw_payload"]["filings"][0]["filing_id"].startswith("filing-")

    def test_duplicate_same_content_is_idempotent(self, tmp_path):
        filing = _filing("SH600519", "1225114741", "年度报告", "010301", date(2026, 4, 17))
        event, _ = map_filing_record_to_event(filing)
        batch = batch_for_events([event, event.model_copy(deep=True)])
        assert len(batch.events) == 1

    def test_conflicting_duplicate_content_fails_closed(self):
        base = _filing("SH600519", "1225114741", "标题", "010301", date(2026, 4, 17))
        other = _filing(
            "SH600519", "1225114741", "不同的标题", "010301", date(2026, 4, 18)
        )
        first, _ = map_filing_record_to_event(base)
        second, _ = map_filing_record_to_event(other)
        assert first.event_id == second.event_id
        with pytest.raises(MonitoringConflictError, match="EVENT_CONFLICT"):
            batch_for_events([first, second])

    def test_provider_rejects_duplicate_filing_identity_outright(self, tmp_path):
        client = FakeDiscoveryClient({
            "SH600519": [
                FilingDescriptor(
                    title="年度报告", document_type="010301",
                    published_date=date(2026, 4, 17),
                    url="https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF",
                    source_document_id="1225114741",
                ),
                FilingDescriptor(
                    title="年度报告摘要", document_type="010301",
                    published_date=date(2026, 4, 17),
                    url="https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF",
                    source_document_id="1225114741",
                ),
            ],
        })
        with pytest.raises(AcquisitionError):
            _acquire(client, FilesystemRawResponseCache(tmp_path / "c"))

    def test_canonical_ordering_independent_of_source_row_order(self, tmp_path):
        descriptors = [
            FilingDescriptor(
                title=f"公告{index}", document_type="012399",
                published_date=date(2026, 4, 10 + index % 5),
                url=f"https://static.cninfo.com.cn/finalpage/2026-04-10/700000000{index}.PDF",
                source_document_id=f"700000000{index}",
            )
            for index in range(5)
        ]
        forward = FakeDiscoveryClient({"SH600519": descriptors})
        backward = FakeDiscoveryClient({"SH600519": list(reversed(descriptors))})
        first = _acquire(forward, FilesystemRawResponseCache(tmp_path / "a"))
        second = _acquire(backward, FilesystemRawResponseCache(tmp_path / "b"))
        assert first.batch_id == second.batch_id
        assert [e.event_id for e in first.batch.events] == [
            e.event_id for e in second.batch.events
        ]


class TestScopeAndBounds:
    def test_window_cannot_exceed_the_hard_cap(self):
        with pytest.raises(AcquisitionError, match="maximum is"):
            AcquisitionWindow(date(2024, 1, 1), date(2026, 4, 30))

    def test_window_from_after_to_rejected(self):
        with pytest.raises(AcquisitionError, match="after published_to"):
            AcquisitionWindow(date(2026, 5, 1), date(2026, 4, 30))

    def test_max_window_days_boundary_is_accepted(self):
        window = AcquisitionWindow(
            date(2025, 4, 30), date(2025, 4, 30) + timedelta(days=MAX_WINDOW_DAYS - 1)
        )
        assert window.published_to > window.published_from

    def test_too_many_listings_rejected(self, tmp_path):
        listings = [f"SH6005{i:02d}" for i in range(MAX_LISTINGS_PER_ACQUISITION + 1)]
        with pytest.raises(AcquisitionError, match="listings may be acquired"):
            _acquire(FakeDiscoveryClient(), FilesystemRawResponseCache(tmp_path / "c"),
                     listings=listings)

    def test_duplicate_listings_rejected(self, tmp_path):
        with pytest.raises(AcquisitionError, match="duplicate listing"):
            _acquire(FakeDiscoveryClient(), FilesystemRawResponseCache(tmp_path / "c"),
                     listings=["SH600519", "SH600519"])

    def test_empty_listing_scope_rejected(self, tmp_path):
        with pytest.raises(AcquisitionError, match="at least one listing"):
            _acquire(FakeDiscoveryClient(), FilesystemRawResponseCache(tmp_path / "c"),
                     listings=[])

    def test_unsupported_source_rejected(self, tmp_path):
        with pytest.raises(AcquisitionError, match="only the CNINFO"):
            acquire_filing_events(
                provider=_provider(FakeDiscoveryClient()),
                listings=["SH600519"],
                window=AcquisitionWindow(date(2026, 4, 10), date(2026, 4, 30)),
                source_id="AKSHARE",
                adapter_version=ADAPTER_VERSION,
                cache=FilesystemRawResponseCache(tmp_path / "c"),
                network_allowed=True,
            )

    def test_hk_listing_rejected_by_query_contract(self, tmp_path):
        with pytest.raises(AcquisitionError, match="invalid acquisition scope"):
            _acquire(FakeDiscoveryClient(), FilesystemRawResponseCache(tmp_path / "c"),
                     listings=["HK00288"])

    def test_limit_must_be_positive(self, tmp_path):
        with pytest.raises(AcquisitionError, match="positive integer"):
            _acquire(FakeDiscoveryClient(), FilesystemRawResponseCache(tmp_path / "c"),
                     limit=0)

    def test_source_failure_becomes_acquisition_error(self, tmp_path):
        from turtle_value_engine.providers.errors import ProviderResponseError

        client = FakeDiscoveryClient({
            "SH600519": ProviderResponseError("upstream refused"),
        })
        with pytest.raises(AcquisitionError, match="acquisition failed"):
            _acquire(client, FilesystemRawResponseCache(tmp_path / "c"))


class TestCursorIsolation:
    def _watchlist(self, *listing_ids: str) -> WatchlistSpecV1:
        return WatchlistSpecV1.build(
            watchlist_id="integration",
            profile_id="strict-v1",
            entries=[WatchlistEntryV1(listing_id=lid) for lid in listing_ids],
        )

    def _committed_workspace(self, tmp_path, watchlist) -> MonitoringWorkspace:
        workspace = MonitoringWorkspace(tmp_path / "ws")
        empty_batch = build_event_batch([])
        run = run_monitoring(watchlist, empty_batch, None, "2026-01-01T00:00:00Z")
        workspace.commit_run(run, watchlist=watchlist, batch=empty_batch)
        return workspace

    def test_successful_acquisition_does_not_mutate_committed_state(self, tmp_path):
        watchlist = self._watchlist("SH600519", "SZ000858")
        self._committed_workspace(tmp_path, watchlist)
        before = {
            path.relative_to(tmp_path / "ws").as_posix(): path.read_bytes()
            for path in sorted((tmp_path / "ws").rglob("*")) if path.is_file()
        }
        client = FakeDiscoveryClient({
            "SH600519": [FilingDescriptor(
                title="2025年年度报告", document_type="010301",
                published_date=date(2026, 4, 17),
                url="https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF",
                source_document_id="1225114741",
            )],
        })
        outcome = _acquire(client, FilesystemRawResponseCache(tmp_path / "c"),
                           listings=["SH600519", "SZ000858"])
        assert outcome.summary.event_count == 1
        after = {
            path.relative_to(tmp_path / "ws").as_posix(): path.read_bytes()
            for path in sorted((tmp_path / "ws").rglob("*")) if path.is_file()
        }
        assert before == after

    def test_failed_acquisition_does_not_move_cursor(self, tmp_path):
        from turtle_value_engine.providers.errors import ProviderResponseError

        watchlist = self._watchlist("SH600519")
        workspace = self._committed_workspace(tmp_path, watchlist)
        state_before = workspace.load_current_state("integration")
        client = FakeDiscoveryClient({
            "SH600519": ProviderResponseError("upstream refused"),
        })
        with pytest.raises(AcquisitionError, match="acquisition failed"):
            _acquire(client, FilesystemRawResponseCache(tmp_path / "c"))
        assert workspace.load_current_state("integration") == state_before

    def test_cursor_advances_only_after_phase6a_atomic_commit(self, tmp_path):
        watchlist = self._watchlist("SH600519", "SZ000858")
        workspace = self._committed_workspace(tmp_path, watchlist)
        client = FakeDiscoveryClient({
            "SH600519": [
                FilingDescriptor(
                    title="2025年年度报告", document_type="010301",
                    published_date=date(2026, 4, 17),
                    url="https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF",
                    source_document_id="1225114741",
                ),
                FilingDescriptor(
                    title="关于回购股份的公告", document_type="011513",
                    published_date=date(2026, 4, 20),
                    url="https://static.cninfo.com.cn/finalpage/2026-04-20/7000000001.PDF",
                    source_document_id="7000000001",
                ),
            ],
            "SZ000858": [
                FilingDescriptor(
                    title="2026年半年度报告", document_type="010303",
                    published_date=date(2026, 4, 22),
                    url="https://static.cninfo.com.cn/finalpage/2026-04-22/7000000002.PDF",
                    source_document_id="7000000002",
                ),
            ],
        })
        outcome = _acquire(client, FilesystemRawResponseCache(tmp_path / "c"),
                           listings=["SH600519", "SZ000858"])
        # Acquisition alone: no cursor movement.
        assert workspace.load_current_state("integration").entry_for("SH600519").cursors == []
        # Phase 6-A planning + commit moves only the expected cursors.
        run = run_monitoring(watchlist, outcome.batch, workspace.load_current_state("integration"),
                             "2026-06-01T00:00:00Z")
        planned = run.next_state.entry_for("SH600519").cursor_for("CNINFO")
        assert planned is not None
        assert planned.last_processed_available_at == datetime(
            2026, 4, 20, 15, 59, 59, 999999, tzinfo=UTC
        )
        workspace.commit_run(run, watchlist=watchlist, batch=outcome.batch)
        committed = workspace.load_current_state("integration")
        sh = committed.entry_for("SH600519").cursor_for("CNINFO")
        sz = committed.entry_for("SZ000858").cursor_for("CNINFO")
        assert sh.last_processed_available_at == datetime(
            2026, 4, 20, 15, 59, 59, 999999, tzinfo=UTC
        )
        assert sh.advanced_by_run_id == run.run_id
        assert sz is not None and sz.last_processed_available_at == datetime(
            2026, 4, 22, 15, 59, 59, 999999, tzinfo=UTC
        )

    def test_derive_window_start_from_state(self, tmp_path):
        watchlist = self._watchlist("SH600519", "SZ000858")
        workspace = self._committed_workspace(tmp_path, watchlist)
        assert derive_window_start_from_state(
            workspace.load_current_state("integration"), "SH600519", "CNINFO"
        ) is None
        client = FakeDiscoveryClient({
            "SH600519": [FilingDescriptor(
                title="2025年年度报告", document_type="010301",
                published_date=date(2026, 4, 17),
                url="https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF",
                source_document_id="1225114741",
            )],
        })
        outcome = _acquire(client, FilesystemRawResponseCache(tmp_path / "c"),
                           listings=["SH600519"])
        run = run_monitoring(watchlist, outcome.batch,
                             workspace.load_current_state("integration"),
                             "2026-06-01T00:00:00Z")
        workspace.commit_run(run, watchlist=watchlist, batch=outcome.batch)
        state = workspace.load_current_state("integration")
        assert derive_window_start_from_state(state, "SH600519", "CNINFO") == date(2026, 4, 18)
        assert derive_window_start_from_state(state, "SZ000858", "CNINFO") is None
        with pytest.raises(AcquisitionError, match="not present"):
            derive_window_start_from_state(state, "SH601398", "CNINFO")


class TestMappingRules:
    @pytest.mark.parametrize(
        ("document_type", "expected"),
        [
            ("010301", "ANNUAL_REPORT"),
            ("010303", "INTERIM_REPORT"),
            ("010305", "INFORMATIONAL_DISCLOSURE"),
            ("010307", "INFORMATIONAL_DISCLOSURE"),
            ("011513", "INFORMATIONAL_DISCLOSURE"),
            ("012399", "INFORMATIONAL_DISCLOSURE"),
            ("999999", "INFORMATIONAL_DISCLOSURE"),
        ],
    )
    def test_frozen_classification_table(self, document_type, expected):
        filing = _filing("SH600519", "1", "标题", document_type, date(2026, 4, 17))
        event, mapping = map_filing_record_to_event(filing)
        assert event.event_type == expected
        if document_type in {"010301", "010303"}:
            assert mapping.classification_rule == f"CNINFO:{document_type}"
            assert "frozen probe-verified rule" in mapping.classification_basis
        else:
            assert mapping.classification_rule == "unverified:informational"
            assert "fail-closed" in mapping.classification_basis

    def test_table_covers_exactly_two_verified_codes(self):
        assert set(FILING_EVENT_CLASSIFICATION) == {
            (FilingSource.CNINFO, "010301"),
            (FilingSource.CNINFO, "010303"),
        }
        assert classification_rule_for(FilingSource.CNINFO, "010301") == "CNINFO:010301"
        assert classification_rule_for(FilingSource.SSE, "010301") == "unverified:informational"

    def test_no_fabricated_timestamp_precision(self):
        filing = _filing("SH600519", "1", "标题", "010301", date(2026, 4, 17))
        event, _ = map_filing_record_to_event(filing)
        assert event.published_at is None
        assert event.available_at == datetime(2026, 4, 17, 15, 59, 59, 999999, tzinfo=UTC)

    def test_available_at_never_precedes_true_publication_within_the_day(self):
        # Any true instant on the Beijing publication date is <= available_at.
        start = datetime(2026, 4, 17, 0, 0, tzinfo=timezone(timedelta(hours=8)))
        end = datetime(2026, 4, 17, 23, 59, 59, 999999, tzinfo=timezone(timedelta(hours=8)))
        available = conservative_available_at(date(2026, 4, 17), FilingMarket.A)
        assert start.astimezone(UTC) <= available
        assert end.astimezone(UTC) <= available
        next_day_start = datetime(2026, 4, 18, 0, 0, tzinfo=timezone(timedelta(hours=8)))
        assert available < next_day_start.astimezone(UTC)

    def test_long_title_is_deterministically_bounded(self):
        filing = _filing("SH600519", "1", "标" * 500, "012399", date(2026, 4, 17))
        event, _ = map_filing_record_to_event(filing)
        assert len(event.title) == 300
        again, _ = map_filing_record_to_event(filing)
        assert again.title == event.title

    def test_event_identity_depends_only_on_source_identity(self):
        first = _filing("SH600519", "1225114741", "标题", "010301", date(2026, 4, 17))
        second = _filing("SH600519", "1225114741", "改期标题", "010301", date(2026, 4, 18))
        e1, _ = map_filing_record_to_event(first)
        e2, _ = map_filing_record_to_event(second)
        assert e1.event_id == e2.event_id  # identity is source-scoped, content-hashed

    def test_h_share_market_uses_same_conservative_calendar(self):
        h_filing = _filing(
            "HK00288", "hk-1", "年報", "010301", date(2026, 4, 17),
            market=FilingMarket.H, source=FilingSource.HKEXNEWS,
            url="https://www.hkexnews.hk/listedco/listconews/2026/0417/hk-1.pdf",
        )
        event, _ = map_filing_record_to_event(h_filing)
        assert event.available_at == datetime(2026, 4, 17, 15, 59, 59, 999999, tzinfo=UTC)
