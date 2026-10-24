"""Phase 7-C4-B-R1: activation-status truthfulness regressions (tests-first).

Every defect probe in this file was executed against the pristine reviewed
PR #28 baseline ``2e1a680be69cd5d2867b1e8a785fae12f8cc5b50`` BEFORE any
production change and failed exactly as recorded in
``docs/status/phase-7-c4-b-2026-10-24.md`` (R1 section); the same file
passes on the hardened tree.  The probes encode the three independently
reviewed defects:

* **F1** — the optional ``--receipt`` inspection ran *after* status
  classification and could append store-level problems (for example
  ``BEFORE_IMAGE_MISSING``) to an already-classified informational status,
  so ``NO_HISTORY``/exit 0 could coexist with nonempty ``problems``.
* **F2** — after a real apply and a real rollback, externally restoring the
  old *activated* bytes left the store reporting ``ACTIVATED_VERIFIED`` /
  exit 0 with only a ``STALE_ROLLBACK_OUTCOME_PRESENT`` observation: the
  valid rollback outcome proves the activation was rolled back, and no
  independently verifiable later activation exists, so a *current*
  activation is not provable from the bytes.
* **F3** — a syntactically valid private config whose ``profiles`` key is
  not a table (``profiles = "unexpected"``) crashed the read-only
  inspection with an uncaught ``AttributeError`` instead of a controlled,
  deterministic observation; the same shape inside a (forged, hash-bound)
  before-image crashed the store scan the same way.

Green controls in the same file pin the boundaries the review required to
stay unchanged: the genuine pending-restore interruption, the interrupted
rollback awaiting outcome finalization, and the legacy pre-R1 rollback
outcome without a recovery intent (still ``ROLLED_BACK_VERIFIED``).

No real owner key material, no network, no sleeps.  Published rules,
release manifest, default profile and the executor's own apply/rollback
behaviour stay byte-identical.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.test_activation_execution import (
    BASE_PROFILE_PATH,
    MANIFEST_PATH,
    PRIVATE_CONFIG_TEMPLATE,
    TARGET_PROFILE_PATH,
    _accept_payload,
    _cli,
    _Env,
    _sha,
    _signed_statement,
)
from tests.test_activation_status import (
    _applied,
    _assert_zero_writes,
    _env_status,
    _library_apply_inputs,
    _observed_paths,
    _status_cli,
    _tree_snapshot,
)
from turtle_value_engine.providers.models import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[1]

INFORMATIONAL_STATUSES = {
    "NO_HISTORY",
    "ACTIVATED_VERIFIED",
    "ROLLED_BACK_VERIFIED",
}


def _assert_informational_has_no_problems(payload: dict, context: str) -> None:
    if payload["status"] in INFORMATIONAL_STATUSES:
        assert payload["problems"] == [], (
            f"{context}: informational status {payload['status']} carries "
            f"store-level problems {payload['problems']}"
        )


# ---------------------------------------------------------------------------
# F1 — receipt diagnostics must never pollute an informational classification
# ---------------------------------------------------------------------------


def test_r1_f1_external_receipt_against_empty_store_never_adds_problems(
    tmp_path, capsys
):
    """A valid same-config receipt over an EMPTY store: NO_HISTORY stays clean.

    Baseline (red): classification ran first and returned NO_HISTORY, then
    the receipt inspection appended ``BEFORE_IMAGE_MISSING`` — exit 0 with a
    nonempty ``problems`` list.
    """

    env, receipt_path, *_rest = _applied(tmp_path, capsys)
    exported = env.tmp / "exported receipt.json"
    exported.write_bytes(receipt_path.read_bytes())

    empty_root = env.tmp / "empty activation root"
    empty_root.mkdir()
    observed = [empty_root, env.config_path.parent, env.config_path, exported]
    before = _tree_snapshot(*observed)

    code, out = _status_cli(capsys, empty_root, env.config_path, receipt=exported)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "NO_HISTORY"
    assert payload["relevant_histories"] == 0
    _assert_informational_has_no_problems(payload, "external receipt, empty store")
    inspection = payload["receipt_inspection"]
    # The additive receipt facts carry the diagnostics unambiguously.
    assert inspection["relevant_to_config"] is True
    assert inspection["current_config_matches_activated"] is True
    assert inspection["store_copy_present"] is False
    assert inspection["store_copy_matches"] is False
    assert inspection["journal_present"] is False
    assert inspection["before_image_verified"] is False

    code2, out2 = _status_cli(capsys, empty_root, env.config_path, receipt=exported)
    assert code2 == 0, out2
    assert out2 == out, "repeated inspection must be byte-identical"
    _assert_zero_writes(before, _tree_snapshot(*observed))


def test_r1_f1_external_receipt_against_missing_root_never_adds_problems(
    tmp_path, capsys
):
    """Same probe with a store root that does not exist at all."""

    env, receipt_path, *_rest = _applied(tmp_path, capsys)
    exported = env.tmp / "exported receipt.json"
    exported.write_bytes(receipt_path.read_bytes())
    missing_root = env.tmp / "missing activation root"
    observed = [missing_root, env.config_path.parent, env.config_path]
    before = _tree_snapshot(*observed)

    code, out = _status_cli(capsys, missing_root, env.config_path, receipt=exported)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "NO_HISTORY"
    assert payload["activation_root_present"] is False
    _assert_informational_has_no_problems(payload, "external receipt, missing root")
    assert not missing_root.exists(), "the missing store must stay missing"
    _assert_zero_writes(before, _tree_snapshot(*observed))


def test_r1_f1_informational_statuses_never_carry_problems_all_variants(
    tmp_path, capsys
):
    """Pin ``status informational => problems == []`` for every receipt variant.

    Baseline (red): the external-against-empty-store variant below reported
    NO_HISTORY/exit 0 together with ``BEFORE_IMAGE_MISSING``.
    """

    env, receipt_path, *_rest = _applied(tmp_path, capsys)

    # Variant 1: no receipt, activated.
    code, out = _env_status(capsys, env)
    assert code == 0, out
    _assert_informational_has_no_problems(json.loads(out), "no receipt")

    # Variant 2: the store's own current receipt.
    code, out = _env_status(capsys, env, receipt=receipt_path)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATED_VERIFIED"
    _assert_informational_has_no_problems(payload, "current receipt")

    # Variant 3: outside copy of the current receipt.
    exported = env.tmp / "exported receipt.json"
    exported.write_bytes(receipt_path.read_bytes())
    code, out = _env_status(capsys, env, receipt=exported)
    assert code == 0, out
    _assert_informational_has_no_problems(json.loads(out), "outside copy")

    # Variant 4: rolled-back receipt over the rolled-back store.
    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    code, out = _env_status(capsys, env, receipt=receipt_path)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "ROLLED_BACK_VERIFIED"
    _assert_informational_has_no_problems(payload, "rolled-back receipt")

    # Variant 5: unrelated receipt (another config's history in this store).
    other_config = env.tmp / "other private" / "project.toml"
    other_config.parent.mkdir(parents=True, exist_ok=True)
    other_config.write_text(PRIVATE_CONFIG_TEMPLATE, "utf-8")
    from tests.test_activation_status import _apply_over_config

    result = _apply_over_config(env, capsys, other_config)
    other_receipt = (
        env.activation_root / "receipts" / f"{result.receipt.activation_id}.json"
    )
    code, out = _env_status(capsys, env, receipt=other_receipt)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "ROLLED_BACK_VERIFIED"
    _assert_informational_has_no_problems(payload, "unrelated receipt")

    # Variant 6 (the F1 defect): external same-config receipt, empty store.
    fresh = env.tmp / "fresh activation root"
    fresh.mkdir()
    code, out = _status_cli(capsys, fresh, env.config_path, receipt=receipt_path)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "NO_HISTORY"
    _assert_informational_has_no_problems(payload, "external vs empty store")


def test_r1_f1_projection_model_rejects_informational_status_with_problems(
    tmp_path, capsys
):
    """The versioned projection contract itself pins the invariant.

    Baseline (red): a hand-assembled NO_HISTORY projection with one problem
    and a correctly recomputed ``content_sha256`` validated fine.
    """

    from turtle_value_engine.evolution.activation_execution import _sha256_hex
    from turtle_value_engine.evolution.activation_status import (
        ProfileActivationStatusV1,
        inspect_activation_status,
    )

    env = _Env(tmp_path).setup(capsys)
    status = inspect_activation_status(
        activation_root=env.activation_root,
        project_config_path=env.config_path,
    )
    assert status.status == "NO_HISTORY"

    payload = status.model_dump(mode="json", exclude={"content_sha256"})
    payload["problems"] = ["BEFORE_IMAGE_MISSING:before-images/deadbeef.toml"]
    payload["content_sha256"] = _sha256_hex(canonical_json_bytes(payload))
    with pytest.raises(ValidationError, match="informational"):
        ProfileActivationStatusV1.model_validate(payload)


# ---------------------------------------------------------------------------
# F2 — stale rollback evidence must not certify a *current* activation
# ---------------------------------------------------------------------------


def test_r1_f2_rolled_back_then_externally_restored_activated_bytes_is_diverged(
    tmp_path, capsys
):
    """Real apply → real rollback → externally restore activated bytes.

    Baseline (red): ``ACTIVATED_VERIFIED`` / exit 0 with only
    ``STALE_ROLLBACK_OUTCOME_PRESENT`` — historical evidence certifying a
    "new" activation the store cannot prove.
    """

    env, receipt_path, original_sha, activated_sha, _preview = _applied(
        tmp_path, capsys
    )
    activated_bytes = env.config_path.read_bytes()

    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    assert _sha(env.config_path) == original_sha, "the rollback really happened"

    # Independently restore the old ACTIVATED bytes without a new apply.
    env.config_path.write_bytes(activated_bytes)
    assert _sha(env.config_path) == activated_sha

    before = _tree_snapshot(*_observed_paths(env))
    code, out = _env_status(capsys, env)
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "CONFIG_DIVERGED"
    assert "ROLLED_BACK_ACTIVATION_BYTES_PRESENT" in payload["observations"]
    assert payload["problems"] == []
    focal = payload["focal"]
    assert focal["activated_config_sha256"] == activated_sha
    assert focal["rollback_outcome_present"] is True
    assert focal["rollback_intent_present"] is True

    code2, out2 = _env_status(capsys, env)
    assert code2 == 1
    assert out2 == out, "repeated inspection must be byte-identical"
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


def test_r1_f2_genuine_reapply_after_rollback_is_equally_unprovable(
    tmp_path, capsys
):
    """A REAL executor re-apply leaves a byte-identical store — same truth.

    The executor deterministically reuses the same activation identities on
    re-apply after rollback (proven by the C4-A suite), so the store cannot
    distinguish a genuine re-apply from an external byte restoration: no
    *independently verifiable later activation history* exists either way.
    Status must therefore report the same named divergence, not a verified
    activation.  Baseline (red): ``ACTIVATED_VERIFIED`` / exit 0.
    """

    env, receipt_path, original_sha, _activated_sha, preview = _applied(
        tmp_path, capsys
    )
    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out

    code, out = env.apply(capsys, preview["plan_id"], original_sha)
    assert code == 0, out
    assert json.loads(out)["status"] == "ACTIVATED"
    assert _sha(env.config_path) != original_sha, "config holds activated bytes"

    code, out = _env_status(capsys, env)
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "CONFIG_DIVERGED"
    assert "ROLLED_BACK_ACTIVATION_BYTES_PRESENT" in payload["observations"]
    assert "STALE_ROLLBACK_OUTCOME_PRESENT" not in payload["observations"]


def test_r1_f2_later_distinct_activation_overcomes_the_stale_outcome(
    tmp_path, capsys
):
    """A genuinely later, distinct, unrolled-back activation IS current.

    apply A → rollback A → a real second apply from a different signed
    decision (distinct plan/activation id, no rollback outcome): the second
    receipt is the independently verifiable later activation history, so the
    status is ``ACTIVATED_VERIFIED`` with the first activation's outcome
    honestly observed as stale.  Baseline (red): the two matching finished
    activations collapsed into ``AMBIGUOUS_HISTORY`` / exit 1.
    """

    from turtle_value_engine.evolution.activation_execution import (
        apply_profile_activation,
        preview_profile_activation,
    )

    env, receipt_path, original_sha, _activated_sha, _preview = _applied(
        tmp_path, capsys
    )
    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out

    second_payload = _accept_payload(
        rationale="A later, distinct rationale re-activating the profile.",
        decided_at="2026-10-23",
    )
    second_decision = env.submission / "decision-input-later.json"
    second_decision.write_bytes(canonical_json_bytes(second_payload))
    second_statement = _signed_statement(env.key, second_decision.read_bytes())
    second_statement_path = env.submission / "statement-later.json"
    second_statement_path.write_text(
        json.dumps(
            json.loads(second_statement.model_dump_json()),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        "utf-8",
    )
    second_record = env.decisions / "record-later.json"
    code, out = _cli(
        capsys,
        "evolution",
        "record-decision",
        "--decision-input",
        second_decision,
        "--base-profile",
        BASE_PROFILE_PATH,
        "--target-profile",
        TARGET_PROFILE_PATH,
        "--release-manifest",
        MANIFEST_PATH,
        "--policy-exception",
        env.exception_path,
        "--signed-statement",
        second_statement_path,
        "--trust-root",
        env.trust_root,
        "--evidence-root",
        env.tmp / "evidence-later",
        "--record-output",
        second_record,
    )
    assert code == 0, out
    bundle_path = Path(json.loads(out)["evidence_bundle"]["path"])

    common = _library_apply_inputs(
        env, record_path=second_record, bundle_path=bundle_path
    )
    preview = preview_profile_activation(**common)
    assert preview.plan_id != _preview["plan_id"]
    result = apply_profile_activation(
        expected_plan_id=preview.plan_id,
        expected_config_sha256=preview.original_config_sha256,
        **common,
    )
    assert result.status == "ACTIVATED"
    assert result.receipt.activation_id != json.loads(
        receipt_path.read_text("utf-8")
    )["activation_id"]

    code, out = _env_status(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATED_VERIFIED"
    assert payload["problems"] == []
    assert "STALE_ROLLBACK_OUTCOME_PRESENT" in payload["observations"]
    focal = payload["focal"]
    assert focal["activation_id"] == result.receipt.activation_id
    assert focal["rollback_outcome_present"] is False


def test_r1_f2_controls_unchanged_around_the_new_classification(tmp_path, capsys):
    """Green controls: pending-restore and interrupted rollback keep their
    own classes; a plain activated store stays verified."""

    from tests.test_activation_status import (
        _rollback_with_fault,
    )

    # Control 1: normal activated state stays ACTIVATED_VERIFIED.
    env_a, _receipt_a, *_rest = _applied(tmp_path / "a", capsys)
    code, out = _env_status(capsys, env_a)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATED_VERIFIED"
    assert payload["problems"] == []

    # Control 2: rollback intent persisted, restoration still pending (crash
    # between rollback intent persistence and the restore) keeps
    # ACTIVATED_VERIFIED + ROLLBACK_INTENT_PENDING_RESTORE — the activation
    # itself is fully proven; only the rollback is unfinished.
    env_b, receipt_b, _original_b, _activated_b, _preview_b = _applied(
        tmp_path / "b", capsys
    )
    _rollback_with_fault(receipt_b, env_b, "rollback_intent_persisted")
    code, out = _env_status(capsys, env_b)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "ACTIVATED_VERIFIED"
    assert "ROLLBACK_INTENT_PENDING_RESTORE" in payload["observations"]

    # Control 3: interrupted rollback awaiting outcome finalization keeps its
    # own pending class (crash after the restore, before the outcome).
    env_c, receipt_c, original_c, _activated_c, _preview_c = _applied(
        tmp_path / "c", capsys
    )
    _rollback_with_fault(receipt_c, env_c, "config_restored")
    assert _sha(env_c.config_path) == original_c
    code, out = _env_status(capsys, env_c)
    assert code == 1, out
    assert json.loads(out)["status"] == "ROLLBACK_FINALIZATION_PENDING"


def test_r1_f2_legacy_outcome_without_intent_still_rolled_back_verified(
    tmp_path, capsys
):
    """Compatibility pin: a valid rollback outcome ALONE still qualifies.

    Early C4-A rollback outcomes predate the R1 recovery-intent format.  The
    outcome is deterministically recomputed from and bound to the receipt
    content hash (any tampering is ``ROLLBACK_CONTENT_MISMATCH``), so an
    outcome without an intent is terminal evidence of a *completed* restore,
    never corruption.  Green on the baseline and after the R1 fix.
    """

    env, receipt_path, original_sha, *_rest = _applied(tmp_path, capsys)
    code, out = env.rollback(capsys, receipt_path)
    assert code == 0, out
    intent_files = sorted(
        (env.activation_root / "rollbacks").glob("*.intent.json")
    )
    assert len(intent_files) == 1
    intent_files[0].unlink()  # simulate the pre-R1 outcome-only store

    before = _tree_snapshot(*_observed_paths(env))
    code, out = _env_status(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "ROLLED_BACK_VERIFIED"
    assert payload["problems"] == []
    assert payload["current_config_sha256"] == original_sha
    focal = payload["focal"]
    assert focal["rollback_outcome_present"] is True
    assert focal["rollback_intent_present"] is False
    code2, out2 = _env_status(capsys, env)
    assert out2 == out
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


# ---------------------------------------------------------------------------
# F3 — malformed (but parseable) configuration shape must stay controlled
# ---------------------------------------------------------------------------


def test_r1_f3_config_profiles_scalar_shape_is_a_controlled_observation(
    tmp_path, capsys
):
    """``profiles = "unexpected"`` is valid TOML with a non-table profiles
    key.  Baseline (red): ``AttributeError: 'str' object has no attribute
    'get'`` from the status inspection, uncaught by the CLI.
    """

    env = _Env(tmp_path).setup(capsys)
    env.config_path.write_text('profiles = "unexpected"\n', "utf-8")
    before = _tree_snapshot(*_observed_paths(env))

    code, out = _env_status(capsys, env)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "NO_HISTORY"
    assert payload["problems"] == []
    assert payload["current_default_profile"] is None
    assert "CURRENT_CONFIG_PROFILES_NOT_TABLE" in payload["observations"]
    code2, out2 = _env_status(capsys, env)
    assert out2 == out
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


def test_r1_f3_config_profiles_scalar_shape_no_traceback_subprocess(tmp_path):
    """The literal CLI boundary returns controlled JSON, never a traceback."""

    env_dir = tmp_path / "private tree"
    env_dir.mkdir()
    config = env_dir / "project.toml"
    config.write_text('profiles = "unexpected"\n', "utf-8")
    root = tmp_path / "activation"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "turtle_value_engine",
            "evolution",
            "activation-status",
            "--activation-root",
            str(root),
            "--project-config",
            str(config),
        ],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(ROOT),
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert "Traceback" not in completed.stderr
    assert "AttributeError" not in completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "NO_HISTORY"
    assert "CURRENT_CONFIG_PROFILES_NOT_TABLE" in payload["observations"]


def test_r1_f3_before_image_non_table_profiles_is_a_named_problem(
    tmp_path, capsys
):
    """Same defect class inside the store scan: a hash-consistent forged
    before-image whose ``profiles`` key is not a table.

    Baseline (red): the scan crashed with ``AttributeError`` before any
    classification; fixed: a named ``BEFORE_IMAGE_CONTENT_MISMATCH`` problem
    forces ``CORRUPT_OR_UNVERIFIABLE`` — corruption is reported, never
    raised away.
    """

    from turtle_value_engine.evolution.activation_execution import (
        ROLLBACK_EXCLUSIONS,
        ProfileActivationReceiptV1,
        _build_intent,
        _sha256_hex,
    )
    from turtle_value_engine.providers.normalization import deterministic_id

    env = _Env(tmp_path).setup(capsys)
    bad_image = b'profiles = "unexpected"\n'
    bad_sha = hashlib.sha256(bad_image).hexdigest()
    activated_bytes = b'[profiles]\ndefault = "strict-v2"\n'
    activated_sha = hashlib.sha256(activated_bytes).hexdigest()
    hex64 = "11" * 32

    fields = {
        "plan_id": "forged-plan",
        "plan_content_sha256": hex64,
        "current_profile_id": "strict-v1",
        "current_profile_sha256": hex64,
        "activated_profile_id": "strict-v2",
        "activated_profile_sha256": hex64,
        "release_manifest_id": "forged-manifest",
        "release_manifest_content_sha256": hex64,
        "audit_id": "forged-audit",
        "audit_content_sha256": hex64,
        "decision_record_id": "forged-decision",
        "decision_record_content_sha256": hex64,
        "evidence_bundle_id": "forged-evidence",
        "evidence_bundle_content_sha256": hex64,
        "authority_registry_id": "forged-registry",
        "authority_registry_content_sha256": hex64,
        "project_config_path": str(env.config_path),
        "prior_config_sha256": bad_sha,
        "activated_config_sha256": activated_sha,
        "prior_default_profile": "unexpected",
        "activated_default_profile": "strict-v2",
        "before_image_name": f"{bad_sha}.toml",
        "before_image_sha256": bad_sha,
        "rollback_reference": "forged-reference",
        "rollback_exclusions": list(ROLLBACK_EXCLUSIONS),
    }
    receipt_payload = {
        "contract": "profile_activation_receipt_v1",
        "schema_version": "1.0.0",
        "activation_id": deterministic_id(
            "profile-activation-execution",
            fields["plan_id"],
            fields["project_config_path"],
            fields["prior_config_sha256"],
            fields["activated_config_sha256"],
            fields["decision_record_id"],
            fields["decision_record_content_sha256"],
            fields["evidence_bundle_id"],
            fields["evidence_bundle_content_sha256"],
            fields["authority_registry_id"],
            fields["authority_registry_content_sha256"],
        ),
        **fields,
        "outcome": "ACTIVATED",
        "apply_was_explicit_opt_in": True,
        "automatic_rollback_allowed": False,
    }
    receipt_payload["content_sha256"] = _sha256_hex(
        canonical_json_bytes(
            {
                key: value
                for key, value in receipt_payload.items()
                if key != "content_sha256"
            }
        )
    )
    receipt = ProfileActivationReceiptV1.model_validate(receipt_payload)

    journal = env.activation_root / "journal"
    receipts = env.activation_root / "receipts"
    images = env.activation_root / "before-images"
    for directory in (journal, receipts, images):
        directory.mkdir(parents=True)
    (journal / f"{receipt.activation_id}.json").write_bytes(
        _build_intent(receipt).serialized_bytes()
    )
    (receipts / f"{receipt.activation_id}.json").write_bytes(
        receipt.serialized_bytes()
    )
    (images / receipt.before_image_name).write_bytes(bad_image)
    env.config_path.write_bytes(activated_bytes)

    before = _tree_snapshot(*_observed_paths(env))
    code, out = _env_status(capsys, env)
    assert code == 1, out
    payload = json.loads(out)
    assert payload["status"] == "CORRUPT_OR_UNVERIFIABLE"
    assert any(
        problem.startswith("BEFORE_IMAGE_CONTENT_MISMATCH:")
        for problem in payload["problems"]
    )
    code2, out2 = _env_status(capsys, env)
    assert out2 == out
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))
