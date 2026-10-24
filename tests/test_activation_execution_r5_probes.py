"""Phase 7-C4-A-R5 conditional probe: rollback input classification parity.

Test-first discipline (goal
``docs/goals/phase-7-c4-a-r5-conditional-rollback-input-classification.md``,
selected by the C4-B-R1 independent review): this file was first committed
UNCHANGED on the pristine reviewed baseline (``origin/main`` at merge commit
``e60d7b436a0f6bac5788a6e9126324ada29eede8`` after PR #29) and executed
before any production change, twice, with the observed baseline outcomes
recorded in ``docs/status/phase-7-c4-a-r5-2026-10-24.md``.

The R5 hypothesis (review finding H1): the executor rollback paths verify the
before-image *byte hashes* but then parse and inspect the bytes without the
structural guard the C4-B status inspector already has
(``activation_status._verify_before_image``).  A locally forged, fully
self-consistent receipt (all identity/content hashes recomputed with the real
deterministic helpers, so it passes receipt validation) whose bound
before-image or current config is *hash-consistent but structurally
anomalous* can therefore escape as an unclassified exception:

* ``_load_verified_before_image`` — ``tomllib.loads`` /
  ``image_parsed.get("profiles", {}).get("default")`` on a scalar
  ``profiles`` value raises ``AttributeError``; malformed TOML or invalid
  UTF-8 escapes as a bare parser/decode error instead of the established
  named ``BEFORE_IMAGE_CONTENT_MISMATCH``.
* ``rollback_profile_activation`` — the prior-bytes idempotence branch
  repeats the same unguarded nested ``.get`` over the *current* config
  bytes.

The threat model is forged or adversarial receipt-bound local inputs in a
disposable private root — never a genuine executor-generated receipt (a real
apply starts from a parsed valid config).  Every negative fixture here is
built in ``tmp_path``; no real owner key, signature or activation state is
used.  The controls pin the exact preexisting statuses and durable effects
(genuine apply -> rollback -> idempotent rollback, missing/tampered
before-image, interrupted-restore finalization) and a mechanism control
proves the forged-but-well-formed fixture still rolls back, so the refusals
below are structural, not an artifact of early rejection.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_activation_execution import (
    ROOT,
    _applied_env,
    _Env,
    _sha,
)
from turtle_value_engine.evolution.activation_execution import (
    ActivationExecutionBlocked,
    ActivationExecutionError,
    ProfileActivationReceiptV1,
    rollback_profile_activation,
)
from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.providers.normalization import deterministic_id

#: Valid TOML whose ``profiles`` value is a scalar, not a table — the exact
#: structural anomaly the review named (``profiles = "unexpected"``).
SCALAR_PROFILES_BYTES = b'profiles = "unexpected"\n'

#: Hash-consistent but syntactically invalid TOML (unterminated string).
INVALID_TOML_BYTES = b'profiles = "unterminated\n'

#: Hash-consistent bytes that are not valid UTF-8 at all.
INVALID_UTF8_BYTES = b'\xff\xfe profiles = "strict-v1"\n'

#: A well-formed alternative prior config (still ``strict-v1``, one extra
#: comment line) for the mechanism control: structurally valid forged
#: receipts must keep rolling back exactly as before.
WELLFORMED_ALTERNATIVE_PRIOR = (
    b'# an alternative but well-formed prior configuration\n\n[profiles]\ndefault = "strict-v1"\n'
)


class _Crash(Exception):
    """Deterministic interruption raised from a library fault hook."""


def _reforge_receipt(base: ProfileActivationReceiptV1, **overrides) -> ProfileActivationReceiptV1:
    """Rebuild a *self-consistent* receipt from a genuine one.

    Receipt validation proves internal consistency, not genuine owner
    authority: every identity is recomputed with the repository's real
    deterministic helpers exactly as the model validator does, so the forged
    document passes ``ProfileActivationReceiptV1`` validation and reaches
    the executor paths under probe.
    """

    payload = base.model_dump(mode="json")
    payload.pop("content_sha256")
    payload.update(overrides)
    payload["activation_id"] = deterministic_id(
        "profile-activation-execution",
        payload["plan_id"],
        payload["project_config_path"],
        payload["prior_config_sha256"],
        payload["activated_config_sha256"],
        payload["decision_record_id"],
        payload["decision_record_content_sha256"],
        payload["evidence_bundle_id"],
        payload["evidence_bundle_content_sha256"],
        payload["authority_registry_id"],
        payload["authority_registry_content_sha256"],
    )
    payload["content_sha256"] = _sha256(canonical_json_bytes(payload))
    return ProfileActivationReceiptV1.model_validate(payload)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bind_prior_bytes(
    receipt: ProfileActivationReceiptV1, prior_bytes: bytes
) -> ProfileActivationReceiptV1:
    """Re-bind a receipt's prior/before-image identity to ``prior_bytes``."""

    prior_sha = _sha256(prior_bytes)
    return _reforge_receipt(
        receipt,
        prior_config_sha256=prior_sha,
        before_image_sha256=prior_sha,
        before_image_name=f"{prior_sha}.toml",
    )


def _publish_forged_store_entries(
    env: _Env, receipt: ProfileActivationReceiptV1, prior_bytes: bytes
) -> Path:
    """Publish the forged receipt and its hash-consistent before-image."""

    image_path = env.activation_root / "before-images" / receipt.before_image_name
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(prior_bytes)
    receipt_path = env.activation_root / "receipts" / f"{receipt.activation_id}.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_bytes(receipt.serialized_bytes())
    return receipt_path


def _tree_snapshot(env: _Env) -> dict[str, str]:
    """Hash snapshot of the whole disposable tree minus per-config locks.

    The executor's exclusive per-config lock file under ``locks/`` is its
    legitimate, documented behavior and is the only artifact a refusal may
    create; everything else — config bytes, journal, receipts, before-images,
    rollbacks — must be byte-identical across a refused rollback.
    """

    state: dict[str, str] = {}
    for path in sorted(env.tmp.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(env.tmp)
        if relative.parts[0] == "activation" and "locks" in relative.parts:
            continue
        state[str(relative)] = _sha(path)
    return state


def _rollback_subprocess(env: _Env, receipt_path: Path) -> subprocess.CompletedProcess:
    argv = [
        sys.executable,
        "-m",
        "turtle_value_engine",
        "evolution",
        "rollback-activation",
        "--receipt",
        str(receipt_path),
        "--activation-root",
        str(env.activation_root),
    ]
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )


# ---------------------------------------------------------------------------
# Mechanism control — the forged fixture is not trivially rejected earlier
# ---------------------------------------------------------------------------


def test_r5_control_wellformed_forged_receipt_still_rolls_back(tmp_path, capsys):
    """A structurally valid forged receipt must reach the full restore path.

    Required first proof for every refusal below: the forging mechanism
    (real deterministic identity helpers, hash-consistent before-image,
    receipt validation) drives the real executor through its ordinary
    successful rollback, so the structural refusals in the probes are caused
    by the anomalous bytes alone, not by an incidental earlier guard.
    """

    env, receipt_path, original_sha, activated_sha = _applied_env(tmp_path, capsys)
    genuine = ProfileActivationReceiptV1.model_validate(json.loads(receipt_path.read_bytes()))
    forged = _bind_prior_bytes(genuine, WELLFORMED_ALTERNATIVE_PRIOR)
    forged_path = _publish_forged_store_entries(env, forged, WELLFORMED_ALTERNATIVE_PRIOR)
    assert _sha(env.config_path) == activated_sha

    code, out = env.rollback(capsys, forged_path)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "ROLLED_BACK", payload
    assert env.config_path.read_bytes() == WELLFORMED_ALTERNATIVE_PRIOR
    # The genuine receipt and its before-image survive untouched.
    assert receipt_path.read_bytes() == genuine.serialized_bytes()
    genuine_image = env.activation_root / "before-images" / genuine.before_image_name
    assert _sha(genuine_image) == genuine.before_image_sha256


# ---------------------------------------------------------------------------
# Probe 1 — hash-consistent before-image with a scalar `profiles` value
# (current config holds the genuine activated bytes)
# ---------------------------------------------------------------------------


def _scalar_before_image_env(tmp_path, capsys):
    env, receipt_path, original_sha, activated_sha = _applied_env(tmp_path, capsys)
    genuine = ProfileActivationReceiptV1.model_validate(json.loads(receipt_path.read_bytes()))
    forged = _bind_prior_bytes(genuine, SCALAR_PROFILES_BYTES)
    forged_path = _publish_forged_store_entries(env, forged, SCALAR_PROFILES_BYTES)
    assert _sha(env.config_path) == activated_sha
    assert activated_sha != forged.prior_config_sha256
    return env, forged_path, forged


def test_r5_probe_before_image_scalar_profiles_classified(tmp_path, capsys):
    """Library probe 1: named BEFORE_IMAGE_CONTENT_MISMATCH, not AttributeError.

    Pristine baseline: ``AttributeError: 'str' object has no attribute
    'get'`` escaped ``_load_verified_before_image`` after both byte-hash
    checks had already passed.
    """

    env, forged_path, forged = _scalar_before_image_env(tmp_path, capsys)
    snapshot = _tree_snapshot(env)

    with pytest.raises(ActivationExecutionError) as excinfo:
        rollback_profile_activation(
            receipt_path=forged_path,
            activation_root=env.activation_root,
        )
    assert excinfo.value.code == "BEFORE_IMAGE_CONTENT_MISMATCH", excinfo.value
    assert _tree_snapshot(env) == snapshot


def test_r5_cli_before_image_scalar_profiles_exit2_named(tmp_path, capsys):
    """CLI probe 1: exit class 2 with the named code, no traceback.

    Pristine baseline: uncaught ``AttributeError`` — exit code 1 with a
    Python traceback on stderr.
    """

    env, forged_path, _forged = _scalar_before_image_env(tmp_path, capsys)
    snapshot = _tree_snapshot(env)

    proc = _rollback_subprocess(env, forged_path)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 2, combined
    assert "BEFORE_IMAGE_CONTENT_MISMATCH" in proc.stderr, combined
    assert "Traceback" not in combined
    _assert_tree_unchanged(env, snapshot)


def _assert_tree_unchanged(env: _Env, snapshot: dict[str, str]) -> None:
    after = _tree_snapshot(env)
    assert after == snapshot, sorted(set(after) ^ set(snapshot)) or [
        key for key in after if after[key] != snapshot.get(key)
    ]


# ---------------------------------------------------------------------------
# Probe 2 — hash-consistent before-image that is malformed TOML or invalid
# UTF-8 (current config still holds the genuine activated bytes)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "anomaly_bytes",
    [
        pytest.param(INVALID_TOML_BYTES, id="invalid-toml"),
        pytest.param(INVALID_UTF8_BYTES, id="invalid-utf8"),
    ],
)
def test_r5_probe_before_image_unparsable_classified(tmp_path, capsys, anomaly_bytes):
    """Library probe 2: the same named before-image error, no bare exception.

    Pristine baseline: ``tomllib.TOMLDecodeError`` /
    ``UnicodeDecodeError`` escaped ``_load_verified_before_image`` as bare
    parser/decode errors instead of the established named classification
    the C4-B status inspector already reports for the same bytes.
    """

    env, receipt_path, original_sha, activated_sha = _applied_env(tmp_path, capsys)
    genuine = ProfileActivationReceiptV1.model_validate(json.loads(receipt_path.read_bytes()))
    forged = _bind_prior_bytes(genuine, anomaly_bytes)
    forged_path = _publish_forged_store_entries(env, forged, anomaly_bytes)
    snapshot = _tree_snapshot(env)

    with pytest.raises(ActivationExecutionError) as excinfo:
        rollback_profile_activation(
            receipt_path=forged_path,
            activation_root=env.activation_root,
        )
    assert excinfo.value.code == "BEFORE_IMAGE_CONTENT_MISMATCH", excinfo.value
    assert _tree_snapshot(env) == snapshot


@pytest.mark.parametrize(
    "anomaly_bytes",
    [
        pytest.param(INVALID_TOML_BYTES, id="invalid-toml"),
        pytest.param(INVALID_UTF8_BYTES, id="invalid-utf8"),
    ],
)
def test_r5_cli_before_image_unparsable_exit2_named(tmp_path, capsys, anomaly_bytes):
    """CLI probe 2: exit 2 with the named code — not a raw parser message.

    Pristine baseline: the ``ValueError``-derived parser/decode error
    already exited 2 but printed an unclassified raw parser message with no
    named before-image code.
    """

    env, receipt_path, original_sha, activated_sha = _applied_env(tmp_path, capsys)
    genuine = ProfileActivationReceiptV1.model_validate(json.loads(receipt_path.read_bytes()))
    forged = _bind_prior_bytes(genuine, anomaly_bytes)
    forged_path = _publish_forged_store_entries(env, forged, anomaly_bytes)
    snapshot = _tree_snapshot(env)

    proc = _rollback_subprocess(env, forged_path)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 2, combined
    assert "BEFORE_IMAGE_CONTENT_MISMATCH" in proc.stderr, combined
    assert "Traceback" not in combined
    _assert_tree_unchanged(env, snapshot)


# ---------------------------------------------------------------------------
# Probe 3 — self-consistent receipt whose prior hash equals the *current*
# config bytes, but the current TOML's `profiles` is structurally anomalous
# (the prior-bytes idempotence branch)
# ---------------------------------------------------------------------------


def _prior_hash_current_env(tmp_path, capsys, current_bytes: bytes):
    """Env whose config holds ``current_bytes`` and a receipt binding them.

    The genuine apply establishes the real activated identity; the config is
    then overwritten with the anomalous bytes and the forged receipt claims
    exactly those bytes as its hash-consistent prior config, so the
    idempotence branch is reached first.
    """

    env, receipt_path, original_sha, activated_sha = _applied_env(tmp_path, capsys)
    genuine = ProfileActivationReceiptV1.model_validate(json.loads(receipt_path.read_bytes()))
    env.config_path.write_bytes(current_bytes)
    forged = _bind_prior_bytes(genuine, current_bytes)
    forged_path = _publish_forged_store_entries(env, forged, current_bytes)
    assert _sha(env.config_path) == forged.prior_config_sha256
    assert forged.prior_config_sha256 != activated_sha
    return env, forged_path, forged


@pytest.mark.parametrize(
    "anomaly_bytes",
    [
        pytest.param(SCALAR_PROFILES_BYTES, id="scalar-profiles"),
        pytest.param(INVALID_TOML_BYTES, id="invalid-toml"),
        pytest.param(INVALID_UTF8_BYTES, id="invalid-utf8"),
    ],
)
def test_r5_probe_prior_hash_current_config_anomalous_classified(tmp_path, capsys, anomaly_bytes):
    """Library probe 3: controlled blocked refusal, not AttributeError.

    Pristine baseline: the idempotence branch's unguarded
    ``parsed.get("profiles", {}).get("default")`` raised ``AttributeError``
    on the scalar case and a bare parser/decode error otherwise.  Fixed
    truth: structurally unverifiable prior-hash bytes do not *prove* the
    prior default in place, so the executor falls through to its existing
    hash-precondition refusal — the established blocked class, exit 1, zero
    clobber, zero rollback-intent/outcome writes.
    """

    env, forged_path, forged = _prior_hash_current_env(tmp_path, capsys, anomaly_bytes)
    snapshot = _tree_snapshot(env)

    with pytest.raises(ActivationExecutionBlocked) as excinfo:
        rollback_profile_activation(
            receipt_path=forged_path,
            activation_root=env.activation_root,
        )
    payload = excinfo.value.payload
    assert payload["status"] == "ROLLBACK_PRECONDITION_VIOLATED", payload
    assert payload["current_config_sha256"] == forged.prior_config_sha256
    assert payload["expected_config_sha256"] == forged.activated_config_sha256
    assert env.config_path.read_bytes() == anomaly_bytes
    assert _tree_snapshot(env) == snapshot


def test_r5_cli_prior_hash_current_config_scalar_exit1_blocked(tmp_path, capsys):
    """CLI probe 3 (scalar profiles): blocked JSON payload, no traceback.

    Pristine baseline: uncaught ``AttributeError`` — exit 1 with a Python
    traceback and no printable payload.  Fixed truth: exit 1 remains the
    *blocked* class but now prints the machine-readable
    ``ROLLBACK_PRECONDITION_VIOLATED`` payload; the config is not clobbered
    and no rollback intent/outcome is written.
    """

    env, forged_path, forged = _prior_hash_current_env(tmp_path, capsys, SCALAR_PROFILES_BYTES)
    snapshot = _tree_snapshot(env)

    proc = _rollback_subprocess(env, forged_path)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined
    assert "Traceback" not in combined
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ROLLBACK_PRECONDITION_VIOLATED", payload
    assert payload["current_config_sha256"] == forged.prior_config_sha256
    assert env.config_path.read_bytes() == SCALAR_PROFILES_BYTES
    _assert_tree_unchanged(env, snapshot)


# ---------------------------------------------------------------------------
# Controls — exact preexisting statuses and durable effects stay untouched
# ---------------------------------------------------------------------------


def test_r5_control_genuine_apply_rollback_idempotent(tmp_path, capsys):
    """Control: genuine signed apply -> rollback -> idempotent rollback."""

    env, receipt_path, original_sha, activated_sha = _applied_env(tmp_path, capsys)
    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    assert json.loads(out)["status"] == "ROLLED_BACK"
    assert _sha(env.config_path) == original_sha

    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    assert json.loads(out)["status"] == "ALREADY_RESTORED"
    assert _sha(env.config_path) == original_sha


def test_r5_control_before_image_missing_refused(tmp_path, capsys):
    """Control: missing before-image keeps BEFORE_IMAGE_UNAVAILABLE / exit 2."""

    env, receipt_path, original_sha, activated_sha = _applied_env(tmp_path, capsys)
    for image in (env.activation_root / "before-images").iterdir():
        image.unlink()
    code, out = env.rollback(capsys, receipt_path)
    assert code == 2, out
    assert "BEFORE_IMAGE_UNAVAILABLE" in out
    assert _sha(env.config_path) == activated_sha


def test_r5_control_before_image_hash_mismatch_refused(tmp_path, capsys):
    """Control: tampered before-image keeps BEFORE_IMAGE_HASH_MISMATCH."""

    env, receipt_path, original_sha, activated_sha = _applied_env(tmp_path, capsys)
    image = next((env.activation_root / "before-images").iterdir())
    image.write_bytes(image.read_bytes() + b"# tampered\n")
    code, out = env.rollback(capsys, receipt_path)
    assert code == 2, out
    assert "BEFORE_IMAGE_HASH_MISMATCH" in out
    assert _sha(env.config_path) == activated_sha


def test_r5_control_interrupted_restore_finalization_preserved(tmp_path, capsys):
    """Control: interrupted-restore retry still finalizes the outcome."""

    env, receipt_path, original_sha, activated_sha = _applied_env(tmp_path, capsys)

    def crash_after_restore(point: str) -> None:
        if point == "config_restored":
            raise _Crash()

    with pytest.raises(_Crash):
        rollback_profile_activation(
            receipt_path=receipt_path,
            activation_root=env.activation_root,
            fault_hook=crash_after_restore,
        )
    assert _sha(env.config_path) == original_sha

    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "FINALIZED_AFTER_INTERRUPTED_RESTORE", payload
    assert payload["outcome"] is not None
    assert _sha(env.config_path) == original_sha

    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    assert json.loads(out)["status"] == "ALREADY_RESTORED"
