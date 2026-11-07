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


# --- R1 acceptance boundary coverage -------------------------------------------------

from pathlib import Path  # noqa: E402
from urllib.error import HTTPError  # noqa: E402

import yaml  # noqa: E402

import scripts.ci_change_scope as scope  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


@pytest.mark.parametrize(
    "files",
    [
        # Every non added/modified status (incl. mode-only "changed" and copies).
        [changed("docs/status/a.md", "changed")],
        [changed("docs/status/a.md", "copied")],
        [changed("docs/status/a.md", "unchanged")],
        [changed("scripts/check_workflow_action_pins.py", "renamed")],
        [changed("tests/test_workflow_action_pins.py", "removed")],
        # Path-shape bypass attempts must never match the allowlists.
        [changed("docs/status/../../src/turtle_value_engine/x.md")],
        [changed("docs/status/./a.md")],
        [changed("docs/status//a.md")],
        [changed("/docs/status/a.md")],
        [changed("./docs/status/a.md")],
        [changed("docs\\status\\a.md")],
        [changed("docs/status/a.md\n")],
        [changed("docs/status/")],
        [changed("docs/status/a.MD")],
        [changed("docs/status/a.md.py")],
        [changed("docs/status/a.mdx")],
        [changed("Docs/status/a.md")],
        [changed("docs/goals")],
        [changed("scripts/check_workflow_action_pins.py/../evil.py")],
        [changed("scripts/../scripts/check_workflow_action_pins.py")],
        # Protected-contract areas stay full even when Markdown.
        [changed("docs/releases/strict-v2/notes.md")],
        [changed("docs/architecture/x.md")],
        [changed("docs/roadmap.md")],
        [changed("README.md")],
        [changed("AGENTS.md")],
        # Representative code/contract changes.
        [changed("src/turtle_value_engine/cli.py")],
        [changed("schemas/owner-readiness-summary.schema.json")],
        [changed("rules/strict-v1.yaml")],
        [changed("tests/fixtures/example.json")],
        [changed("config/project.example.toml")],
        [changed("pyproject.toml")],
        [changed("scripts/ci_change_scope.py")],
        [changed(".github/workflows/ci.yml"), changed("docs/status/a.md")],
        [changed("scripts/check_workflow_action_pins.py"), changed("src/a.py")],
        [changed("scripts/check_workflow_action_pins.py"), changed(".github/workflows/ci.yml")],
        [changed("apps/dashboard/src/App.tsx")],
        # Duplicate entries signal pagination drift.
        [changed("docs/status/a.md"), changed("docs/status/a.md")],
    ],
)
def test_bypass_and_contract_paths_stay_full(files):
    assert classify_changed_files(files) == "full"


def test_nested_status_and_goal_markdown_is_docs_only():
    assert classify_changed_files([changed("docs/status/2026/r1/review.md")]) == "docs-only"
    assert classify_changed_files([changed("docs/goals/phase 7 中文.md", "added")]) == "docs-only"


def test_pagination_exact_page_boundaries():
    for count in (100, 200, 3000):
        served = []

        def fetcher(url, token, count=count, served=served):
            remaining = count - len(served)
            size = min(100, remaining)
            batch = [changed(f"docs/status/{len(served) + i}.md") for i in range(size)]
            served.extend(batch)
            return batch

        files = list_changed_files("https://api.github.test/repos/o/r", 1, count, "t", fetcher)
        assert len(files) == count
        assert classify_changed_files(files) == "docs-only"


@pytest.mark.parametrize(
    "bad_batch",
    [
        lambda: [changed(f"docs/status/{i}.md") for i in range(101)],  # oversized page
        lambda: {"message": "rate limited"},  # error object, not a list
        lambda: None,
        lambda: [],
    ],
)
def test_pagination_malformed_pages_rejected(bad_batch):
    with pytest.raises(ValueError):
        list_changed_files("https://api.github.test/repos/o/r", 1, 100, "t", lambda *_: bad_batch())


def test_pagination_drift_duplicates_fail_closed():
    pages = iter(
        [
            [changed(f"docs/status/{i}.md") for i in range(100)],
            # Second page repeats an entry instead of the real 101st file.
            [changed("docs/status/99.md")],
        ]
    )
    files = list_changed_files(
        "https://api.github.test/repos/o/r", 1, 101, "t", lambda *_: next(pages)
    )
    assert classify_changed_files(files) == "full"


def _write_event(tmp_path, *, changed_files=1, head="h", base="b", number=8, extra=None):
    event = {
        "number": number,
        "pull_request": {
            "number": number,
            "head": {"sha": head},
            "base": {"sha": base},
            "changed_files": changed_files,
        },
    }
    if extra:
        event["pull_request"].update(extra)
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event), encoding="utf-8")
    return {
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_EVENT_PATH": str(path),
        "GITHUB_REPOSITORY": "o/r",
        "GITHUB_TOKEN": "token",
        "GITHUB_API_URL": "https://api.github.test",
    }


def _pr_fetcher(files, *, metadata_seq=None, count=None):
    calls = []
    metas = iter(metadata_seq or [])

    def fetcher(url, token):
        calls.append(url)
        if "/files?" in url:
            return files
        meta = next(metas, None)
        return meta or {
            "number": 8,
            "head": {"sha": "h"},
            "base": {"sha": "b"},
            "changed_files": len(files) if count is None else count,
        }

    fetcher.calls = calls
    return fetcher


def _resolve(env, fetcher):
    return scope.resolve_mode(env, fetcher)[0]


def test_docs_only_happy_path_reads_metadata_twice(tmp_path):
    env = _write_event(tmp_path)
    fetcher = _pr_fetcher([changed("docs/status/a.md")])
    assert _resolve(env, fetcher) == "docs-only"
    assert [("/files?" in url) for url in fetcher.calls] == [False, True, False]
    assert all(url.startswith("https://api.github.test/repos/o/r/pulls/8") for url in fetcher.calls)


def test_pin_guard_happy_path(tmp_path):
    env = _write_event(tmp_path, changed_files=2)
    files = [
        changed("scripts/check_workflow_action_pins.py"),
        changed("tests/test_workflow_action_pins.py"),
    ]
    assert _resolve(env, _pr_fetcher(files)) == "pin-guard-only"


@pytest.mark.parametrize(
    "event_name",
    ["push", "pull_request_target", "workflow_dispatch", "merge_group", "schedule", "", None],
)
def test_every_non_pull_request_event_is_full(event_name):
    env = {} if event_name is None else {"GITHUB_EVENT_NAME": event_name}
    # The fetcher must never be consulted for non-PR events.
    assert scope.resolve_mode(env, lambda *_: pytest.fail("fetched"))[0] == "full"


@pytest.mark.parametrize(
    "error",
    [
        HTTPError("https://api.github.test", 500, "boom", {}, None),
        HTTPError("https://api.github.test", 403, "rate limit", {}, None),
        HTTPError("https://api.github.test", 301, "redirects are not followed", {}, None),
        TimeoutError("timed out"),
        OSError("network unreachable"),
        json.JSONDecodeError("bad", "x", 0),
    ],
)
@pytest.mark.parametrize("fail_on_call", [1, 2, 3])
def test_api_failures_at_any_call_fall_back_to_full(tmp_path, error, fail_on_call):
    env = _write_event(tmp_path)
    inner = _pr_fetcher([changed("docs/status/a.md")])
    calls = []

    def fetcher(url, token):
        calls.append(url)
        if len(calls) == fail_on_call:
            raise error
        return inner(url, token)

    mode, reason = scope.resolve_mode(env, fetcher)
    assert mode == "full"
    assert reason.startswith("scope detection failed closed")


@pytest.mark.parametrize(
    "mutation",
    [
        {"head": {"sha": "pushed-later"}},
        {"base": {"sha": "retargeted"}},
        {"number": 9},
        {"head": None},
        {"head": {}},
        {"base": "b"},
    ],
)
@pytest.mark.parametrize("phase", ["before", "after"])
def test_head_base_or_number_drift_before_or_after_listing_is_full(tmp_path, mutation, phase):
    env = _write_event(tmp_path)
    good = {"number": 8, "head": {"sha": "h"}, "base": {"sha": "b"}, "changed_files": 1}
    bad = {**good, **mutation}
    seq = [bad, good] if phase == "before" else [good, bad]
    assert _resolve(env, _pr_fetcher([changed("docs/status/a.md")], metadata_seq=seq)) == "full"


def test_changed_files_growth_during_listing_is_full(tmp_path):
    env = _write_event(tmp_path)
    good = {"number": 8, "head": {"sha": "h"}, "base": {"sha": "b"}, "changed_files": 1}
    seq = [good, {**good, "changed_files": 2}]
    assert _resolve(env, _pr_fetcher([changed("docs/status/a.md")], metadata_seq=seq)) == "full"


def test_event_count_mismatch_is_full(tmp_path):
    env = _write_event(tmp_path, changed_files=2)
    assert _resolve(env, _pr_fetcher([changed("docs/status/a.md")], count=1)) == "full"


@pytest.mark.parametrize("count", [3001, 0, "1", None, True])
def test_unlistable_counts_fail_closed(tmp_path, count):
    env = _write_event(tmp_path, changed_files=None)
    meta = {"number": 8, "head": {"sha": "h"}, "base": {"sha": "b"}, "changed_files": count}
    fetcher = _pr_fetcher([changed("docs/status/a.md")], metadata_seq=[meta, meta])
    assert _resolve(env, fetcher) == "full"


@pytest.mark.parametrize(
    "env_patch",
    [
        {"GITHUB_EVENT_PATH": "/nonexistent/event.json"},
        {"GITHUB_REPOSITORY": "no-slash"},
        {"GITHUB_REPOSITORY": "a/b/c"},
        {"GITHUB_REPOSITORY": "/r"},
        {"GITHUB_TOKEN": None},
    ],
)
def test_bad_runner_environment_fails_closed(tmp_path, env_patch):
    env = _write_event(tmp_path)
    for key, value in env_patch.items():
        if value is None:
            env.pop(key)
        else:
            env[key] = value
    assert _resolve(env, _pr_fetcher([changed("docs/status/a.md")])) == "full"


@pytest.mark.parametrize(
    "event",
    [
        {},
        {"number": 8},
        {"number": "8", "pull_request": {"head": {"sha": "h"}, "base": {"sha": "b"}}},
        {"number": True, "pull_request": {"head": {"sha": "h"}, "base": {"sha": "b"}}},
        {"number": 8, "pull_request": {"head": {"sha": ""}, "base": {"sha": "b"}}},
        {"number": 8, "pull_request": {"number": 7, "head": {"sha": "h"}, "base": {"sha": "b"}}},
    ],
)
def test_malformed_event_payload_fails_closed(tmp_path, event):
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event), encoding="utf-8")
    env = {
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_EVENT_PATH": str(path),
        "GITHUB_REPOSITORY": "o/r",
        "GITHUB_TOKEN": "t",
    }
    assert _resolve(env, _pr_fetcher([changed("docs/status/a.md")])) == "full"


def test_unknown_mode_from_detector_degrades_to_full(monkeypatch):
    monkeypatch.setattr(scope, "detect_scope", lambda *_: ("turbo", "made up"))
    assert scope.resolve_mode({})[0] == "full"


def test_main_writes_only_an_allowlisted_mode(tmp_path, capsys):
    output = tmp_path / "out"
    env = _write_event(tmp_path)
    env["GITHUB_OUTPUT"] = str(output)

    def exploding(url, token):
        raise OSError("api down")

    assert scope.main(env, exploding) == 0
    assert output.read_text(encoding="utf-8") == "mode=full\n"
    assert "failed closed" in capsys.readouterr().err

    output.unlink()
    assert scope.main(env, _pr_fetcher([changed("docs/status/a.md")])) == 0
    assert output.read_text(encoding="utf-8") == "mode=docs-only\n"


def test_main_never_echoes_pr_controlled_filenames(tmp_path, capsys):
    output = tmp_path / "out"
    env = _write_event(tmp_path)
    env["GITHUB_OUTPUT"] = str(output)
    evil = "docs/status/x.md\nmode=docs-only"
    assert scope.main(env, _pr_fetcher([changed(evil)])) == 0
    assert output.read_text(encoding="utf-8") == "mode=full\n"
    assert evil not in capsys.readouterr().out


def test_fetch_json_rejects_non_https_and_missing_token():
    with pytest.raises(ValueError):
        scope.fetch_json("http://api.github.test/x", "t")
    with pytest.raises(ValueError):
        scope.fetch_json("https://api.github.test/x", "")


def test_fetch_json_keeps_token_off_redirects_and_never_follows_them():
    from urllib.request import Request

    handler = scope._RejectRedirects()
    req = Request("https://api.github.test/x")
    req.add_unredirected_header("Authorization", "Bearer t")
    with pytest.raises(HTTPError):
        handler.redirect_request(req, None, 301, "Moved", {}, "https://evil.test/x")
    # Authorization is stored as an unredirected header, never copied on redirect.
    assert "Authorization" not in req.headers
    assert req.unredirected_hdrs["Authorization"] == "Bearer t"


# --- Boundary composition: real fetcher guards must hold through resolve_mode ----------


def test_http_api_url_fails_closed_through_real_fetcher(tmp_path):
    # The scheme guard lives in the real fetch_json before any network I/O, so
    # the production path (no injected fetcher) must degrade to full offline.
    env = _write_event(tmp_path)
    env["GITHUB_API_URL"] = "http://api.github.test"
    mode, reason = scope.resolve_mode(env)
    assert mode == "full"
    assert reason.startswith("scope detection failed closed")
    assert "https" in reason


def test_empty_token_fails_closed_through_real_fetcher(tmp_path):
    env = _write_event(tmp_path)
    env["GITHUB_TOKEN"] = ""
    mode, reason = scope.resolve_mode(env, scope.fetch_json)
    assert mode == "full"
    assert reason.startswith("scope detection failed closed")


def test_non_object_event_payload_fails_closed(tmp_path):
    path = tmp_path / "event.json"
    path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    env = {
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_EVENT_PATH": str(path),
        "GITHUB_REPOSITORY": "o/r",
        "GITHUB_TOKEN": "t",
    }
    assert _resolve(env, _pr_fetcher([changed("docs/status/a.md")])) == "full"


def test_empty_filename_fails_closed():
    assert classify_changed_files([changed("")]) == "full"


# --- Workflow structure: main keeps the full matrix, fast paths stay narrow ----------

_CONDITION_PREFIX = "steps.scope.outputs.mode "


def _ci():
    return yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))


def _steps():
    return _ci()["jobs"]["test"]["steps"]


def _runs(step, mode):
    condition = step.get("if")
    if condition is None:
        return True
    assert condition.startswith(_CONDITION_PREFIX), condition
    op, _, literal = condition[len(_CONDITION_PREFIX):].partition(" ")
    value = literal.strip("'")
    assert value in scope.MODES, condition
    assert op in ("==", "!="), condition
    return (mode == value) if op == "==" else (mode != value)


def test_workflow_triggers_permissions_and_concurrency():
    ci = _ci()
    triggers = ci.get("on", ci.get(True))
    assert triggers["push"] == {"branches": ["main"]}
    assert "pull_request" in triggers
    assert "pull_request_target" not in triggers
    assert ci["permissions"] == {"contents": "read", "pull-requests": "read"}
    assert "permissions" not in ci["jobs"]["test"]
    concurrency = ci["concurrency"]
    # PR runs share a per-PR group; each main push uses its unique run id.
    assert concurrency["group"] == (
        "ci-${{ github.workflow }}-${{ github.event.pull_request.number || github.run_id }}"
    )
    assert concurrency["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"


def test_single_required_check_name_is_preserved():
    assert list(_ci()["jobs"]) == ["test"]


def test_scope_step_runs_first_and_is_asserted():
    names = [step["name"] for step in _steps()]
    scope_index = names.index("Classify PR changes (fail closed)")
    assert _steps()[scope_index]["id"] == "scope"
    assert _steps()[scope_index]["env"] == {"GITHUB_TOKEN": "${{ github.token }}"}
    assert names[scope_index + 1] == "Assert CI scope is a known mode"
    # Only checkout and Python setup may precede classification.
    assert names[:scope_index] == ["Check out repository", "Set up Python"]
    assert all("if" not in step for step in _steps()[: scope_index + 2])


def test_full_mode_runs_every_verification_step():
    skipped_in_full = [s["name"] for s in _steps() if not _runs(s, "full")]
    assert skipped_in_full == ["Test action pin guard (PR fast path)"]
    run_cmds = " ".join(s.get("run", "") for s in _steps() if _runs(s, "full"))
    for required in (
        "pip install",
        "check_workflow_action_pins.py",
        "ruff check",
        "config validate",
        "python -m pytest -n auto --dist loadgroup --durations=30",
        "systemd-analyze verify",
        "export_surface_openapi.py --check",
        "dashboard lint",
        "dashboard typecheck",
        "dashboard test --run",
        "dashboard build",
        "security:client-bundle",
        "wrangler deploy --dry-run",
        "dashboard_cross_stack_smoke.py",
    ):
        assert required in run_cmds, required


def test_ci_pins_the_measured_fast_supported_interpreter():
    """CI runs the suite on Python 3.13, within ``requires-python``.

    Efficiency R4 measured the deterministic suite on identical dependency
    versions (pydantic 2.14.3 / core 2.50.4), identical flags
    (``-n 4 --dist loadgroup``) and one host: Python 3.11 median ~81.2 s vs
    3.13 median ~68.2 s — a ~16 % pytest wall/CPU reduction with byte-identical
    results (7763 passed / 2 skipped / 9 warnings) and a byte-identical
    ``export_surface_openapi.py --check`` output. Python 3.14 measured slower
    than 3.13 on this suite (~75.0 s). Reverting the pin to 3.11 would
    silently give back ~26-40 s per full CI run, so the pin is contractual;
    moving to a newer interpreter is a measured decision, not a drive-by.
    """

    setup = next(s for s in _steps() if s["name"] == "Set up Python")
    assert setup["with"]["python-version"] == "3.13"
    assert setup["with"]["cache"] == "pip"


def test_docs_only_mode_runs_no_tests_or_installs():
    names = [s["name"] for s in _steps() if _runs(s, "docs-only")]
    assert names == [
        "Check out repository",
        "Set up Python",
        "Classify PR changes (fail closed)",
        "Assert CI scope is a known mode",
    ]


def test_pin_guard_mode_runs_guard_ruff_and_focused_tests_only():
    names = [s["name"] for s in _steps() if _runs(s, "pin-guard-only")]
    assert names == [
        "Check out repository",
        "Set up Python",
        "Classify PR changes (fail closed)",
        "Assert CI scope is a known mode",
        "Install development, API and provenance dependencies",
        "Check workflow action pins",
        "Run Ruff",
        "Test action pin guard (PR fast path)",
    ]
    focused = next(s for s in _steps() if s["name"] == "Test action pin guard (PR fast path)")
    assert focused["run"].startswith("python -m pytest tests/test_workflow_action_pins.py")
