"""Roadmap completeness guard for the Phase 7 controlled-evolution record.

``docs/roadmap.md`` is the repository's milestone-level historical phase
record (AGENTS.md section 11). Between the Phase 7-C3-B closure (2026-10-16)
and the Phase 7-C4-D closure (2026-10-29), fifteen closed Phase 7 packages
were recorded only under ``docs/status/`` and never promoted to the roadmap,
so the top-level historical record silently went stale while the phase chain
kept closing (reconciled in 2026-11-07; see
``docs/status/phase-7-record-reconciliation-2026-11-07.md``). These tests pin
the reconciled state and fail whenever a ``docs/goals/phase-7-*.md`` package
is absent from the roadmap again.

Scope is deliberately the Phase 7 family only: earlier phase families used
looser roadmap labelling conventions (for example the Phase 5R-A M2/M5/M6
sub-packages) that do not map one-to-one onto goal filenames, so a
repository-wide rule would fail on pre-existing history. When a new phase
family starts, extend the family prefixes deliberately.

Known residual: CI's docs-only fast path (``scripts/ci_change_scope.py``)
runs no pytest, so a PR touching only ``docs/status/``/``docs/goals/``
Markdown does not execute this guard; every implementation PR runs full mode
and does. This guard therefore backs the convention, it does not replace it.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROADMAP = ROOT / "docs" / "roadmap.md"
GOALS_DIR = ROOT / "docs" / "goals"

# A goal filename token contributes to the phase label when it is a single
# letter, a letter+digit form such as ``c4``/``b1``/``d2b``, or an ``rN``
# hardening revision; descriptive slug words (``controlled``, ``readiness``,
# ``pr``-construction, ...) terminate the label.
_TOKEN_RE = re.compile(r"^(?:r\d+|[a-z](?:\d+[a-z0-9]*)?)$")

# The frozen mapping from every checked-in Phase 7 goal file to its roadmap
# phase label. A new Phase 7 goal file must extend this set (and the roadmap)
# in the same change; a renamed/removed goal file must update it here.
_EXPECTED_PHASE7_LABELS = frozenset(
    {
        "7-A",
        "7-A-R1",
        "7-A-R2",
        "7-B1",
        "7-B1-R1",
        "7-B2-A",
        "7-B2-B1",
        "7-C1",
        "7-C2",
        "7-C2-R1",
        "7-C3-A",
        "7-C3-A-R1",
        "7-C3-A-R2",
        "7-C3-B",
        "7-C3-B-R1",
        "7-C3-B-R2",
        "7-C3-B-R3",
        "7-C4-A",
        "7-C4-A-R1",
        "7-C4-A-R2",
        "7-C4-A-R3",
        "7-C4-A-R4",
        "7-C4-A-R5",
        "7-C4-B",
        "7-C4-C",
        "7-C4-C-R1",
        "7-C4-C-R2",
        "7-C4-C-R3",
        "7-C4-D",
    }
)


def _goal_files() -> list[Path]:
    return sorted(GOALS_DIR.glob("phase-7-*.md"))


def _phase_label(goal_stem: str) -> str:
    """Derive the roadmap phase label (e.g. ``7-C4-A-R1``) from a goal stem."""
    tokens = goal_stem.split("-")[1:]  # drop the leading ``phase``
    assert tokens, f"could not derive a phase label from {goal_stem!r}"
    # The first token is always the phase-family number (``7``, ``5r``...).
    phase_tokens: list[str] = [tokens[0].upper()]
    for token in tokens[1:]:
        if not _TOKEN_RE.fullmatch(token):
            break
        phase_tokens.append(token.upper())
    return "-".join(phase_tokens)


def test_phase7_goal_inventory_matches_the_frozen_label_set() -> None:
    """The tokenizer must keep mapping every goal file onto the frozen set.

    A failure here means either a Phase 7 goal file was added, renamed or
    removed without recording the package in the roadmap (update both the
    roadmap and this frozen set in the same change), or the tokenizer rule
    above drifted and must be repaired without silently reshaping coverage.
    """

    labels = {_phase_label(path.stem) for path in _goal_files()}
    missing_from_labels = sorted(_EXPECTED_PHASE7_LABELS - labels)
    unknown_labels = sorted(labels - _EXPECTED_PHASE7_LABELS)
    assert not missing_from_labels, (
        "frozen Phase 7 labels without a docs/goals/phase-7-*.md file: "
        f"{missing_from_labels}"
    )
    assert not unknown_labels, (
        "Phase 7 goal files absent from the frozen label set "
        f"(tests/test_roadmap_phase_record.py): {unknown_labels}"
    )


def test_phase7_goal_files_exist() -> None:
    """Guard the glob itself: an empty family must never pass silently."""

    files = _goal_files()
    assert len(files) == len(_EXPECTED_PHASE7_LABELS)


@pytest.mark.parametrize("label", sorted(_EXPECTED_PHASE7_LABELS))
def test_every_phase7_package_is_recorded_in_the_roadmap(label: str) -> None:
    """Every Phase 7 package must appear in the milestone-level record.

    This is the regression pin for the 2026-10-16..2026-10-29 drift: the
    Phase 7-C3-B-R1..R3, C4-A(+R1..R5), C4-B, C4-C(+R1..R3) and C4-D
    closures existed only as ``docs/status/`` records while the roadmap
    ended at Phase 7-C3-B.
    """

    roadmap = ROADMAP.read_text(encoding="utf-8")
    assert label in roadmap, (
        f"Phase {label} is closed (docs/goals/phase-{label.lower()}*.md) but "
        "docs/roadmap.md does not record it; add its milestone-level section "
        "per AGENTS.md section 11"
    )
