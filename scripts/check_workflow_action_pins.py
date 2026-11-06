"""Static guard for GitHub Actions supply-chain provenance in repository workflows.

Phase-2 fast-path verification probe (2026-11-06): comment-only change; behavior is unchanged.

Every external ``uses:`` reference in the repository's workflow files must point
at an immutable full 40-character commit SHA and carry a trailing ``# vX.Y.Z``
version comment so the pinned commit stays traceable to an upstream release.
The annotation must be the complete three-component ``vX.Y.Z`` form anchored at
the end of the line; truncated (``# v7.1``), over-long (``# v7.0.1.4``) or
suffixed (``# v7.1abc``) annotations are rejected. Local composite actions
(``./...``) are out of scope; ``docker://`` references cannot be commit-pinned
and are rejected explicitly.

Every *effective* YAML ``uses`` occurrence (located through PyYAML node marks,
the authoritative view) is bound to its own source line and validated there: a
reference and its ``# vX.Y.Z`` annotation are only accepted when one plain
``uses: <ref> # vX.Y.Z`` scan line carries exactly that occurrence's value at
exactly that occurrence's line. Scanned ``uses:`` text that is no real
occurrence (run-block decoys, unusual encodings) and real occurrences that are
invisible to the line scanner (quoted ``'uses':`` keys, block scalars,
multi-line values, aliases) each fail closed, so an annotated decoy line can
never authorize a different actual action occurrence. Duplicate ``uses`` keys
in one mapping are rejected as an ambiguous encoding.

PyYAML aliases reuse node objects, so the composed structure is a graph, not
necessarily a tree. The collector traverses it with per-node memoization: a
node reached while still being processed is a cyclic alias graph and a node
reached again after completion is an alias re-reference. Cyclic graphs are
rejected with a controlled ``path:line`` diagnostic (never an uncaught
``RecursionError``), and a ``uses``-bearing subtree reached through an alias is
rejected because its single annotated source line would have to authorize
multiple effective occurrences. Anchors whose subtree contains no ``uses`` key
are harmless and stay clean, and the memoized traversal stays linear in unique
nodes plus alias references, so alias fan-out cannot cause exponential work.
A memoized alias re-reference additionally never re-expands the shared
subtree's occurrences into the caller's list, so the materialized occurrence
multiset and every diagnostic stay bounded by unique nodes and distinct
source ``uses`` lines instead of root-to-node paths.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_TARGET = Path(__file__).resolve().parents[1] / ".github" / "workflows"

COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
VERSION_COMMENT_PATTERN = re.compile(r"#\s*v\d+\.\d+\.\d+\s*$")
USES_LINE_PATTERN = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<ref>[^\s#]+)(?P<rest>.*)$")
BLOCK_SCALAR_INDICATOR = re.compile(r"^[|>][+-]?$")

# Value reported for a `uses` mapping whose value is not a plain YAML scalar
# (alias or collection). The spaces guarantee it can never equal a raw scan
# token, so such occurrences always fail closed as unbindable.
NONSCALAR_USES_VALUE = "<non-scalar 'uses:' value>"


@dataclass(frozen=True)
class _SubtreeUses:
    """``uses`` occurrences collected inside one composed YAML subtree, plus
    whether the subtree contains any ``uses`` key at all (shared-alias
    detection must fire even when the occurrences themselves fail line
    binding) and the subtree's first ``uses`` source line. ``first_uses_line``
    is derived from the node structure during the fresh traversal, so the
    shared-alias diagnostic anchor stays exact even when a compact
    (non-re-expanded) occurrence list no longer carries every entry."""

    occurrences: tuple[tuple[int, str, int], ...]
    has_uses: bool
    first_uses_line: int | None = None


@dataclass
class _AliasGraphState:
    """Graph-safe traversal state for one composed YAML document.

    ``active`` holds node ids on the current depth-first path (a node reached
    while active is a back-edge: a cyclic alias graph). ``done`` memoizes each
    node's subtree result, which both bounds alias fan-out DAGs to linear work
    and identifies a completed node reached again as an alias re-reference.
    ``alias_ref_result`` is set at every collector return so the caller can
    tell a fresh child traversal from a memoized alias re-reference and never
    re-expand a shared subtree's occurrences into its own list."""

    active: set[int] = field(default_factory=set)
    done: dict[int, _SubtreeUses] = field(default_factory=dict)
    reported_shared: set[int] = field(default_factory=set)
    reported_cycles: set[int] = field(default_factory=set)
    reported_violations: set[tuple[int, str]] = field(default_factory=set)
    duplicate_key_lines: list[int] = field(default_factory=list)
    graph_violations: list[tuple[int, str]] = field(default_factory=list)
    # True when the most recent collector return was a memoized alias
    # re-reference; callers read it immediately after each child call,
    # before any other call can overwrite it.
    alias_ref_result: bool = False


def _record_graph_violation(
    state: _AliasGraphState, line: int, message: str
) -> None:
    """Append one graph diagnostic, deduplicated on its exact
    ``(line, message)`` pair, so repeated sharing that anchors equivalent
    subtrees (for example a doubling alias DAG whose every level resolves to
    the same ``uses`` source line) yields one diagnostic per distinct source
    line, never one per alias re-reference."""
    key = (line, message)
    if key in state.reported_violations:
        return
    state.reported_violations.add(key)
    state.graph_violations.append(key)


def _collect_yaml_use_occurrences(
    node: Any,
    _state: _AliasGraphState | None = None,
) -> _SubtreeUses:
    """Walk the composed YAML node graph and return every effective ``uses``
    occurrence in this subtree as ``(key_line, value, value_line)`` (1-based
    lines, value normalized like the raw scan).

    Graph safety: each node object is processed exactly once. A node reached
    while still being processed is a cyclic alias graph; a node reached again
    after completion is an alias re-reference whose subtree would authorize
    several effective occurrences with one set of source lines. Both are
    reported through ``_state.graph_violations`` as controlled diagnostics by
    the caller, never as unbounded recursion.

    Occurrences are additionally never re-expanded through alias
    re-references: a caller receiving a memoized result (signalled through
    ``_state.alias_ref_result``, set at every return) keeps the child's
    ``has_uses`` flag but does not copy its occurrences again, so a fan-out
    DAG materializes at most one entry per distinct source ``uses`` key per
    node instead of one per root-to-node path. The skipped entries are exact
    duplicates of the defining reference's occurrences and their subtree
    sharing is already a reported violation, so no binding diagnostic is
    lost."""
    if _state is None:
        _state = _AliasGraphState()
    node_id = id(node)
    completed = _state.done.get(node_id)
    if completed is not None:
        if completed.has_uses and node_id not in _state.reported_shared:
            _state.reported_shared.add(node_id)
            first_line = completed.first_uses_line
            if first_line is None:  # defensive: unreachable while has_uses
                first_line = node.start_mark.line + 1
            _record_graph_violation(
                _state,
                first_line,
                "'uses:' occurrence is shared through a YAML alias: one "
                "annotated source line cannot authorize multiple effective "
                "action references",
            )
        _state.alias_ref_result = True
        return completed
    if node_id in _state.active:
        if node_id not in _state.reported_cycles:
            _state.reported_cycles.add(node_id)
            _record_graph_violation(
                _state,
                node.start_mark.line + 1,
                "cyclic YAML alias graph (an anchor is referenced inside "
                "its own definition); refusing to traverse",
            )
        _state.alias_ref_result = False
        return _SubtreeUses((), False)
    _state.active.add(node_id)
    occurrences: list[tuple[int, str, int]] = []
    has_uses = False
    first_uses_line: int | None = None
    if isinstance(node, yaml.MappingNode):
        uses_pairs = [
            (key_node, value_node)
            for key_node, value_node in node.value
            if isinstance(key_node, yaml.ScalarNode) and key_node.value == "uses"
        ]
        if uses_pairs:
            has_uses = True
            first_uses_line = uses_pairs[0][0].start_mark.line + 1
        if len(uses_pairs) > 1:
            _state.duplicate_key_lines.append(uses_pairs[1][0].start_mark.line + 1)
        for key_node, value_node in uses_pairs:
            raw_value = value_node.value if isinstance(value_node, yaml.ScalarNode) else None
            value = (
                raw_value.strip().strip("'\"")
                if isinstance(raw_value, str)
                else NONSCALAR_USES_VALUE
            )
            occurrences.append(
                (
                    key_node.start_mark.line + 1,
                    value,
                    value_node.start_mark.line + 1,
                )
            )
        for _key_node, value_node in node.value:
            child = _collect_yaml_use_occurrences(value_node, _state)
            if not _state.alias_ref_result:
                occurrences.extend(child.occurrences)
            has_uses = has_uses or child.has_uses
            if child.first_uses_line is not None:
                first_uses_line = (
                    child.first_uses_line
                    if first_uses_line is None
                    else min(first_uses_line, child.first_uses_line)
                )
    elif isinstance(node, yaml.SequenceNode):
        for item in node.value:
            child = _collect_yaml_use_occurrences(item, _state)
            if not _state.alias_ref_result:
                occurrences.extend(child.occurrences)
            has_uses = has_uses or child.has_uses
            if child.first_uses_line is not None:
                first_uses_line = (
                    child.first_uses_line
                    if first_uses_line is None
                    else min(first_uses_line, child.first_uses_line)
                )
    _state.active.discard(node_id)
    result = _SubtreeUses(tuple(occurrences), has_uses, first_uses_line)
    _state.done[node_id] = result
    _state.alias_ref_result = False
    return result


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
    """Return a deterministic list of violation messages for one workflow file."""
    violations: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return [f"{path}: unreadable workflow file: {error}"]

    try:
        documents = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
    except yaml.YAMLError as error:
        return [f"{path}: unparseable workflow YAML: {error}"]
    if len(documents) != 1 or not isinstance(documents[0], yaml.MappingNode):
        return [f"{path}: workflow document is not a YAML mapping"]

    state = _AliasGraphState()
    root = _collect_yaml_use_occurrences(documents[0], state)
    occurrences = list(root.occurrences)
    raw_uses = _scan_raw_uses(text)
    raw_by_line = {lineno: (ref, rest) for lineno, ref, rest in raw_uses}

    for line, message in state.graph_violations:
        violations.append(f"{path}:{line}: {message}")

    for line in state.duplicate_key_lines:
        violations.append(
            f"{path}:{line}: duplicate 'uses' key in one mapping "
            "(ambiguous encoding)"
        )

    # Occurrence-level binding: a real `uses` occurrence is only authorized by
    # the single plain scan line at its own value line carrying exactly its
    # own value. Anything else (quoted keys, block scalars, multi-line values,
    # aliases, decoy balancing) fails closed instead of being guessed away.
    bound_lines: set[int] = set()
    for key_line, value, value_line in occurrences:
        entry = raw_by_line.get(value_line)
        if entry is None or entry[0] != value:
            violations.append(
                f"{path}:{key_line}: 'uses:' value {value!r} invisible to the "
                "line scanner (multi-line or quoted encoding); every action "
                "reference must be one plain 'uses: <ref> # vX.Y.Z' source line"
            )
            continue
        bound_lines.add(value_line)
        ref, rest = entry
        if ref.startswith("./"):
            continue
        if ref.startswith("docker://"):
            violations.append(
                f"{path}:{value_line}: docker:// reference {ref!r} cannot be commit-pinned"
            )
            continue
        _repo, separator, commit = ref.partition("@")
        if not separator:
            violations.append(
                f"{path}:{value_line}: external reference {ref!r} carries no '@ref'"
            )
            continue
        if not COMMIT_SHA_PATTERN.match(commit):
            violations.append(
                f"{path}:{value_line}: external reference {ref!r} is not pinned to a "
                "full 40-character commit SHA"
            )
        if VERSION_COMMENT_PATTERN.search(rest) is None:
            violations.append(
                f"{path}:{value_line}: pinned reference {ref!r} lacks a '# vX.Y.Z' "
                "version comment"
            )

    # Scanned `uses:` text that is not any real occurrence at that line is
    # run-block text, a decoy line or an unusual encoding; it can never
    # authorize a different actual occurrence.
    for lineno, ref, _rest in raw_uses:
        if lineno in bound_lines:
            continue
        violations.append(
            f"{path}:{lineno}: 'uses:' text invisible to YAML keys "
            f"(run-block text or unusual encoding): {ref!r}"
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
