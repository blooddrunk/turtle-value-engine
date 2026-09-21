"""Deterministic Phase 6-A monitoring contract tests (models/policy)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from turtle_value_engine.monitoring import (
    EVENT_IMPACT_POLICY_ID,
    CanonicalEventType,
    ImpactClass,
    MonitoringEventBatchV1,
    MonitoringEventV1,
    UnknownEventTypeError,
    WatchlistSpecV1,
    build_event_batch,
    event_impact_mapping,
    event_type_catalog,
    impact_for_event_type,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "monitoring"


def _basic_watchlist_payload() -> dict:
    return json.loads((FIXTURES / "watchlist-basic.json").read_text(encoding="utf-8"))


def _basic_events_payload() -> list:
    return json.loads((FIXTURES / "events-basic.json").read_text(encoding="utf-8"))


def _event_payload(**overrides) -> dict:
    payload = {
        "event_id": "evt-1",
        "listing_id": "600519.SH",
        "event_type": "ANNUAL_REPORT",
        "source_id": "cninfo",
        "source_event_id": "cninfo:1",
        "available_at": "2026-03-28T16:00:00+08:00",
    }
    payload.update(overrides)
    return payload


def _validate_schema(filename: str, value) -> None:
    schema = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(
        value.model_dump(mode="json", warnings=False)
    )


class TestWatchlistSpec:
    def test_fixture_validates_and_carries_stable_hash(self):
        watchlist = WatchlistSpecV1.build(**_basic_watchlist_payload())
        assert watchlist.watchlist_id == "personal-core"
        assert watchlist.profile_id == "strict-v1"
        assert [entry.listing_id for entry in watchlist.entries] == [
            "600519.SH",
            "HK00288",
            "000001.SZ",
        ]
        again = WatchlistSpecV1.build(**_basic_watchlist_payload())
        assert again.content_sha256 == watchlist.content_sha256
        _validate_schema("watchlist-spec.schema.json", watchlist)

    def test_duplicate_listing_identity_is_rejected(self):
        payload = json.loads(
            (FIXTURES / "watchlist-invalid-duplicate.json").read_text(encoding="utf-8")
        )
        with pytest.raises(ValidationError, match="duplicate watchlist listing_id"):
            WatchlistSpecV1.build(**payload)

    def test_unknown_top_level_fields_are_rejected(self):
        payload = _basic_watchlist_payload() | {"surprise": 1}
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            WatchlistSpecV1.build(**payload)

    def test_content_change_changes_hash(self):
        payload = _basic_watchlist_payload()
        first = WatchlistSpecV1.build(**payload)
        payload["entries"][0]["company_display_name"] = "另一个名字"
        second = WatchlistSpecV1.build(**payload)
        assert first.content_sha256 != second.content_sha256

    def test_tampered_hash_fails_closed(self):
        watchlist = WatchlistSpecV1.build(**_basic_watchlist_payload())
        payload = watchlist.model_dump(mode="json")
        payload["profile_id"] = "other-profile-v1"
        with pytest.raises(ValidationError, match="content_sha256 does not match"):
            WatchlistSpecV1.model_validate(payload)


class TestMonitoringEvent:
    def test_event_builds_with_canonical_hash(self):
        event = MonitoringEventV1.build(**_event_payload())
        assert event.event_type is CanonicalEventType.ANNUAL_REPORT
        _validate_schema("monitoring-event.schema.json", event)

    def test_missing_provenance_reference_is_rejected(self):
        with pytest.raises(ValidationError, match="auditable source reference"):
            MonitoringEventV1.build(**_event_payload(source_event_id=None))

    def test_missing_source_identity_is_rejected(self):
        with pytest.raises(ValidationError):
            MonitoringEventV1.build(**_event_payload(source_id=""))

    def test_unknown_event_type_is_rejected_not_coerced(self):
        with pytest.raises(ValidationError, match="event_type"):
            MonitoringEventV1.build(**_event_payload(event_type="WAT"))

    def test_unknown_event_type_has_no_harmless_policy_mapping(self):
        with pytest.raises(UnknownEventTypeError, match="no event-impact-v1 mapping"):
            impact_for_event_type("WAT")
        with pytest.raises(UnknownEventTypeError, match="unknown event impact policy"):
            impact_for_event_type("ANNUAL_REPORT", policy_id="strict-v1")

    def test_bounded_title_and_summary(self):
        with pytest.raises(ValidationError):
            MonitoringEventV1.build(**_event_payload(title="x" * 301))
        with pytest.raises(ValidationError):
            MonitoringEventV1.build(**_event_payload(summary="y" * 2001))

    def test_datetime_normalization_is_utc_deterministic(self):
        offset = MonitoringEventV1.build(**_event_payload())
        naive = MonitoringEventV1.build(**_event_payload(available_at="2026-03-28T08:00:00"))
        zulu = MonitoringEventV1.build(**_event_payload(available_at="2026-03-28T08:00:00Z"))
        assert offset.content_sha256 == naive.content_sha256 == zulu.content_sha256

    def test_changed_semantic_content_changes_event_hash(self):
        first = MonitoringEventV1.build(**_event_payload())
        second = MonitoringEventV1.build(**_event_payload(title="年度报告"))
        assert first.content_sha256 != second.content_sha256


class TestEventBatch:
    def test_fixture_batch_has_stable_identity(self):
        batch = build_event_batch(_basic_events_payload())
        again = build_event_batch(list(reversed(_basic_events_payload())))
        assert batch.batch_id == again.batch_id
        assert batch.content_sha256 == batch.batch_id
        _validate_schema("monitoring-event-batch.schema.json", batch)

    def test_exact_duplicates_collapse(self):
        payload = _event_payload()
        batch = build_event_batch([payload, dict(payload)])
        assert len(batch.events) == 1

    def test_conflicting_duplicates_fail_closed(self):
        from turtle_value_engine.monitoring import MonitoringConflictError

        with pytest.raises(MonitoringConflictError, match="EVENT_CONFLICT"):
            build_event_batch(
                [_event_payload(), _event_payload(available_at="2026-03-29T08:00:00Z")]
            )

    def test_out_of_order_input_is_canonicalized(self):
        payloads = [_event_payload(event_id=f"e{i}") for i in range(5)]
        forward = build_event_batch(payloads)
        backward = build_event_batch(list(reversed(payloads)))
        assert forward.batch_id == backward.batch_id
        keys = [event.canonical_sort_key() for event in forward.events]
        assert keys == sorted(keys)

    def test_hand_written_unordered_batch_is_rejected(self):
        payloads = [
            _event_payload(event_id="b", available_at="2026-04-01T08:00:00Z"),
            _event_payload(event_id="a", available_at="2026-03-01T08:00:00Z"),
        ]
        events = [MonitoringEventV1.build(**payload) for payload in payloads]
        with pytest.raises(ValidationError, match="canonical order"):
            MonitoringEventBatchV1.model_validate(
                {
                    "batch_id": "0" * 64,
                    "content_sha256": "0" * 64,
                    "events": [event.model_dump(mode="json") for event in events],
                }
            )


class TestEventImpactPolicy:
    def test_exact_frozen_mapping(self):
        expected = {
            "INFORMATIONAL_DISCLOSURE": "NO_REANALYSIS",
            "INTERIM_REPORT": "PARTIAL_REANALYSIS",
            "EARNINGS_PREANNOUNCEMENT": "PARTIAL_REANALYSIS",
            "DIVIDEND_POLICY_CHANGE": "PARTIAL_REANALYSIS",
            "DIVIDEND_DECLARATION": "PARTIAL_REANALYSIS",
            "BUYBACK": "PARTIAL_REANALYSIS",
            "ANNUAL_REPORT": "FULL_REANALYSIS",
            "SHARE_ISSUANCE": "FULL_REANALYSIS",
            "MAJOR_ACQUISITION": "FULL_REANALYSIS",
            "MAJOR_DISPOSAL": "FULL_REANALYSIS",
            "AUDIT_OPINION_CHANGE": "URGENT_MANUAL_REVIEW",
            "REGULATORY_PENALTY": "URGENT_MANUAL_REVIEW",
            "CONTROLLING_SHAREHOLDER_EVENT": "URGENT_MANUAL_REVIEW",
            "MATERIAL_LITIGATION": "URGENT_MANUAL_REVIEW",
            "PROFIT_WARNING": "URGENT_MANUAL_REVIEW",
            "TRADING_SUSPENSION": "URGENT_MANUAL_REVIEW",
        }
        mapping = event_impact_mapping()
        assert {key: str(value) for key, value in mapping.items()} == expected
        assert set(mapping) == set(event_type_catalog()) == {
            member.value for member in CanonicalEventType
        }

    def test_policy_is_versioned_and_monitoring_scoped(self):
        assert EVENT_IMPACT_POLICY_ID == "event-impact-v1"
        assert ImpactClass.NO_REANALYSIS.value == "NO_REANALYSIS"


class TestSchemaDrift:
    @pytest.mark.parametrize(
        ("filename", "factory"),
        [
            ("watchlist-spec.schema.json", lambda: WatchlistSpecV1.build(
                **_basic_watchlist_payload()
            )),
            ("monitoring-event.schema.json", lambda: MonitoringEventV1.build(
                **_event_payload()
            )),
            ("monitoring-event-batch.schema.json", lambda: build_event_batch(
                _basic_events_payload()
            )),
        ],
    )
    def test_checked_in_schema_matches_model(self, filename, factory):
        model = factory()
        checked_in = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
        assert model.__class__.model_json_schema() == checked_in
