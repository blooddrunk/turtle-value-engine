"""Phase 7-C4-A-R1 regressions: store containment, rollback audit recovery,
runnable apply instructions and publication fsync ordering.

Every defect reproduced here was first executed against pristine main
``3e1520e`` (executor code identical to the C4-A closure ``5667cf7``) with the
exact test file committed by this phase; the observed baseline failures
(exit codes, statuses, off-root bytes, missing audit artifacts) are recorded
in ``docs/status/phase-7-c4-a-r1-2026-10-23.md``.  The same file passes on
the R1 tree.  Nothing here uses a real owner key: every key, trust root,
evidence bundle, private config and activation store is a throwaway
runtime fixture under ``tmp_path``.

Coverage map (goal ``docs/goals/phase-7-c4-a-r1-artifact-containment-rollback-recovery.md``):

* F1 — a symlinked or non-directory descendant of the activation root
  (``locks``/``journal``/``receipts``/``before-images`` for apply,
  ``rollbacks`` for rollback) must be refused with a stable named code
  before any mutation, with zero bytes written outside the store.
* F2 — a rollback interrupted after the config restoration but before the
  immutable rollback outcome is published must be recoverable by retrying
  the same explicit rollback (intent bound before the replace; outcome
  finalized after it), while genuinely completed rollbacks, and
  prior-byte states without durable proof, stay distinct and are never
  fabricated.
* F3 — the READY preview's ``apply_command_hint``/``rollback_command`` must
  be complete, safely shell-quoted and directly executable (proved by
  ``shlex.split`` + real CLI execution), including paths with spaces.
* Durability — every store publication (journal, before-image, receipt,
  rollback intent, rollback outcome) must fsync the file body *and* its
  parent directory entry, ordered before/after the config swap as
  appropriate.  This is simulated-interruption/fsync-call evidence, not a
  physical power-loss certification.
"""

import contextlib
import hashlib
import json
import os
import shlex
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from tests.test_activation_execution import (
    PRIVATE_CONFIG_TEMPLATE,
    _activated_bytes,
    _cli,
    _Env,
    _sha,
)
from turtle_value_engine.evolution import activation_execution
from turtle_value_engine.providers.models import canonical_json_bytes

ROOT_DIR = Path(__file__).resolve().parents[1]
APPLY_STORE_DIRS = ("locks", "journal", "receipts", "before-images")
ROLLBACK_STORE_DIRS = ("locks", "before-images", "rollbacks")


class _Crash(Exception):
    """Simulated process death at a named publication point."""


@contextlib.contextmanager
def _crash_on_outcome_publication():
    """Interrupt exactly between the config restoration and the rollback
    outcome publication (the F2 audit window), whatever the internal order."""

    real = activation_execution._write_create_or_identical

    def wrapper(path, content, *, label, mode=0o600):
        if label == "rollback outcome":
            raise _Crash()
        return real(path, content, label=label, mode=mode)

    with mock.patch.object(
        activation_execution, "_write_create_or_identical", wrapper
    ):
        yield


def _outcome_files(activation_root: Path) -> list[Path]:
    rollbacks = activation_root / "rollbacks"
    if not rollbacks.is_dir():
        return []
    return sorted(p for p in rollbacks.iterdir() if p.is_file())


def _completed_outcomes(activation_root: Path) -> list[Path]:
    return [
        p for p in _outcome_files(activation_root) if not p.name.endswith(".intent.json")
    ]


def _applied(tmp_path: Path, capsys):
    env = _Env(tmp_path).setup(capsys)
    original_sha = _sha(env.config_path)
    preview = env.ready_preview(capsys)
    code, out = env.apply(capsys, preview["plan_id"], original_sha)
    assert code == 0, out
    receipt_path = (
        env.activation_root / "receipts" / f"{preview['activation_id']}.json"
    )
    return env, receipt_path, original_sha, _sha(env.config_path)


# ---------------------------------------------------------------------------
# F1 — activation-store descendant containment (symlinks)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("store_dir", APPLY_STORE_DIRS)
def test_apply_refuses_symlinked_store_descendant(tmp_path, capsys, store_dir):
    env = _Env(tmp_path).setup(capsys)
    trap = tmp_path / "trap"
    trap.mkdir()
    env.activation_root.mkdir(parents=True, exist_ok=True)
    (env.activation_root / store_dir).symlink_to(trap, target_is_directory=True)

    preview = env.ready_preview(capsys)
    assert preview["preview_state"] == "READY_FOR_APPLY"
    assert list(trap.iterdir()) == [], "the read-only preview wrote into the trap"

    code, out = env.apply(capsys, preview["plan_id"], preview["original_config_sha256"])
    assert code == 2, out
    assert "ACTIVATION_STORE_SYMLINK" in out
    assert list(trap.iterdir()) == [], "bytes escaped the activation root"
    assert _sha(env.config_path) == preview["original_config_sha256"]


def test_rollback_refuses_symlinked_rollbacks_descendant(tmp_path, capsys):
    env, receipt_path, original_sha, activated_sha = _applied(tmp_path, capsys)
    trap = tmp_path / "trap"
    trap.mkdir()
    (env.activation_root / "rollbacks").symlink_to(trap, target_is_directory=True)

    code, out = env.rollback(capsys, receipt_path)
    assert code == 2, out
    assert "ACTIVATION_STORE_SYMLINK" in out
    assert list(trap.iterdir()) == [], "the rollback outcome escaped the store"
    assert _sha(env.config_path) == activated_sha


# ---------------------------------------------------------------------------
# F1 — activation-store descendant containment (non-directory entries)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("store_dir", APPLY_STORE_DIRS)
def test_apply_refuses_non_directory_store_descendant(tmp_path, capsys, store_dir):
    env = _Env(tmp_path).setup(capsys)
    env.activation_root.mkdir(parents=True, exist_ok=True)
    (env.activation_root / store_dir).write_text("not a directory\n", "utf-8")

    preview = env.ready_preview(capsys)
    code, out = env.apply(capsys, preview["plan_id"], preview["original_config_sha256"])
    assert code == 2, out
    assert "ACTIVATION_STORE_NOT_DIRECTORY" in out
    assert _sha(env.config_path) == preview["original_config_sha256"]
    for entry in env.activation_root.iterdir():
        if entry.name != store_dir:
            # No partial store (e.g. a lock file) may be created before the
            # refusal.
            assert not entry.is_dir() or list(entry.iterdir()) == [], entry


def test_rollback_refuses_non_directory_rollbacks_descendant(tmp_path, capsys):
    env, receipt_path, original_sha, activated_sha = _applied(tmp_path, capsys)
    (env.activation_root / "rollbacks").write_text("not a directory\n", "utf-8")

    code, out = env.rollback(capsys, receipt_path)
    assert code == 2, out
    assert "ACTIVATION_STORE_NOT_DIRECTORY" in out
    assert _sha(env.config_path) == activated_sha, (
        "the refusal must happen before the config restoration"
    )


def test_preview_stays_read_only_with_hostile_store_layout(tmp_path, capsys):
    """Pinned semantics: a hostile *unused* store layout never makes the
    byte-exact read-only preview fail or write."""

    env = _Env(tmp_path).setup(capsys)
    trap = tmp_path / "trap"
    trap.mkdir()
    env.activation_root.mkdir(parents=True, exist_ok=True)
    for store_dir in APPLY_STORE_DIRS:
        (env.activation_root / store_dir).symlink_to(trap, target_is_directory=True)

    before = _sha(env.config_path)
    preview = env.ready_preview(capsys)
    assert preview["preview_state"] == "READY_FOR_APPLY"
    assert _sha(env.config_path) == before
    assert list(trap.iterdir()) == []
    for store_dir in APPLY_STORE_DIRS:
        assert (env.activation_root / store_dir).is_symlink()


# ---------------------------------------------------------------------------
# F2 — rollback audit recovery across an interrupted publication
# ---------------------------------------------------------------------------


def test_rollback_outcome_recovered_after_interrupted_publication(
    tmp_path, capsys
):
    env, receipt_path, original_sha, activated_sha = _applied(tmp_path, capsys)

    with _crash_on_outcome_publication(), pytest.raises(_Crash):
        activation_execution.rollback_profile_activation(
            receipt_path=receipt_path,
            activation_root=env.activation_root,
        )
    # Observable on-disk state: config already restored, no durable outcome
    # (the recovery intent predates the restoration and is expected).
    assert _sha(env.config_path) == original_sha
    assert _completed_outcomes(env.activation_root) == []

    # Retry the same explicit rollback: the audit outcome must be finalized.
    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "FINALIZED_AFTER_INTERRUPTED_RESTORE", payload
    assert payload["outcome"] is not None
    outcomes = [
        p
        for p in _outcome_files(env.activation_root)
        if not p.name.endswith(".intent.json")
    ]
    assert len(outcomes) == 1, _outcome_files(env.activation_root)
    assert _sha(env.config_path) == original_sha, (
        "recovery must not rewrite the already-restored config"
    )

    # A further repeat is the genuine completed no-op.
    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    assert json.loads(out)["status"] == "ALREADY_RESTORED"


def test_rollback_interrupted_before_restore_completes_on_retry(
    tmp_path, capsys, monkeypatch
):
    env, receipt_path, original_sha, activated_sha = _applied(tmp_path, capsys)

    with pytest.raises(_Crash):
        activation_execution.rollback_profile_activation(
            receipt_path=receipt_path,
            activation_root=env.activation_root,
            fault_hook=lambda point: (_ for _ in ()).throw(_Crash())
            if point == "rollback_intent_persisted"
            else None,
        )
    # Config NOT restored yet; the recovery intent is already durable.
    assert _sha(env.config_path) == activated_sha
    intents = [
        p for p in _outcome_files(env.activation_root) if p.name.endswith(".intent.json")
    ]
    assert len(intents) == 1

    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "ROLLED_BACK", payload
    assert _sha(env.config_path) == original_sha
    outcomes = [
        p
        for p in _outcome_files(env.activation_root)
        if not p.name.endswith(".intent.json")
    ]
    assert len(outcomes) == 1


def test_tampered_recovery_intent_fails_closed(tmp_path, capsys):
    env, receipt_path, original_sha, activated_sha = _applied(tmp_path, capsys)

    with _crash_on_outcome_publication(), pytest.raises(_Crash):
        activation_execution.rollback_profile_activation(
            receipt_path=receipt_path,
            activation_root=env.activation_root,
        )
    assert _sha(env.config_path) == original_sha
    intents = [
        p for p in _outcome_files(env.activation_root) if p.name.endswith(".intent.json")
    ]
    assert len(intents) == 1
    payload = json.loads(intents[0].read_text("utf-8"))
    payload["restored_config_sha256"] = "0" * 64
    intents[0].write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")

    code, out = env.rollback(capsys, receipt_path)
    assert code == 2, out
    assert "ROLLBACK_INTENT_CORRUPT" in out
    assert _sha(env.config_path) == original_sha
    assert not [
        p
        for p in _outcome_files(env.activation_root)
        if not p.name.endswith(".intent.json")
    ], "no outcome may be finalized from a tampered intent"


def test_foreign_valid_recovery_intent_fails_closed(tmp_path, capsys):
    """A structurally valid intent bound to *different* content (every
    internal hash recomputed) must still be refused at the binding check."""

    from turtle_value_engine.providers.normalization import deterministic_id

    env, receipt_path, original_sha, activated_sha = _applied(tmp_path, capsys)

    with _crash_on_outcome_publication(), pytest.raises(_Crash):
        activation_execution.rollback_profile_activation(
            receipt_path=receipt_path,
            activation_root=env.activation_root,
        )
    assert _sha(env.config_path) == original_sha
    intent_path = next(
        p for p in _outcome_files(env.activation_root) if p.name.endswith(".intent.json")
    )
    payload = json.loads(intent_path.read_text("utf-8"))
    payload["activation_id"] = "foreign-activation-id"
    payload["rollback_id"] = deterministic_id(
        "profile-activation-rollback",
        payload["activation_id"],
        payload["receipt_content_sha256"],
        payload["project_config_path"],
        payload["restored_config_sha256"],
    )
    payload["content_sha256"] = _sha256_of(payload)
    intent_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")
    # The forged intent must validate as a standalone contract instance.
    activation_execution.ProfileActivationRollbackIntentV1.model_validate(
        json.loads(intent_path.read_text("utf-8"))
    )

    code, out = env.rollback(capsys, receipt_path)
    assert code == 2, out
    assert "ROLLBACK_INTENT_MISMATCH" in out
    assert _sha(env.config_path) == original_sha


def _sha256_of(payload: dict) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
    ).hexdigest()


def test_corrupt_completed_outcome_fails_closed(tmp_path, capsys):
    env, receipt_path, original_sha, activated_sha = _applied(tmp_path, capsys)
    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    outcome_path = _completed_outcomes(env.activation_root)[0]
    payload = json.loads(outcome_path.read_text("utf-8"))
    payload["restored_default_profile"] = "strict-v9"
    outcome_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")

    code, out = env.rollback(capsys, receipt_path)
    assert code == 2, out
    assert "ROLLBACK_OUTCOME_CORRUPT" in out
    assert _sha(env.config_path) == original_sha


def test_prior_bytes_without_durable_rollback_record_are_not_fabricated(
    tmp_path, capsys
):
    """Case (c): the config bytes happen to equal the prior hash but no
    completed outcome or recovery intent proves this rollback ran."""

    env, receipt_path, original_sha, activated_sha = _applied(tmp_path, capsys)
    env.config_path.write_bytes(PRIVATE_CONFIG_TEMPLATE.encode("utf-8"))
    assert _sha(env.config_path) == original_sha

    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "ALREADY_RESTORED", payload
    assert payload["outcome"] is None
    assert "no durable rollback" in payload["detail"], payload["detail"]
    assert _outcome_files(env.activation_root) == [], (
        "an audit outcome must never be fabricated without proof"
    )


def test_recovery_preserves_older_independent_artifacts(tmp_path, capsys):
    env, receipt_path, original_sha, activated_sha = _applied(tmp_path, capsys)

    # First cycle completes normally; its audit artifacts are immutable.
    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    first_outcomes = _completed_outcomes(env.activation_root)
    assert len(first_outcomes) == 1
    first_outcome_bytes = first_outcomes[0].read_bytes()
    first_receipt_bytes = receipt_path.read_bytes()
    journal_dir = env.activation_root / "journal"
    first_journal_state = {p.name: p.read_bytes() for p in journal_dir.iterdir()}

    # A second, independent activation (different prior bytes) interrupted at
    # its rollback-outcome publication.
    env.config_path.write_bytes(
        PRIVATE_CONFIG_TEMPLATE.encode("utf-8") + b"# touched between cycles\n"
    )
    second_prior_sha = _sha(env.config_path)
    preview = env.ready_preview(capsys)
    code, out = env.apply(capsys, preview["plan_id"], second_prior_sha)
    assert code == 0, out
    second_receipt = (
        env.activation_root / "receipts" / f"{preview['activation_id']}.json"
    )

    with _crash_on_outcome_publication(), pytest.raises(_Crash):
        activation_execution.rollback_profile_activation(
            receipt_path=second_receipt,
            activation_root=env.activation_root,
        )
    assert _sha(env.config_path) == second_prior_sha
    code, out = env.rollback(capsys, second_receipt)
    assert code == 0, out
    assert json.loads(out)["status"] == "FINALIZED_AFTER_INTERRUPTED_RESTORE"

    outcomes = [
        p
        for p in _outcome_files(env.activation_root)
        if not p.name.endswith(".intent.json")
    ]
    assert len(outcomes) == 2
    assert first_outcomes[0].read_bytes() == first_outcome_bytes
    assert receipt_path.read_bytes() == first_receipt_bytes
    for name, value in first_journal_state.items():
        assert (journal_dir / name).read_bytes() == value


# ---------------------------------------------------------------------------
# F3 — complete, shell-safe, directly executable operator commands
# ---------------------------------------------------------------------------


def _spaced_env(tmp_path: Path, capsys) -> _Env:
    base = tmp_path / "owner space dir"
    base.mkdir(parents=True, exist_ok=True)
    return _Env(base).setup(capsys)


def test_apply_command_hint_is_complete_and_directly_executable(tmp_path, capsys):
    env = _spaced_env(tmp_path, capsys)
    preview = env.ready_preview(capsys)
    hint = preview["apply_command_hint"]

    assert "..." not in hint.split(), "the hint must not carry a literal ellipsis"
    tokens = shlex.split(hint)
    assert tokens[0] == "tve"
    # Executing the hint's argv (the shell-level program token aside)
    # performs exactly the advertised activation.
    code, out = _cli(capsys, *tokens[1:])
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATED", payload
    assert env.config_path.read_bytes() == _activated_bytes()
    receipt_path = (
        env.activation_root / "receipts" / f"{preview['activation_id']}.json"
    )
    assert receipt_path.is_file()
    assert "strict-v2" in env.config_path.read_text("utf-8")


def test_rollback_command_round_trips_paths_with_spaces(tmp_path, capsys):
    env = _spaced_env(tmp_path, capsys)
    preview = env.ready_preview(capsys)
    original_sha = preview["original_config_sha256"]
    code, out = env.apply(capsys, preview["plan_id"], original_sha)
    assert code == 0, out

    command = preview["rollback_command"]
    tokens = shlex.split(command)
    assert tokens[0] == "tve"
    code, out = _cli(capsys, *tokens[1:])
    assert code == 0, out
    assert json.loads(out)["status"] == "ROLLED_BACK"
    assert _sha(env.config_path) == original_sha


def test_hint_carries_no_secret_material(tmp_path, capsys):
    """The rendered commands reference paths only; no key material value
    (the throwaway private key bytes here) may appear."""

    from cryptography.hazmat.primitives import serialization

    env = _spaced_env(tmp_path, capsys)
    secret_material = env.key.private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    preview = env.ready_preview(capsys)
    for field in ("apply_command_hint", "rollback_command"):
        assert secret_material not in preview[field]
        assert "PRIVATE KEY" not in preview[field]


def test_apply_hint_runs_verbatim_in_a_shell(tmp_path, capsys):
    """The strongest F3 form: the hint executes verbatim in a real shell.

    The ``tve`` program token is resolved through a deterministic shim onto
    the current source tree (``python -m turtle_value_engine``) so the proof
    is independent of whatever older console script happens to be installed
    on the host; the command string itself is executed byte-for-byte.
    """

    bin_dir = tmp_path / "shim-bin"
    bin_dir.mkdir()
    shim = bin_dir / "tve"
    shim.write_text(
        "#!/bin/sh\n"
        f"exec {os.sys.executable} -m turtle_value_engine \"$@\"\n",
        "utf-8",
    )
    shim.chmod(0o755)
    env = _spaced_env(tmp_path, capsys)
    preview = env.ready_preview(capsys)
    completed = subprocess.run(
        preview["apply_command_hint"],
        shell=True,
        capture_output=True,
        text=True,
        cwd=str(ROOT_DIR),
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
             "PYTHONPATH": str(ROOT_DIR / "src")},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(completed.stdout)["status"] == "ACTIVATED"
    assert env.config_path.read_bytes() == _activated_bytes()


# ---------------------------------------------------------------------------
# Durability — publication fsync ordering (simulated interruption evidence)
# ---------------------------------------------------------------------------


def test_publication_fsync_order_covers_directory_entries(
    tmp_path, capsys, monkeypatch
):
    env = _Env(tmp_path).setup(capsys)
    original_sha = _sha(env.config_path)
    preview = env.ready_preview(capsys)

    events: list[tuple] = []
    real_fsync = os.fsync
    real_replace = os.replace

    def traced_fsync(fd: int) -> None:
        try:
            events.append(("fsync", os.readlink(f"/proc/self/fd/{fd}")))
        except OSError:
            events.append(("fsync", f"fd:{fd}"))
        return real_fsync(fd)

    def traced_replace(src, dst, **kwargs):
        events.append(("replace", str(dst)))
        return real_replace(src, dst, **kwargs)

    monkeypatch.setattr(activation_execution.os, "fsync", traced_fsync)
    monkeypatch.setattr(activation_execution.os, "replace", traced_replace)

    code, out = env.apply(capsys, preview["plan_id"], original_sha)
    assert code == 0, out
    receipt_path = (
        env.activation_root / "receipts" / f"{preview['activation_id']}.json"
    )
    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out

    apply_replace_index = next(
        i for i, event in enumerate(events) if event[0] == "replace"
    )
    rollback_replace_index = next(
        i
        for i in range(apply_replace_index + 1, len(events))
        if events[i][0] == "replace"
    )

    def fsync_index(path: Path, before: int) -> int:
        target = str(path)
        return next(
            i
            for i, event in enumerate(events[:before])
            if event[0] == "fsync" and event[1] == target
        )

    def last_fsync_index(path: Path) -> int:
        target = str(path)
        return max(
            i
            for i, event in enumerate(events)
            if event[0] == "fsync" and event[1] == target
        )

    activation_id = preview["activation_id"]
    journal_file = env.activation_root / "journal" / f"{activation_id}.json"
    before_image = (
        env.activation_root
        / "before-images"
        / f"{preview['original_config_sha256']}.toml"
    )
    receipt_file = env.activation_root / "receipts" / f"{activation_id}.json"
    intent_file = next(
        p
        for p in _outcome_files(env.activation_root)
        if p.name.endswith(".intent.json")
    )
    outcome_file = next(
        p
        for p in _outcome_files(env.activation_root)
        if not p.name.endswith(".intent.json")
    )

    # Intent journal and before-image (file body + directory entry) are
    # durable strictly BEFORE the config swap.
    assert fsync_index(journal_file, apply_replace_index) < apply_replace_index
    assert fsync_index(journal_file.parent, apply_replace_index) < (
        apply_replace_index
    )
    assert fsync_index(before_image, apply_replace_index) < apply_replace_index
    assert fsync_index(before_image.parent, apply_replace_index) < (
        apply_replace_index
    )
    # The receipt is published (and durable) only AFTER the swap, as is the
    # config directory entry itself.
    config_dir_fsync = next(
        i
        for i in range(apply_replace_index, len(events))
        if events[i] == ("fsync", str(env.config_path.parent))
    )
    receipt_fsync = next(
        i
        for i in range(apply_replace_index, len(events))
        if events[i] == ("fsync", str(receipt_file))
    )
    assert receipt_fsync > config_dir_fsync
    assert fsync_index(receipt_file.parent, len(events)) > receipt_fsync

    # Rollback: the recovery intent is durable BEFORE the restore replace;
    # the outcome (and a fresh fsync of its directory entry) only AFTER it.
    assert fsync_index(intent_file, rollback_replace_index) < rollback_replace_index
    assert fsync_index(intent_file.parent, rollback_replace_index) < (
        rollback_replace_index
    )
    assert fsync_index(outcome_file, len(events)) > rollback_replace_index
    assert last_fsync_index(outcome_file.parent) > rollback_replace_index


# ---------------------------------------------------------------------------
# Preserve the repaired boundary: a genuine completed rollback stays the
# documented zero-write no-op (the (a) classification).
# ---------------------------------------------------------------------------


def test_completed_rollback_repeat_is_zero_write(tmp_path, capsys):
    env, receipt_path, original_sha, activated_sha = _applied(tmp_path, capsys)
    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    store_state = {
        str(p): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in sorted(env.activation_root.rglob("*"))
        if p.is_file()
    }
    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    assert json.loads(out)["status"] == "ALREADY_RESTORED"
    after = {
        str(p): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in sorted(env.activation_root.rglob("*"))
        if p.is_file()
    }
    assert after == store_state
