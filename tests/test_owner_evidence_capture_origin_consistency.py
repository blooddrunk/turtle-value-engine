"""Phase 7-C3-B-R3 regressions: capture-origin and authority-annotation
consistency.

Every test here drives the *real* capture / persistence / offline-replay,
strict-loader, plan and CLI paths with throwaway runtime-generated Ed25519
keys.  The red cases reproduce the R2 post-closure review candidates against
pristine main ``eb8245b``:

* F1 — a fully self-consistent forged bundle whose record provenance
  ``source_content_sha256`` no longer binds the actual decision-input bytes
  replayed with the named ``RECORD_PROVENANCE_NOT_BOUND_TO_INPUT_BYTES``
  mismatch, but the **strict loader silently accepted it** (replay/loader
  asymmetry);
* F2 — separately forged ``authority.verifier_kind``,
  ``authority.allowlist_matched`` (false/null) and ``authority.reason_code``
  (fields outside both the owner signature and the deterministic record id)
  replayed ``REPLAYS_BYTE_IDENTICAL``, loaded strictly and CLI exit 0, so
  forged capture annotations were treated as genuine capture metadata;
* F3 — a captured record carrying an unsigned
  ``supersedes_decision_record_id`` (never produced by the capture boundary;
  supersession lives in the separately signed lifecycle protocol) replayed
  clean, loaded strictly and CLI exit 0.

The green cases pin the preserved invariants: the genuine VERIFIED capture,
the honest REJECTED/INVALID capture and the honest INVALID-with-VERIFIED-
crypto capture still replay byte-identically; replay stays socket-free; the
activation plan keeps re-attesting against the operator's *current* trust
root (revocation flips READY to BLOCKED; a tampered provenance hash or an
unsigned supersession is rejected at plan time even where historical replay
once overstated integrity, while a genuine signature with forged cosmetic
annotation text still verifies freshly because plan authority never consults
persisted annotations); foreign bundle content fails closed.

All Ed25519 keys and passphrases here are throwaway runtime fixtures; no
real owner key material exists in this repository and no real owner
acceptance of strict-v2 is claimed or synthesized.
"""

import base64
import hashlib
import json
import socket
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from turtle_value_engine import cli as cli_module
from turtle_value_engine import load_normalized_input
from turtle_value_engine.evolution.activation_plan import plan_profile_activation
from turtle_value_engine.evolution.owner_decision import (
    DecisionProvenanceV1,
    OwnerAuthorityAssessmentV1,
    OwnerPolicyDecisionInputV1,
    OwnerPolicyDecisionRecordV1,
)
from turtle_value_engine.evolution.owner_provenance import (
    PROVENANCE_ALGORITHM,
    SignedOwnerProvenanceVerifier,
    build_owner_provenance_key_registry,
    build_owner_signed_decision_statement,
    owner_decision_input_signature_message,
    owner_provenance_key_id,
)
from turtle_value_engine.evolution.owner_provenance import (
    OwnerProvenanceKeyRecordV1 as LifecycleKeyRecord,
)
from turtle_value_engine.evolution.owner_trust_store import (
    OwnerTrustStoreError,
    build_initial_registry_snapshot,
    capture_owner_decision_evidence,
    load_owner_decision_evidence,
    persist_owner_decision_evidence,
    reverify_owner_decision_evidence,
)
from turtle_value_engine.evolution.profile_semantic_audit import (
    VersionedPolicyExceptionV1,
    audit_profile_semantics,
)
from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.providers.normalization import deterministic_id

ROOT = Path(__file__).resolve().parents[1]
BASE_PROFILE_PATH = ROOT / "rules" / "strict-v1.yaml"
TARGET_PROFILE_PATH = ROOT / "rules" / "strict-v2.yaml"
MANIFEST_PATH = ROOT / "docs" / "releases" / "strict-v2" / "release-candidate.json"
BOUNDARY_PATH = ROOT / "fixtures" / "healthy_cash_cow.json"

STRICT_V2_SHA256 = "adba44b799fdb42a6e443d55891dd3262842aee1dbc441e823b2a3155396dd7d"
OWNER_IDENTITY = "Ryder Xie"

_boundary_input = None
_audit_result = None


def _boundary():
    global _boundary_input
    if _boundary_input is None:
        _boundary_input = load_normalized_input(BOUNDARY_PATH)
    return _boundary_input


def _audit():
    global _audit_result
    if _audit_result is None:
        _audit_result = audit_profile_semantics(
            base_profile_path=BASE_PROFILE_PATH,
            target_profile_path=TARGET_PROFILE_PATH,
            release_manifest_path=MANIFEST_PATH,
            boundary_input=_boundary(),
            policy_exceptions=[_policy_exception()],
        )
    return _audit_result


def _policy_exception(rationale: str | None = None) -> VersionedPolicyExceptionV1:
    return VersionedPolicyExceptionV1.build(
        profile_id="strict-v2",
        profile_sha256=STRICT_V2_SHA256,
        rule_path="cdc.yield_bands.pass",
        exception_code="CDC_GATE_ABOVE_S_BAND_PERMITTED",
        rationale=rationale
        or "Owner accepts the 14% CDC gate sitting above the retained 12% S band.",
        declared_by=OWNER_IDENTITY,
    )


def _accept_payload(**overrides) -> dict:
    audit = _audit()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    payload = {
        "contract": "owner_policy_decision_input_v1",
        "decision": "ACCEPT_WITH_EXCEPTION",
        "base_profile_id": "strict-v1",
        "base_profile_sha256": "e3618f78b2f8e4d1e8e81ce3065da977685ad5256bd0ab3332b3a8054e0b6333",
        "target_profile_id": "strict-v2",
        "target_profile_sha256": STRICT_V2_SHA256,
        "release_manifest_id": manifest["release_candidate_id"],
        "release_manifest_content_sha256": (
            "c0d6cb5b60595c8eb67d45735fc8ef05a9a13b6db0f90bf3468f635ec99c61e8"
        ),
        "audit_id": audit.audit_id,
        "audit_content_sha256": audit.content_sha256,
        "exception_id": _policy_exception().exception_id,
        "exception_content_sha256": _policy_exception().content_sha256,
        "rationale": "Accept the stricter 14% CDC gate as intended owner policy.",
        "declared_owner_identity": OWNER_IDENTITY,
        "decided_at": "2026-10-15",
        "source_revision": "c3b-r3-test",
    }
    payload.update(overrides)
    return payload


def _accept_bytes(**overrides) -> bytes:
    return canonical_json_bytes(_accept_payload(**overrides))


class _FixtureKey:
    """A throwaway Ed25519 keypair with its registry record."""

    def __init__(self) -> None:
        self.private = Ed25519PrivateKey.generate()
        self.public_base64 = base64.b64encode(
            self.private.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
        ).decode("ascii")
        self.key_id = owner_provenance_key_id(
            algorithm=PROVENANCE_ALGORITHM, public_key_base64=self.public_base64
        )
        self.record = LifecycleKeyRecord(
            key_id=self.key_id,
            algorithm=PROVENANCE_ALGORITHM,
            public_key_base64=self.public_base64,
            owner_identity=OWNER_IDENTITY,
            authorized_decisions=["ACCEPT_WITH_EXCEPTION", "REJECT"],
            valid_from="2026-01-01",
            valid_until="2026-12-31",
        )


def _signed_statement(key: _FixtureKey, decision_bytes: bytes):
    decision_input = OwnerPolicyDecisionInputV1.model_validate(
        json.loads(decision_bytes)
    )
    return build_owner_signed_decision_statement(
        signature=key.private.sign(owner_decision_input_signature_message(decision_input)),
        key_id=key.key_id,
        decision_input=decision_input,
    )


def _capture(key: _FixtureKey, *, decision_bytes: bytes | None = None, statement=None):
    """A genuine capture through the real record-time boundary."""

    decision_bytes = decision_bytes or _accept_bytes()
    statement = statement or _signed_statement(key, decision_bytes)
    snapshot = build_initial_registry_snapshot(
        build_owner_provenance_key_registry([key.record])
    )
    validation, bundle = capture_owner_decision_evidence(
        decision_input_bytes=decision_bytes,
        statement=statement,
        registry_snapshot=snapshot,
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=_boundary(),
        policy_exceptions=[_policy_exception()],
    )
    assert validation.state == "VALID"
    return decision_bytes, statement, snapshot, validation, bundle


def _persisted(tmp_path: Path, key: _FixtureKey):
    decision_bytes, statement, snapshot, validation, bundle = _capture(key)
    evidence_root = tmp_path / "evidence"
    persist_owner_decision_evidence(
        evidence_root,
        bundle,
        decision_input_bytes=decision_bytes,
        statement=statement,
        registry_snapshot=snapshot,
    )
    return evidence_root / bundle.bundle_id, (
        decision_bytes,
        statement,
        snapshot,
        validation,
        bundle,
    )


def _persisted_rejected(tmp_path: Path):
    """An honestly rejected capture: the statement names the trusted key id
    but carries an attacker signature (INVALID bundle, no record)."""

    trusted, attacker = _FixtureKey(), _FixtureKey()
    decision_bytes = _accept_bytes()
    decision_input = OwnerPolicyDecisionInputV1.model_validate(
        json.loads(decision_bytes)
    )
    statement = build_owner_signed_decision_statement(
        signature=attacker.private.sign(
            owner_decision_input_signature_message(decision_input)
        ),
        key_id=trusted.key_id,
        decision_input=decision_input,
    )
    snapshot = build_initial_registry_snapshot(
        build_owner_provenance_key_registry([trusted.record])
    )
    validation, bundle = capture_owner_decision_evidence(
        decision_input_bytes=decision_bytes,
        statement=statement,
        registry_snapshot=snapshot,
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=_boundary(),
        policy_exceptions=[_policy_exception()],
    )
    assert validation.state == "INVALID"
    assert bundle.verification.verification_status == "REJECTED"
    assert bundle.record is None
    evidence_root = tmp_path / "evidence-rejected"
    persist_owner_decision_evidence(
        evidence_root,
        bundle,
        decision_input_bytes=decision_bytes,
        statement=statement,
        registry_snapshot=snapshot,
    )
    return evidence_root / bundle.bundle_id


def _dump_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "utf-8",
    )


def _bundle_content_sha256(payload: dict) -> str:
    body = {key: value for key, value in payload.items() if key != "content_sha256"}
    return hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def _bundle_id_for(payload: dict) -> str:
    record = payload.get("record")
    return deterministic_id(
        "owner-provenance-evidence-bundle",
        payload["decision_input_content_sha256"],
        payload["statement_content_sha256"],
        payload["registry_snapshot_id"],
        payload["registry_snapshot_content_sha256"],
        payload["verification"]["verification_id"],
        record["decision_record_id"] if record is not None else "",
        payload.get("record_content_sha256") or "",
        payload["validation_state"],
    )


def _forged_bundle_from_record(
    evidence_root: Path, original_dir: Path, forged_record: OwnerPolicyDecisionRecordV1
) -> Path:
    """A fully self-consistent forged bundle: recomputed record id/content
    hash, bundle id and bundle content hash, matching directory name, all six
    physical components, original signed bytes and dossier preserved."""

    payload = json.loads((original_dir / "bundle.json").read_text("utf-8"))
    payload["record"] = forged_record.model_dump(mode="json")
    payload["record_content_sha256"] = forged_record.content_sha256
    payload["bundle_id"] = _bundle_id_for(payload)
    payload["content_sha256"] = _bundle_content_sha256(payload)
    forged_dir = evidence_root / payload["bundle_id"]
    forged_dir.mkdir(parents=True)
    for name in (
        "decision-input.json",
        "statement.json",
        "registry-snapshot.json",
        "verification.json",
    ):
        (forged_dir / name).write_bytes((original_dir / name).read_bytes())
    _dump_json(forged_dir / "record.json", forged_record.model_dump(mode="json"))
    _dump_json(forged_dir / "bundle.json", payload)
    return forged_dir


def _record_with_forged_provenance(
    decision_bytes: bytes,
    original_record: OwnerPolicyDecisionRecordV1,
    source_content_sha256: str,
) -> OwnerPolicyDecisionRecordV1:
    """Rebuild the record with a forged provenance content hash; every signed
    decision field, the source revision and the authority stay verbatim."""

    forged_input = OwnerPolicyDecisionInputV1.model_validate(
        json.loads(decision_bytes)
    )
    return OwnerPolicyDecisionRecordV1.build(
        decision_input=forged_input,
        provenance=DecisionProvenanceV1(
            source_kind=original_record.provenance.source_kind,
            source_revision=original_record.provenance.source_revision,
            source_content_sha256=source_content_sha256,
        ),
        authority=original_record.authority,
    )


def _record_with_forged_authority(
    decision_bytes: bytes,
    original_record: OwnerPolicyDecisionRecordV1,
    **authority_updates,
) -> OwnerPolicyDecisionRecordV1:
    """Rebuild the record byte-consistently with one forged authority field.

    Every owner-signed decision field and the source revision stay verbatim
    (they come from the genuine signed bytes); only the unsigned authority
    annotation changes, and the record id / content hash are recomputed."""

    forged_input = OwnerPolicyDecisionInputV1.model_validate(
        json.loads(decision_bytes)
    )
    return OwnerPolicyDecisionRecordV1.build(
        decision_input=forged_input,
        provenance=original_record.provenance,
        authority=original_record.authority.model_copy(update=authority_updates),
    )


def _record_with_unsigned_supersession(
    decision_bytes: bytes,
    original_record: OwnerPolicyDecisionRecordV1,
    superseded_id: str,
) -> OwnerPolicyDecisionRecordV1:
    forged_input = OwnerPolicyDecisionInputV1.model_validate(
        json.loads(decision_bytes)
    )
    return OwnerPolicyDecisionRecordV1.build(
        decision_input=forged_input,
        provenance=original_record.provenance,
        authority=original_record.authority,
        supersedes_decision_record_id=superseded_id,
    )


def _cli(capsys, *argv):
    code = cli_module.main([str(item) for item in argv])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def _plan_verifier(decision_bytes, statement, snapshot) -> SignedOwnerProvenanceVerifier:
    return SignedOwnerProvenanceVerifier(
        registry=snapshot.registry,
        statement=statement,
        decision_input_bytes=decision_bytes,
    )


def _write_project_config(tmp_path: Path) -> Path:
    path = tmp_path / "project.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                "",
                "[project]",
                'id = "turtle-value-engine"',
                'environment = "private"',
                'timezone = "Asia/Taipei"',
                "",
                "[profiles]",
                'default = "strict-v1"',
                "",
            ]
        ),
        "utf-8",
    )
    return path


def _plan_over_record(
    tmp_path: Path,
    decision_bytes: bytes,
    statement,
    snapshot,
    record: OwnerPolicyDecisionRecordV1,
):
    """Derive the read-only activation plan over one record with the real
    plan-time verifier (fresh re-attestation against the capture registry)."""

    return plan_profile_activation(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=_boundary(),
        decision_records=[record],
        policy_exceptions=[_policy_exception()],
        authority_verifier=_plan_verifier(decision_bytes, statement, snapshot),
        project_config_path=_write_project_config(tmp_path),
    )


# ---------------------------------------------------------------------------
# F1 (red) — record provenance no longer bound to the input bytes
# ---------------------------------------------------------------------------


def test_f1_replay_already_names_the_provenance_binding_mismatch(tmp_path):
    key = _FixtureKey()
    bundle_dir, (decision_bytes, _, _, _, bundle) = _persisted(tmp_path, key)
    assert bundle.record is not None
    assert (
        bundle.record.provenance.source_content_sha256
        == hashlib.sha256(decision_bytes).hexdigest()
    )
    forged_record = _record_with_forged_provenance(
        decision_bytes, bundle.record, "ab" * 32
    )
    # The forgery is fully self-consistent: every id and hash recomputes, and
    # the deterministic record id changes (it binds the provenance hash).
    OwnerPolicyDecisionRecordV1.model_validate(
        json.loads(json.dumps(forged_record.model_dump(mode="json")))
    )
    assert forged_record.decision_record_id != bundle.record.decision_record_id

    forged_dir = _forged_bundle_from_record(
        tmp_path / "evidence", bundle_dir, forged_record
    )
    result = reverify_owner_decision_evidence(forged_dir / "bundle.json")
    assert result.replay_status == "MISMATCH", result.mismatches
    assert "RECORD_PROVENANCE_NOT_BOUND_TO_INPUT_BYTES" in result.mismatches


def test_f1_strict_loader_must_fail_closed_on_forged_provenance_hash(tmp_path):
    key = _FixtureKey()
    bundle_dir, (decision_bytes, _, _, _, bundle) = _persisted(tmp_path, key)
    forged_record = _record_with_forged_provenance(
        decision_bytes, bundle.record, "ab" * 32
    )
    forged_dir = _forged_bundle_from_record(
        tmp_path / "evidence", bundle_dir, forged_record
    )
    with pytest.raises(OwnerTrustStoreError) as excinfo:
        load_owner_decision_evidence(forged_dir / "bundle.json")
    assert "RECORD_PROVENANCE_NOT_BOUND_TO_INPUT_BYTES" in str(excinfo.value)


def test_f1_plan_time_reverification_still_blocks_the_forged_provenance(tmp_path):
    key = _FixtureKey()
    _, (decision_bytes, statement, snapshot, _, bundle) = _persisted(tmp_path, key)
    forged_record = _record_with_forged_provenance(
        decision_bytes, bundle.record, "ab" * 32
    )
    plan = _plan_over_record(
        tmp_path, decision_bytes, statement, snapshot, forged_record
    )
    assert plan.plan_state != "READY_FOR_EXPLICIT_OWNER_EXECUTION"
    assert plan.authority_reverification_status == "REVERIFICATION_FAILED"
    assert "OWNER_AUTHORITY_REVERIFICATION_REJECTED" in plan.blockers


# ---------------------------------------------------------------------------
# F2 (red) — forged capture annotations outside the signature and record id
# ---------------------------------------------------------------------------


def test_genuine_capture_authority_annotations_are_the_real_verifier_values(
    tmp_path,
):
    """The record-time truth the annotations must reconcile with."""

    key = _FixtureKey()
    _, (_, _, _, _, bundle) = _persisted(tmp_path, key)
    assert bundle.record is not None
    authority = bundle.record.authority
    assert authority.verifier_kind == SignedOwnerProvenanceVerifier.kind
    assert authority.allowlist_matched is True
    assert authority.reason_code == "ED25519_OWNER_PROVENANCE_VERIFIED"


_F2_CASES = [
    ("verifier_kind", "forged-not-the-real-verifier-kind", "AUTHORITY_VERIFIER_KIND_DIVERGED"),
    ("allowlist_matched", False, "AUTHORITY_ALLOWLIST_DIVERGED"),
    ("allowlist_matched", None, "AUTHORITY_ALLOWLIST_DIVERGED"),
    ("reason_code", "FORGED_REASON_CODE_NEVER_REAL", "AUTHORITY_REASON_CODE_DIVERGED"),
]


@pytest.mark.parametrize(
    "field,forged_value,expected_code",
    _F2_CASES,
    ids=[f"{f}={v!r}" for f, v, _ in _F2_CASES],
)
def test_f2_forged_authority_annotation_is_a_named_mismatch(
    tmp_path, capsys, field, forged_value, expected_code
):
    key = _FixtureKey()
    bundle_dir, (decision_bytes, _, _, _, bundle) = _persisted(tmp_path, key)
    forged_record = _record_with_forged_authority(
        decision_bytes, bundle.record, **{field: forged_value}
    )
    # Fully self-consistent forgery: the record id does not bind these
    # annotation fields, so only the content hash and bundle identity move.
    OwnerPolicyDecisionRecordV1.model_validate(
        json.loads(json.dumps(forged_record.model_dump(mode="json")))
    )
    assert forged_record.content_sha256 != bundle.record.content_sha256
    assert forged_record.decision_record_id == bundle.record.decision_record_id

    forged_dir = _forged_bundle_from_record(
        tmp_path / "evidence", bundle_dir, forged_record
    )
    forged_path = forged_dir / "bundle.json"

    result = reverify_owner_decision_evidence(forged_path)
    assert result.replay_status == "MISMATCH", (field, forged_value, result.mismatches)
    assert expected_code in result.mismatches

    code, out = _cli(capsys, "provenance", "verify-evidence", "--bundle", forged_path)
    assert code == 1, out

    with pytest.raises(OwnerTrustStoreError) as excinfo:
        load_owner_decision_evidence(forged_path)
    assert expected_code in str(excinfo.value)


def test_f2_plan_time_fresh_verification_stays_independent_of_annotations(tmp_path):
    """A genuine signature with forged cosmetic annotation text still verifies
    freshly at plan time: persisted annotations are never authority, and the
    plan consults only the fresh assessment (the forged record keeps every
    signed field genuine, so fresh re-attestation legitimately succeeds)."""

    key = _FixtureKey()
    _, (decision_bytes, statement, snapshot, _, bundle) = _persisted(tmp_path, key)
    forged_record = _record_with_forged_authority(
        decision_bytes, bundle.record, verifier_kind="forged-not-the-real-verifier"
    )
    plan = _plan_over_record(
        tmp_path, decision_bytes, statement, snapshot, forged_record
    )
    assert plan.authority_reverification_status == "REVERIFIED"
    assert plan.plan_state == "READY_FOR_EXPLICIT_OWNER_EXECUTION"
    assert plan.execution_performed is False


# ---------------------------------------------------------------------------
# F3 (red) — unsigned supersession carried by a forged capture record
# ---------------------------------------------------------------------------


_SUPERSEDED_ID = "owner-policy-decision-forged-target-000000000000000000"


def test_f3_unsigned_supersession_in_a_capture_is_a_named_mismatch(tmp_path, capsys):
    key = _FixtureKey()
    bundle_dir, (decision_bytes, _, _, _, bundle) = _persisted(tmp_path, key)
    assert bundle.record.supersedes_decision_record_id is None
    forged_record = _record_with_unsigned_supersession(
        decision_bytes, bundle.record, _SUPERSEDED_ID
    )
    OwnerPolicyDecisionRecordV1.model_validate(
        json.loads(json.dumps(forged_record.model_dump(mode="json")))
    )
    assert forged_record.supersedes_decision_record_id == _SUPERSEDED_ID

    forged_dir = _forged_bundle_from_record(
        tmp_path / "evidence", bundle_dir, forged_record
    )
    forged_path = forged_dir / "bundle.json"

    result = reverify_owner_decision_evidence(forged_path)
    assert result.replay_status == "MISMATCH", result.mismatches
    assert "RECORD_UNSIGNED_SUPERSESSION" in result.mismatches

    code, out = _cli(capsys, "provenance", "verify-evidence", "--bundle", forged_path)
    assert code == 1, out

    with pytest.raises(OwnerTrustStoreError) as excinfo:
        load_owner_decision_evidence(forged_path)
    assert "RECORD_UNSIGNED_SUPERSESSION" in str(excinfo.value)


def test_f3_plan_time_still_rejects_unsigned_supersession(tmp_path):
    """The resolver applies a record-carried supersession at face value (the
    superseding record becomes active), so plan-time authority is exactly the
    guard: fresh re-attestation over the superseding record rejects the
    unsigned supersession the signed decision-input contract never covers."""

    key = _FixtureKey()
    _, (decision_bytes, statement, snapshot, _, bundle) = _persisted(tmp_path, key)
    forged_record = _record_with_unsigned_supersession(
        decision_bytes, bundle.record, bundle.record.decision_record_id
    )
    plan = plan_profile_activation(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=_boundary(),
        decision_records=[bundle.record, forged_record],
        policy_exceptions=[_policy_exception()],
        authority_verifier=_plan_verifier(decision_bytes, statement, snapshot),
        project_config_path=_write_project_config(tmp_path / "supersession"),
    )
    assert plan.plan_state != "READY_FOR_EXPLICIT_OWNER_EXECUTION"
    assert "OWNER_AUTHORITY_REVERIFICATION_REJECTED" in plan.blockers


# ---------------------------------------------------------------------------
# Green preservation — honest evidence, offline replay, plan authority
# ---------------------------------------------------------------------------


def test_genuine_verified_capture_still_replays_clean_and_loads(tmp_path, capsys):
    key = _FixtureKey()
    bundle_dir, (_, _, _, _, bundle) = _persisted(tmp_path, key)
    result = reverify_owner_decision_evidence(bundle_dir / "bundle.json")
    assert result.replay_status == "REPLAYS_BYTE_IDENTICAL", result.mismatches
    loaded = load_owner_decision_evidence(bundle_dir / "bundle.json")
    assert loaded.bundle.bundle_id == bundle.bundle_id
    code, out = _cli(
        capsys, "provenance", "verify-evidence", "--bundle", bundle_dir / "bundle.json"
    )
    assert code == 0, out


def test_honest_rejected_capture_still_replays_byte_identically(tmp_path, capsys):
    bundle_dir = _persisted_rejected(tmp_path)
    result = reverify_owner_decision_evidence(bundle_dir / "bundle.json")
    assert result.replay_status == "REPLAYS_BYTE_IDENTICAL", result.mismatches
    loaded = load_owner_decision_evidence(bundle_dir / "bundle.json")
    assert loaded.bundle.validation_state == "INVALID"
    code, out = _cli(
        capsys, "provenance", "verify-evidence", "--bundle", bundle_dir / "bundle.json"
    )
    assert code == 0, out


def test_honest_invalid_capture_with_verified_crypto_still_replays(tmp_path):
    """A signature that verifies while a decision check fails is a legitimate
    INVALID capture (verified crypto, blockers, no record): the capture-origin
    contract must not overreach into re-deriving the economic audit."""

    key = _FixtureKey()
    decision_bytes = _accept_bytes(audit_content_sha256="00" * 32)
    statement = _signed_statement(key, decision_bytes)
    snapshot = build_initial_registry_snapshot(
        build_owner_provenance_key_registry([key.record])
    )
    validation, bundle = capture_owner_decision_evidence(
        decision_input_bytes=decision_bytes,
        statement=statement,
        registry_snapshot=snapshot,
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=_boundary(),
        policy_exceptions=[_policy_exception()],
    )
    assert validation.state == "INVALID"
    assert bundle.verification.verification_status == "VERIFIED"
    assert bundle.record is None
    evidence_root = tmp_path / "evidence-invalid-verified"
    persist_owner_decision_evidence(
        evidence_root,
        bundle,
        decision_input_bytes=decision_bytes,
        statement=statement,
        registry_snapshot=snapshot,
    )
    bundle_path = evidence_root / bundle.bundle_id / "bundle.json"
    result = reverify_owner_decision_evidence(bundle_path)
    assert result.replay_status == "REPLAYS_BYTE_IDENTICAL", result.mismatches
    loaded = load_owner_decision_evidence(bundle_path)
    assert loaded.bundle.validation_state == "INVALID"


def test_forged_bundle_replay_is_repeatable_and_socket_free(tmp_path, monkeypatch):
    def no_sockets(*args, **kwargs):
        raise AssertionError("evidence re-verification constructed a socket")

    monkeypatch.setattr(socket, "socket", no_sockets)
    monkeypatch.setattr(socket, "create_connection", no_sockets)
    key = _FixtureKey()
    bundle_dir, (decision_bytes, _, _, _, bundle) = _persisted(tmp_path, key)
    forged_record = _record_with_forged_provenance(
        decision_bytes, bundle.record, "ab" * 32
    )
    forged_dir = _forged_bundle_from_record(
        tmp_path / "evidence", bundle_dir, forged_record
    )
    first = reverify_owner_decision_evidence(forged_dir / "bundle.json")
    second = reverify_owner_decision_evidence(forged_dir / "bundle.json")
    assert first == second
    assert first.replay_status == "MISMATCH"


def test_duplicate_persistence_is_idempotent_and_foreign_content_fails(tmp_path):
    key = _FixtureKey()
    decision_bytes, statement, snapshot, _, bundle = _capture(key)
    evidence_root = tmp_path / "evidence"
    first = persist_owner_decision_evidence(
        evidence_root,
        bundle,
        decision_input_bytes=decision_bytes,
        statement=statement,
        registry_snapshot=snapshot,
    )
    second = persist_owner_decision_evidence(
        evidence_root,
        bundle,
        decision_input_bytes=decision_bytes,
        statement=statement,
        registry_snapshot=snapshot,
    )
    assert first == "CREATED"
    assert second == "IDEMPOTENT"
    # A foreign file inside the bundle directory fails closed on replay.
    (evidence_root / bundle.bundle_id / "foreign.json").write_text("{}", "utf-8")
    with pytest.raises(OwnerTrustStoreError):
        reverify_owner_decision_evidence(
            evidence_root / bundle.bundle_id / "bundle.json"
        )


def test_plan_authority_flips_blocked_when_the_current_key_is_revoked(tmp_path):
    """Historical capture integrity never transfers authority: revoking the
    signing key in the operator's CURRENT trust root flips the plan from
    READY back to BLOCKED even though the persisted bundle is genuine."""

    key = _FixtureKey()
    _, (decision_bytes, statement, snapshot, _, bundle) = _persisted(tmp_path, key)
    plan = _plan_over_record(tmp_path, decision_bytes, statement, snapshot, bundle.record)
    assert plan.plan_state == "READY_FOR_EXPLICIT_OWNER_EXECUTION"
    assert plan.authority_reverification_status == "REVERIFIED"
    assert plan.execution_performed is False

    revoked_key = key.record.model_copy(
        update={"revoked": True, "revocation_reference": "r3 control revocation"}
    )
    revoked_snapshot = build_initial_registry_snapshot(
        build_owner_provenance_key_registry([revoked_key])
    )
    revoked_plan = plan_profile_activation(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=_boundary(),
        decision_records=[bundle.record],
        policy_exceptions=[_policy_exception()],
        authority_verifier=SignedOwnerProvenanceVerifier(
            registry=revoked_snapshot.registry,
            statement=statement,
            decision_input_bytes=decision_bytes,
        ),
        project_config_path=_write_project_config(tmp_path / "revoked"),
    )
    assert revoked_plan.plan_state != "READY_FOR_EXPLICIT_OWNER_EXECUTION"
    assert revoked_plan.authority_reverification_status == "REVERIFICATION_FAILED"
    assert any(
        item.startswith("OWNER_AUTHORITY_REVERIFICATION")
        for item in revoked_plan.blockers
    )


def test_forged_authority_annotations_from_r2_fixture_class_still_mismatch(
    tmp_path,
):
    """The R2-era forged VERIFIED-over-REJECTED record (whose annotation text
    was already inauthentic) keeps every R2 divergence and additionally the
    R3 annotation codes — the shared contract only grew stricter."""

    bundle_dir = _persisted_rejected(tmp_path)
    decision_bytes = _accept_bytes()
    decision_input = OwnerPolicyDecisionInputV1.model_validate(
        json.loads(decision_bytes)
    )
    statement = json.loads(
        (bundle_dir / "statement.json").read_text("utf-8")
    )
    snapshot = json.loads(
        (bundle_dir / "registry-snapshot.json").read_text("utf-8")
    )
    forged_authority = OwnerAuthorityAssessmentV1(
        authority_status="OWNER_AUTHORITY_VERIFIED",
        verification_method="INJECTED_VERIFIER",
        verifier_kind="signed_owner_provenance",
        allowlist_matched=True,
        reason_code="ED25519_OWNER_PROVENANCE_VERIFIED",
        detail="Forged verified-authority claim over an honestly rejected signature.",
        evidence_content_sha256=hashlib.sha256(decision_bytes).hexdigest(),
        attested_key_id=statement["key_id"],
        attested_registry_id=snapshot["registry"]["registry_id"],
        attested_registry_content_sha256=snapshot["registry"]["content_sha256"],
    )
    provenance = DecisionProvenanceV1(
        source_kind="LOCAL_UNSIGNED_JSON",
        source_revision=decision_input.source_revision,
        source_content_sha256=hashlib.sha256(decision_bytes).hexdigest(),
    )
    forged_record = OwnerPolicyDecisionRecordV1.build(
        decision_input=decision_input,
        provenance=provenance,
        authority=forged_authority,
    )
    payload = json.loads((bundle_dir / "bundle.json").read_text("utf-8"))
    payload["validation_state"] = "VALID"
    payload["validation_blockers"] = []
    payload["record"] = forged_record.model_dump(mode="json")
    payload["record_content_sha256"] = forged_record.content_sha256
    payload["bundle_id"] = _bundle_id_for(payload)
    payload["content_sha256"] = _bundle_content_sha256(payload)
    forged_dir = tmp_path / "evidence-forged" / payload["bundle_id"]
    forged_dir.mkdir(parents=True)
    for name in (
        "decision-input.json",
        "statement.json",
        "registry-snapshot.json",
        "verification.json",
    ):
        (forged_dir / name).write_bytes((bundle_dir / name).read_bytes())
    _dump_json(forged_dir / "record.json", forged_record.model_dump(mode="json"))
    _dump_json(forged_dir / "bundle.json", payload)

    result = reverify_owner_decision_evidence(forged_dir / "bundle.json")
    assert result.replay_status == "MISMATCH", result.mismatches
    assert "AUTHORITY_STATUS_INCONSISTENT" in result.mismatches
    assert "AUTHORITY_VERIFIER_KIND_DIVERGED" in result.mismatches
    with pytest.raises(OwnerTrustStoreError):
        load_owner_decision_evidence(forged_dir / "bundle.json")
