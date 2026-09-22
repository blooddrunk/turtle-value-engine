"""Deterministic Phase 6-A monitoring CLI and configuration tests."""

from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

import pytest

from turtle_value_engine.cli import main
from turtle_value_engine.config import ProjectConfig, load_project_config

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "monitoring"
AS_OF = "2026-06-01T00:00:00Z"

# Frozen at Phase 6-A implementation time: this package must not change
# strict-v1 investment semantics or the normalized-input contract.
FROZEN_FILE_HASHES = {
    "rules/strict-v1.yaml": "e3618f78b2f8e4d1e8e81ce3065da977685ad5256bd0ab3332b3a8054e0b6333",
    "schemas/normalized-input.schema.json": (
        "4b23efc830160bb12fa78114a830794d955fd7dd097e131e28a22eb872070f3c"
    ),
}


def _fixture(name: str) -> Path:
    return FIXTURES / name


class TestWatchValidate:
    def test_valid_watchlist_exits_zero(self, capsys):
        code = main(["watch", "validate", "--watchlist", str(_fixture("watchlist-basic.json"))])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["watchlist_id"] == "personal-core"
        assert payload["content_sha256"]

    def test_duplicate_listing_exits_nonzero_with_exact_blocker(self, capsys):
        code = main(
            [
                "watch",
                "validate",
                "--watchlist",
                str(_fixture("watchlist-invalid-duplicate.json")),
            ]
        )
        assert code == 2
        error = capsys.readouterr().err
        assert "tve: invalid watchlist" in error
        assert "duplicate watchlist listing_id: 600519.SH" in error

    def test_malformed_json_exits_nonzero(self, tmp_path, capsys):
        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        code = main(["watch", "validate", "--watchlist", str(broken)])
        assert code == 2
        assert "tve:" in capsys.readouterr().err


class TestWatchReplay:
    def test_replay_commits_workspace_and_writes_output(self, tmp_path, capsys):
        workspace = tmp_path / "ws"
        output = tmp_path / "run.json"
        code = main(
            [
                "watch",
                "replay",
                "--watchlist",
                str(_fixture("watchlist-basic.json")),
                "--events",
                str(_fixture("events-basic.json")),
                "--workspace",
                str(workspace),
                "--as-of",
                AS_OF,
                "--output",
                str(output),
            ]
        )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["contract"] == "monitoring_run_v1"
        assert output.is_file()
        assert json.loads(output.read_text(encoding="utf-8"))["run_id"] == payload["run_id"]
        assert (workspace / "watchlists").is_dir()
        assert (workspace / "event-batches").is_dir()
        assert (workspace / "runs").is_dir()
        assert (workspace / "states" / "current-personal-core.json").is_file()

        status_code = main(
            ["watch", "status", "--workspace", str(workspace), "--watchlist-id", "personal-core"]
        )
        assert status_code == 0
        status = json.loads(capsys.readouterr().out)
        assert status["availability"] == "AVAILABLE"
        by_listing = {entry["listing_id"]: entry for entry in status["entries"]}
        assert by_listing["600519.SH"]["processed_event_count"] == 2
        assert by_listing["HK00288"]["processed_event_count"] == 1

    def test_second_replay_is_idempotent(self, tmp_path):
        workspace = tmp_path / "ws"
        argv = [
            "watch",
            "replay",
            "--watchlist",
            str(_fixture("watchlist-basic.json")),
            "--events",
            str(_fixture("events-basic.json")),
            "--workspace",
            str(workspace),
            "--as-of",
            AS_OF,
        ]
        assert main(argv) == 0
        pointer_file = workspace / "states" / "current-personal-core.json"
        first_pointer = pointer_file.read_bytes()

        # The second replay is a distinct audit record, but it must not move
        # the committed state: every event is already processed.
        assert main(argv) == 0
        assert pointer_file.read_bytes() == first_pointer
        runs_after_two = {
            path.name: path.read_bytes() for path in sorted((workspace / "runs").iterdir())
        }
        assert len(runs_after_two) == 2

        # A third replay replans against the unchanged prior state, so its
        # run identity and bytes repeat instead of growing.
        assert main(argv) == 0
        runs_after_three = {
            path.name: path.read_bytes() for path in sorted((workspace / "runs").iterdir())
        }
        assert runs_after_three == runs_after_two

    def test_identical_replays_into_two_workspaces_are_byte_equivalent(self, tmp_path):
        outputs = []
        for index in range(2):
            workspace = tmp_path / f"ws{index}"
            output = tmp_path / f"run{index}.json"
            assert (
                main(
                    [
                        "watch",
                        "replay",
                        "--watchlist",
                        str(_fixture("watchlist-basic.json")),
                        "--events",
                        str(_fixture("events-basic.json")),
                        "--workspace",
                        str(workspace),
                        "--as-of",
                        AS_OF,
                        "--output",
                        str(output),
                    ]
                )
                == 0
            )
            outputs.append(output.read_bytes())
        assert outputs[0] == outputs[1]

    def test_conflicting_event_content_exits_nonzero_with_blocker(self, tmp_path, capsys):
        events = tmp_path / "conflict.json"
        events.write_text(
            json.dumps(
                [
                    {
                        "event_id": "e1",
                        "listing_id": "600519.SH",
                        "event_type": "ANNUAL_REPORT",
                        "source_id": "cninfo",
                        "source_event_id": "cn:1",
                        "available_at": "2026-04-01T08:00:00Z",
                    },
                    {
                        "event_id": "e1",
                        "listing_id": "600519.SH",
                        "event_type": "ANNUAL_REPORT",
                        "source_id": "cninfo",
                        "source_event_id": "cn:1",
                        "available_at": "2026-04-02T08:00:00Z",
                    },
                ]
            ),
            encoding="utf-8",
        )
        code = main(
            [
                "watch",
                "replay",
                "--watchlist",
                str(_fixture("watchlist-basic.json")),
                "--events",
                str(events),
                "--workspace",
                str(tmp_path / "ws"),
                "--as-of",
                AS_OF,
            ]
        )
        assert code == 2
        error = capsys.readouterr().err
        assert "EVENT_CONFLICT" in error
        assert "e1" in error

    def test_unknown_event_type_exits_nonzero_with_blocker(self, tmp_path, capsys):
        events = tmp_path / "unknown.json"
        events.write_text(
            json.dumps(
                [
                    {
                        "event_id": "e1",
                        "listing_id": "600519.SH",
                        "event_type": "WAT",
                        "source_id": "cninfo",
                        "source_event_id": "cn:1",
                        "available_at": "2026-04-01T08:00:00Z",
                    }
                ]
            ),
            encoding="utf-8",
        )
        code = main(
            [
                "watch",
                "replay",
                "--watchlist",
                str(_fixture("watchlist-basic.json")),
                "--events",
                str(events),
                "--workspace",
                str(tmp_path / "ws"),
                "--as-of",
                AS_OF,
            ]
        )
        assert code == 2
        assert "invalid monitoring event" in capsys.readouterr().err

    def test_invalid_as_of_is_rejected(self, tmp_path, capsys):
        with pytest.raises(SystemExit) as excinfo:
            main(
                [
                    "watch",
                    "replay",
                    "--watchlist",
                    str(_fixture("watchlist-basic.json")),
                    "--events",
                    str(_fixture("events-basic.json")),
                    "--workspace",
                    str(tmp_path / "ws"),
                    "--as-of",
                    "not-a-date",
                ]
            )
        assert excinfo.value.code == 2
        assert "ISO-8601" in capsys.readouterr().err

    def test_replay_performs_no_network_access(self, tmp_path, monkeypatch):
        def no_sockets(*args, **kwargs):
            raise AssertionError("monitoring replay attempted a network call")

        monkeypatch.setattr(socket, "socket", no_sockets)
        monkeypatch.setattr(socket, "create_connection", no_sockets)
        code = main(
            [
                "watch",
                "replay",
                "--watchlist",
                str(_fixture("watchlist-basic.json")),
                "--events",
                str(_fixture("events-basic.json")),
                "--workspace",
                str(tmp_path / "ws"),
                "--as-of",
                AS_OF,
            ]
        )
        assert code == 0

    def test_replay_does_not_invoke_analysis_or_research_entry_points(
        self, tmp_path, monkeypatch
    ):
        import turtle_value_engine.pipeline as pipeline
        import turtle_value_engine.research.orchestration as orchestration

        def forbidden(*args, **kwargs):
            raise AssertionError("monitoring replay invoked an analysis/research runtime")

        for name in dir(pipeline):
            if name.startswith("run_"):
                monkeypatch.setattr(pipeline, name, forbidden)
        monkeypatch.setattr(
            orchestration, "ResearchOrchestrator", forbidden, raising=False
        )
        code = main(
            [
                "watch",
                "replay",
                "--watchlist",
                str(_fixture("watchlist-basic.json")),
                "--events",
                str(_fixture("events-basic.json")),
                "--workspace",
                str(tmp_path / "ws"),
                "--as-of",
                AS_OF,
            ]
        )
        assert code == 0


class TestWatchStatus:
    def test_status_of_unknown_watchlist_is_explicitly_unavailable(self, tmp_path, capsys):
        code = main(
            ["watch", "status", "--workspace", str(tmp_path / "ws"), "--watchlist-id", "nope"]
        )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload == {
            "contract": "monitoring_status_v1",
            "schema_version": "1.0.0",
            "watchlist_id": "nope",
            "availability": "NOT_AVAILABLE",
            "state_id": None,
            "last_committed_run_id": None,
            "entries": [],
        }

    def test_status_reads_only_and_never_mutates_workspace(self, tmp_path):
        workspace = tmp_path / "ws"
        assert (
            main(
                [
                    "watch",
                    "replay",
                    "--watchlist",
                    str(_fixture("watchlist-basic.json")),
                    "--events",
                    str(_fixture("events-basic.json")),
                    "--workspace",
                    str(workspace),
                    "--as-of",
                    AS_OF,
                ]
            )
            == 0
        )
        before = {
            path.relative_to(workspace).as_posix(): path.read_bytes()
            for path in sorted(workspace.rglob("*"))
            if path.is_file()
        }
        assert (
            main(
                [
                    "watch",
                    "status",
                    "--workspace",
                    str(workspace),
                    "--watchlist-id",
                    "personal-core",
                ]
            )
            == 0
        )
        after = {
            path.relative_to(workspace).as_posix(): path.read_bytes()
            for path in sorted(workspace.rglob("*"))
            if path.is_file()
        }
        assert before == after


class TestProjectConfigMonitoring:
    def _config_toml(self, tmp_path: Path) -> Path:
        content = (ROOT / "config" / "project.example.toml").read_text(encoding="utf-8")
        target = tmp_path / "project.toml"
        target.write_text(content, encoding="utf-8")
        return target

    def test_monitoring_fields_round_trip(self, tmp_path):
        config_path = self._config_toml(tmp_path)
        config = load_project_config(config_path)
        assert config.monitoring.watchlist_path == ".tve-private/monitoring/watchlist.json"
        assert config.monitoring.workspace_root == ".tve-private/monitoring"
        assert config.monitoring.event_impact_policy == "event-impact-v1"

    def test_default_config_has_empty_monitoring_paths(self):
        config = ProjectConfig()
        assert config.monitoring.watchlist_path is None
        assert config.monitoring.workspace_root is None
        assert config.monitoring.event_impact_policy == "event-impact-v1"

    def test_safe_summary_contains_monitoring_without_secrets(self, tmp_path):
        config = load_project_config(self._config_toml(tmp_path))
        summary = config.safe_summary()
        assert summary["monitoring"] == {
            "watchlist_path": ".tve-private/monitoring/watchlist.json",
            "workspace_root": ".tve-private/monitoring",
            "event_impact_policy": "event-impact-v1",
            "delivery": {
                "enabled": False,
                "transport": "webhook-v1",
                "destination_id": "owner-primary",
                "delivery_root": ".tve-private/monitoring/delivery",
                "endpoint_ref": "TVE_MONITORING_WEBHOOK_URL",
                "auth_token_ref": None,
            },
        }
        summary_text = json.dumps(summary)
        for marker in ("CLOUDFLARE_API_TOKEN=", "token-value", "SECRET_VALUE"):
            assert marker not in summary_text

    def test_unknown_policy_id_fails_closed(self, tmp_path):
        config_path = self._config_toml(tmp_path)
        content = config_path.read_text(encoding="utf-8").replace(
            'event_impact_policy = "event-impact-v1"',
            'event_impact_policy = "strict-v1"',
        )
        config_path.write_text(content, encoding="utf-8")
        from turtle_value_engine.config import ProjectConfigError

        with pytest.raises(ProjectConfigError, match="invalid project config"):
            load_project_config(config_path)

    def test_template_and_example_file_stay_in_sync(self, tmp_path):
        from turtle_value_engine.config.project import project_config_template

        example = (ROOT / "config" / "project.example.toml").read_text(encoding="utf-8")
        assert project_config_template() == example


class TestFrozenInvestmentContracts:
    @pytest.mark.parametrize("relative_path", sorted(FROZEN_FILE_HASHES))
    def test_file_is_byte_identical(self, relative_path):
        digest = hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()
        assert digest == FROZEN_FILE_HASHES[relative_path], relative_path

    def test_monitoring_policy_does_not_touch_rules_directory(self):
        watch_rules = sorted((ROOT / "rules").glob("*.yaml"))
        assert watch_rules
        for rule in watch_rules:
            text = rule.read_text(encoding="utf-8")
            assert "event-impact" not in text
            assert "REANALYSIS" not in text


class TestSchemaCoverage:
    def test_run_state_plan_pointer_status_schemas_match_models(self):
        from turtle_value_engine.monitoring import (
            MonitoringRunV1,
            MonitoringStatePointerV1,
            MonitoringStatusV1,
            ReanalysisPlanV1,
            WatchlistStateV1,
        )

        pairs = {
            "monitoring-run.schema.json": MonitoringRunV1,
            "watchlist-state.schema.json": WatchlistStateV1,
            "reanalysis-plan.schema.json": ReanalysisPlanV1,
            "monitoring-state-pointer.schema.json": MonitoringStatePointerV1,
            "monitoring-status.schema.json": MonitoringStatusV1,
        }
        for filename, model in pairs.items():
            checked_in = json.loads(
                (ROOT / "schemas" / filename).read_text(encoding="utf-8")
            )
            assert model.model_json_schema() == checked_in, filename
        # status entries are inlined into the status schema defs
        status_schema = json.loads(
            (ROOT / "schemas" / "monitoring-status.schema.json").read_text(encoding="utf-8")
        )
        assert "MonitoringStatusEntryV1" in status_schema["$defs"]

    def test_generated_run_artifacts_validate_against_checked_in_schemas(
        self, tmp_path
    ):
        from jsonschema import Draft202012Validator

        workspace_dir = tmp_path / "ws"
        output = tmp_path / "run.json"
        assert (
            main(
                [
                    "watch",
                    "replay",
                    "--watchlist",
                    str(_fixture("watchlist-basic.json")),
                    "--events",
                    str(_fixture("events-basic.json")),
                    "--workspace",
                    str(workspace_dir),
                    "--as-of",
                    AS_OF,
                    "--output",
                    str(output),
                ]
            )
            == 0
        )
        run_payload = json.loads(output.read_text(encoding="utf-8"))
        run_schema = json.loads(
            (ROOT / "schemas" / "monitoring-run.schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(run_schema)
        Draft202012Validator(run_schema).validate(run_payload)

        state_file = workspace_dir / "states" / f"{run_payload['next_state']['state_id']}.json"
        state_payload = json.loads(state_file.read_text(encoding="utf-8"))
        state_schema = json.loads(
            (ROOT / "schemas" / "watchlist-state.schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator(state_schema).validate(state_payload)
