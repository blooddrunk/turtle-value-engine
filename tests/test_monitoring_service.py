"""Deterministic Phase 6-A monitoring planning tests (service layer)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from turtle_value_engine.monitoring import (
    EVENT_IMPACT_POLICY_ID,
    ImpactClass,
    MonitoringConflictError,
    MonitoringError,
    WatchlistSpecV1,
    build_event_batch,
    combine_impacts,
    initial_watchlist_state,
    run_monitoring,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "monitoring"
AS_OF = "2026-06-01T00:00:00Z"

FORBIDDEN_IMPORT_TOKENS = (
    "requests",
    "urllib",
    "httpx",
    "socket",
    "AnalystClient",
    "ResearchOrchestrator",
    "run_analyze",
    "cloudflare",
    "wrangler",
    "boto3",
    "openai",
    "brokerage",
)


def _watchlist() -> WatchlistSpecV1:
    payload = json.loads((FIXTURES / "watchlist-basic.json").read_text(encoding="utf-8"))
    return WatchlistSpecV1.build(**payload)


def _event(event_id: str, **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "listing_id": "600519.SH",
        "event_type": "INFORMATIONAL_DISCLOSURE",
        "source_id": "cninfo",
        "source_event_id": f"cninfo:{event_id}",
        "available_at": "2026-04-01T08:00:00Z",
    }
    payload.update(overrides)
    return payload


def _events_payload() -> list:
    return json.loads((FIXTURES / "events-basic.json").read_text(encoding="utf-8"))


class TestCanonicalPlanning:
    def test_out_of_order_input_yields_identical_run(self):
        watchlist = _watchlist()
        batch = build_event_batch(_events_payload())
        reversed_batch = build_event_batch(list(reversed(_events_payload())))
        first = run_monitoring(watchlist, batch, None, AS_OF)
        second = run_monitoring(watchlist, reversed_batch, None, AS_OF)
        assert first.run_id == second.run_id
        assert first.canonical_bytes() == second.canonical_bytes()

    def test_same_inputs_produce_byte_identical_run(self):
        watchlist = _watchlist()
        batch = build_event_batch(_events_payload())
        first = run_monitoring(watchlist, batch, None, AS_OF)
        second = run_monitoring(watchlist, batch, None, AS_OF)
        assert first.canonical_bytes() == second.canonical_bytes()
        assert first.plan.plan_id == second.plan.plan_id
        assert first.next_state.state_id == second.next_state.state_id

    def test_fixture_run_decisions_and_requests(self):
        watchlist = _watchlist()
        batch = build_event_batch(_events_payload())
        run = run_monitoring(watchlist, batch, None, AS_OF)
        decisions = {decision.event_id: str(decision.impact) for decision in run.decisions}
        assert decisions == {
            "cninfo-600519-2025-annual": "FULL_REANALYSIS",
            "cninfo-600519-2026-penalty": "URGENT_MANUAL_REVIEW",
            "hkex-00288-2026-interim": "PARTIAL_REANALYSIS",
        }
        requests = {
            request.listing_id: (str(request.impact), list(request.event_ids))
            for request in run.plan.requests
        }
        assert requests["600519.SH"] == (
            "URGENT_MANUAL_REVIEW",
            ["cninfo-600519-2025-annual", "cninfo-600519-2026-penalty"],
        )
        assert requests["HK00288"] == ("PARTIAL_REANALYSIS", ["hkex-00288-2026-interim"])
        assert "000001.SZ" not in requests


class TestSeverityPrecedence:
    def test_combine_impacts_ordering(self):
        assert combine_impacts([ImpactClass.NO_REANALYSIS]) is ImpactClass.NO_REANALYSIS
        assert (
            combine_impacts(
                [ImpactClass.NO_REANALYSIS, ImpactClass.PARTIAL_REANALYSIS]
            )
            is ImpactClass.PARTIAL_REANALYSIS
        )
        assert (
            combine_impacts(
                [ImpactClass.PARTIAL_REANALYSIS, ImpactClass.FULL_REANALYSIS]
            )
            is ImpactClass.FULL_REANALYSIS
        )
        assert (
            combine_impacts(
                [ImpactClass.FULL_REANALYSIS, ImpactClass.URGENT_MANUAL_REVIEW]
            )
            is ImpactClass.URGENT_MANUAL_REVIEW
        )


class TestPointInTime:
    def test_future_events_are_deferred_without_cursor_advance(self):
        watchlist = _watchlist()
        batch = build_event_batch([_event("future", available_at="2026-12-01T00:00:00Z")])
        run = run_monitoring(watchlist, batch, None, AS_OF)
        assert [record.event_id for record in run.deferred] == ["future"]
        assert run.decisions == []
        assert run.plan.requests == []
        entry = run.next_state.entry_for("600519.SH")
        assert entry is not None and entry.cursors == []
        assert entry.processed_events == []

    def test_boundary_is_inclusive(self):
        watchlist = _watchlist()
        batch = build_event_batch([_event("edge", available_at=AS_OF)])
        run = run_monitoring(watchlist, batch, None, AS_OF)
        assert [decision.event_id for decision in run.decisions] == ["edge"]

    def test_prior_state_from_other_watchlist_is_rejected(self):
        watchlist = _watchlist()
        other = WatchlistSpecV1.build(
            watchlist_id="other",
            profile_id="strict-v1",
            entries=[{"listing_id": "600519.SH"}],
        )
        batch = build_event_batch([_event("e")])
        with pytest.raises(MonitoringError, match="belongs to watchlist"):
            run_monitoring(watchlist, batch, initial_watchlist_state(other), AS_OF)


class TestDuplicatesAndConflicts:
    def test_identical_duplicate_events_are_idempotent(self):
        watchlist = _watchlist()
        batch = build_event_batch([_event("dup"), _event("dup")])
        run = run_monitoring(watchlist, batch, None, AS_OF)
        assert len(run.decisions) == 1
        assert len(run.next_state.entry_for("600519.SH").processed_events) == 1

    def test_same_event_id_with_changed_content_fails_closed(self):
        with pytest.raises(MonitoringConflictError, match="EVENT_CONFLICT"):
            build_event_batch(
                [_event("dup"), _event("dup", available_at="2026-04-02T08:00:00Z")]
            )

    def test_same_event_id_with_changed_content_against_state_fails_closed(self):
        watchlist = _watchlist()
        first = run_monitoring(
            watchlist, build_event_batch([_event("dup")]), None, AS_OF
        )
        state = first.next_state
        conflicting = build_event_batch(
            [_event("dup", available_at="2026-04-02T08:00:00Z")]
        )
        with pytest.raises(MonitoringConflictError, match="EVENT_CONFLICT"):
            run_monitoring(watchlist, conflicting, state, AS_OF)

    def test_already_processed_events_create_no_duplicate_request(self):
        watchlist = _watchlist()
        batch = build_event_batch([_event("once")])
        first = run_monitoring(watchlist, batch, None, AS_OF)
        second = run_monitoring(watchlist, batch, first.next_state, AS_OF)
        assert second.decisions == []
        assert second.plan.requests == []
        assert [record.reason.value for record in second.skipped] == ["ALREADY_PROCESSED"]
        assert second.next_state.state_id == first.next_state.state_id

    def test_stale_late_arrivals_are_skipped_without_cursor_move(self):
        watchlist = _watchlist()
        early = run_monitoring(
            watchlist,
            build_event_batch([_event("late", available_at="2026-04-05T08:00:00Z")]),
            None,
            AS_OF,
        )
        cursor = early.next_state.entry_for("600519.SH").cursor_for("cninfo")
        assert cursor is not None
        assert cursor.last_processed_available_at.isoformat().startswith("2026-04-05")
        late = run_monitoring(
            watchlist,
            build_event_batch([_event("older", available_at="2026-04-01T08:00:00Z")]),
            early.next_state,
            AS_OF,
        )
        assert [record.reason.value for record in late.skipped] == ["STALE"]
        assert late.decisions == []
        assert late.plan.requests == []
        after = late.next_state.entry_for("600519.SH").cursor_for("cninfo")
        assert after.last_processed_available_at == cursor.last_processed_available_at
        assert after.advanced_by_run_id == cursor.advanced_by_run_id


class TestExclusions:
    def test_out_of_watchlist_listing_is_reported_not_applied(self):
        watchlist = _watchlist()
        batch = build_event_batch([_event("outside", listing_id="00700.HK")])
        run = run_monitoring(watchlist, batch, None, AS_OF)
        assert [(record.event_id, record.reason.value) for record in run.excluded] == [
            ("outside", "OUT_OF_WATCHLIST")
        ]
        assert run.decisions == []
        assert run.next_state.entry_for("00700.HK") is None

    def test_disabled_listing_is_reported_not_applied(self):
        watchlist = _watchlist()
        batch = build_event_batch([_event("off", listing_id="000001.SZ")])
        run = run_monitoring(watchlist, batch, None, AS_OF)
        assert [(record.event_id, record.reason.value) for record in run.excluded] == [
            ("off", "LISTING_DISABLED")
        ]
        entry = run.next_state.entry_for("000001.SZ")
        assert entry is not None and entry.processed_events == []


class TestCursors:
    def test_cursor_advances_to_max_processed_availability_per_source(self):
        watchlist = _watchlist()
        batch = build_event_batch(
            [
                _event("a", available_at="2026-04-01T08:00:00Z"),
                _event("b", available_at="2026-05-01T08:00:00Z"),
                _event(
                    "h",
                    listing_id="HK00288",
                    source_id="hkexnews",
                    available_at="2026-04-15T08:00:00Z",
                ),
            ]
        )
        run = run_monitoring(watchlist, batch, None, AS_OF)
        cninfo = run.next_state.entry_for("600519.SH").cursor_for("cninfo")
        assert cninfo is not None
        assert cninfo.last_processed_available_at.isoformat().startswith("2026-05-01")
        assert cninfo.last_event_id == "b"
        assert cninfo.advanced_by_run_id == run.run_id
        hkex = run.next_state.entry_for("HK00288").cursor_for("hkexnews")
        assert hkex is not None
        assert hkex.advanced_by_run_id == run.run_id

    def test_state_grows_across_runs_with_processed_records(self):
        watchlist = _watchlist()
        first = run_monitoring(
            watchlist, build_event_batch([_event("one")]), None, AS_OF
        )
        second = run_monitoring(
            watchlist,
            build_event_batch([_event("two", available_at="2026-04-03T08:00:00Z")]),
            first.next_state,
            AS_OF,
        )
        entry = second.next_state.entry_for("600519.SH")
        assert [record.event_id for record in entry.processed_events] == ["one", "two"]
        assert second.next_state.last_committed_run_id == second.run_id


class TestNoHiddenRuntimes:
    def _import_lines(self, text: str) -> list[str]:
        return [
            line.strip()
            for line in text.splitlines()
            if line.strip().startswith(("import ", "from "))
        ]

    def test_monitoring_imports_only_stdlib_pydantic_and_itself(self):
        package = ROOT / "src" / "turtle_value_engine" / "monitoring"
        sources = list(package.glob("*.py"))
        assert len(sources) >= 5
        for source in sources:
            imports = self._import_lines(source.read_text(encoding="utf-8"))
            assert imports, source.name
            for line in imports:
                assert "turtle_value_engine" not in line, (
                    f"{source.name} imports outside the monitoring package: {line}"
                )
                for token in FORBIDDEN_IMPORT_TOKENS:
                    assert token not in line, f"{token!r} imported by {source.name}"

    def test_importing_monitoring_adds_no_engine_runtime_modules(self):
        code = (
            "import sys\n"
            "import turtle_value_engine\n"  # root package init is unavoidable
            "before = set(sys.modules)\n"
            "import turtle_value_engine.monitoring\n"
            "import turtle_value_engine.monitoring.service\n"
            "import turtle_value_engine.monitoring.workspace\n"
            "added = sorted(set(sys.modules) - before)\n"
            "print('\\n'.join(added))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(ROOT),
        )
        added = [line for line in result.stdout.strip().splitlines() if line]
        assert added
        assert all(
            module.startswith("turtle_value_engine.monitoring") for module in added
        ), added

    def test_policy_module_is_isolated_from_strict_v1(self):
        from turtle_value_engine.monitoring import policy

        imports = self._import_lines(Path(policy.__file__).read_text(encoding="utf-8"))
        for line in imports:
            assert "turtle_value_engine" not in line, line
            assert "config" not in line, line
        assert EVENT_IMPACT_POLICY_ID == "event-impact-v1"
