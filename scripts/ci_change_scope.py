"""Fail-closed PR scope classification for GitHub Actions.

Only documentation changes in non-executable status/goal notes and isolated
action-pin guard changes qualify for shorter PR checks. All main pushes and
unclassifiable PRs receive the full CI suite.

Every error path (missing/malformed event, GitHub API failure, redirect,
oversized or truncated response, pagination drift, head/base movement) yields
``full``. The only value ever written to ``GITHUB_OUTPUT`` is one of
:data:`MODES`; PR-controlled file names are never echoed into step outputs.
"""

from __future__ import annotations

import json
import os
import posixpath
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

FULL = "full"
DOCS_ONLY = "docs-only"
PIN_GUARD_ONLY = "pin-guard-only"
MODES = frozenset({FULL, DOCS_ONLY, PIN_GUARD_ONLY})

_PAGE_SIZE = 100
# GitHub's "list pull request files" endpoint returns at most 3000 files.
_MAX_FILES = 3000
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_TIMEOUT_SECONDS = 10
_DOC_PREFIXES = ("docs/goals/", "docs/status/")
_PIN_GUARD_FILES = frozenset(
    {"scripts/check_workflow_action_pins.py", "tests/test_workflow_action_pins.py"}
)
_SAFE_STATUSES = frozenset({"added", "modified"})

Fetcher = Callable[[str, str], object]


def _is_canonical_relative_path(name: str) -> bool:
    """Reject anything that is not a plain, normalized, repository-relative path."""
    return (
        bool(name)
        and name.isprintable()
        and "\\" not in name
        and not name.startswith("/")
        and not name.endswith("/")
        and posixpath.normpath(name) == name
        and not any(part in ("", ".", "..") for part in name.split("/"))
    )


def classify_changed_files(files: object) -> str:
    """Return a fast-path mode only for an exact, narrow file allowlist."""
    if not isinstance(files, list) or not files:
        return FULL

    filenames: list[str] = []
    for entry in files:
        if not isinstance(entry, dict) or entry.get("status") not in _SAFE_STATUSES:
            return FULL
        filename = entry.get("filename")
        if not isinstance(filename, str) or not _is_canonical_relative_path(filename):
            return FULL
        filenames.append(filename)

    if len(set(filenames)) != len(filenames):
        # Duplicate entries mean the paginated listing drifted; never trust it.
        return FULL
    if all(
        name.endswith(".md") and name.startswith(_DOC_PREFIXES) for name in filenames
    ):
        return DOCS_ONLY
    if all(name in _PIN_GUARD_FILES for name in filenames):
        return PIN_GUARD_ONLY
    return FULL


class _RejectRedirects(HTTPRedirectHandler):
    """Never follow redirects: they could forward the token or change the source."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        raise HTTPError(req.full_url, code, "redirects are not followed", headers, fp)


def fetch_json(url: str, token: str) -> object:
    """Read only GitHub metadata; no pull-request code is executed here."""
    if not token:
        raise ValueError("GITHUB_TOKEN is missing")
    if urlsplit(url).scheme != "https":
        raise ValueError("GitHub API URL must use https")
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    request.add_unredirected_header("Authorization", f"Bearer {token}")
    opener = build_opener(_RejectRedirects)
    with opener.open(request, timeout=_TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise ValueError(f"unexpected GitHub API status {response.status}")
        body = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(body) > _MAX_RESPONSE_BYTES:
        raise ValueError("GitHub API response exceeds size limit")
    return json.loads(body)


def list_changed_files(
    repo_api_url: str,
    number: int,
    expected_count: int,
    token: str,
    fetcher: Fetcher = fetch_json,
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


def _sha(container: object, key: str) -> object:
    ref = container.get(key) if isinstance(container, dict) else None
    return ref.get("sha") if isinstance(ref, dict) else None


def detect_scope(
    environ: Mapping[str, str], fetcher: Fetcher = fetch_json
) -> tuple[str, str]:
    if environ.get("GITHUB_EVENT_NAME") != "pull_request":
        return FULL, "non-PR event requires full CI"

    event = json.loads(Path(environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    pr = event["pull_request"]
    number = event["number"]
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise ValueError("invalid PR number")
    if pr.get("number", number) != number:
        raise ValueError("event PR number mismatch")

    repo = environ["GITHUB_REPOSITORY"]
    if repo.count("/") != 1 or not all(repo.split("/")):
        raise ValueError("invalid repository name")
    api_url = environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    repo_api_url = f"{api_url}/repos/{repo}"
    token = environ["GITHUB_TOKEN"]
    expected_head = _sha(pr, "head")
    expected_base = _sha(pr, "base")
    if not isinstance(expected_head, str) or not isinstance(expected_base, str):
        raise ValueError("event head/base SHA missing")
    if not expected_head or not expected_base:
        raise ValueError("event head/base SHA missing")

    def snapshot_matches(metadata: object) -> bool:
        return (
            isinstance(metadata, dict)
            and metadata.get("number") == number
            and _sha(metadata, "head") == expected_head
            and _sha(metadata, "base") == expected_base
        )

    # PR file-list APIs expose the *current* head, not the event's immutable
    # head. Check before and after pagination so a concurrent push or base
    # update cannot silently turn an old code-changing run into a docs fast path.
    url = f"{repo_api_url}/pulls/{number}"
    before = fetcher(url, token)
    if not snapshot_matches(before):
        return FULL, "PR head/base changed before scope detection"
    count = before["changed_files"]
    event_count = pr.get("changed_files")
    if event_count is not None and event_count != count:
        return FULL, "PR changed-files count differs from triggering event"

    files = list_changed_files(repo_api_url, number, count, token, fetcher)
    after = fetcher(url, token)
    if not snapshot_matches(after) or after.get("changed_files") != count:
        return FULL, "PR changed during scope detection"

    mode = classify_changed_files(files)
    return mode, f"{count} changed files; scope={mode}"


def resolve_mode(
    environ: Mapping[str, str], fetcher: Fetcher = fetch_json
) -> tuple[str, str]:
    """Never raise: any detection failure or unknown mode degrades to full CI."""
    try:
        mode, reason = detect_scope(environ, fetcher)
    except Exception as exc:  # noqa: BLE001 - fail closed on every error class
        return FULL, f"scope detection failed closed: {type(exc).__name__}: {exc}"
    if mode not in MODES:
        return FULL, f"unknown scope {mode!r} failed closed"
    return mode, reason


def main(environ: Mapping[str, str] | None = None, fetcher: Fetcher = fetch_json) -> int:
    env = os.environ if environ is None else environ
    mode, reason = resolve_mode(env, fetcher)
    if mode == FULL and reason.startswith(("scope detection failed", "unknown scope")):
        print(f"::warning::{reason}", file=sys.stderr)

    with open(env["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"mode={mode}\n")
    print(f"CI scope: {mode} ({reason})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
