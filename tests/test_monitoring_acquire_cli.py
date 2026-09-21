"""Deterministic Phase 6-B acquire-events CLI tests.

All tests run against an injected scripted CNINFO source client; sockets are
never needed.  The suite proves the network permission boundary, the offline
replay path, scope validation and the end-to-end integration with the frozen
Phase 6-A replay/status commands.
"""

from __future__ import annotations

import json
import socket
from datetime import date
from pathlib import Path

import pytest

from turtle_value_engine.cli import main
from turtle_value_engine.monitoring.canonical import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[1]

ADAPTER_VERSION = "filing-discovery-v1+cninfo-disclosure-v1"


class ScriptedSource:
    """Replaces the live CNINFO client factory inside the CLI process."""

    installed = False

    def __init__(self, results: dict[str, list[dict]] | None = None):
        self.results = results or {}
        self.discover_calls: list[str] = []

    def factory(self, transport):  # noqa: ARG002 - transport must stay unused
        from turtle_value_engine.providers.filings import (
            FilingDiscoverySourceClient,
            FilingSource,
        )

        def discover(query):
            self.discover_calls.append(query.listing_id)
            rows = self.results.get(query.listing_id, [])
            from turtle_value_engine.providers.filings import FilingDescriptor

            in_window = [
                row
                for row in rows
                if (query.published_from is None
                    or date.fromisoformat(row["published_date"]) >= query.published_from)
                and (query.published_to is None
                    or date.fromisoformat(row["published_date"]) <= query.published_to)
            ]
            return [FilingDescriptor.model_validate(row) for row in in_window]

        return FilingDiscoverySourceClient(
            source=FilingSource.CNINFO,
            source_uri="https://www.cninfo.com.cn/new/hisAnnouncement/query",
            discover=discover,
        )

    def install(self, monkeypatch):
        import turtle_value_engine.providers.cninfo_disclosure as module

        monkeypatch.setattr(
            module, "cninfo_disclosure_source_client", self.factory
        )


def _descriptor_rows() -> list[dict]:
    return [
        {
            "title": "贵州茅台2025年年度报告",
            "document_type": "010301",
            "published_date": "2026-04-17",
            "url": "https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF",
            "source_document_id": "1225114741",
            "issuer_name": "贵州茅台",
        },
        {
            "title": "贵州茅台关于回购股份实施进展的公告",
            "document_type": "011513",
            "published_date": "2026-04-20",
            "url": "https://static.cninfo.com.cn/finalpage/2026-04-20/7000000001.PDF",
            "source_document_id": "7000000001",
            "issuer_name": "贵州茅台",
        },
    ]


def _watchlist(tmp_path: Path, listing_ids: list[str]) -> Path:
    payload = {
        "watchlist_id": "cli-acquire",
        "profile_id": "strict-v1",
        "entries": [{"listing_id": lid} for lid in listing_ids],
    }
    target = tmp_path / "watchlist.json"
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return target


def _base_argv(**overrides) -> list[str]:
    argv = [
        "watch", "acquire-events",
        "--listing", "SH600519",
        "--from", "2026-04-10",
        "--to", "2026-04-30",
    ]
    argv.extend(overrides.pop("extra", []))
    return argv


class TestNetworkPermission:
    def test_deny_by_default_fails_closed_without_any_source_call(
        self, tmp_path, capsys, monkeypatch
    ):
        source = ScriptedSource()
        source.install(monkeypatch)
        cache = tmp_path / "cache"
        code = main(_base_argv(extra=["--cache-dir", str(cache)]))
        assert code == 2
        error = capsys.readouterr().err
        assert "tve:" in error
        assert "network is denied" in error
        assert "--network=allow" in error
        assert source.discover_calls == []
        assert not cache.exists()

    def test_allow_and_from_cache_are_mutually_exclusive(self, tmp_path, capsys, monkeypatch):
        ScriptedSource().install(monkeypatch)
        code = main(_base_argv(extra=[
            "--network=allow", "--from-cache", "--cache-dir", str(tmp_path / "c"),
        ]))
        assert code == 2
        assert "mutually exclusive" in capsys.readouterr().err

    def test_offline_replay_needs_no_network_and_no_flag(self, tmp_path, capsys, monkeypatch):
        def no_sockets(*args, **kwargs):
            raise AssertionError("network access attempted during offline replay")

        monkeypatch.setattr(socket, "socket", no_sockets)
        monkeypatch.setattr(socket, "create_connection", no_sockets)
        source = ScriptedSource({"SH600519": _descriptor_rows()})
        source.install(monkeypatch)
        cache = tmp_path / "cache"
        assert main(_base_argv(extra=["--network=allow", "--cache-dir", str(cache)])) == 0
        source.discover_calls.clear()
        capsys.readouterr()
        code = main(_base_argv(extra=["--from-cache", "--cache-dir", str(cache)]))
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["offline_replay"] is True
        assert payload["listings"][0]["retrieval_mode"] == "CACHE_REPLAY"
        assert source.discover_calls == []


class TestAcquireEvents:
    def test_live_allow_produces_canonical_batch(self, tmp_path, capsys, monkeypatch):
        source = ScriptedSource({"SH600519": _descriptor_rows()})
        source.install(monkeypatch)
        output = tmp_path / "batch.json"
        code = main(_base_argv(extra=[
            "--network=allow", "--cache-dir", str(tmp_path / "cache"),
            "--output", str(output),
        ]))
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["network_allowed"] is True
        assert payload["source_id"] == "CNINFO"
        assert payload["adapter_version"] == ADAPTER_VERSION
        assert payload["event_count"] == 2
        assert payload["listings"][0]["retrieval_mode"] == "LIVE"
        assert payload["listings"][0]["source_record_count"] == 2
        # The batch artifact is canonical JSON with the exact batch identity.
        assert output.is_file()
        batch_payload = json.loads(output.read_text(encoding="utf-8"))
        assert batch_payload["contract"] == "monitoring_event_batch_v1"
        assert batch_payload["batch_id"] == payload["batch_id"]
        from turtle_value_engine.monitoring import MonitoringEventBatchV1

        batch = MonitoringEventBatchV1.model_validate(batch_payload)
        assert canonical_json_bytes(batch.model_dump(mode="json")) + b"\n" == output.read_bytes()
        # Raw provenance landed in the private raw cache, not in the batch dir.
        raw_files = list((tmp_path / "cache").rglob("*.json"))
        assert raw_files, "raw cache record missing"

    def test_batch_matches_checked_in_schema(self, tmp_path, monkeypatch):
        import jsonschema

        source = ScriptedSource({"SH600519": _descriptor_rows()})
        source.install(monkeypatch)
        output = tmp_path / "batch.json"
        assert main(_base_argv(extra=[
            "--network=allow", "--cache-dir", str(tmp_path / "cache"),
            "--output", str(output),
        ])) == 0
        schema = json.loads(
            (ROOT / "schemas" / "monitoring-event-batch.schema.json").read_text("utf-8")
        )
        jsonschema.validate(json.loads(output.read_text("utf-8")), schema)

    def test_live_and_offline_output_are_byte_identical(self, tmp_path, monkeypatch):
        source = ScriptedSource({"SH600519": _descriptor_rows()})
        source.install(monkeypatch)
        cache = str(tmp_path / "cache")
        live_out = tmp_path / "live.json"
        replay_out = tmp_path / "replay.json"
        assert main(_base_argv(extra=[
            "--network=allow", "--cache-dir", cache, "--output", str(live_out),
        ])) == 0
        assert main(_base_argv(extra=[
            "--from-cache", "--cache-dir", cache, "--output", str(replay_out),
        ])) == 0
        assert live_out.read_bytes() == replay_out.read_bytes()

    def test_as_of_filters_future_unavailable_events(self, tmp_path, capsys, monkeypatch):
        ScriptedSource({"SH600519": _descriptor_rows()}).install(monkeypatch)
        code = main(_base_argv(extra=[
            "--network=allow", "--cache-dir", str(tmp_path / "cache"),
            "--as-of", "2026-04-19T00:00:00Z",
        ]))
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["event_count"] == 1
        assert payload["listings"][0]["deferred_future_count"] == 1

    def test_watchlist_scope_uses_enabled_entries(self, tmp_path, capsys, monkeypatch):
        watchlist = tmp_path / "watchlist.json"
        watchlist.write_text(json.dumps({
            "watchlist_id": "cli-acquire",
            "profile_id": "strict-v1",
            "entries": [
                {"listing_id": "SH600519"},
                {"listing_id": "SZ000858", "enabled": False},
            ],
        }, ensure_ascii=False), encoding="utf-8")
        source = ScriptedSource({"SH600519": _descriptor_rows()})
        source.install(monkeypatch)
        code = main([
            "watch", "acquire-events",
            "--watchlist", str(watchlist),
            "--from", "2026-04-10",
            "--to", "2026-04-30",
            "--network=allow",
            "--cache-dir", str(tmp_path / "cache"),
        ])
        assert code == 0
        assert source.discover_calls == ["SH600519"]

    def test_duplicate_explicit_listing_scope_fails_closed(self, tmp_path, capsys, monkeypatch):
        ScriptedSource().install(monkeypatch)
        code = main(_base_argv(extra=[
            "--listing", "SH600519", "--network=allow",
            "--cache-dir", str(tmp_path / "cache"),
        ]))
        assert code == 2
        assert "duplicate listing" in capsys.readouterr().err

    def test_watchlist_with_non_provider_listing_form_fails_with_exact_blocker(
        self, tmp_path, capsys, monkeypatch
    ):
        watchlist = _watchlist(tmp_path, ["600519.SH"])
        ScriptedSource().install(monkeypatch)
        code = main([
            "watch", "acquire-events",
            "--watchlist", str(watchlist),
            "--from", "2026-04-10",
            "--to", "2026-04-30",
            "--network=allow",
            "--cache-dir", str(tmp_path / "cache"),
        ])
        assert code == 2
        error = capsys.readouterr().err
        assert "invalid acquisition scope" in error
        assert "600519.SH" in error

    def test_missing_window_start_fails_with_exact_blocker(self, tmp_path, capsys, monkeypatch):
        ScriptedSource().install(monkeypatch)
        code = main([
            "watch", "acquire-events",
            "--listing", "SH600519",
            "--to", "2026-04-30",
            "--network=allow",
            "--cache-dir", str(tmp_path / "cache"),
        ])
        assert code == 2
        error = capsys.readouterr().err
        assert "acquisition window start is required" in error
        assert "--from" in error

    def test_oversized_window_fails_closed(self, tmp_path, capsys, monkeypatch):
        ScriptedSource().install(monkeypatch)
        code = main(_base_argv(extra=[
            "--from", "2024-01-01",
            "--network=allow",
            "--cache-dir", str(tmp_path / "cache"),
        ]))
        assert code == 2
        assert "maximum is 366" in capsys.readouterr().err

    def test_limit_bounds_are_enforced_by_argparse(self, tmp_path, monkeypatch):
        ScriptedSource().install(monkeypatch)
        with pytest.raises(SystemExit) as excinfo:
            main(_base_argv(extra=[
                "--limit", "31", "--network=allow", "--cache-dir", str(tmp_path / "cache"),
            ]))
        assert excinfo.value.code == 2  # argparse rejects before anything runs

    def test_stdout_carries_no_secret_material(self, tmp_path, capsys, monkeypatch):
        ScriptedSource({"SH600519": _descriptor_rows()}).install(monkeypatch)
        assert main(_base_argv(extra=[
            "--network=allow", "--cache-dir", str(tmp_path / "cache"),
        ])) == 0
        text = capsys.readouterr().out
        for marker in ("cookie", "token", "secret", "authorization", "password"):
            assert marker not in text.lower()


class TestPhase6AIntegration:
    def test_acquire_replay_status_end_to_end(self, tmp_path, capsys, monkeypatch):
        watchlist = _watchlist(tmp_path, ["SH600519", "SZ000858"])
        source = ScriptedSource({"SH600519": _descriptor_rows()})
        source.install(monkeypatch)
        cache = str(tmp_path / "cache")
        workspace = tmp_path / "ws"
        batch_file = tmp_path / "batch.json"

        # 1. acquire (explicit allow) - workspace must stay untouched.
        assert main([
            "watch", "acquire-events",
            "--watchlist", str(watchlist),
            "--from", "2026-04-10",
            "--to", "2026-04-30",
            "--network=allow",
            "--cache-dir", cache,
            "--output", str(batch_file),
            "--workspace", str(workspace),
        ]) == 0
        capsys.readouterr()
        assert not workspace.exists()  # read-only cursor consultation, no writes

        # 2. Phase 6-A replay commits the acquired batch.
        assert main([
            "watch", "replay",
            "--watchlist", str(watchlist),
            "--events", str(batch_file),
            "--workspace", str(workspace),
            "--as-of", "2026-06-01T00:00:00Z",
        ]) == 0
        run_payload = json.loads(capsys.readouterr().out)
        assert run_payload["contract"] == "monitoring_run_v1"
        assert len(run_payload["decisions"]) == 2

        # 3. status shows the advanced CNINFO cursor for SH600519 only.
        assert main([
            "watch", "status", "--workspace", str(workspace),
            "--watchlist-id", "cli-acquire",
        ]) == 0
        status = json.loads(capsys.readouterr().out)
        by_listing = {entry["listing_id"]: entry for entry in status["entries"]}
        sh_cursors = by_listing["SH600519"]["cursors"]
        assert len(sh_cursors) == 1
        assert sh_cursors[0]["source_id"] == "CNINFO"
        assert sh_cursors[0]["last_processed_available_at"].startswith("2026-04-20T15:59:59")
        assert by_listing["SZ000858"]["cursors"] == []
        assert by_listing["SH600519"]["processed_event_count"] == 2

    def test_second_acquire_from_derived_cursor_window(self, tmp_path, capsys, monkeypatch):
        watchlist = _watchlist(tmp_path, ["SH600519"])
        source = ScriptedSource({"SH600519": _descriptor_rows()})
        source.install(monkeypatch)
        cache = str(tmp_path / "cache")
        workspace = tmp_path / "ws"
        batch_file = tmp_path / "batch.json"
        common = ["--watchlist", str(watchlist), "--workspace", str(workspace)]
        assert main([
            "watch", "acquire-events", *common,
            "--from", "2026-04-10", "--to", "2026-04-30",
            "--network=allow", "--cache-dir", cache, "--output", str(batch_file),
        ]) == 0
        capsys.readouterr()
        assert main([
            "watch", "replay",
            "--watchlist", str(watchlist),
            "--events", str(batch_file),
            "--workspace", str(workspace),
            "--as-of", "2026-06-01T00:00:00Z",
        ]) == 0
        capsys.readouterr()
        # The second acquisition derives its window start from the committed
        # cursor (day after 2026-04-20) without an explicit --from.
        source.discover_calls.clear()
        assert main([
            "watch", "acquire-events", *common,
            "--to", "2026-06-30",
            "--network=allow", "--cache-dir", cache,
        ]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["published_from"] == "2026-04-21"
        assert payload["event_count"] == 0  # no rows inside the derived window
        assert source.discover_calls == ["SH600519"]

    def test_existing_phase6a_commands_stay_offline_and_unchanged(self, tmp_path, capsys):
        # sanity: the frozen Phase 6-A surface keeps working without network flags
        watchlist = _watchlist(tmp_path, ["SH600519"])
        events = tmp_path / "events.json"
        events.write_text(json.dumps([{
            "event_id": "evt-1",
            "listing_id": "SH600519",
            "event_type": "ANNUAL_REPORT",
            "source_id": "CNINFO",
            "source_event_id": "1225114741",
            "available_at": "2026-04-17T15:59:59.999999Z",
            "title": "年度报告",
        }], ensure_ascii=False), encoding="utf-8")
        assert main([
            "watch", "replay",
            "--watchlist", str(watchlist),
            "--events", str(events),
            "--workspace", str(tmp_path / "ws"),
            "--as-of", "2026-06-01T00:00:00Z",
        ]) == 0
