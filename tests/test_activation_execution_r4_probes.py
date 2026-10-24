"""Phase 7-C4-A-R4 conditional probe: prepared-input read/hash consistency.

Test-first discipline (goal
``docs/goals/phase-7-c4-a-r4-prepared-input-read-hash-consistency.md``):
this file was first committed UNCHANGED to a pristine worktree of the
reviewed selection baseline (``origin/main`` after PR #25, merge commit
``96d89e65ead14b6d2946e5e07af0e657cccdddac``) and executed before any
production change — twice — with the observed baseline outcomes recorded in
``docs/status/phase-7-c4-a-r4-2026-10-24.md``.

The R4 hypothesis: ``cli._prepare_activation_inputs`` parses each named
preloaded input file into an in-memory object (first read, inside the
loaders) and only afterwards calls ``_prepared_input_file_sha256s``, which
re-reads the same paths (second read) to record the R3 freshness digests.
A file replaced *between those two reads* binds the NEW bytes' SHA-256 to
the OLD prepared object: the in-memory authority drives the plan while both
R3 anchors re-hash the unchanged NEW on-disk bytes and see no drift.

* Probe A — the named policy-exception file is replaced with different
  valid canonical bytes (same ``exception_id``, different
  ``content_sha256``) at a deterministic barrier installed at
  ``_load_policy_exceptions`` return, i.e. immediately after the parser
  consumed the original bytes and strictly before the digest read.
* Probe B — the same replacement happens at ``_prepared_input_file_sha256s``
  entry, i.e. immediately before the digest read itself (the widest
  deterministic point inside the load-to-hash interval).
* Probe C — the decision-record file is replaced with different valid
  canonical bytes (same record id, altered authority annotation) at the
  same digest-entry barrier.
* Truth control — a separately started fresh CLI invocation on the mutated
  bytes must BLOCK (``DECISION_EXCEPTION_BINDING_STALE`` /
  ``EVIDENCE_RECORD_CONTENT_MISMATCH``), proving the replacement really
  changes the authorization outcome.
* Mechanism control — the identical monkeypatch barrier with NO mutation
  must leave the ordinary successful apply byte-identical, proving the
  barrier itself does not alter behavior.

Pristine main completed the activation through the stale in-memory objects
while the on-disk bytes were exactly the ones a fresh invocation refuses
(observed baseline: exit 0 / ACTIVATED, config replaced, receipt published).
The fixed truth pinned here derives every recorded digest from the exact
byte buffer that produced its prepared object, so both anchors refuse the
same interleaving with ``ACTIVATION_AUTHORITY_STALE`` before any durable
write.  No sleeps, no probabilistic timing, no real owner key: every key,
trust root, evidence bundle, private config and activation store is a
throwaway runtime fixture under ``tmp_path``.
"""

import json

from tests.test_activation_execution import (
    _activated_bytes,
    _Env,
    _sha,
)
from tests.test_activation_execution_r3_probes import (
    _assert_zero_receipts,
    _evidence_bundle_sha,
    _forged_record_bytes,
    _latest_snapshot_sha,
    _mutated_exception_bytes,
)
from turtle_value_engine import cli as cli_module


def _assert_no_durable_attempt(env: _Env) -> None:
    """A first-anchor refusal leaves zero durable attempt artifacts."""

    for name in ("journal", "receipts", "before-images", "rollbacks"):
        directory = env.activation_root / name
        assert not directory.is_dir() or list(directory.iterdir()) == [], name
    staged = [
        entry
        for entry in env.config_path.parent.iterdir()
        if entry.name.startswith(".tve-activation-")
    ]
    assert staged == []


# ---------------------------------------------------------------------------
# Truth control — the mutated bytes really change the authorization outcome
# ---------------------------------------------------------------------------


def test_r4_fresh_invocation_on_mutated_exception_blocks(tmp_path, capsys):
    """A separately started fresh CLI invocation must BLOCK on the new bytes.

    Required first proof for the same-invocation probes below: the in-place
    replacement is authorization-relevant, not cosmetic — a fresh
    preparation loads the new bytes and the plan is no longer READY.
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


# ---------------------------------------------------------------------------
# Probe A — replacement immediately after parser consumption of the
# exception bytes, strictly before the digest read
# ---------------------------------------------------------------------------


def test_r4_exception_replaced_after_parse_consumption_refused(
    tmp_path, capsys, monkeypatch
):
    """Barrier: ``_load_policy_exceptions`` return (parser consumption).

    The parser has consumed the ORIGINAL exception bytes when the external
    replacement lands; the recorded digest must therefore be the hash of
    the original consumed buffer, and the first in-lock anchor must refuse
    on the on-disk mismatch.  Pristine main recorded the digest of the NEW
    on-disk bytes for the OLD prepared object and completed the activation
    through it (observed baseline: exit 0 / ACTIVATED with the config
    replaced and a receipt published for bytes a fresh invocation refuses).
    """

    env = _Env(tmp_path).setup(capsys)
    original_bytes = env.config_path.read_bytes()
    preview = env.ready_preview(capsys)
    consumed_exception_sha = _sha(env.exception_path)
    snapshot_before = _latest_snapshot_sha(env)
    evidence_before = _evidence_bundle_sha(env)
    mutated = _mutated_exception_bytes()

    real_load = cli_module._load_policy_exceptions

    def mutating_load(source):
        exceptions = real_load(source)
        env.exception_path.write_bytes(mutated)
        return exceptions

    monkeypatch.setattr(cli_module, "_load_policy_exceptions", mutating_load)

    code, out = env.apply(
        capsys, preview["plan_id"], preview["original_config_sha256"]
    )
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATION_AUTHORITY_STALE", out
    assert "AUTHORITY_INPUT_CHANGED:policy-exception[0]" in payload["blockers"], out
    # The config was never replaced and no durable attempt artifact exists.
    assert env.config_path.read_bytes() == original_bytes
    assert _sha(env.config_path) == preview["original_config_sha256"]
    _assert_no_durable_attempt(env)
    # The replacement really happened on disk, and it is confined to the
    # named input file: the consumed (parsed) bytes and the on-disk bytes
    # are now two different valid documents, while the trust root and the
    # evidence bundle stay byte-identical.
    assert _sha(env.exception_path) != consumed_exception_sha
    assert env.exception_path.read_bytes() == mutated
    assert _latest_snapshot_sha(env) == snapshot_before
    assert _evidence_bundle_sha(env) == evidence_before
    # A fresh invocation on the resulting on-disk state still blocks: the
    # refusal did not consume or repair the mutated authorization input.
    code2, out2 = env.apply(
        capsys, preview["plan_id"], preview["original_config_sha256"]
    )
    assert code2 == 1, out2
    assert (
        "DECISION_EXCEPTION_BINDING_STALE" in json.loads(out2)["blockers"]
    ), out2


# ---------------------------------------------------------------------------
# Probe B — replacement immediately before the digest read itself
# ---------------------------------------------------------------------------


def test_r4_exception_replaced_before_digest_read_refused(
    tmp_path, capsys, monkeypatch
):
    """Barrier: ``_prepared_input_file_sha256s`` entry (the digest read).

    This is the widest deterministic point inside the load-to-hash
    interval: every parser read has happened and the digest read is the
    next file access.  The recorded digest must still be the hash of the
    exact buffer the parser consumed (the original bytes), so the first
    anchor refuses.  Pristine main hashed the NEW bytes here, both anchors
    then compared the NEW on-disk bytes against that NEW digest and the
    activation completed through the OLD prepared object (observed
    baseline: exit 0 / ACTIVATED).
    """

    env = _Env(tmp_path).setup(capsys)
    original_bytes = env.config_path.read_bytes()
    preview = env.ready_preview(capsys)
    consumed_exception_sha = _sha(env.exception_path)
    mutated = _mutated_exception_bytes()

    real_digests = cli_module._prepared_input_file_sha256s

    def mutating_digests(source):
        env.exception_path.write_bytes(mutated)
        return real_digests(source)

    monkeypatch.setattr(
        cli_module, "_prepared_input_file_sha256s", mutating_digests
    )

    code, out = env.apply(
        capsys, preview["plan_id"], preview["original_config_sha256"]
    )
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATION_AUTHORITY_STALE", out
    assert "AUTHORITY_INPUT_CHANGED:policy-exception[0]" in payload["blockers"], out
    assert env.config_path.read_bytes() == original_bytes
    assert _sha(env.config_path) == preview["original_config_sha256"]
    assert _sha(env.exception_path) != consumed_exception_sha
    _assert_no_durable_attempt(env)


# ---------------------------------------------------------------------------
# Probe C — the decision-record file replaced inside the same interval
# ---------------------------------------------------------------------------


def test_r4_decision_record_replaced_before_digest_read_refused(
    tmp_path, capsys, monkeypatch
):
    """Same digest-entry barrier for the decision-record file.

    The in-memory record (the one the plan authority consumes) stays the
    original one whose authority annotation matches the evidence bundle,
    so a digest recomputed from the mutated on-disk bytes would let the
    activation complete through a record a fresh invocation refuses with
    ``EVIDENCE_RECORD_CONTENT_MISMATCH``.  The fixed truth refuses at the
    first anchor on the consumed-vs-on-disk mismatch.
    """

    env = _Env(tmp_path).setup(capsys)
    original_bytes = env.config_path.read_bytes()
    preview = env.ready_preview(capsys)
    consumed_record_sha = _sha(env.record_path)
    mutated = _forged_record_bytes(env)

    real_digests = cli_module._prepared_input_file_sha256s

    def mutating_digests(source):
        env.record_path.write_bytes(mutated)
        return real_digests(source)

    monkeypatch.setattr(
        cli_module, "_prepared_input_file_sha256s", mutating_digests
    )

    code, out = env.apply(
        capsys, preview["plan_id"], preview["original_config_sha256"]
    )
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATION_AUTHORITY_STALE", out
    assert "AUTHORITY_INPUT_CHANGED:decision-record[0]" in payload["blockers"], out
    assert env.config_path.read_bytes() == original_bytes
    assert _sha(env.record_path) != consumed_record_sha
    _assert_no_durable_attempt(env)
    # Fresh-invocation truth for the mutated record bytes.
    code2, out2 = env.apply(
        capsys, preview["plan_id"], preview["original_config_sha256"]
    )
    assert code2 == 1, out2
    assert (
        "EVIDENCE_RECORD_CONTENT_MISMATCH" in json.loads(out2)["blockers"]
    ), out2


# ---------------------------------------------------------------------------
# Mechanism control — the barrier without any mutation completes normally
# ---------------------------------------------------------------------------


def test_r4_passthrough_digest_barrier_control_completes(
    tmp_path, capsys, monkeypatch
):
    """The identical barrier with NO mutation must not alter the apply.

    Proves the monkeypatch mechanism (and, post-fix, the consumed-bytes
    digest derivation reached through it) preserves the ordinary
    successful activation byte-for-byte: same exit 0, same ACTIVATED
    status, same receipt, same activated config bytes.
    """

    env = _Env(tmp_path).setup(capsys)
    preview = env.ready_preview(capsys)

    real_digests = cli_module._prepared_input_file_sha256s

    def passthrough_digests(source):
        return real_digests(source)

    monkeypatch.setattr(
        cli_module, "_prepared_input_file_sha256s", passthrough_digests
    )

    code, out = env.apply(
        capsys, preview["plan_id"], preview["original_config_sha256"]
    )
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATED", out
    assert env.config_path.read_bytes() == _activated_bytes()
    receipt_path = (
        env.activation_root / "receipts" / f"{payload['receipt']['activation_id']}.json"
    )
    assert receipt_path.is_file()
    assert payload["receipt"]["activation_id"] == preview["activation_id"]
