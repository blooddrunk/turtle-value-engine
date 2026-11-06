"""Offline, deterministic checks for CI's fail-closed PR scope classifier."""

from __future__ import annotations

import json

import pytest

from scripts.ci_change_scope import classify_changed_files, detect_scope, list_changed_files


def changed(path: str, status: str = "modified") -> dict[str, str]:
    return {"filename": path, "status": status}


@pytest.mark.parametrize(
    ("files", "mode"),
    [
        ([changed("docs/status/phase-7.md")], "docs-only"),
        ([changed("docs/goals/next-step.md", "added")], "docs-only"),
        ([changed("docs/status/a.md"), changed("docs/goals/b.md")], "docs-only"),
        ([changed("scripts/check_workflow_action_pins.py")], "pin-guard-only"),
        ([changed("tests/test_workflow_action_pins.py")], "pin-guard-only"),
        (
            [
                changed("scripts/check_workflow_action_pins.py"),
                changed("tests/test_workflow_action_pins.py"),
            ],
            "pin-guard-only",
        ),
        ([changed("docs/spec/frozen.md")], "full"),
        ([changed("docs/operations/runbook.md")], "full"),
        ([changed("docs/status/fixtures.json")], "full"),
        ([changed("docs/status/a.md", "renamed")], "full"),
        ([changed("docs/goals/a.md", "removed")], "full"),
        ([changed("docs/status/a.md"), changed("src/a.py")], "full"),
        ([changed("tests/test_workflow_action_pins.py"), changed("docs/status/a.md")], "full"),
        ([changed(".github/workflows/ci.yml")], "full"),
        ([changed("tests/test_ci_change_scope.py")], "full"),
        ([changed("docs/status-a.md")], "full"),
        ([], "full"),
        ([{"status": "modified"}], "full"),
        ([{"filename": "docs/status/a.md"}], "full"),
    ],
)
def test_scope_allowlists(files, mode):
    assert classify_changed_files(files) == mode


def test_malformed_payloads_fail_closed():
    assert classify_changed_files(None) == "full"
    assert classify_changed_files({}) == "full"
    assert classify_changed_files([None]) == "full"
    assert classify_changed_files([changed("docs/status/a.md"), {"filename": 42}]) == "full"


def test_paginated_file_list_is_complete():
    calls = []

    def fetcher(url, token):
        assert token == "read-token"
        calls.append(url)
        return [changed(f"docs/status/{i}.md") for i in range(100 if len(calls) == 1 else 1)]

    files = list_changed_files("https://api.github.test/repos/o/r", 5, 101, "read-token", fetcher)
    assert len(files) == 101
    assert "page=1" in calls[0]
    assert "page=2" in calls[1]


@pytest.mark.parametrize("count", [0, -1, 3001, True, None])
def test_invalid_file_counts_rejected(count):
    with pytest.raises(ValueError):
        list_changed_files("https://api.github.test/repos/o/r", 5, count, "token")


def test_incomplete_page_rejected():
    with pytest.raises(ValueError, match="incomplete"):
        list_changed_files(
            "https://api.github.test/repos/o/r", 5, 2, "token", lambda *_: [changed("a")]
        )


def test_non_pr_event_always_full():
    assert detect_scope({"GITHUB_EVENT_NAME": "push"})[0] == "full"


@pytest.mark.parametrize("changed_head", [False, True])
def test_event_head_is_immutable_during_classification(tmp_path, changed_head):
    event = {
        "number": 8,
        "pull_request": {
            "head": {"sha": "head-at-trigger"},
            "base": {"sha": "base-at-trigger"},
            "changed_files": 1,
        },
    }
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    env = {
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_EVENT_PATH": str(event_path),
        "GITHUB_REPOSITORY": "o/r",
        "GITHUB_TOKEN": "token",
    }
    calls = []

    def fetcher(url, token):
        calls.append(url)
        if "/files?" in url:
            return [changed("docs/status/a.md")]
        head = "new-head" if changed_head and len(calls) == 3 else "head-at-trigger"
        return {
            "number": 8,
            "head": {"sha": head},
            "base": {"sha": "base-at-trigger"},
            "changed_files": 1,
        }

    mode, _ = detect_scope(env, fetcher)
    assert mode == ("full" if changed_head else "docs-only")


def test_changed_base_forces_full(tmp_path):
    event = {
        "number": 8,
        "pull_request": {
            "head": {"sha": "head"},
            "base": {"sha": "old-base"},
            "changed_files": 1,
        },
    }
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")

    def fetcher(url, token):
        return {
            "number": 8,
            "head": {"sha": "head"},
            "base": {"sha": "moved-base"},
            "changed_files": 1,
        }

    mode, _ = detect_scope(
        {
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_EVENT_PATH": str(event_path),
            "GITHUB_REPOSITORY": "o/r",
            "GITHUB_TOKEN": "token",
        },
        fetcher,
    )
    assert mode == "full"
