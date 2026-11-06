"""Fail-closed PR scope classification for GitHub Actions.

Only documentation changes in non-executable status/goal notes and isolated
action-pin guard changes qualify for shorter PR checks. All main pushes and
unclassifiable PRs receive the full CI suite.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen

_PAGE_SIZE = 100
_MAX_FILES = 3000
_DOC_PREFIXES = ("docs/goals/", "docs/status/")
_PIN_GUARD_FILES = frozenset(
    {"scripts/check_workflow_action_pins.py", "tests/test_workflow_action_pins.py"}
)
_SAFE_STATUSES = frozenset({"added", "modified"})


def classify_changed_files(files: object) -> str:
    """Return a fast-path mode only for an exact, narrow file allowlist."""
    if not isinstance(files, list) or not files:
        return "full"

    filenames: list[str] = []
    for entry in files:
        if not isinstance(entry, dict) or entry.get("status") not in _SAFE_STATUSES:
            return "full"
        filename = entry.get("filename")
        if not isinstance(filename, str) or not filename:
            return "full"
        filenames.append(filename)

    if all(
        name.endswith(".md") and name.startswith(_DOC_PREFIXES) for name in filenames
    ):
        return "docs-only"
    if all(name in _PIN_GUARD_FILES for name in filenames):
        return "pin-guard-only"
    return "full"


def fetch_json(url: str, token: str) -> object:
    """Read only GitHub metadata; no pull-request code is executed here."""
    if not token:
        raise ValueError("GITHUB_TOKEN is missing")
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def list_changed_files(
    repo_api_url: str, number: int, expected_count: int, token: str, fetcher=fetch_json
) -> list[dict]:
    """Require the complete paginated diff; partial/truncated results fail closed."""
    if (
        isinstance(expected_count, bool)
        or not isinstance(expected_count, int)
        or not 1 <= expected_count <= _MAX_FILES
    ):
        raise ValueError("invalid or excessive PR changed-files count")

    files: list[dict] = []
    pages = (expected_count + _PAGE_SIZE - 1) // _PAGE_SIZE
    for page in range(1, pages + 1):
        url = (
            f"{repo_api_url}/pulls/{number}/files"
            f"?per_page={_PAGE_SIZE}&page={page}"
        )
        batch = fetcher(url, token)
        expected_page_size = min(_PAGE_SIZE, expected_count - len(files))
        if not isinstance(batch, list) or len(batch) != expected_page_size:
            raise ValueError("PR changed-files response is incomplete")
        files.extend(batch)

    if len(files) != expected_count:
        raise ValueError("PR changed-files count mismatch")
    return files


def detect_scope(environ: dict[str, str], fetcher=fetch_json) -> tuple[str, str]:
    if environ.get("GITHUB_EVENT_NAME") != "pull_request":
        return "full", "non-PR event requires full CI"

    event = json.loads(Path(environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    pr = event["pull_request"]
    number = event["number"]
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise ValueError("invalid PR number")

    repo = environ["GITHUB_REPOSITORY"]
    if repo.count("/") != 1:
        raise ValueError("invalid repository name")
    api_url = environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    repo_api_url = f"{api_url}/repos/{repo}"
    token = environ["GITHUB_TOKEN"]
    expected_head = pr["head"]["sha"]
    expected_base = pr["base"]["sha"]

    def snapshot_matches(metadata: object) -> bool:
        return (
            isinstance(metadata, dict)
            and metadata.get("number") == number
            and metadata.get("head", {}).get("sha") == expected_head
            and metadata.get("base", {}).get("sha") == expected_base
        )

    # PR file-list APIs expose the *current* head, not the event's immutable
    # head. Check before and after pagination so a concurrent push or base
    # update cannot silently turn an old code-changing run into a docs fast path.
    url = f"{repo_api_url}/pulls/{number}"
    before = fetcher(url, token)
    if not snapshot_matches(before):
        return "full", "PR head/base changed before scope detection"
    count = before["changed_files"]
    event_count = pr.get("changed_files")
    if event_count is not None and event_count != count:
        return "full", "PR changed-files count differs from triggering event"

    files = list_changed_files(repo_api_url, number, count, token, fetcher)
    after = fetcher(url, token)
    if not snapshot_matches(after) or after.get("changed_files") != count:
        return "full", "PR changed during scope detection"

    mode = classify_changed_files(files)
    return mode, f"{count} changed files; scope={mode}"


def main() -> None:
    mode = "full"
    try:
        mode, reason = detect_scope(dict(os.environ))
    except Exception as exc:
        reason = f"scope detection failed closed: {type(exc).__name__}: {exc}"
        print(f"::warning::{reason}", file=sys.stderr)

    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"mode={mode}\n")
    print(f"CI scope: {mode} ({reason})")


if __name__ == "__main__":
    main()
