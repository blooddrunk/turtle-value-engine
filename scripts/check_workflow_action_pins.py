"""Static guard for GitHub Actions supply-chain provenance in repository workflows.

Every external ``uses:`` reference in the repository's workflow files must point
at an immutable full 40-character commit SHA and carry a trailing ``# vX.Y.Z``
version comment so the pinned commit stays traceable to an upstream release.
The annotation must be the complete three-component ``vX.Y.Z`` form anchored at
the end of the line; truncated (``# v7.1``), over-long (``# v7.0.1.4``) or
suffixed (``# v7.1abc``) annotations are rejected. Local composite actions
(``./...``) are out of scope; ``docker://`` references cannot be commit-pinned
and are rejected explicitly.

References are extracted both from the parsed YAML (the authoritative view) and
from a raw line scan (the only place comments survive); the two views are
compared as multisets of occurrences so a repeated reference cannot cancel a
scanner-invisible duplicate (for example a quoted ``'uses':`` key), and any
divergence in value or count fails closed instead of being guessed away.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

DEFAULT_TARGET = Path(__file__).resolve().parents[1] / ".github" / "workflows"

COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
VERSION_COMMENT_PATTERN = re.compile(r"#\s*v\d+\.\d+\.\d+\s*$")
USES_LINE_PATTERN = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<ref>[^\s#]+)(?P<rest>.*)$")
BLOCK_SCALAR_INDICATOR = re.compile(r"^[|>][+-]?$")


def _collect_yaml_uses(node: Any, found: Counter[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "uses" and isinstance(value, str):
                found[value.strip().strip("'\"")] += 1
            _collect_yaml_uses(value, found)
    elif isinstance(node, list):
        for item in node:
            _collect_yaml_uses(item, found)


def _scan_raw_uses(text: str) -> list[tuple[int, str, str]]:
    entries: list[tuple[int, str, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = USES_LINE_PATTERN.match(line)
        if match is None:
            continue
        ref = match.group("ref").strip().strip("'\"")
        if BLOCK_SCALAR_INDICATOR.match(ref):
            # A block-scalar indicator means the real value lives on the
            # following lines; the divergence check reports it via the
            # YAML-derived set instead of guessing here.
            continue
        entries.append((lineno, ref, match.group("rest")))
    return entries


def check_workflow_file(path: Path) -> list[str]:
    """Return a sorted list of violation messages for one workflow file."""
    violations: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return [f"{path}: unreadable workflow file: {error}"]

    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        return [f"{path}: unparseable workflow YAML: {error}"]
    if not isinstance(document, dict):
        return [f"{path}: workflow document is not a YAML mapping"]

    yaml_uses: Counter[str] = Counter()
    _collect_yaml_uses(document, yaml_uses)
    raw_uses = _scan_raw_uses(text)
    raw_refs: Counter[str] = Counter(ref for _, ref, _ in raw_uses)

    # Multiset comparison: Counter subtraction keeps only positive deltas, so a
    # scanner-invisible duplicate of an already-scanned reference (quoted
    # 'uses': key, second run-block echo of the same ref) can no longer cancel
    # out against the set-based view.
    only_raw = sorted((raw_refs - yaml_uses).elements())
    only_yaml = sorted((yaml_uses - raw_refs).elements())
    if only_raw:
        violations.append(
            f"{path}: 'uses:' text invisible to YAML keys (run-block text or "
            f"unusual encoding): {only_raw}"
        )
    if only_yaml:
        violations.append(
            f"{path}: 'uses:' values invisible to the line scanner "
            f"(multi-line or quoted encoding): {only_yaml}"
        )

    for lineno, ref, rest in raw_uses:
        if ref.startswith("./"):
            continue
        if ref.startswith("docker://"):
            violations.append(
                f"{path}:{lineno}: docker:// reference {ref!r} cannot be commit-pinned"
            )
            continue
        _repo, separator, commit = ref.partition("@")
        if not separator:
            violations.append(
                f"{path}:{lineno}: external reference {ref!r} carries no '@ref'"
            )
            continue
        if not COMMIT_SHA_PATTERN.match(commit):
            violations.append(
                f"{path}:{lineno}: external reference {ref!r} is not pinned to a "
                "full 40-character commit SHA"
            )
        if VERSION_COMMENT_PATTERN.search(rest) is None:
            violations.append(
                f"{path}:{lineno}: pinned reference {ref!r} lacks a '# vX.Y.Z' "
                "version comment"
            )
    return violations


def _resolve_targets(arguments: list[str]) -> list[Path] | None:
    if not arguments:
        arguments = [str(DEFAULT_TARGET)]
    files: list[Path] = []
    for argument in arguments:
        path = Path(argument)
        if path.is_dir():
            files.extend(sorted(path.rglob("*.yml")))
            files.extend(sorted(path.rglob("*.yaml")))
        elif path.is_file():
            files.append(path)
        else:
            print(f"error: no such file or directory: {path}", file=sys.stderr)
            return None
    if not files:
        print("error: no workflow files found to check", file=sys.stderr)
        return None
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "targets",
        nargs="*",
        help="workflow files or directories to check (default: .github/workflows)",
    )
    args = parser.parse_args(argv)

    files = _resolve_targets(args.targets)
    if files is None:
        return 2

    violations: list[str] = []
    for path in files:
        violations.extend(check_workflow_file(path))
    if violations:
        for violation in violations:
            print(f"action-pin guard: {violation}")
        print(
            f"action-pin guard: {len(violations)} violation(s) across {len(files)} "
            "workflow file(s); external actions must be pinned to full 40-hex "
            "commit SHAs with '# vX.Y.Z' comments"
        )
        return 1
    print(
        f"action-pin guard: all external 'uses:' references pinned "
        f"({len(files)} workflow file(s) checked)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
