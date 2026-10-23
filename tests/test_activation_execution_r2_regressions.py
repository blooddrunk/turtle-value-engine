"""Phase 7-C4-A-R2 regressions: execution-boundary authority freshness (F1)
and final lock-component inode containment (F2).

Every defect reproduced here was first executed against pristine main
``2acc5a8`` (the merged R1 post-closure review / R2 selection head) with the
exact test file committed by this phase, run twice, and the observed baseline
outcomes (exit codes, statuses, config hashes, trust-root snapshot
identities, external trap-file effects) recorded in
``docs/status/phase-7-c4-a-r2-2026-10-23.md``.  The same file passes on the
R2 tree.  Nothing here uses a real owner key: every key, trust root, evidence
bundle, private config, activation store and trap file is a throwaway
runtime fixture under ``tmp_path``.

Coverage map (goal ``docs/goals/phase-7-c4-a-r2-execution-freshness-lock-path-hardening.md``):

* F1 — the CLI prepares the signed evidence, the trust-root snapshot and the
  authority verifier *before* the executor takes the config lock.  A key
  revocation/rotation or an evidence change landing in the real on-disk
  trust root *inside the same apply invocation* — after preparation, before
  protected execution — must produce the named fail-closed status
  ``ACTIVATION_AUTHORITY_STALE`` with zero config replacement, at both the
  derivation boundary and the last-moment pre-replace anchor.  The barriers
  are deterministic: library transitions are applied to the real temporary
  trust root exactly at the CLI-preparation→executor and
  derivation→``os.replace`` transitions.  This is explicitly NOT the
  already-covered "revoke between two separate CLI invocations" case.
* F2 — a pre-existing final-component ``locks/<digest>.lock`` symlink (or
  other non-regular entry) must be refused by name with no open/flock of
  the foreign inode, while a pre-existing *regular* lock file, genuine
  flock contention (``ACTIVATION_BUSY`` exit 3 only for real contention on
  the in-store lock) and the existing two-process 0/3 outcome keep working
  (``test_concurrent_apply_one_wins_one_busy`` in
  ``test_activation_execution.py`` covers the cross-process proof).

No cross-process or cross-file global atomicity is claimed: the last-moment
anchor observes the trust root at a point inside the lock, immediately
before the same-directory ``os.replace``; a change landing in the remaining
microseconds of that window is outside what this single-host executor can
prevent without inventing atomicity it does not have.
"""

import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

from tests.test_activation_execution import (
    _activated_bytes,
    _Env,
    _FixtureKey,
    _sha,
)
from turtle_value_engine import cli as cli_module
from turtle_value_engine.evolution import activation_execution
from turtle_value_engine.evolution.owner_trust_store import (
    OwnerProvenanceTrustStore,
    revoke_registry_key,
    rotate_registry_key,
)

ROOT_DIR = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _latest_snapshot_sha(env: _Env) -> str:
    """The current authoritative latest-snapshot identity of the trust root."""

    return (
        OwnerProvenanceTrustStore(env.trust_root)
        .latest_snapshot()
        .snapshot_content_sha256
    )


def _revoke_signing_key(env: _Env, reference: str) -> None:
    """Append a real revocation snapshot to the on-disk trust root."""

    OwnerProvenanceTrustStore(env.trust_root).apply_snapshot_operation(
        lambda latest: revoke_registry_key(latest, env.key.key_id, reference)
    )


def _rotate_signing_key(env: _Env, reference: str) -> None:
    """Append a real rotation snapshot (revoke old + enroll successor)."""

    successor = _FixtureKey()
    OwnerProvenanceTrustStore(env.trust_root).apply_snapshot_operation(
        lambda latest: rotate_registry_key(
            latest, env.key.key_id, successor.record, reference
        )
    )


def _lock_file_path(env: _Env) -> Path:
    """The exact final lock path the executor derives for this config."""

    return activation_execution._lock_path(
        env.activation_root.resolve(), env.config_path.resolve()
    )


def _plant_lock_symlink(env: _Env, trap: Path) -> Path:
    """Place a final-component lock symlink pointing at a foreign file."""

    trap.write_bytes(b"external trap target - must never be opened or locked\n")
    lock = _lock_file_path(env)
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.exists() or lock.is_symlink():
        lock.unlink()
    lock.symlink_to(trap)
    return lock


def _assert_authority_stale_refusal(out: str, payload: dict) -> None:
    assert payload["status"] == "ACTIVATION_AUTHORITY_STALE", out
    assert "AUTHORITY_TRUST_ROOT_SUPERSEDED" in payload["blockers"], out


# ---------------------------------------------------------------------------
# F1 — control: the fully authorized ordinary apply still succeeds
# ---------------------------------------------------------------------------


def test_f1_control_fully_authorized_apply_succeeds(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    original_bytes = env.config_path.read_bytes()
    preview = env.ready_preview(capsys)
    snapshot_before = _latest_snapshot_sha(env)

    code, out = env.apply(capsys, preview["plan_id"], preview["original_config_sha256"])
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATED", out
    assert env.config_path.read_bytes() == _activated_bytes()
    assert env.config_path.read_bytes() != original_bytes
    # The unchanged-authority apply consumes no trust-root transition.
    assert _latest_snapshot_sha(env) == snapshot_before


# ---------------------------------------------------------------------------
# F1 — revocation/rotation inside ONE apply invocation
# ---------------------------------------------------------------------------


def test_f1_revocation_after_preparation_before_execution_refused(
    tmp_path, capsys, monkeypatch
):
    """Barrier: CLI input preparation -> executor lock entry.

    The owner revokes the signing key in the real on-disk trust root after
    ``_prepare_activation_inputs`` has loaded the (now stale) snapshot and
    verifier, before ``apply_profile_activation`` runs.  Pristine main
    completed the activation through the stale authority (observed baseline:
    exit 0 / ACTIVATED); the fixed truth is a named fail-closed refusal.
    """

    env = _Env(tmp_path).setup(capsys)
    original_bytes = env.config_path.read_bytes()
    preview = env.ready_preview(capsys)
    snapshot_before = _latest_snapshot_sha(env)

    real_apply = cli_module.apply_profile_activation

    def revoking_apply(**kwargs):
        _revoke_signing_key(env, "c4a-r2 F1: revoked after preparation")
        return real_apply(**kwargs)

    monkeypatch.setattr(cli_module, "apply_profile_activation", revoking_apply)

    code, out = env.apply(capsys, preview["plan_id"], preview["original_config_sha256"])
    assert code == 1, out
    _assert_authority_stale_refusal(out, json.loads(out))
    assert env.config_path.read_bytes() == original_bytes
    assert _sha(env.config_path) == preview["original_config_sha256"]
    # The revocation really happened on disk (the refusal is not vacuous).
    assert _latest_snapshot_sha(env) != snapshot_before
    receipts = env.activation_root / "receipts"
    assert not receipts.is_dir() or list(receipts.iterdir()) == []


def test_f1_rotation_after_preparation_before_execution_refused(
    tmp_path, capsys, monkeypatch
):
    """Same boundary, key rotation instead of bare revocation."""

    env = _Env(tmp_path).setup(capsys)
    original_bytes = env.config_path.read_bytes()
    preview = env.ready_preview(capsys)
    snapshot_before = _latest_snapshot_sha(env)

    real_apply = cli_module.apply_profile_activation

    def rotating_apply(**kwargs):
        _rotate_signing_key(env, "c4a-r2 F1: rotated after preparation")
        return real_apply(**kwargs)

    monkeypatch.setattr(cli_module, "apply_profile_activation", rotating_apply)

    code, out = env.apply(capsys, preview["plan_id"], preview["original_config_sha256"])
    assert code == 1, out
    _assert_authority_stale_refusal(out, json.loads(out))
    assert env.config_path.read_bytes() == original_bytes
    assert _latest_snapshot_sha(env) != snapshot_before


def test_f1_revocation_after_derivation_before_replace_refused(
    tmp_path, capsys, monkeypatch
):
    """Barrier: fresh plan derivation -> the actual config ``os.replace``.

    The journal and before-image are already durable at this point; the
    last-moment anchor inside the staged replace must still refuse before
    the config byte is replaced.  Pristine main completed the activation
    (observed baseline: exit 0 / ACTIVATED) even at this late boundary.
    """

    env = _Env(tmp_path).setup(capsys)
    original_bytes = env.config_path.read_bytes()
    preview = env.ready_preview(capsys)

    real_stage = activation_execution._stage_and_replace

    def revoking_stage(*args, **kwargs):
        _revoke_signing_key(env, "c4a-r2 F1: revoked after derivation")
        return real_stage(*args, **kwargs)

    monkeypatch.setattr(activation_execution, "_stage_and_replace", revoking_stage)

    code, out = env.apply(capsys, preview["plan_id"], preview["original_config_sha256"])
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATION_AUTHORITY_STALE", out
    assert env.config_path.read_bytes() == original_bytes
    # No receipt may exist for an activation whose config was never replaced.
    receipts = env.activation_root / "receipts"
    assert not receipts.is_dir() or list(receipts.iterdir()) == []
    # The durable audit artifacts of the refused attempt (journal /
    # before-image) are immutable history; only the config is guaranteed
    # untouched, and no staged temp file may survive the refusal.
    staged = [
        entry
        for entry in env.config_path.parent.iterdir()
        if entry.name.startswith(".tve-activation-")
    ]
    assert staged == []


def test_f1_evidence_changed_after_preparation_before_execution_refused(
    tmp_path, capsys, monkeypatch
):
    """The strictly loaded evidence bundle must also still be loadable and
    byte-identical at the execution boundary; a tampered bundle directory is
    a named staleness refusal, not a stale-authority activation."""

    env = _Env(tmp_path).setup(capsys)
    original_bytes = env.config_path.read_bytes()
    preview = env.ready_preview(capsys)
    assert env.bundle_path is not None
    statement_path = env.bundle_path.parent / "statement.json"
    original_statement = statement_path.read_bytes()

    real_apply = cli_module.apply_profile_activation

    def tampering_apply(**kwargs):
        statement_path.write_bytes(b'{"contract": "tampered"}\n')
        return real_apply(**kwargs)

    monkeypatch.setattr(cli_module, "apply_profile_activation", tampering_apply)

    try:
        code, out = env.apply(
            capsys, preview["plan_id"], preview["original_config_sha256"]
        )
    finally:
        statement_path.write_bytes(original_statement)
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATION_AUTHORITY_STALE", out
    assert "AUTHORITY_EVIDENCE_UNREADABLE" in payload["blockers"], out
    assert env.config_path.read_bytes() == original_bytes


def test_f1_after_preview_between_invocation_revocation_still_blocks(
    tmp_path, capsys
):
    """Distinction case (not the within-one-invocation race): a revocation
    landing between two SEPARATE CLI invocations (preview, then apply) must
    keep blocking at plan time exactly as before R2."""

    env = _Env(tmp_path).setup(capsys)
    original_bytes = env.config_path.read_bytes()
    preview = env.ready_preview(capsys)
    _revoke_signing_key(env, "c4a-r2 F1: revoked between invocations")
    code, out = env.apply(capsys, preview["plan_id"], preview["original_config_sha256"])
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATION_BLOCKED", out
    assert any(
        "OWNER_AUTHORITY_REVERIFICATION" in blocker for blocker in payload["blockers"]
    )
    assert env.config_path.read_bytes() == original_bytes


# ---------------------------------------------------------------------------
# F2 — final lock-component inode containment
# ---------------------------------------------------------------------------


def test_f2_apply_refuses_preexisting_final_lock_symlink(tmp_path, capsys):
    """A legitimate ``locks/`` directory with a symlinked final lock entry.

    Pristine main followed the symlink, opened and flocked the foreign trap
    inode and completed the activation through it (observed baseline: exit 0
    / ACTIVATED with the trap file locked).  The fixed executor refuses the
    lock path by name and never touches the foreign file.
    """

    env = _Env(tmp_path).setup(capsys)
    original_bytes = env.config_path.read_bytes()
    preview = env.ready_preview(capsys)
    trap = tmp_path / "outside-store-trap.lock"
    lock = _plant_lock_symlink(env, trap)
    assert lock.is_symlink()

    code, out = env.apply(capsys, preview["plan_id"], preview["original_config_sha256"])
    assert code == 2, out
    assert "ACTIVATION_LOCK_SYMLINK" in out
    assert env.config_path.read_bytes() == original_bytes
    # The foreign target is neither altered nor removed; the hostile entry
    # itself is left in place (no "delete the stale lock" recovery).
    assert trap.read_bytes() == b"external trap target - must never be opened or locked\n"
    assert lock.is_symlink()
    receipts = env.activation_root / "receipts"
    assert not receipts.is_dir() or list(receipts.iterdir()) == []


def test_f2_apply_lock_symlink_with_held_trap_is_not_activation_busy(
    tmp_path, capsys
):
    """``ACTIVATION_BUSY`` (exit 3) must mean genuine flock contention on the
    in-store lock only.  With this process holding the trap file's flock,
    pristine main's foreign open+flock surfaced as exit 3 ACTIVATION_BUSY
    (proving the external inode was locked); the fixed executor answers with
    the symlink refusal instead — never exit 3."""

    env = _Env(tmp_path).setup(capsys)
    original_bytes = env.config_path.read_bytes()
    preview = env.ready_preview(capsys)
    trap = tmp_path / "outside-store-held-trap.lock"
    _plant_lock_symlink(env, trap)

    trap_fd = os.open(trap, os.O_RDWR)
    try:
        fcntl.flock(trap_fd, fcntl.LOCK_EX)
        code, out = env.apply(
            capsys, preview["plan_id"], preview["original_config_sha256"]
        )
    finally:
        os.close(trap_fd)
    assert code == 2, out
    assert "ACTIVATION_LOCK_SYMLINK" in out
    assert "ACTIVATION_BUSY" not in out
    assert env.config_path.read_bytes() == original_bytes


def _applied_env(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    preview = env.ready_preview(capsys)
    code, out = env.apply(capsys, preview["plan_id"], preview["original_config_sha256"])
    assert code == 0, out
    receipt_path = (
        env.activation_root / "receipts" / f"{preview['activation_id']}.json"
    )
    assert receipt_path.is_file()
    return env, receipt_path


def test_f2_rollback_refuses_preexisting_final_lock_symlink(tmp_path, capsys):
    """Rollback must refuse the same hostile final lock entry; pristine main
    rolled the config back through the foreign inode (observed baseline:
    exit 0 / ROLLED_BACK)."""

    env, receipt_path = _applied_env(tmp_path, capsys)
    activated_bytes = env.config_path.read_bytes()
    trap = tmp_path / "outside-store-rollback-trap.lock"
    lock = _plant_lock_symlink(env, trap)
    assert lock.is_symlink()

    code, out = env.rollback(capsys, receipt_path)
    assert code == 2, out
    assert "ACTIVATION_LOCK_SYMLINK" in out
    assert env.config_path.read_bytes() == activated_bytes
    assert trap.read_bytes() == b"external trap target - must never be opened or locked\n"
    rollbacks = env.activation_root / "rollbacks"
    assert not rollbacks.is_dir() or list(rollbacks.iterdir()) == []


def test_f2_rollback_lock_symlink_with_held_trap_is_not_activation_busy(
    tmp_path, capsys
):
    env, receipt_path = _applied_env(tmp_path, capsys)
    activated_bytes = env.config_path.read_bytes()
    trap = tmp_path / "outside-store-rollback-held-trap.lock"
    _plant_lock_symlink(env, trap)

    trap_fd = os.open(trap, os.O_RDWR)
    try:
        fcntl.flock(trap_fd, fcntl.LOCK_EX)
        code, out = env.rollback(capsys, receipt_path)
    finally:
        os.close(trap_fd)
    assert code == 2, out
    assert "ACTIVATION_LOCK_SYMLINK" in out
    assert "ACTIVATION_BUSY" not in out
    assert env.config_path.read_bytes() == activated_bytes


def test_f2_preexisting_regular_lock_file_still_works(tmp_path, capsys):
    """Control: a pre-existing *regular* lock file is ordinary operation."""

    env = _Env(tmp_path).setup(capsys)
    preview = env.ready_preview(capsys)
    lock = _lock_file_path(env)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_bytes(b"")
    inode_before = lock.stat().st_ino

    code, out = env.apply(capsys, preview["plan_id"], preview["original_config_sha256"])
    assert code == 0, out
    assert json.loads(out)["status"] == "ACTIVATED", out
    assert env.config_path.read_bytes() == _activated_bytes()
    # The same regular inode is reused (no unlink/recreate churn).
    assert lock.stat().st_ino == inode_before


def test_f2_fifo_lock_target_refused(tmp_path, capsys):
    """A non-regular final lock entry (FIFO) is refused by name; pristine
    main opened and flocked it and completed the activation."""

    env = _Env(tmp_path).setup(capsys)
    original_bytes = env.config_path.read_bytes()
    preview = env.ready_preview(capsys)
    lock = _lock_file_path(env)
    lock.parent.mkdir(parents=True, exist_ok=True)
    os.mkfifo(lock)

    code, out = env.apply(capsys, preview["plan_id"], preview["original_config_sha256"])
    assert code == 2, out
    assert "ACTIVATION_LOCK_NOT_REGULAR" in out
    assert env.config_path.read_bytes() == original_bytes


def test_f2_directory_lock_target_still_unavailable(tmp_path, capsys):
    """Control: a directory at the lock path keeps the existing open-failure
    classification on both the baseline and the fixed tree."""

    env = _Env(tmp_path).setup(capsys)
    original_bytes = env.config_path.read_bytes()
    preview = env.ready_preview(capsys)
    lock = _lock_file_path(env)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.mkdir()

    code, out = env.apply(capsys, preview["plan_id"], preview["original_config_sha256"])
    assert code == 2, out
    assert "ACTIVATION_LOCK_UNAVAILABLE" in out
    assert env.config_path.read_bytes() == original_bytes


def test_f2_real_two_process_contention_still_zero_or_three(tmp_path, capsys):
    """Real flock contention on the in-store regular lock keeps the exact
    0/3 outcome pair after the R2 lock hardening (same-process re-proof of
    the cross-process guarantee; the cross-process proof stays in
    ``test_concurrent_apply_one_wins_one_busy``)."""

    env = _Env(tmp_path).setup(capsys)
    preview = env.ready_preview(capsys)
    lock = _lock_file_path(env)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_bytes(b"")

    holder_fd = os.open(lock, os.O_RDWR)
    try:
        fcntl.flock(holder_fd, fcntl.LOCK_EX)
        argv = [
            sys.executable,
            "-m",
            "turtle_value_engine",
            *env.argv,
            "--apply",
            "--expected-plan-id",
            preview["plan_id"],
            "--expected-config-sha256",
            preview["original_config_sha256"],
        ]
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            cwd=ROOT_DIR,
            env={**os.environ, "PYTHONPATH": str(ROOT_DIR / "src")},
            timeout=180,
        )
    finally:
        os.close(holder_fd)
    assert completed.returncode == 3, completed.stdout + completed.stderr
    assert "ACTIVATION_BUSY" in completed.stdout + completed.stderr
    # The contender performed zero work while the real lock was held.
    assert _sha(env.config_path) == preview["original_config_sha256"]


# ---------------------------------------------------------------------------
# Fixtures stay honest: no production module state is silently mutated
# ---------------------------------------------------------------------------


def test_r2_regressions_use_only_throwaway_fixtures(tmp_path):
    """The R2 suite never ships keys or private material: every fixture lives
    under the disposable tmp_path (a cheap invariant worth pinning)."""

    env = _Env(tmp_path)
    assert env.trust_root.is_relative_to(tmp_path)
    assert env.activation_root.is_relative_to(tmp_path)
    assert env.config_path.is_relative_to(tmp_path)
