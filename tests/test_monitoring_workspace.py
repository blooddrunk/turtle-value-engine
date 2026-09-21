"""Deterministic Phase 6-A monitoring workspace tests (atomicity/corruption)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from turtle_value_engine.monitoring import (
    MonitoringWorkspace,
    MonitoringWorkspaceError,
    WatchlistSpecV1,
    build_event_batch,
    run_monitoring,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "monitoring"
AS_OF = "2026-06-01T00:00:00Z"


def _watchlist() -> WatchlistSpecV1:
    payload = json.loads((FIXTURES / "watchlist-basic.json").read_text(encoding="utf-8"))
    return WatchlistSpecV1.build(**payload)


def _events_payload() -> list:
    return json.loads((FIXTURES / "events-basic.json").read_text(encoding="utf-8"))


def _plan_run(watchlist: WatchlistSpecV1, payloads: list | None = None):
    batch = build_event_batch(
        payloads if payloads is not None else _events_payload()
    )
    return batch, run_monitoring(watchlist, batch, None, AS_OF)


class TestCommitAndRead:
    def test_commit_moves_pointer_and_persists_canonical_artifacts(self, tmp_path):
        workspace = MonitoringWorkspace(tmp_path)
        watchlist = _watchlist()
        batch, run = _plan_run(watchlist)
        pointer = workspace.commit_run(run, watchlist=watchlist, batch=batch)

        state = workspace.load_current_state("personal-core")
        assert state is not None
        assert state.state_id == run.next_state.state_id
        assert pointer.state_id == state.state_id
        assert workspace.load_run(run.run_id).run_id == run.run_id

        run_file = workspace.run_path(run.run_id)
        assert run_file.read_bytes() == run.canonical_bytes() + b"\n"
        state_file = workspace.state_path(state.state_id)
        assert state_file.read_bytes() == state.canonical_bytes() + b"\n"

    def test_cursor_visible_only_after_commit(self, tmp_path):
        watchlist = _watchlist()
        batch, run = _plan_run(watchlist)
        assert MonitoringWorkspace(tmp_path).load_current_state("personal-core") is None
        workspace = MonitoringWorkspace(tmp_path)
        workspace.commit_run(run, watchlist=watchlist, batch=batch)
        committed = workspace.load_current_state("personal-core")
        assert committed is not None
        cursor = committed.entry_for("600519.SH").cursor_for("cninfo")
        assert cursor is not None
        assert cursor.advanced_by_run_id == run.run_id

    def test_recommit_of_identical_run_is_idempotent_and_byte_equal(self, tmp_path):
        workspace = MonitoringWorkspace(tmp_path)
        watchlist = _watchlist()
        batch, run = _plan_run(watchlist)
        workspace.commit_run(run, watchlist=watchlist, batch=batch)
        first_bytes = workspace.run_path(run.run_id).read_bytes()
        workspace.commit_run(run, watchlist=watchlist, batch=batch)
        assert workspace.run_path(run.run_id).read_bytes() == first_bytes

    def test_replanning_same_run_twice_is_byte_equivalent(self, tmp_path):
        watchlist = _watchlist()
        batch, run = _plan_run(watchlist)
        again = run_monitoring(watchlist, batch, None, AS_OF)
        assert again.canonical_bytes() == run.canonical_bytes()

    def test_repeated_replay_converges_without_state_growth(self, tmp_path):
        workspace = MonitoringWorkspace(tmp_path)
        watchlist = _watchlist()
        batch, run = _plan_run(watchlist)
        workspace.commit_run(run, watchlist=watchlist, batch=batch)
        state = workspace.load_current_state("personal-core")
        replay = run_monitoring(watchlist, batch, state, AS_OF)
        workspace.commit_run(replay, watchlist=watchlist, batch=batch)
        after = workspace.load_current_state("personal-core")
        assert after is not None
        assert after.state_id == state.state_id
        assert len(list((tmp_path / "states").glob("*.json"))) == 2  # state + pointer

    def test_status_before_any_run_is_explicitly_unavailable(self, tmp_path):
        status = MonitoringWorkspace(tmp_path).status("personal-core")
        assert status.availability == "NOT_AVAILABLE"
        assert status.state_id is None


class TestFailureInjection:
    def test_failure_before_pointer_leaves_previous_state_intact(self, tmp_path):
        workspace = MonitoringWorkspace(tmp_path)
        watchlist = _watchlist()
        first_batch, first_run = _plan_run(watchlist)
        workspace.commit_run(first_run, watchlist=watchlist, batch=first_batch)
        committed_state = workspace.load_current_state("personal-core")
        pointer_bytes = workspace.pointer_path("personal-core").read_bytes()

        second_batch = build_event_batch(
            [
                {
                    "event_id": "post-failure-event",
                    "listing_id": "600519.SH",
                    "event_type": "SHARE_ISSUANCE",
                    "source_id": "cninfo",
                    "source_event_id": "cninfo:post",
                    "available_at": "2026-05-20T08:00:00Z",
                }
            ]
        )
        second_run = run_monitoring(
            watchlist, second_batch, committed_state, AS_OF
        )

        def fail_on_pointer(path: Path, kind: str) -> None:
            if kind == "pointer":
                raise OSError("simulated durable-write failure at pointer stage")

        broken = MonitoringWorkspace(tmp_path, failure_injector=fail_on_pointer)
        with pytest.raises(MonitoringWorkspaceError, match="write failed"):
            broken.commit_run(second_run, watchlist=watchlist, batch=second_batch)

        # The previous committed state is still readable and still current.
        readable = MonitoringWorkspace(tmp_path).load_current_state("personal-core")
        assert readable is not None
        assert readable.state_id == committed_state.state_id
        assert workspace.pointer_path("personal-core").read_bytes() == pointer_bytes

        # Retrying the same run after the failure succeeds and is idempotent.
        retry = MonitoringWorkspace(tmp_path)
        retry.commit_run(second_run, watchlist=watchlist, batch=second_batch)
        final = retry.load_current_state("personal-core")
        assert final is not None
        assert final.state_id == second_run.next_state.state_id
        record = final.entry_for("600519.SH").processed_event("post-failure-event")
        assert record is not None

    @pytest.mark.parametrize("stage", ["watchlist", "batch", "run", "state", "pointer"])
    def test_failure_at_every_stage_never_moves_the_pointer(self, tmp_path, stage):
        watchlist = _watchlist()
        first_batch, first_run = _plan_run(watchlist)
        seeded = MonitoringWorkspace(tmp_path)
        seeded.commit_run(first_run, watchlist=watchlist, batch=first_batch)
        pointer_bytes = seeded.pointer_path("personal-core").read_bytes()
        state_id = first_run.next_state.state_id

        second_batch = build_event_batch(
            [
                {
                    "event_id": "late-issuance",
                    "listing_id": "600519.SH",
                    "event_type": "MAJOR_ACQUISITION",
                    "source_id": "cninfo",
                    "source_event_id": "cninfo:late",
                    "available_at": "2026-05-25T08:00:00Z",
                }
            ]
        )
        state = seeded.load_current_state("personal-core")
        second_run = run_monitoring(watchlist, second_batch, state, AS_OF)

        targets = {
            "watchlist": seeded.watchlist_path(watchlist),
            "batch": seeded.event_batch_path(second_batch.batch_id),
            "run": seeded.run_path(second_run.run_id),
            "state": seeded.state_path(second_run.next_state.state_id),
            "pointer": seeded.pointer_path("personal-core"),
        }

        def fail_at_target(path: Path, kind: str) -> None:
            if path == targets[stage]:
                raise OSError(f"simulated failure at {stage}")

        broken = MonitoringWorkspace(tmp_path, failure_injector=fail_at_target)
        with pytest.raises(MonitoringWorkspaceError):
            broken.commit_run(second_run, watchlist=watchlist, batch=second_batch)

        assert seeded.pointer_path("personal-core").read_bytes() == pointer_bytes
        recovered = MonitoringWorkspace(tmp_path).load_current_state("personal-core")
        assert recovered is not None and recovered.state_id == state_id


class TestCorruption:
    def test_truncated_state_fails_closed(self, tmp_path):
        workspace = MonitoringWorkspace(tmp_path)
        watchlist = _watchlist()
        batch, run = _plan_run(watchlist)
        workspace.commit_run(run, watchlist=watchlist, batch=batch)
        state_file = workspace.state_path(run.next_state.state_id)
        state_file.write_bytes(state_file.read_bytes()[: len(state_file.read_bytes()) // 2])
        with pytest.raises(MonitoringWorkspaceError, match="corrupt or invalid"):
            MonitoringWorkspace(tmp_path).load_current_state("personal-core")

    def test_tampered_run_field_fails_closed(self, tmp_path):
        workspace = MonitoringWorkspace(tmp_path)
        watchlist = _watchlist()
        batch, run = _plan_run(watchlist)
        workspace.commit_run(run, watchlist=watchlist, batch=batch)
        run_file = workspace.run_path(run.run_id)
        payload = json.loads(run_file.read_text(encoding="utf-8"))
        payload["as_of"] = "2027-01-01T00:00:00Z"
        run_file.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(MonitoringWorkspaceError, match="corrupt or invalid"):
            MonitoringWorkspace(tmp_path).load_run(run.run_id)

    def test_non_canonical_bytes_fail_closed(self, tmp_path):
        workspace = MonitoringWorkspace(tmp_path)
        watchlist = _watchlist()
        batch, run = _plan_run(watchlist)
        workspace.commit_run(run, watchlist=watchlist, batch=batch)
        run_file = workspace.run_path(run.run_id)
        payload = json.loads(run_file.read_text(encoding="utf-8"))
        run_file.write_text(json.dumps(payload, indent=4), encoding="utf-8")
        with pytest.raises(MonitoringWorkspaceError, match="canonical form"):
            MonitoringWorkspace(tmp_path).load_run(run.run_id)

    def test_tampered_pointer_fails_closed(self, tmp_path):
        workspace = MonitoringWorkspace(tmp_path)
        watchlist = _watchlist()
        batch, run = _plan_run(watchlist)
        workspace.commit_run(run, watchlist=watchlist, batch=batch)
        pointer_file = workspace.pointer_path("personal-core")
        payload = json.loads(pointer_file.read_text(encoding="utf-8"))
        payload["state_id"] = "f" * 64
        pointer_file.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(MonitoringWorkspaceError, match="corrupt or invalid"):
            MonitoringWorkspace(tmp_path).load_current_state("personal-core")

    def test_missing_state_artifact_fails_closed(self, tmp_path):
        workspace = MonitoringWorkspace(tmp_path)
        watchlist = _watchlist()
        batch, run = _plan_run(watchlist)
        workspace.commit_run(run, watchlist=watchlist, batch=batch)
        workspace.state_path(run.next_state.state_id).unlink()
        with pytest.raises(MonitoringWorkspaceError):
            MonitoringWorkspace(tmp_path).load_current_state("personal-core")

    def test_conflicting_bytes_for_same_identity_fail_closed(self, tmp_path):
        workspace = MonitoringWorkspace(tmp_path)
        watchlist = _watchlist()
        batch, run = _plan_run(watchlist)
        run_file = workspace.run_path(run.run_id)
        run_file.parent.mkdir(parents=True, exist_ok=True)
        run_file.write_bytes(b'{"contract": "monitoring_run_v1"}\n')
        with pytest.raises(MonitoringWorkspaceError, match="conflicting content"):
            workspace.commit_run(run, watchlist=watchlist, batch=batch)


class TestIdentityMismatch:
    def test_commit_rejects_mismatched_watchlist(self, tmp_path):
        watchlist = _watchlist()
        batch, run = _plan_run(watchlist)
        other = WatchlistSpecV1.build(
            watchlist_id="other",
            profile_id="strict-v1",
            entries=[{"listing_id": "600519.SH"}],
        )
        with pytest.raises(MonitoringWorkspaceError, match="identities differ"):
            MonitoringWorkspace(tmp_path).commit_run(run, watchlist=other, batch=batch)

    def test_commit_rejects_mismatched_batch(self, tmp_path):
        watchlist = _watchlist()
        _, run = _plan_run(watchlist)
        other_batch = build_event_batch(
            [
                {
                    "event_id": "unrelated",
                    "listing_id": "600519.SH",
                    "event_type": "BUYBACK",
                    "source_id": "cninfo",
                    "source_event_id": "cninfo:unrelated",
                    "available_at": "2026-05-01T08:00:00Z",
                }
            ]
        )
        with pytest.raises(MonitoringWorkspaceError, match="identities differ"):
            MonitoringWorkspace(tmp_path).commit_run(
                run, watchlist=watchlist, batch=other_batch
            )
