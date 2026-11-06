"""Deterministic red/green coverage for the workflow action-pin guard.

The pre-change workflow text below reproduces the exact mutable tag references
that `ci/pin-action-shas-issue43-20261030` replaced (checkout@v7.0.1,
setup-python@v7.1.0, setup-node@v7.1.0); the guard must reject it, accept the
pinned repository workflows, and fail closed on every evasion class.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import scripts.check_workflow_action_pins as guard

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

PRE_CHANGE_WORKFLOW = """\
name: CI
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@v7.0.1

      - name: Set up Python
        uses: actions/setup-python@v7.1.0
        with:
          python-version: "3.11"
          cache: pip

      - name: Set up Node
        uses: actions/setup-node@v7.1.0
        with:
          node-version: "24"
"""

PINNED_STEP_TEMPLATE = """\
name: CI
on:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: One step
        uses: {reference}
"""

VERIFIED_PINS = {
    "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1",
    "actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0",
    "actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7.1.0",
}


def _write(tmp_path: Path, name: str, text: str) -> Path:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    path = workflows / name
    path.write_text(text, encoding="utf-8")
    return workflows


def test_guard_passes_on_repository_workflows() -> None:
    assert guard.main([str(WORKFLOWS)]) == 0


def test_guard_cli_passes_on_repository_workflows() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_workflow_action_pins.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "all external 'uses:' references pinned" in result.stdout


def test_ci_workflow_uses_the_verified_pinned_shas() -> None:
    text = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    for pin in VERIFIED_PINS:
        assert pin in text


def test_guard_fails_on_pre_change_mutable_tags(tmp_path: Path) -> None:
    workflows = _write(tmp_path, "ci.yml", PRE_CHANGE_WORKFLOW)
    assert guard.main([str(workflows)]) == 1


def test_guard_reports_every_pre_change_reference(tmp_path: Path) -> None:
    workflows = _write(tmp_path, "ci.yml", PRE_CHANGE_WORKFLOW)
    violations = guard.check_workflow_file(workflows / "ci.yml")
    joined = "\n".join(violations)
    for tag in ("actions/checkout@v7.0.1", "actions/setup-python@v7.1.0",
                "actions/setup-node@v7.1.0"):
        assert tag in joined
    assert "not pinned to a full 40-character commit SHA" in joined


def test_guard_fails_on_mutable_branch_reference(tmp_path: Path) -> None:
    workflows = _write(
        tmp_path, "branch.yml", PINNED_STEP_TEMPLATE.format(
            reference="actions/checkout@main # v7.0.1"
        )
    )
    assert guard.main([str(workflows)]) == 1


def test_guard_fails_on_major_version_tag(tmp_path: Path) -> None:
    workflows = _write(
        tmp_path, "major.yml", PINNED_STEP_TEMPLATE.format(
            reference="actions/setup-python@v7 # v7.1.0"
        )
    )
    assert guard.main([str(workflows)]) == 1


def test_guard_fails_on_sha_without_version_comment(tmp_path: Path) -> None:
    workflows = _write(
        tmp_path, "nocomment.yml",
        PINNED_STEP_TEMPLATE.format(
            reference="actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
        ),
    )
    violations = guard.check_workflow_file(workflows / "nocomment.yml")
    assert len(violations) == 1
    assert "lacks a '# vX.Y.Z' version comment" in violations[0]


def test_guard_fails_on_uppercase_sha(tmp_path: Path) -> None:
    workflows = _write(
        tmp_path, "upper.yml",
        PINNED_STEP_TEMPLATE.format(
            reference="actions/checkout@3D3C42E5AAC5BA805825DA76410C181273BA90B1 # v7.0.1"
        ),
    )
    assert guard.main([str(workflows)]) == 1


def test_guard_accepts_pinned_sha_with_version_comment(tmp_path: Path) -> None:
    workflows = _write(
        tmp_path, "pinned.yml",
        PINNED_STEP_TEMPLATE.format(
            reference=(
                "actions/checkout@"
                "3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1"
            )
        ),
    )
    assert guard.main([str(workflows)]) == 0


def test_guard_skips_local_actions(tmp_path: Path) -> None:
    workflows = _write(
        tmp_path, "local.yml",
        PINNED_STEP_TEMPLATE.format(reference="./.github/actions/local-tool"),
    )
    assert guard.main([str(workflows)]) == 0


def test_guard_fails_on_docker_reference(tmp_path: Path) -> None:
    workflows = _write(
        tmp_path, "docker.yml",
        PINNED_STEP_TEMPLATE.format(reference="docker://alpine:3.20 # v3.20"),
    )
    violations = guard.check_workflow_file(workflows / "docker.yml")
    assert len(violations) == 1
    assert "cannot be commit-pinned" in violations[0]


def test_guard_fails_on_reference_without_at(tmp_path: Path) -> None:
    workflows = _write(
        tmp_path, "noat.yml", PINNED_STEP_TEMPLATE.format(reference="actions/checkout")
    )
    violations = guard.check_workflow_file(workflows / "noat.yml")
    assert len(violations) == 1
    assert "carries no '@ref'" in violations[0]


def test_guard_fails_on_unparseable_yaml(tmp_path: Path) -> None:
    workflows = _write(tmp_path, "broken.yml", "jobs: [unclosed\n  - {")
    violations = guard.check_workflow_file(workflows / "broken.yml")
    assert len(violations) == 1
    assert "unparseable workflow YAML" in violations[0]


def test_guard_fails_on_non_mapping_document(tmp_path: Path) -> None:
    workflows = _write(tmp_path, "list.yml", "- just\n- a\n- list\n")
    violations = guard.check_workflow_file(workflows / "list.yml")
    assert len(violations) == 1
    assert "not a YAML mapping" in violations[0]


def test_guard_fails_when_uses_text_hides_in_run_block(tmp_path: Path) -> None:
    workflow = """\
name: CI
on:
  push:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Pinned
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: Script echoing action text
        run: |
          set -e
          uses: actions/setup-python@v7.1.0
          echo "$uses"
"""
    workflows = _write(tmp_path, "hidden.yml", workflow)
    violations = guard.check_workflow_file(workflows / "hidden.yml")
    assert guard.main([str(workflows)]) == 1
    assert any("invisible to YAML keys" in violation for violation in violations)


def test_guard_fails_when_yaml_value_escapes_line_scan(tmp_path: Path) -> None:
    workflow = (
        "name: CI\n"
        "on:\n"
        "  push:\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - name: Folded\n"
        "        uses: >\n"
        "          actions/checkout@v7.0.1\n"
    )
    workflows = _write(tmp_path, "folded.yml", workflow)
    violations = guard.check_workflow_file(workflows / "folded.yml")
    assert guard.main([str(workflows)]) == 1
    assert any("invisible to the line scanner" in violation for violation in violations)


def test_guard_fails_when_no_workflow_files_exist(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert guard.main([str(empty)]) == 2


def test_guard_fails_on_missing_path(tmp_path: Path) -> None:
    assert guard.main([str(tmp_path / "does-not-exist")]) == 2


# --- Issue #45 F1: duplicate refs must not collapse the YAML-vs-raw view ---


def test_guard_fails_on_duplicate_quoted_key_hiding_unannotated_occurrence(
    tmp_path: Path,
) -> None:
    """One annotated plain ``uses:`` plus one quoted ``'uses':`` with the same
    pinned SHA and no version comment: PyYAML parses both action steps but the
    raw line scanner only sees the plain key, so occurrence counts diverge and
    the untraceable second occurrence must fail closed (Issue #45 F1)."""
    workflow = """\
name: Guard Repro
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: annotated
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: missing annotation, quoted key
        'uses': actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
"""
    workflows = _write(tmp_path, "dup-quoted.yml", workflow)
    violations = guard.check_workflow_file(workflows / "dup-quoted.yml")
    assert guard.main([str(workflows)]) == 1
    assert any("invisible to the line scanner" in violation for violation in violations)


def test_guard_accepts_repeated_pinned_references_with_annotations(
    tmp_path: Path,
) -> None:
    """Positive control: the same pinned SHA declared twice as ordinary
    ``uses:`` lines, each carrying its own complete version comment, stays
    clean; only a scanner-invisible encoding of a repeated reference fails."""
    workflow = """\
name: Guard Repro Repeated
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: first use
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: second use
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
"""
    workflows = _write(tmp_path, "repeated.yml", workflow)
    assert guard.main([str(workflows)]) == 0


def test_guard_fails_on_duplicate_ref_hidden_in_run_block(tmp_path: Path) -> None:
    """A run-block ``uses:`` line repeating a legitimately pinned reference
    used to cancel out against the set-based comparison; the multiset view
    must report the scanner-only occurrence (Issue #45 F1 variant)."""
    workflow = """\
name: CI
on:
  push:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Pinned
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: Script echoing action text
        run: |
          set -e
          uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
          echo "$uses"
"""
    workflows = _write(tmp_path, "dup-run-block.yml", workflow)
    violations = guard.check_workflow_file(workflows / "dup-run-block.yml")
    assert guard.main([str(workflows)]) == 1
    assert any("invisible to YAML keys" in violation for violation in violations)


# --- Issue #45 F2: version annotations must be complete vX.Y.Z ---


def _annotated_workflow(reference: str, comment: str) -> str:
    return PINNED_STEP_TEMPLATE.format(reference=f"{reference} {comment}")


def test_guard_fails_on_truncated_two_component_version_comment(
    tmp_path: Path,
) -> None:
    workflows = _write(
        tmp_path, "truncated.yml",
        _annotated_workflow(
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", "# v7.1"
        ),
    )
    violations = guard.check_workflow_file(workflows / "truncated.yml")
    assert guard.main([str(workflows)]) == 1
    assert "lacks a '# vX.Y.Z' version comment" in violations[0]


def test_guard_fails_on_malformed_version_comment_suffix(tmp_path: Path) -> None:
    workflows = _write(
        tmp_path, "malformed.yml",
        _annotated_workflow(
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", "# v7.1abc"
        ),
    )
    violations = guard.check_workflow_file(workflows / "malformed.yml")
    assert guard.main([str(workflows)]) == 1
    assert "lacks a '# vX.Y.Z' version comment" in violations[0]


def test_guard_fails_on_four_component_version_comment(tmp_path: Path) -> None:
    workflows = _write(
        tmp_path, "fourcomp.yml",
        _annotated_workflow(
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", "# v7.0.1.4"
        ),
    )
    violations = guard.check_workflow_file(workflows / "fourcomp.yml")
    assert guard.main([str(workflows)]) == 1
    assert "lacks a '# vX.Y.Z' version comment" in violations[0]


def test_guard_fails_on_version_comment_with_trailing_text(tmp_path: Path) -> None:
    workflows = _write(
        tmp_path, "trailing.yml",
        _annotated_workflow(
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
            "# v7.0.1 pinned upstream tag",
        ),
    )
    violations = guard.check_workflow_file(workflows / "trailing.yml")
    assert guard.main([str(workflows)]) == 1
    assert "lacks a '# vX.Y.Z' version comment" in violations[0]


def test_guard_accepts_no_space_version_comment(tmp_path: Path) -> None:
    """Positive control: a compact ``#v7.0.1`` annotation with no space after
    the hash remains supported valid syntax."""
    workflows = _write(
        tmp_path, "compact.yml",
        _annotated_workflow(
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", "#v7.0.1"
        ),
    )
    assert guard.main([str(workflows)]) == 0


# --- Issue #47 F3: a decoy line cannot authorize a different real occurrence ---


def test_guard_fails_on_decoy_annotating_quoted_key_real_action(
    tmp_path: Path,
) -> None:
    """The actual action step is a quoted ``'uses':`` key without a version
    comment; an annotated ``uses:`` decoy line inside a ``run: |`` block
    repeats the same pinned reference. Value-based Counters balance, but the
    decoy must not authorize the real occurrence: the guard must fail closed
    on both the scanner-invisible real line and the YAML-invisible decoy
    (Issue #47 F3, fixture A)."""
    workflow = """\
name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: real action
        'uses': actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0
      - name: decoy line, not an action
        run: |
          uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0
"""
    workflows = _write(tmp_path, "decoy-quoted.yml", workflow)
    violations = guard.check_workflow_file(workflows / "decoy-quoted.yml")
    assert guard.main([str(workflows)]) == 1
    assert any("invisible to the line scanner" in v for v in violations), violations
    assert any("invisible to YAML keys" in v for v in violations), violations


def test_guard_fails_on_decoy_annotating_folded_scalar_real_action(
    tmp_path: Path,
) -> None:
    """The actual action step is a folded scalar whose effective value cannot
    carry a same-line annotation; an annotated decoy line inside a ``run: |``
    block repeats the same pinned reference. The decoy must not authorize the
    folded occurrence: the guard must fail closed on both (Issue #47 F3,
    fixture B)."""
    workflow = """\
name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: real folded action
        uses: >-
          actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0
      - name: decoy line, not an action
        run: |
          uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0
"""
    workflows = _write(tmp_path, "decoy-folded.yml", workflow)
    violations = guard.check_workflow_file(workflows / "decoy-folded.yml")
    assert guard.main([str(workflows)]) == 1
    assert any("invisible to the line scanner" in v for v in violations), violations
    assert any("invisible to YAML keys" in v for v in violations), violations


def test_guard_accepts_distinct_annotated_references(tmp_path: Path) -> None:
    """Positive control: several genuinely distinct external actions, each an
    ordinary single-line ``uses:`` carrying its own pinned SHA and complete
    same-line version comment, stays clean under occurrence-level binding."""
    workflow = """\
name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: Set up Python
        uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0
      - name: Set up Node
        uses: actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7.1.0
"""
    workflows = _write(tmp_path, "distinct.yml", workflow)
    assert guard.main([str(workflows)]) == 0


def test_guard_fails_on_duplicate_uses_key_in_one_step(tmp_path: Path) -> None:
    """Two ``uses`` keys inside the same step mapping are an ambiguous
    encoding (PyYAML keeps only the last): the guard must fail closed instead
    of letting either occurrence authorize the other."""
    workflow = """\
name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: ambiguous step
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0
"""
    workflows = _write(tmp_path, "dup-key.yml", workflow)
    violations = guard.check_workflow_file(workflows / "dup-key.yml")
    assert guard.main([str(workflows)]) == 1
    assert len(violations) >= 1
    joined = "\n".join(violations)
    assert "uses" in joined


# --- Issue #49 F4/F5: alias-graph robustness and source fidelity ---


def test_guard_fails_on_alias_shared_action_mapping(tmp_path: Path) -> None:
    """F4: PyYAML aliases reuse node objects, so a step mapping anchored once
    and referenced twice makes two *effective* ``uses`` occurrences share one
    annotated source line. A single annotation must not authorize multiple
    action references; the guard must fail closed with an alias diagnostic
    anchored at the shared ``uses`` line (Issue #49 F4)."""
    workflow = """\
name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - &shared
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - *shared
"""
    workflows = _write(tmp_path, "alias-shared.yml", workflow)
    violations = guard.check_workflow_file(workflows / "alias-shared.yml")
    assert guard.main([str(workflows)]) == 1
    path = workflows / "alias-shared.yml"
    shared = [v for v in violations if "alias" in v and "shared" in v]
    assert shared, violations
    assert any(v.startswith(f"{path}:7:") for v in shared), violations


def test_guard_fails_on_cyclic_alias_graph_with_controlled_diagnostic(
    tmp_path: Path,
) -> None:
    """F5: an anchor referenced inside its own definition composes into a
    cyclic node graph. The guard must reject it with a controlled
    ``path:line`` diagnostic and exit 1, never an uncaught RecursionError
    (Issue #49 F5)."""
    workflow = """\
name: CI
metadata: &cycle [*cycle]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
"""
    workflows = _write(tmp_path, "cycle.yml", workflow)
    violations = guard.check_workflow_file(workflows / "cycle.yml")
    assert guard.main([str(workflows)]) == 1
    path = workflows / "cycle.yml"
    cyclic = [v for v in violations if "cyclic" in v]
    assert cyclic, violations
    assert any(v.startswith(f"{path}:2:") for v in cyclic), violations


def test_guard_bounds_alias_fanout_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F5 resource budget: a doubling-layer alias DAG has a tiny unique-node
    set but an exponential number of root-to-node paths. The collector must
    visit each composed node O(1) times (memoized), keeping the traversal
    linear in nodes plus edges; the pre-R3 collector made 786,420 recursive
    calls on this exact 17-layer fixture. Bounded structurally by counting
    visitor invocations, not by timing."""
    lines = [
        "name: CI",
        "jobs:",
        "  test:",
        "    runs-on: ubuntu-latest",
        "    steps:",
        "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
        " # v7.0.1",
        "layers:",
        "  l0: &l0 [0]",
    ]
    lines.extend(f"  l{i}: &l{i} [*l{i - 1}, *l{i - 1}]" for i in range(1, 18))
    workflows = _write(tmp_path, "fanout.yml", "\n".join(lines) + "\n")

    calls = 0
    original = guard._collect_yaml_use_occurrences

    def counting(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(guard, "_collect_yaml_use_occurrences", counting)
    assert guard.main([str(workflows)]) == 0
    assert calls <= 200, f"alias fan-out traversal made {calls} node visits"


def test_guard_accepts_harmless_reused_non_uses_anchor(tmp_path: Path) -> None:
    """Positive control: reusing a YAML anchor that contains no ``uses`` key
    (a shared env block) is harmless and must stay clean."""
    workflow = """\
name: CI
configs:
  env: &env-config
    PYTHONHASHSEED: "0"
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: first
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        env: *env-config
      - name: second
        uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0
        env: *env-config
"""
    workflows = _write(tmp_path, "harmless-anchor.yml", workflow)
    assert guard.main([str(workflows)]) == 0


def test_guard_accepts_dead_anchor_on_pinned_step(tmp_path: Path) -> None:
    """Positive control: an anchor defined on a legitimately pinned step but
    never referenced by any alias is harmless (only alias *sharing* of a
    ``uses``-bearing subtree is rejected)."""
    workflow = """\
name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - &step
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
"""
    workflows = _write(tmp_path, "dead-anchor.yml", workflow)
    assert guard.main([str(workflows)]) == 0


# --- Issue #51 F6: uses-bearing alias DAG materialization must stay bounded ---


CHECKOUT_PIN = (
    "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1"
)


def _doubling_alias_dag_workflow(depth: int, *, uses_base: bool) -> str:
    """Tiny-input doubling alias DAG (Issue #51 F6 fixture generator).

    Each ``l{i}`` sequence references ``l{i-1}`` twice, so the composed
    unique-node set grows linearly with ``depth`` while root-to-node paths
    double at every level. ``uses_base`` plants a pinned ``uses`` key inside
    the shared leaf; the non-``uses`` variant is the benign control."""
    lines = [
        "name: CI",
        "jobs:",
        "  test:",
        "    runs-on: ubuntu-latest",
        "    steps:",
        f"      - uses: {CHECKOUT_PIN}",
        "layers:",
    ]
    if uses_base:
        lines.extend(["  l0: &l0", f"    uses: {CHECKOUT_PIN}"])
    else:
        lines.append("  l0: &l0 [0]")
    lines.extend(
        f"  l{i}: &l{i} [*l{i - 1}, *l{i - 1}]" for i in range(1, depth + 1)
    )
    return "\n".join(lines) + "\n"


def test_guard_bounds_uses_bearing_alias_dag_occurrence_materialization(
    tmp_path: Path,
) -> None:
    """F6: the R3 memoized collector visits each node once, but every caller
    still re-copied completed children's ``occurrences`` through alias
    re-references, so this 649-byte fixture materialized 524,288 root
    occurrences (2**19) from 29 unique nodes on main@6aa29c9. Occurrence
    materialization must stay bounded by distinct source ``uses`` lines, not
    by root-to-node paths."""
    workflow = _doubling_alias_dag_workflow(18, uses_base=True)
    documents = list(yaml.compose_all(workflow, Loader=yaml.SafeLoader))
    assert len(documents) == 1
    state = guard._AliasGraphState()
    result = guard._collect_yaml_use_occurrences(documents[0], state)
    distinct_source_uses_lines = 2  # the jobs step and the shared l0 leaf
    assert len(result.occurrences) <= distinct_source_uses_lines, (
        len(result.occurrences)
    )
    total_materialized = sum(
        len(entry.occurrences) for entry in state.done.values()
    )
    assert total_materialized <= distinct_source_uses_lines * len(state.done), (
        total_materialized
    )
    assert len(state.done) <= 64  # 29 unique nodes on main; O(depth), O(paths) never


def test_guard_fails_closed_on_uses_bearing_alias_dag_with_bounded_diagnostics(
    tmp_path: Path,
) -> None:
    """End-to-end F6: the guard must reject the uses-bearing doubling DAG
    with exit 1 and a bounded, deterministic diagnostic list anchored at the
    shared ``uses`` source line — one alias-shared diagnostic, not one per
    DAG level, and never runaway output."""
    workflow = _doubling_alias_dag_workflow(18, uses_base=True)
    workflows = _write(tmp_path, "fanout-uses.yml", workflow)
    violations = guard.check_workflow_file(workflows / "fanout-uses.yml")
    assert guard.main([str(workflows)]) == 1
    path = workflows / "fanout-uses.yml"
    shared = [v for v in violations if "shared through a YAML alias" in v]
    assert shared, violations
    assert all(v.startswith(f"{path}:9:") for v in shared), violations
    assert len(violations) <= 2, violations


def test_guard_bounds_non_uses_alias_dag_materialization(
    tmp_path: Path,
) -> None:
    """Positive control: the same doubling DAG with a non-``uses`` leaf stays
    bounded and clean — legal repeated aliases must not be penalized."""
    workflow = _doubling_alias_dag_workflow(18, uses_base=False)
    documents = list(yaml.compose_all(workflow, Loader=yaml.SafeLoader))
    state = guard._AliasGraphState()
    result = guard._collect_yaml_use_occurrences(documents[0], state)
    assert len(result.occurrences) == 1  # only the ordinary jobs step
    assert (
        sum(len(entry.occurrences) for entry in state.done.values())
        <= len(state.done)
    )
    assert not state.graph_violations
    workflows = _write(tmp_path, "fanout-benign.yml", workflow)
    assert guard.main([str(workflows)]) == 0


def test_guard_reports_each_shared_alias_binding_violation_once(
    tmp_path: Path,
) -> None:
    """F6 diagnostic determinism: a shared alias step whose pinned reference
    lacks a version comment must produce exactly one version-comment
    diagnostic for its one source line, not one per materialized duplicate
    occurrence (two on main@6aa29c9)."""
    workflow = """\
name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - &shared
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
      - *shared
"""
    workflows = _write(tmp_path, "alias-shared-unannotated.yml", workflow)
    violations = guard.check_workflow_file(
        workflows / "alias-shared-unannotated.yml"
    )
    assert guard.main([str(workflows)]) == 1
    assert (
        len([v for v in violations if "version comment" in v]) == 1
    ), violations
    assert (
        len([v for v in violations if "shared through a YAML alias" in v]) == 1
    ), violations


def test_guard_fails_on_shared_uses_bearing_step_sequence(tmp_path: Path) -> None:
    """Nested sharing: an anchored whole ``steps`` sequence containing a
    pinned step, referenced by a second job, shares the ``uses`` occurrence;
    the alias diagnostic must anchor at the shared step's source line."""
    workflow = """\
name: CI
jobs:
  first:
    runs-on: ubuntu-latest
    steps: &steps
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
  second:
    runs-on: ubuntu-latest
    steps: *steps
"""
    workflows = _write(tmp_path, "alias-steps.yml", workflow)
    violations = guard.check_workflow_file(workflows / "alias-steps.yml")
    assert guard.main([str(workflows)]) == 1
    path = workflows / "alias-steps.yml"
    shared = [v for v in violations if "shared through a YAML alias" in v]
    assert shared, violations
    assert all(v.startswith(f"{path}:6:") for v in shared), violations


def test_guard_fails_on_cyclic_steps_alias_containing_uses(tmp_path: Path) -> None:
    """A ``steps`` sequence referencing itself composes into a cycle that
    also contains a ``uses`` key; the guard must fail closed with the cyclic
    diagnostic at the sequence's source line while the in-sequence pinned
    occurrence stays deterministic."""
    workflow = """\
name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    steps: &steps
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - *steps
"""
    workflows = _write(tmp_path, "cycle-steps.yml", workflow)
    violations = guard.check_workflow_file(workflows / "cycle-steps.yml")
    assert guard.main([str(workflows)]) == 1
    path = workflows / "cycle-steps.yml"
    cyclic = [v for v in violations if "cyclic" in v]
    assert cyclic, violations
    assert any(v.startswith(f"{path}:5:") for v in cyclic), violations


# --- Issue #59 F7/F8: bounded occurrence materialization and deep-YAML safety ---


def _nested_uses_chain_workflow(depth: int) -> str:
    """Acyclic distinct-mapping chain fixture (Issue #59 F7).

    Each of the ``depth`` nested mappings carries one genuine plain ``uses``
    line and one nested ``child`` mapping, with no aliases anywhere: the
    unique-node set and the distinct source ``uses`` lines both grow linearly
    with ``depth`` while (pre-R5) every cached ancestor stored a full copy of
    its descendants' occurrences."""
    lines = [
        "name: CI",
        "jobs:",
        "  test:",
        "    runs-on: ubuntu-latest",
        "    steps:",
        f"      - uses: {CHECKOUT_PIN}",
        "layers:",
    ]
    for index in range(depth):
        indent = "  " * (index + 1)
        lines.append(f"{indent}m{index}:")
        lines.append(f"{indent}  uses: {CHECKOUT_PIN}")
        lines.append(f"{indent}  child:")
    lines.append(f"{'  ' * (depth + 2)}leaf: 1")
    return "\n".join(lines) + "\n"


def _nested_flow_collections_workflow(levels: int) -> str:
    """``levels`` nested flow mappings under one root mapping (one line, no
    aliases, no ``uses``): ``levels + 1`` collection nesting levels in a tiny
    linear-byte input."""
    return "root: " + "{a: " * levels + "1" + "}" * levels + "\n"


def test_guard_bounds_acyclic_nested_uses_chain_materialization() -> None:
    """F7: a chain of distinct mappings, each with one genuine ``uses`` key
    and one nested child, has no aliases at all, yet the pre-R5 collector
    copied every fresh child's full descendant tuple up into each ancestor's
    cached result, storing O(depth^2) aggregate entries (3,405 cached entries
    for 81 distinct source lines at depth 80 on main@2587c73). Aggregate
    cached occurrence storage must stay linear: every cached node result
    holds only its own node's occurrences."""
    workflow = _nested_uses_chain_workflow(80)
    documents = list(yaml.compose_all(workflow, Loader=yaml.SafeLoader))
    assert len(documents) == 1
    state = guard._AliasGraphState()
    result = guard._collect_yaml_use_occurrences(documents[0], state)
    distinct_source_uses_lines = 81  # the jobs step plus 80 chain levels
    assert len(result.occurrences) == distinct_source_uses_lines
    total_materialized = sum(len(entry.occurrences) for entry in state.done.values())
    assert total_materialized <= len(state.done), total_materialized
    assert len(state.done) <= 4 * distinct_source_uses_lines, len(state.done)


def test_guard_materializes_each_distinct_source_occurrence_once() -> None:
    """F7 design contract: the collector appends each distinct source
    ``uses`` occurrence exactly once to the document-level accumulator, so
    deep acyclic nesting never duplicates or drops entries."""
    workflow = _nested_uses_chain_workflow(80)
    documents = list(yaml.compose_all(workflow, Loader=yaml.SafeLoader))
    state = guard._AliasGraphState()
    guard._collect_yaml_use_occurrences(documents[0], state)
    assert len(state.occurrences) == 81
    assert len({entry[0] for entry in state.occurrences}) == 81


def test_guard_accepts_deep_acyclic_nested_uses_chain(tmp_path: Path) -> None:
    """F7 positive control: every chain level is an ordinary plain annotated
    ``uses`` line, so a deep-but-legal acyclic chain (still far below the
    supported nesting depth) stays accepted end to end."""
    workflows = _write(tmp_path, "chain.yml", _nested_uses_chain_workflow(80))
    assert guard.main([str(workflows)]) == 0


def test_guard_fails_closed_on_parser_recursion_error(tmp_path: Path) -> None:
    """F8: ~500 nested flow collections exhaust the recursive YAML parser.
    The guard must return one controlled file-level diagnostic and exit 1,
    never propagate a raw ``RecursionError`` traceback (main@2587c73 raises
    out of ``check_workflow_file`` and crashes the CLI)."""
    text = "root: " + "[" * 500 + "x" + "]" * 500 + "\n"
    workflows = _write(tmp_path, "too-deep.yml", text)
    violations = guard.check_workflow_file(workflows / "too-deep.yml")
    assert guard.main([str(workflows)]) == 1
    assert len(violations) == 1
    assert "nested too deeply for the parser" in violations[0]


def test_guard_fails_closed_on_collector_recursion_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F8: recursion exhaustion raised inside the collector itself must also
    fail closed with one controlled file-level diagnostic instead of a
    traceback (main@2587c73 propagates it out of ``check_workflow_file``)."""
    workflows = _write(
        tmp_path, "pinned.yml", PINNED_STEP_TEMPLATE.format(reference=CHECKOUT_PIN)
    )

    def exploding(*args: object, **kwargs: object) -> None:
        raise RecursionError("simulated collector recursion exhaustion")

    monkeypatch.setattr(guard, "_collect_yaml_use_occurrences", exploding)
    violations = guard.check_workflow_file(workflows / "pinned.yml")
    assert violations == [
        f"{workflows / 'pinned.yml'}: workflow YAML is nested too deeply "
        "for the occurrence collector (RecursionError); refusing to verify"
    ]
    assert guard.main([str(workflows)]) == 1


def test_guard_accepts_workflow_at_supported_nesting_depth(tmp_path: Path) -> None:
    """F8 boundary: exactly ``MAX_SUPPORTED_NESTING_DEPTH`` collection levels
    (root plus 99 nested flow mappings) is inside the documented envelope and
    must verify cleanly."""
    levels = guard.MAX_SUPPORTED_NESTING_DEPTH - 1
    workflows = _write(
        tmp_path, "edge-ok.yml", _nested_flow_collections_workflow(levels)
    )
    assert guard.main([str(workflows)]) == 0


def test_guard_fails_closed_beyond_supported_nesting_depth(tmp_path: Path) -> None:
    """F8 boundary: one collection level beyond the documented limit is
    refused before that branch is traversed, with a single deterministic
    ``path:line`` diagnostic and exit 1 — a deep-but-parseable structure can
    never pass or crash the guard (main@2587c73 has no depth limit and
    accepts this exact input with zero violations)."""
    levels = guard.MAX_SUPPORTED_NESTING_DEPTH
    workflows = _write(
        tmp_path, "edge-deep.yml", _nested_flow_collections_workflow(levels)
    )
    violations = guard.check_workflow_file(workflows / "edge-deep.yml")
    assert guard.main([str(workflows)]) == 1
    path = workflows / "edge-deep.yml"
    deep = [v for v in violations if "supported depth limit" in v]
    assert len(deep) == 1, violations
    assert deep[0].startswith(f"{path}:1:")
    assert "refusing to traverse" in deep[0]
    assert len(violations) == 1
