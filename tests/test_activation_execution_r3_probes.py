"""Phase 7-C4-A-R3 conditional probes: preloaded-input freshness inside ONE
apply invocation (F1) and an externally hard-linked final lock inode (F2).

Test-first discipline (goal
``docs/goals/phase-7-c4-a-r3-execution-input-freshness-lock-hardlink.md``):
this file was first committed UNCHANGED to a pristine worktree of the
reviewed selection head ``4247f20300464ada44019ecb2225527c9f407797``
(origin/main after PR #23) and executed before any production change —
twice — with the observed baseline outcomes (exit codes, statuses,
blockers, config/artifact hashes, inode identities, link counts) recorded
in ``docs/status/phase-7-c4-a-r3-2026-10-24.md``.  Only a reproduced
erroneous outcome justifies a fix; a green baseline control is reported as
NOT_REPRODUCED and never used as a defect-fix justification.

* F1 — the CLI's ``_prepare_activation_inputs`` loads the decision records,
  unsigned revocations, policy exceptions, the boundary input and the signed
  lifecycle statements BEFORE the executor takes the config lock, while the
  R2 recheck (``_build_activation_authority_recheck``) re-reads only the
  trust-root snapshot and the authority evidence bundle.  Each probe
  replaces ONE actually supplied named input file with different valid
  canonical bytes at a deterministic preparation -> executor (or derivation
  -> replace) monkeypatch barrier — no sleeps, no probabilistic timing —
  while the trust root and the evidence bundle stay byte-identical, after
  first proving that a separately started fresh CLI invocation would BLOCK
  on the mutated bytes.
* F2 — ``_ConfigLock.__enter__`` proves the final lock entry is not a
  symlink (``O_NOFOLLOW``) and is a regular file (``fstat``), but a regular
  entry hard-linked from OUTSIDE the activation store passes both checks
  and binds the executor's mutual exclusion to an inode that is also
  reachable (and flock-controllable) through a foreign directory entry.
  Each probe plants ``os.link`` on the same temporary filesystem and drives
  the real CLI apply/rollback, with and without an external flock held on
  the trap, proving inode identity, link counts, unchanged trap bytes and
  the exact exit/status.  ``ACTIVATION_BUSY`` (exit 3) must keep meaning
  only genuine contention on the in-store single-link lock.

Nothing here uses a real owner key: every key, trust root, evidence bundle,
private config, activation store and trap file is a throwaway runtime
fixture under ``tmp_path``.  Ordinary authorized apply/rollback, read-only
preview, genuine two-process 0/3 contention and single-link lock reuse stay
pinned by the C4-A/R1/R2 suites (``test_activation_execution.py``,
``test_activation_execution_r1_regressions.py``,
``test_activation_execution_r2_regressions.py``).
"""

import fcntl
import hashlib
import json
import os
from pathlib import Path

import pytest

from tests.test_activation_execution import (
    _activated_bytes,
    _Env,
    _policy_exception,
    _sha,
)
from turtle_value_engine import cli as cli_module
from turtle_value_engine.evolution import activation_execution
from turtle_value_engine.evolution.owner_decision import OwnerPolicyDecisionRecordV1
from turtle_value_engine.evolution.owner_trust_store import (
    OwnerProvenanceTrustStore,
    load_owner_decision_evidence,
)
from turtle_value_engine.providers.models import canonical_json_bytes

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


def _evidence_bundle_sha(env: _Env) -> str:
    """The current strictly loaded evidence-bundle content identity."""

    assert env.bundle_path is not None
    return load_owner_decision_evidence(env.bundle_path).bundle.content_sha256


def _mutated_exception_bytes() -> bytes:
    """Different valid canonical exception bytes (same id, altered rationale).

    ``exception_id`` deliberately omits rationale/declarer while
    ``content_sha256`` covers them, so this is exactly the class a fresh
    invocation refuses with ``DECISION_EXCEPTION_BINDING_STALE`` (pinned by
    ``test_forged_exception_content_blocks``).
    """

    mutated = _policy_exception(
        rationale="An externally rewritten policy rationale after preparation."
    )
    original = _policy_exception()
    assert mutated.exception_id == original.exception_id
    assert mutated.content_sha256 != original.content_sha256
    return (mutated.model_dump_json() + "\n").encode("utf-8")


def _forged_record_bytes(env: _Env) -> bytes:
    """Different valid canonical record bytes (same id, altered content).

    The record id derivation omits authority annotation text, so editing
    only ``authority.detail`` keeps the id while changing the content hash —
    the preflight's mismatch class a fresh invocation refuses through the
    executor association check (``EVIDENCE_RECORD_*``, pinned by
    ``test_forged_annotation_record_still_refused_by_executor``).
    """

    payload = json.loads(env.record_path.read_text("utf-8"))
    payload["authority"]["detail"] = (
        "R3 probe annotation: never produced by the capture boundary that "
        "wrote the bundle's embedded record."
    )
    payload["content_sha256"] = hashlib.sha256(
        canonical_json_bytes(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
    ).hexdigest()
    record = OwnerPolicyDecisionRecordV1.model_validate(payload)
    original = OwnerPolicyDecisionRecordV1.model_validate(
        json.loads(env.record_path.read_text("utf-8"))
    )
    assert record.decision_record_id == original.decision_record_id
    assert record.content_sha256 != original.content_sha256
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _lock_file_path(env: _Env) -> Path:
    """The exact final lock path the executor derives for this config."""

    return activation_execution._lock_path(
        env.activation_root.resolve(), env.config_path.resolve()
    )


def _plant_external_hardlink_lock(env: _Env, trap: Path) -> Path:
    """Make the final lock entry share an inode with a foreign regular file.

    The trap lives outside the activation store on the same filesystem; the
    planted ``locks/<digest>.lock`` entry is a genuine regular directory
    entry (not a symlink), so the R2 ``O_NOFOLLOW`` + regular-file checks
    alone cannot distinguish it from an ordinary lock file.
    """

    trap.parent.mkdir(parents=True, exist_ok=True)
    trap.write_bytes(b"external hardlink trap - must never be locked\n")
    lock = _lock_file_path(env)
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.exists() or lock.is_symlink():
        lock.unlink()
    os.link(trap, lock)
    lock_stat, trap_stat = lock.stat(), trap.stat()
    assert (lock_stat.st_ino, lock_stat.st_dev) == (trap_stat.st_ino, trap_stat.st_dev)
    assert lock_stat.st_nlink == 2 and trap_stat.st_nlink == 2
    return lock


def _skip_without_hardlink_support(tmp_path: Path) -> None:
    """Report (skip) platforms whose temporary filesystem refuses os.link."""

    source = tmp_path / "r3-link-support-probe-src"
    source.write_bytes(b"probe")
    target = tmp_path / "r3-link-support-probe-dst"
    try:
        os.link(source, target)
    except OSError as exc:
        pytest.skip(
            f"os.link is unsupported on this filesystem ({exc}); the F2 "
            "hardlink containment probes execute on the Linux CI host"
        )
    finally:
        source.unlink(missing_ok=True)
        target.unlink(missing_ok=True)


def _assert_zero_receipts(env: _Env) -> None:
    receipts = env.activation_root / "receipts"
    assert not receipts.is_dir() or list(receipts.iterdir()) == []


# ---------------------------------------------------------------------------
# F1 — fresh-invocation truth: the mutated named input files really block
# ---------------------------------------------------------------------------


def test_f1_fresh_invocation_on_mutated_exception_file_blocks(tmp_path, capsys):
    """A separately started CLI invocation must BLOCK on the mutated bytes.

    This is the required first proof for the same-invocation probes below:
    the in-place replacement is not cosmetic — a fresh preparation loads it
    and the plan is no longer READY.
    """

    env = _Env(tmp_path).setup(capsys)
    original_bytes = env.config_path.read_bytes()
    preview = env.ready_preview(capsys)
    mutated = _mutated_exception_bytes()
    assert mutated != env.exception_path.read_bytes()

    env.exception_path.write_bytes(mutated)
    code, out = env.apply(
        capsys, preview["plan_id"], preview["original_config_sha256"]
    )
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATION_BLOCKED", out
    assert "DECISION_EXCEPTION_BINDING_STALE" in payload["blockers"], out
    assert env.config_path.read_bytes() == original_bytes
    _assert_zero_receipts(env)


def test_f1_fresh_invocation_on_mutated_decision_record_blocks(tmp_path, capsys):
    """Same fresh-invocation truth for the mutated decision-record file."""

    env = _Env(tmp_path).setup(capsys)
    original_bytes = env.config_path.read_bytes()
    preview = env.ready_preview(capsys)
    mutated = _forged_record_bytes(env)
    assert mutated != env.record_path.read_bytes()

    env.record_path.write_bytes(mutated)
    code, out = env.apply(
        capsys, preview["plan_id"], preview["original_config_sha256"]
    )
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATION_BLOCKED", out
    assert "EVIDENCE_RECORD_CONTENT_MISMATCH" in payload["blockers"], out
    assert env.config_path.read_bytes() == original_bytes
    _assert_zero_receipts(env)


# ---------------------------------------------------------------------------
# F1 — same-invocation probes: the named input file changes AFTER
# preparation, BEFORE the executor consumes it
# ---------------------------------------------------------------------------


def test_f1_exception_replaced_after_preparation_before_apply_refused(
    tmp_path, capsys, monkeypatch
):
    """Barrier: CLI input preparation -> executor entry.

    The hash-bound policy-exception file is replaced with different valid
    canonical bytes after ``_prepare_activation_inputs`` consumed it and
    before ``apply_profile_activation`` runs, while the trust root and the
    evidence bundle stay byte-identical (proving the R2 recheck alone is
    blind to this class).  Pristine main completed the activation through
    the stale in-memory exception (observed baseline: exit 0 / ACTIVATED);
    the fixed truth is a named fail-closed refusal before any durable
    write.
    """

    env = _Env(tmp_path).setup(capsys)
    original_bytes = env.config_path.read_bytes()
    preview = env.ready_preview(capsys)
    prepared_exception_sha = _sha(env.exception_path)
    snapshot_before = _latest_snapshot_sha(env)
    evidence_before = _evidence_bundle_sha(env)
    mutated = _mutated_exception_bytes()

    real_apply = cli_module.apply_profile_activation

    def mutating_apply(**kwargs):
        env.exception_path.write_bytes(mutated)
        return real_apply(**kwargs)

    monkeypatch.setattr(cli_module, "apply_profile_activation", mutating_apply)

    code, out = env.apply(
        capsys, preview["plan_id"], preview["original_config_sha256"]
    )
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATION_AUTHORITY_STALE", out
    assert "AUTHORITY_INPUT_CHANGED:policy-exception[0]" in payload["blockers"], out
    assert env.config_path.read_bytes() == original_bytes
    assert _sha(env.config_path) == preview["original_config_sha256"]
    # The mutation really happened on disk, and it is confined to the named
    # input file — the trust root and the evidence bundle are unchanged.
    assert _sha(env.exception_path) != prepared_exception_sha
    assert _latest_snapshot_sha(env) == snapshot_before
    assert _evidence_bundle_sha(env) == evidence_before
    # Refused at the first anchor: no durable attempt artifact may exist.
    journal = env.activation_root / "journal"
    assert not journal.is_dir() or list(journal.iterdir()) == []
    _assert_zero_receipts(env)


def test_f1_exception_replaced_after_derivation_before_replace_refused(
    tmp_path, capsys, monkeypatch
):
    """Barrier: fresh plan derivation -> the config ``os.replace``.

    The journal and before-image are already durable at this point; the
    last-moment anchor inside the staged replace must still refuse on the
    stale named input, without replacing the config and without leaving a
    staged temp file behind.
    """

    env = _Env(tmp_path).setup(capsys)
    original_bytes = env.config_path.read_bytes()
    preview = env.ready_preview(capsys)
    mutated = _mutated_exception_bytes()

    real_stage = activation_execution._stage_and_replace

    def mutating_stage(*args, **kwargs):
        env.exception_path.write_bytes(mutated)
        return real_stage(*args, **kwargs)

    monkeypatch.setattr(
        activation_execution, "_stage_and_replace", mutating_stage
    )

    code, out = env.apply(
        capsys, preview["plan_id"], preview["original_config_sha256"]
    )
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATION_AUTHORITY_STALE", out
    assert "AUTHORITY_INPUT_CHANGED:policy-exception[0]" in payload["blockers"], out
    assert env.config_path.read_bytes() == original_bytes
    _assert_zero_receipts(env)
    staged = [
        entry
        for entry in env.config_path.parent.iterdir()
        if entry.name.startswith(".tve-activation-")
    ]
    assert staged == []


def test_f1_decision_record_replaced_after_preparation_refused(
    tmp_path, capsys, monkeypatch
):
    """Same preparation -> executor barrier for the decision-record file."""

    env = _Env(tmp_path).setup(capsys)
    original_bytes = env.config_path.read_bytes()
    preview = env.ready_preview(capsys)
    prepared_record_sha = _sha(env.record_path)
    mutated = _forged_record_bytes(env)

    real_apply = cli_module.apply_profile_activation

    def mutating_apply(**kwargs):
        env.record_path.write_bytes(mutated)
        return real_apply(**kwargs)

    monkeypatch.setattr(cli_module, "apply_profile_activation", mutating_apply)

    code, out = env.apply(
        capsys, preview["plan_id"], preview["original_config_sha256"]
    )
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATION_AUTHORITY_STALE", out
    assert "AUTHORITY_INPUT_CHANGED:decision-record[0]" in payload["blockers"], out
    assert env.config_path.read_bytes() == original_bytes
    assert _sha(env.record_path) != prepared_record_sha
    _assert_zero_receipts(env)


def test_f1_exception_removed_after_preparation_refused(
    tmp_path, capsys, monkeypatch
):
    """An input file that becomes unreadable mid-invocation is also stale."""

    env = _Env(tmp_path).setup(capsys)
    original_bytes = env.config_path.read_bytes()
    preview = env.ready_preview(capsys)

    real_apply = cli_module.apply_profile_activation

    def removing_apply(**kwargs):
        env.exception_path.unlink()
        return real_apply(**kwargs)

    monkeypatch.setattr(cli_module, "apply_profile_activation", removing_apply)

    code, out = env.apply(
        capsys, preview["plan_id"], preview["original_config_sha256"]
    )
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATION_AUTHORITY_STALE", out
    assert "AUTHORITY_INPUT_UNREADABLE:policy-exception[0]" in payload["blockers"], out
    assert env.config_path.read_bytes() == original_bytes
    _assert_zero_receipts(env)


# ---------------------------------------------------------------------------
# F2 — externally hard-linked final lock inode
# ---------------------------------------------------------------------------


def test_f2_apply_refuses_preexisting_hardlinked_lock_entry(tmp_path, capsys):
    """A regular lock entry hard-linked from outside the store.

    Pristine main opened the shared inode, flocked it and completed the
    activation with the executor's mutual exclusion bound to an inode also
    reachable outside the activation store (observed baseline: exit 0 /
    ACTIVATED, trap bytes unchanged, link count 2).  The fixed executor
    refuses the multi-link lock entry by name before any inode is locked
    and never touches the foreign file.
    """

    _skip_without_hardlink_support(tmp_path)
    env = _Env(tmp_path).setup(capsys)
    original_bytes = env.config_path.read_bytes()
    preview = env.ready_preview(capsys)
    trap = tmp_path / "outside-store" / "apply-hardlink-trap.lock"
    lock = _plant_external_hardlink_lock(env, trap)

    code, out = env.apply(
        capsys, preview["plan_id"], preview["original_config_sha256"]
    )
    assert code == 2, out
    assert "ACTIVATION_LOCK_HARDLINK" in out
    assert "ACTIVATION_BUSY" not in out
    assert env.config_path.read_bytes() == original_bytes
    # The hostile entry and its foreign target are neither altered nor removed.
    assert trap.read_bytes() == b"external hardlink trap - must never be locked\n"
    lock_stat, trap_stat = lock.stat(), trap.stat()
    assert (lock_stat.st_ino, lock_stat.st_dev) == (trap_stat.st_ino, trap_stat.st_dev)
    assert lock_stat.st_nlink == 2
    _assert_zero_receipts(env)


def test_f2_held_external_hardlink_is_not_activation_busy(tmp_path, capsys):
    """``ACTIVATION_BUSY`` (exit 3) must mean genuine in-store contention.

    With this process holding the trap file's flock, pristine main's
    foreign-inode flock contended and surfaced as exit 3 ACTIVATION_BUSY
    (observed baseline) — a hostile lock layout fabricating genuine-busy
    semantics.  The fixed executor answers with the multi-link refusal
    instead — never exit 3.
    """

    _skip_without_hardlink_support(tmp_path)
    env = _Env(tmp_path).setup(capsys)
    original_bytes = env.config_path.read_bytes()
    preview = env.ready_preview(capsys)
    trap = tmp_path / "outside-store" / "apply-held-hardlink-trap.lock"
    _plant_external_hardlink_lock(env, trap)

    trap_fd = os.open(trap, os.O_RDWR)
    try:
        fcntl.flock(trap_fd, fcntl.LOCK_EX)
        code, out = env.apply(
            capsys, preview["plan_id"], preview["original_config_sha256"]
        )
    finally:
        os.close(trap_fd)
    assert code == 2, out
    assert "ACTIVATION_LOCK_HARDLINK" in out
    assert "ACTIVATION_BUSY" not in out
    assert env.config_path.read_bytes() == original_bytes
    assert trap.read_bytes() == b"external hardlink trap - must never be locked\n"
    _assert_zero_receipts(env)


def _applied_env(tmp_path, capsys):
    env = _Env(tmp_path).setup(capsys)
    preview = env.ready_preview(capsys)
    code, out = env.apply(
        capsys, preview["plan_id"], preview["original_config_sha256"]
    )
    assert code == 0, out
    receipt_path = (
        env.activation_root / "receipts" / f"{preview['activation_id']}.json"
    )
    assert receipt_path.is_file()
    return env, receipt_path


def test_f2_rollback_refuses_hardlinked_lock_entry(tmp_path, capsys):
    """The attacker hard-links the legitimate lock entry after a real apply.

    ``os.link(lock, trap)`` makes the existing in-store lock inode reachable
    from outside the store; pristine main rolled the config back through
    the now-shared inode (observed baseline: exit 0 / ROLLED_BACK).  The
    fixed rollback refuses the multi-link entry without touching the trap.
    """

    _skip_without_hardlink_support(tmp_path)
    env, receipt_path = _applied_env(tmp_path, capsys)
    activated_bytes = env.config_path.read_bytes()
    trap = tmp_path / "outside-store" / "rollback-hardlink-trap.lock"
    trap.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock_file_path(env)
    assert lock.is_file() and lock.stat().st_nlink == 1
    lock_bytes = lock.read_bytes()
    # The attacker's link is the trap entry itself (the store's lock inode
    # becomes reachable from outside the activation store).
    os.link(lock, trap)
    assert lock.stat().st_nlink == 2 and trap.stat().st_nlink == 2
    assert trap.read_bytes() == lock_bytes

    code, out = env.rollback(capsys, receipt_path)
    assert code == 2, out
    assert "ACTIVATION_LOCK_HARDLINK" in out
    assert "ACTIVATION_BUSY" not in out
    assert env.config_path.read_bytes() == activated_bytes
    assert trap.read_bytes() == lock_bytes
    rollbacks = env.activation_root / "rollbacks"
    assert not rollbacks.is_dir() or list(rollbacks.iterdir()) == []


def test_f2_rollback_held_external_hardlink_is_not_activation_busy(
    tmp_path, capsys
):
    """Same held-trap proof for rollback (baseline observed exit 3)."""

    _skip_without_hardlink_support(tmp_path)
    env, receipt_path = _applied_env(tmp_path, capsys)
    activated_bytes = env.config_path.read_bytes()
    trap = tmp_path / "outside-store" / "rollback-held-hardlink-trap.lock"
    trap.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock_file_path(env)
    lock_bytes = lock.read_bytes()
    os.link(lock, trap)
    assert lock.stat().st_nlink == 2

    trap_fd = os.open(trap, os.O_RDWR)
    try:
        fcntl.flock(trap_fd, fcntl.LOCK_EX)
        code, out = env.rollback(capsys, receipt_path)
    finally:
        os.close(trap_fd)
    assert code == 2, out
    assert "ACTIVATION_LOCK_HARDLINK" in out
    assert "ACTIVATION_BUSY" not in out
    assert env.config_path.read_bytes() == activated_bytes
    assert trap.read_bytes() == lock_bytes


def test_f2_executor_created_and_single_link_locks_still_work(tmp_path, capsys):
    """Control: the ordinary lock lifecycle keeps a single directory link.

    The executor-created lock entry (fresh apply) and the reused entry of a
    later rollback both have ``st_nlink == 1``; the containment refusal must
    never fire for ordinary operation.  (The pre-existing regular lock file
    control and the real two-process 0/3 contention proof stay pinned by the
    R2 suite.)
    """

    _skip_without_hardlink_support(tmp_path)
    env, receipt_path = _applied_env(tmp_path, capsys)
    lock = _lock_file_path(env)
    assert lock.is_file() and lock.stat().st_nlink == 1

    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    assert json.loads(out)["status"] == "ROLLED_BACK", out
    assert env.config_path.read_bytes() != _activated_bytes()
    assert lock.stat().st_nlink == 1
