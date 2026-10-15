"""Phase 7-C3-A focused tests: authenticated owner provenance verification.

Covers the Ed25519 provenance contracts (key registry as the independent
trust root, signature statement, verification dossier with the canonical
nine-check sequence), the pure offline verification function, the real
``SignedOwnerProvenanceVerifier`` at both C2 call points (record-time capture
and C2-R1 plan-time re-attestation), signature replay across
profiles/decisions/purposes, the signed-REJECT/ACCEPT-record substitution
attack, fail-closed behavior for unknown/revoked/expired/scope-exceeding
keys and identity mismatches, lazy-cryptography fail-closed imports,
socket-guarded offline execution, schema drift parity with the pinned check
sequence, determinism, published-byte preservation and the absence of any
production backdoor (no CLI wiring, no trust override, no environment
bypass).

All Ed25519 keys here are throwaway fixtures generated at runtime; no real
owner key material exists in this repository, and no real owner acceptance
of strict-v2 is claimed or synthesized.
"""

import base64
import hashlib
import json
import socket
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from turtle_value_engine import load_normalized_input
from turtle_value_engine.evolution.activation_plan import (
    ProfileActivationPlanV1,
    plan_profile_activation,
)
from turtle_value_engine.evolution.owner_decision import (
    DecisionProvenanceV1,
    OwnerAuthorityAssessmentV1,
    OwnerPolicyDecisionInputV1,
    OwnerPolicyDecisionRecordV1,
    OwnerPolicyDecisionRevocationV1,
    validate_owner_decision,
)
from turtle_value_engine.evolution.owner_provenance import (
    PROVENANCE_ALGORITHM,
    PROVENANCE_PURPOSE,
    REQUIRED_PROVENANCE_CHECK_NAMES,
    OwnerProvenanceError,
    OwnerProvenanceKeyRecordV1,
    OwnerProvenanceKeyRegistryV1,
    OwnerProvenanceVerificationV1,
    OwnerSignedDecisionStatementV1,
    SignedOwnerProvenanceVerifier,
    build_owner_provenance_key_registry,
    build_owner_signed_decision_statement,
    owner_decision_input_signature_message,
    owner_provenance_key_id,
    verify_owner_provenance,
)
from turtle_value_engine.evolution.profile_semantic_audit import (
    VersionedPolicyExceptionV1,
    audit_profile_semantics,
)
from turtle_value_engine.providers.models import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[1]
BASE_PROFILE_PATH = ROOT / "rules" / "strict-v1.yaml"
TARGET_PROFILE_PATH = ROOT / "rules" / "strict-v2.yaml"
MANIFEST_PATH = ROOT / "docs" / "releases" / "strict-v2" / "release-candidate.json"
BOUNDARY_PATH = ROOT / "fixtures" / "healthy_cash_cow.json"

STRICT_V2_SHA256 = "adba44b799fdb42a6e443d55891dd3262842aee1dbc441e823b2a3155396dd7d"
OWNER_IDENTITY = "Ryder Xie"

_boundary_input = None


def _boundary():
    global _boundary_input
    if _boundary_input is None:
        _boundary_input = load_normalized_input(BOUNDARY_PATH)
    return _boundary_input


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
    exception = _policy_exception()
    audit = audit_profile_semantics(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=_boundary(),
        policy_exceptions=[exception],
    )
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
        "exception_id": exception.exception_id,
        "exception_content_sha256": exception.content_sha256,
        "rationale": "Accept the stricter 14% CDC gate as intended owner policy.",
        "declared_owner_identity": OWNER_IDENTITY,
        "decided_at": "2026-10-14",
        "source_revision": "c3a-test",
    }
    payload.update(overrides)
    return payload


def _accept_input(**overrides) -> OwnerPolicyDecisionInputV1:
    return OwnerPolicyDecisionInputV1.model_validate(_accept_payload(**overrides))


def _reject_input() -> OwnerPolicyDecisionInputV1:
    return OwnerPolicyDecisionInputV1.model_validate(
        _accept_payload(
            decision="REJECT",
            exception_id=None,
            exception_content_sha256=None,
            rationale=(
                "Owner rejects the stricter gate until band ordering is "
                "corrected in a strict-v3 candidate."
            ),
        )
    )


class _FixtureKey:
    """A throwaway Ed25519 keypair with its registry record."""

    def __init__(
        self,
        *,
        owner_identity: str = OWNER_IDENTITY,
        authorized_decisions: list[str] | None = None,
        valid_from: str = "2026-01-01",
        valid_until: str = "2026-12-31",
        revoked: bool = False,
    ) -> None:
        self.private = Ed25519PrivateKey.generate()
        self.public_base64 = base64.b64encode(
            self.private.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
        ).decode("ascii")
        self.key_id = owner_provenance_key_id(
            algorithm=PROVENANCE_ALGORITHM, public_key_base64=self.public_base64
        )
        self.record = OwnerProvenanceKeyRecordV1(
            key_id=self.key_id,
            algorithm=PROVENANCE_ALGORITHM,
            public_key_base64=self.public_base64,
            owner_identity=owner_identity,
            authorized_decisions=authorized_decisions
            or ["ACCEPT_WITH_EXCEPTION", "REJECT"],
            valid_from=valid_from,
            valid_until=valid_until,
            revoked=revoked,
            **({"revocation_reference": "test-revocation"} if revoked else {}),
        )

    def sign_input(self, decision_input: OwnerPolicyDecisionInputV1):
        message = owner_decision_input_signature_message(decision_input)
        statement = build_owner_signed_decision_statement(
            signature=self.private.sign(message),
            key_id=self.key_id,
            decision_input=decision_input,
        )
        return statement, message.split(b"\x00", 1)[1]


def _registry(*keys: _FixtureKey) -> OwnerProvenanceKeyRegistryV1:
    return build_owner_provenance_key_registry([key.record for key in keys])


def _failed_names(verification: OwnerProvenanceVerificationV1) -> list[str]:
    return [check.name for check in verification.checks if not check.passed]


def _write_project_config(tmp_path: Path, default: str = "strict-v1") -> Path:
    content = [
        "schema_version = 1",
        "",
        "[project]",
        'id = "turtle-value-engine"',
        'environment = "private"',
        'timezone = "Asia/Taipei"',
        "",
        "[profiles]",
        f'default = "{default}"',
        "",
    ]
    path = tmp_path / "project.toml"
    path.write_text("\n".join(content), encoding="utf-8")
    return path


def _plan(tmp_path: Path, *, records, verifier, **kwargs):
    return plan_profile_activation(
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        boundary_input=_boundary(),
        decision_records=records,
        policy_exceptions=kwargs.pop("policy_exceptions", [_policy_exception()]),
        project_config_path=kwargs.pop(
            "project_config_path", _write_project_config(tmp_path)
        ),
        authority_verifier=verifier,
        **kwargs,
    )


def _record_bytes(record: OwnerPolicyDecisionRecordV1) -> bytes:
    return canonical_json_bytes(record.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# 1. Trust-root contracts
# ---------------------------------------------------------------------------


def test_key_id_is_derived_from_key_material_only():
    key = _FixtureKey()
    same_material = owner_provenance_key_id(
        algorithm=PROVENANCE_ALGORITHM, public_key_base64=key.public_base64
    )
    assert same_material == key.key_id
    other = _FixtureKey()
    assert other.key_id != key.key_id

    with pytest.raises(ValidationError):
        OwnerProvenanceKeyRecordV1(
            key_id="owner-provenance-key-0000000000000000000000ff",
            algorithm="ED25519",
            public_key_base64=key.public_base64,
            owner_identity=OWNER_IDENTITY,
            authorized_decisions=["REJECT"],
            valid_from="2026-01-01",
            valid_until="2026-12-31",
        )


def test_key_record_rejects_malformed_material_and_windows():
    key = _FixtureKey()
    base = {
        "key_id": key.key_id,
        "algorithm": "ED25519",
        "public_key_base64": key.public_base64,
        "owner_identity": OWNER_IDENTITY,
        "authorized_decisions": ["REJECT"],
        "valid_from": "2026-01-01",
        "valid_until": "2026-12-31",
    }
    with pytest.raises(ValidationError):
        OwnerProvenanceKeyRecordV1(**{**base, "valid_from": "2026-12-31",
                                      "valid_until": "2026-01-01"})
    with pytest.raises(ValidationError):
        OwnerProvenanceKeyRecordV1(**{**base, "valid_from": "not-a-date"})
    with pytest.raises(ValidationError):
        OwnerProvenanceKeyRecordV1(**{**base, "revoked": True})  # no reference
    with pytest.raises(ValidationError):
        OwnerProvenanceKeyRecordV1(**{**base, "authorized_decisions": []})
    with pytest.raises(ValidationError):
        OwnerProvenanceKeyRecordV1(**{**base, "authorized_decisions": ["REJECT", "REJECT"]})
    # 16-byte key material is not an Ed25519 public key
    short = base64.b64encode(b"x" * 16).decode("ascii")
    with pytest.raises(ValidationError):
        OwnerProvenanceKeyRecordV1(
            **{**base, "public_key_base64": short},
        )


def test_registry_builder_and_integrity_rejection():
    a, b = _FixtureKey(), _FixtureKey()
    registry = _registry(a, b)
    assert len(registry.keys) == 2
    # deterministic id and content hash over the same keys
    rebuilt = _registry(a, b)
    assert rebuilt == registry

    with pytest.raises(ValidationError):
        OwnerProvenanceKeyRegistryV1(
            registry_id=registry.registry_id,
            keys=[a.record, a.record],  # duplicate key id
            content_sha256=registry.content_sha256,
        )

    tampered = registry.model_dump(mode="json")
    tampered["content_sha256"] = "0" * 64
    with pytest.raises(ValidationError):
        OwnerProvenanceKeyRegistryV1.model_validate(tampered)

    wrong_id = registry.model_dump(mode="json")
    wrong_id["registry_id"] = "owner-provenance-key-registry-0000000000000000000ff"
    with pytest.raises(ValidationError):
        OwnerProvenanceKeyRegistryV1.model_validate(wrong_id)


def test_registry_is_independent_of_decision_files():
    """Key identities never reference or change with decision content."""

    key = _FixtureKey()
    registry = _registry(key)
    before = (registry.registry_id, registry.content_sha256, key.key_id)
    # Signing arbitrary different decisions never touches the registry.
    _ = _accept_input()
    _ = _reject_input()
    assert (registry.registry_id, registry.content_sha256, key.key_id) == before


# ---------------------------------------------------------------------------
# 2. Signature evidence contract
# ---------------------------------------------------------------------------


def test_statement_builder_binds_the_exact_signed_message():
    decision_input = _accept_input()
    key = _FixtureKey()
    statement, input_bytes = key.sign_input(decision_input)
    message = PROVENANCE_PURPOSE.encode("utf-8") + b"\x00" + input_bytes
    assert statement.signed_content_sha256 == hashlib.sha256(message).hexdigest()
    assert statement.decision_input_content_sha256 == hashlib.sha256(
        input_bytes
    ).hexdigest()
    assert statement.purpose == PROVENANCE_PURPOSE
    assert len(base64.b64decode(statement.signature_base64)) == 64

    with pytest.raises(ValidationError):
        build_owner_signed_decision_statement(
            signature=b"x" * 63,  # not a valid Ed25519 signature length
            key_id=key.key_id,
            decision_input=decision_input,
        )


def test_statement_rejects_tampered_content_hash():
    key = _FixtureKey()
    statement, _ = key.sign_input(_accept_input())
    tampered = statement.model_dump(mode="json")
    tampered["decision_input_content_sha256"] = "1" * 64
    with pytest.raises(ValidationError):
        OwnerSignedDecisionStatementV1.model_validate(tampered)


# ---------------------------------------------------------------------------
# 3. Pure offline verification: positive and negative matrix
# ---------------------------------------------------------------------------


def test_verified_happy_path_passes_every_canonical_check():
    key = _FixtureKey()
    statement, input_bytes = key.sign_input(_accept_input())
    verification = verify_owner_provenance(
        decision_input_bytes=input_bytes,
        statement=statement,
        registry=_registry(key),
        declared_owner_identity=OWNER_IDENTITY,
    )
    assert verification.verification_status == "VERIFIED"
    assert _failed_names(verification) == []
    assert verification.key_id == key.key_id
    assert verification.revocation_status == "NOT_REVOKED"
    assert verification.key_validity == "WITHIN_WINDOW"
    assert verification.reason_code == "ALL_PROVENANCE_CHECKS_PASSED"
    assert [check.name for check in verification.checks] == list(
        REQUIRED_PROVENANCE_CHECK_NAMES
    )


def test_unknown_key_is_rejected_fail_closed():
    registered = _FixtureKey()
    stranger = _FixtureKey()  # real key, real signature, not registered
    statement, input_bytes = stranger.sign_input(_accept_input())
    verification = verify_owner_provenance(
        decision_input_bytes=input_bytes,
        statement=statement,
        registry=_registry(registered),
        declared_owner_identity=OWNER_IDENTITY,
    )
    assert verification.verification_status == "REJECTED"
    assert "KEY_RESOLUTION" in _failed_names(verification)
    assert verification.key_id is None
    assert verification.revocation_status == "UNKNOWN"


def test_revoked_key_is_rejected():
    key = _FixtureKey(revoked=True)
    statement, input_bytes = key.sign_input(_accept_input())
    verification = verify_owner_provenance(
        decision_input_bytes=input_bytes,
        statement=statement,
        registry=_registry(key),
        declared_owner_identity=OWNER_IDENTITY,
    )
    assert verification.verification_status == "REJECTED"
    assert "KEY_NOT_REVOKED" in _failed_names(verification)
    assert verification.revocation_status == "REVOKED"


def test_out_of_window_and_malformed_dates_fail_closed():
    key = _FixtureKey(valid_from="2026-10-15", valid_until="2026-12-31")
    statement, input_bytes = key.sign_input(
        _accept_input(decided_at="2026-10-14")
    )
    verification = verify_owner_provenance(
        decision_input_bytes=input_bytes,
        statement=statement,
        registry=_registry(key),
    )
    assert "KEY_VALIDITY_WINDOW" in _failed_names(verification)
    assert verification.key_validity == "OUTSIDE_WINDOW"

    key2 = _FixtureKey()
    statement2, input_bytes2 = key2.sign_input(
        _accept_input(decided_at="14 October 2026")
    )
    verification2 = verify_owner_provenance(
        decision_input_bytes=input_bytes2,
        statement=statement2,
        registry=_registry(key2),
    )
    assert "KEY_VALIDITY_WINDOW" in _failed_names(verification2)
    assert verification2.key_validity == "UNKNOWN"


def test_scope_exceeding_key_is_rejected():
    key = _FixtureKey(authorized_decisions=["REJECT"])
    statement, input_bytes = key.sign_input(_accept_input())
    verification = verify_owner_provenance(
        decision_input_bytes=input_bytes,
        statement=statement,
        registry=_registry(key),
    )
    assert "KEY_SCOPE_AUTHORIZED" in _failed_names(verification)
    # a REJECT decision with the same key stays in scope
    reject_statement, reject_bytes = key.sign_input(_reject_input())
    reject_verification = verify_owner_provenance(
        decision_input_bytes=reject_bytes,
        statement=reject_statement,
        registry=_registry(key),
    )
    assert reject_verification.verification_status == "VERIFIED"


def test_identity_binding_rejects_mismatches():
    other_owner_key = _FixtureKey(owner_identity="Someone Else")
    statement, input_bytes = other_owner_key.sign_input(_accept_input())
    verification = verify_owner_provenance(
        decision_input_bytes=input_bytes,
        statement=statement,
        registry=_registry(other_owner_key),
    )
    # the decision input declares Ryder Xie but the key binds Someone Else...
    assert statement.declared_owner_identity == OWNER_IDENTITY
    assert "KEY_IDENTITY_BINDING" in _failed_names(verification)

    key = _FixtureKey()
    statement2, input_bytes2 = key.sign_input(_accept_input())
    # ...and the plan-time identity cross-check also fails closed
    verification2 = verify_owner_provenance(
        decision_input_bytes=input_bytes2,
        statement=statement2,
        registry=_registry(key),
        declared_owner_identity="Someone Else",
    )
    assert "KEY_IDENTITY_BINDING" in _failed_names(verification2)


def test_tampered_decision_bytes_are_rejected():
    key = _FixtureKey()
    statement, input_bytes = key.sign_input(_accept_input())
    payload = json.loads(input_bytes)
    payload["rationale"] = "Tampered rationale after signing."
    tampered_bytes = canonical_json_bytes(payload)
    verification = verify_owner_provenance(
        decision_input_bytes=tampered_bytes,
        statement=statement,
        registry=_registry(key),
    )
    assert verification.verification_status == "REJECTED"
    assert "DECISION_CONTENT_BINDING" in _failed_names(verification)
    assert "SIGNATURE_VERIFIED" in _failed_names(verification)


def test_non_canonical_input_form_is_rejected_anti_malleability():
    key = _FixtureKey()
    statement, input_bytes = key.sign_input(_accept_input())
    pretty = json.dumps(json.loads(input_bytes), indent=2, sort_keys=True).encode()
    assert pretty != input_bytes
    verification = verify_owner_provenance(
        decision_input_bytes=pretty,
        statement=statement,
        registry=_registry(key),
    )
    assert "DECISION_CONTENT_BINDING" in _failed_names(verification)


def test_cross_decision_replay_is_rejected():
    key = _FixtureKey()
    accept_statement, _ = key.sign_input(_accept_input())
    _, reject_bytes = key.sign_input(_reject_input())
    # a genuinely signed REJECT cannot satisfy the ACCEPT statement
    verification = verify_owner_provenance(
        decision_input_bytes=reject_bytes,
        statement=accept_statement,
        registry=_registry(key),
    )
    assert "DECISION_CONTENT_BINDING" in _failed_names(verification)
    assert verification.verification_status == "REJECTED"

    # and a different-but-valid ACCEPT (different audit binding) neither:
    # simulate a strict-v3 context by rebinding the audit fields.
    other_audit = _accept_payload(
        rationale="A different decision context with different content."
    )
    other_input = OwnerPolicyDecisionInputV1.model_validate(other_audit)
    _, other_bytes = key.sign_input(other_input)
    verification2 = verify_owner_provenance(
        decision_input_bytes=other_bytes,
        statement=accept_statement,
        registry=_registry(key),
    )
    assert verification2.verification_status == "REJECTED"


def test_cross_purpose_signature_replay_is_rejected():
    key = _FixtureKey()
    decision_input = _accept_input()
    canonical = canonical_json_bytes(decision_input.model_dump(mode="json"))

    # (a) the owner's key signs a DIFFERENT purpose's message; the attacker
    # wraps that signature in a decision statement with its honest hash.
    foreign_message = b"turtle-value-engine:some-other-purpose:v1\x00" + canonical
    foreign_statement = build_owner_signed_decision_statement(
        signature=key.private.sign(foreign_message),
        key_id=key.key_id,
        decision_input=decision_input,
    )
    # the honest builder hashes OUR message; fix the signed hash to the
    # foreign message so the mismatch is exactly the purpose separation:
    fields = foreign_statement.model_dump(mode="json", exclude={"content_sha256"})
    fields["signed_content_sha256"] = hashlib.sha256(foreign_message).hexdigest()
    fields["content_sha256"] = hashlib.sha256(
        canonical_json_bytes(fields)
    ).hexdigest()
    replay = OwnerSignedDecisionStatementV1.model_validate(fields)
    verification = verify_owner_provenance(
        decision_input_bytes=canonical,
        statement=replay,
        registry=_registry(key),
    )
    assert verification.verification_status == "REJECTED"
    assert "SIGNATURE_VERIFIED" in _failed_names(verification)

    # (b) raw prefix-less message with a claimed-correct hash still fails.
    raw_statement = build_owner_signed_decision_statement(
        signature=key.private.sign(canonical),  # no domain prefix
        key_id=key.key_id,
        decision_input=decision_input,
    )
    verification2 = verify_owner_provenance(
        decision_input_bytes=canonical,
        statement=raw_statement,
        registry=_registry(key),
    )
    assert "SIGNATURE_VERIFIED" in _failed_names(verification2)


def test_verification_is_deterministic_and_offline_replayable():
    key = _FixtureKey()
    statement, input_bytes = key.sign_input(_accept_input())
    first = verify_owner_provenance(
        decision_input_bytes=input_bytes, statement=statement, registry=_registry(key)
    )
    second = verify_owner_provenance(
        decision_input_bytes=input_bytes, statement=statement, registry=_registry(key)
    )
    assert first == second
    assert first.verification_id == second.verification_id
    assert first.content_sha256 == second.content_sha256
    # the dossier carries no wall-clock field
    serialized = json.dumps(first.model_dump(mode="json"))
    for forbidden in ("created_at", "timestamp", "verified_at", "generated_at"):
        assert forbidden not in serialized


def test_missing_cryptography_fails_closed(monkeypatch):
    import sys

    monkeypatch.setitem(
        sys.modules, "cryptography.hazmat.primitives.asymmetric.ed25519", None
    )
    key = _FixtureKey()
    statement, input_bytes = key.sign_input(_accept_input())
    with pytest.raises(OwnerProvenanceError, match=r"\[provenance\] extra"):
        verify_owner_provenance(
            decision_input_bytes=input_bytes,
            statement=statement,
            registry=_registry(key),
        )


# ---------------------------------------------------------------------------
# 4. The real verifier at both C2 call points, and plan integration
# ---------------------------------------------------------------------------


def _signed_accept_fixture():
    key = _FixtureKey()
    statement, input_bytes = key.sign_input(_accept_input())
    verifier = SignedOwnerProvenanceVerifier(
        registry=_registry(key), statement=statement, decision_input_bytes=input_bytes
    )
    return key, statement, input_bytes, verifier


def test_record_time_capture_produces_a_verified_valid_record():
    _key, _statement, input_bytes, verifier = _signed_accept_fixture()
    validation = validate_owner_decision(
        decision_input=_accept_input(),
        decision_source_bytes=input_bytes,
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        policy_exceptions=[_policy_exception()],
        verifier=verifier,
    )
    assert validation.state == "VALID"
    assert validation.authority_status == "OWNER_AUTHORITY_VERIFIED"
    assert validation.record is not None
    assert validation.record.authority.verifier_kind == verifier.kind
    assert validation.record.provenance.source_content_sha256 == hashlib.sha256(
        input_bytes
    ).hexdigest()


def test_signed_decision_reaches_reverified_ready_plan_end_to_end(tmp_path):
    _key, _statement, input_bytes, verifier = _signed_accept_fixture()
    validation = validate_owner_decision(
        decision_input=_accept_input(),
        decision_source_bytes=input_bytes,
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        policy_exceptions=[_policy_exception()],
        verifier=verifier,
    )
    record = validation.record
    assert record is not None

    plan = _plan(tmp_path, records=[record], verifier=verifier)
    assert plan.plan_state == "READY_FOR_EXPLICIT_OWNER_EXECUTION"
    assert plan.authority_reverification_status == "REVERIFIED"
    assert plan.decision_authority_state == "ACCEPT_VERIFIED"
    assert plan.execution_performed is False
    assert plan.automatic_activation_allowed is False


def test_signed_reject_cannot_authorize_an_accept_record(tmp_path):
    key = _FixtureKey()
    reject_statement, reject_bytes = key.sign_input(_reject_input())
    reject_verifier = SignedOwnerProvenanceVerifier(
        registry=_registry(key),
        statement=reject_statement,
        decision_input_bytes=reject_bytes,
    )
    # an ACCEPT record whose provenance points at the signed REJECT bytes
    accept_record = OwnerPolicyDecisionRecordV1.build(
        decision_input=_accept_input(),
        provenance=DecisionProvenanceV1(
            source_kind="LOCAL_UNSIGNED_JSON",
            source_revision="forged",
            source_content_sha256=hashlib.sha256(reject_bytes).hexdigest(),
        ),
        authority=OwnerAuthorityAssessmentV1(
            authority_status="OWNER_AUTHORITY_VERIFIED",
            verification_method="INJECTED_VERIFIER",
            verifier_kind=key.key_id,
            allowlist_matched=True,
            reason_code="FORGED",
            detail="forged accept over a signed reject",
        ),
    )
    plan = _plan(tmp_path, records=[accept_record], verifier=reject_verifier)
    assert plan.plan_state == "BLOCKED"
    assert plan.authority_reverification_status == "REVERIFICATION_FAILED"
    assert "OWNER_AUTHORITY_REVERIFICATION_REJECTED" in plan.blockers
    assert plan.execution_performed is False


def test_plan_time_provenance_hash_mismatch_is_rejected(tmp_path):
    key = _FixtureKey()
    statement, input_bytes = key.sign_input(_accept_input())
    verifier = SignedOwnerProvenanceVerifier(
        registry=_registry(key), statement=statement, decision_input_bytes=input_bytes
    )
    record = OwnerPolicyDecisionRecordV1.build(
        decision_input=_accept_input(),
        provenance=DecisionProvenanceV1(
            source_kind="LOCAL_UNSIGNED_JSON",
            source_revision="about-other-bytes",
            source_content_sha256=hashlib.sha256(b"other-submission").hexdigest(),
        ),
        authority=OwnerAuthorityAssessmentV1(
            authority_status="OWNER_AUTHORITY_VERIFIED",
            verification_method="INJECTED_VERIFIER",
            verifier_kind=verifier.kind,
            allowlist_matched=True,
            reason_code="FORGED",
            detail="record about different bytes",
        ),
    )
    plan = _plan(tmp_path, records=[record], verifier=verifier)
    assert plan.plan_state == "BLOCKED"
    assert "OWNER_AUTHORITY_REVERIFICATION_REJECTED" in plan.blockers


def test_tampered_signature_keeps_the_plan_blocked(tmp_path):
    key = _FixtureKey()
    statement, input_bytes = key.sign_input(_accept_input())
    # flip one signature byte but keep every other binding honest
    fields = statement.model_dump(mode="json", exclude={"content_sha256"})
    raw = bytearray(base64.b64decode(fields["signature_base64"]))
    raw[0] ^= 1
    fields["signature_base64"] = base64.b64encode(bytes(raw)).decode("ascii")
    fields["content_sha256"] = hashlib.sha256(
        canonical_json_bytes(fields)
    ).hexdigest()
    tampered = OwnerSignedDecisionStatementV1.model_validate(fields)
    verifier = SignedOwnerProvenanceVerifier(
        registry=_registry(key), statement=tampered, decision_input_bytes=input_bytes
    )
    validation = validate_owner_decision(
        decision_input=_accept_input(),
        decision_source_bytes=input_bytes,
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        policy_exceptions=[_policy_exception()],
        verifier=verifier,
    )
    assert validation.authority_status == "OWNER_AUTHORITY_REJECTED"
    record = OwnerPolicyDecisionRecordV1.build(
        decision_input=_accept_input(),
        provenance=DecisionProvenanceV1(
            source_kind="LOCAL_UNSIGNED_JSON",
            source_revision="c3a-test",
            source_content_sha256=hashlib.sha256(input_bytes).hexdigest(),
        ),
        authority=OwnerAuthorityAssessmentV1(
            authority_status="OWNER_AUTHORITY_VERIFIED",
            verification_method="INJECTED_VERIFIER",
            verifier_kind=verifier.kind,
            allowlist_matched=True,
            reason_code="FORGED",
            detail="forged claim, tampered signature",
        ),
    )
    plan = _plan(tmp_path, records=[record], verifier=verifier)
    assert plan.plan_state == "BLOCKED"
    assert plan.authority_reverification_status == "REVERIFICATION_FAILED"
    assert plan.execution_performed is False


def test_assessment_evidence_binds_the_exact_record_bytes():
    _key, _statement, input_bytes, verifier = _signed_accept_fixture()
    record = OwnerPolicyDecisionRecordV1.build(
        decision_input=_accept_input(),
        provenance=DecisionProvenanceV1(
            source_kind="LOCAL_UNSIGNED_JSON",
            source_revision="c3a-test",
            source_content_sha256=hashlib.sha256(input_bytes).hexdigest(),
        ),
        authority=OwnerAuthorityAssessmentV1(
            authority_status="OWNER_AUTHORITY_VERIFIED",
            verification_method="INJECTED_VERIFIER",
            verifier_kind=verifier.kind,
            allowlist_matched=True,
            reason_code="CLAIM",
            detail="claim to be re-attested",
        ),
    )
    record_bytes = _record_bytes(record)
    assessment = verifier.verify_decision_authority(
        declared_owner_identity=record.declared_owner_identity,
        provenance=record.provenance,
        decision_source_bytes=record_bytes,
    )
    assert assessment.authority_status == "OWNER_AUTHORITY_VERIFIED"
    assert assessment.evidence_content_sha256 == hashlib.sha256(
        record_bytes
    ).hexdigest()


def test_verifier_record_time_rejects_other_submission_bytes():
    _key, _statement, input_bytes, verifier = _signed_accept_fixture()
    other_bytes = canonical_json_bytes(_reject_input().model_dump(mode="json"))
    assessment = verifier.verify_decision_authority(
        declared_owner_identity=OWNER_IDENTITY,
        provenance=DecisionProvenanceV1(
            source_kind="LOCAL_UNSIGNED_JSON",
            source_revision="x",
            source_content_sha256=hashlib.sha256(other_bytes).hexdigest(),
        ),
        decision_source_bytes=other_bytes,
    )
    assert assessment.authority_status == "OWNER_AUTHORITY_REJECTED"
    assert assessment.reason_code == "OWNER_PROVENANCE_SOURCE_BYTES_MISMATCH"


# ---------------------------------------------------------------------------
# 5. Hardening meta: no backdoor, offline, schemas, published bytes
# ---------------------------------------------------------------------------


def test_no_production_backdoor_or_cli_wiring():
    import turtle_value_engine.cli as cli_module
    import turtle_value_engine.evolution.owner_provenance as provenance_module

    cli_source = Path(cli_module.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "SignedOwnerProvenanceVerifier",
        "owner_provenance",
        "--verifier",
        "--provenance-verifier",
        "--registry",
        "--key-registry",
    ):
        assert forbidden not in cli_source

    module_source = Path(provenance_module.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "os.environ",
        "getenv",
        "trust=True",
        "trust_verified",
        "TVE_TRUST",
    ):
        assert forbidden not in module_source


def test_verification_constructs_no_socket(monkeypatch):
    def no_sockets(*args, **kwargs):
        raise AssertionError("provenance verification constructed a socket")

    monkeypatch.setattr(socket, "socket", no_sockets)
    monkeypatch.setattr(socket, "create_connection", no_sockets)

    key = _FixtureKey()
    statement, input_bytes = key.sign_input(_accept_input())
    verification = verify_owner_provenance(
        decision_input_bytes=input_bytes,
        statement=statement,
        registry=_registry(key),
        declared_owner_identity=OWNER_IDENTITY,
    )
    assert verification.verification_status == "VERIFIED"

    verifier = SignedOwnerProvenanceVerifier(
        registry=_registry(key), statement=statement, decision_input_bytes=input_bytes
    )
    assessment = verifier.verify_decision_authority(
        declared_owner_identity=OWNER_IDENTITY,
        provenance=DecisionProvenanceV1(
            source_kind="LOCAL_UNSIGNED_JSON",
            source_revision="c3a-test",
            source_content_sha256=hashlib.sha256(input_bytes).hexdigest(),
        ),
        decision_source_bytes=canonical_json_bytes(
            OwnerPolicyDecisionRecordV1.build(
                decision_input=_accept_input(),
                provenance=DecisionProvenanceV1(
                    source_kind="LOCAL_UNSIGNED_JSON",
                    source_revision="c3a-test",
                    source_content_sha256=hashlib.sha256(input_bytes).hexdigest(),
                ),
                authority=OwnerAuthorityAssessmentV1(
                    authority_status="OWNER_AUTHORITY_UNVERIFIED",
                    verification_method="NO_AUTHENTICATED_SOURCE",
                    allowlist_matched=None,
                    reason_code="NO_AUTHENTICATED_SOURCE_AVAILABLE",
                    detail="captured",
                ),
            ).model_dump(mode="json")
        ),
    )
    assert assessment.authority_status == "OWNER_AUTHORITY_VERIFIED"


@pytest.mark.parametrize(
    ("schema_name", "model"),
    [
        ("owner-provenance-key-registry.schema.json", OwnerProvenanceKeyRegistryV1),
        (
            "owner-signed-decision-statement.schema.json",
            OwnerSignedDecisionStatementV1,
        ),
        ("owner-provenance-verification.schema.json", OwnerProvenanceVerificationV1),
    ],
)
def test_checked_in_schemas_have_drift_parity(schema_name, model):
    schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema == model.model_json_schema()


def test_verification_schema_pins_exact_check_sequence():
    schema = json.loads(
        (ROOT / "schemas" / "owner-provenance-verification.schema.json").read_text(
            encoding="utf-8"
        )
    )
    checks = schema["properties"]["checks"]
    pinned = [item["properties"]["name"]["const"] for item in checks["prefixItems"]]
    assert pinned == list(REQUIRED_PROVENANCE_CHECK_NAMES)
    assert checks["items"] is False
    assert checks["minItems"] == checks["maxItems"] == len(pinned)


def test_verification_dossier_rejects_noncanonical_check_sequences():
    _key, _statement, input_bytes, verifier = _signed_accept_fixture()
    verification = verify_owner_provenance(
        decision_input_bytes=input_bytes,
        statement=verifier.statement,
        registry=verifier.registry,
        declared_owner_identity=OWNER_IDENTITY,
    )
    payload = verification.model_dump(mode="json")
    reordered = dict(payload)
    reordered["checks"] = [payload["checks"][1], payload["checks"][0]] + (
        payload["checks"][2:]
    )
    with pytest.raises(ValidationError):
        OwnerProvenanceVerificationV1.model_validate(reordered)

    duplicated = dict(payload)
    duplicated["checks"] = payload["checks"][:-1] + [payload["checks"][-2]]
    with pytest.raises(ValidationError):
        OwnerProvenanceVerificationV1.model_validate(duplicated)

    with pytest.raises(ValidationError):
        OwnerProvenanceVerificationV1.model_validate(
            {**payload, "verification_status": "VERIFIED", "checks": []}
        )


def test_published_bytes_and_default_profile_are_preserved():
    assert (
        hashlib.sha256(
            (ROOT / "rules" / "strict-v1.yaml").read_bytes()
        ).hexdigest()
        == "e3618f78b2f8e4d1e8e81ce3065da977685ad5256bd0ab3332b3a8054e0b6333"
    )
    assert (
        hashlib.sha256(
            (ROOT / "rules" / "strict-v2.yaml").read_bytes()
        ).hexdigest()
        == STRICT_V2_SHA256
    )
    example_config = (ROOT / "config" / "project.example.toml").read_text(
        encoding="utf-8"
    )
    assert 'default = "strict-v1"' in example_config


def test_owner_provenance_uses_only_synthetic_fixture_keys():
    """No real owner key material may live in this repository."""

    module = Path(
        SignedOwnerProvenanceVerifier.__module__.replace(".", "/") + ".py"
    )
    source = (ROOT / "src" / module).read_text(encoding="utf-8")
    # production code never signs and never holds private key material
    for forbidden in ("Ed25519PrivateKey", "private_bytes", "SigningKey"):
        assert forbidden not in source


# Phase 7-C3-A-R1 independent trust-boundary regression reproductions.


def _noncanonical_base64_alias(value: str) -> str:
    """Change only unused RFC 4648 pad bits; decoded bytes remain identical."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    pad = len(value) - len(value.rstrip("="))
    assert pad in (1, 2)
    position = len(value) - pad - 1
    chars = list(value)
    chars[position] = alphabet[alphabet.index(chars[position]) ^ 1]
    alias = "".join(chars)
    assert alias != value
    assert base64.b64decode(alias, validate=True) == base64.b64decode(
        value, validate=True
    )
    return alias


def test_r1_reject_noncanonical_public_key_and_signature_base64():
    """Different text encoding must never create an alias of one signing key."""
    key = _FixtureKey()
    alias_key = _noncanonical_base64_alias(key.public_base64)
    with pytest.raises(OwnerProvenanceError, match="canonical"):
        owner_provenance_key_id(
            algorithm=PROVENANCE_ALGORITHM, public_key_base64=alias_key
        )
    with pytest.raises(ValidationError, match="canonical"):
        OwnerProvenanceKeyRecordV1.model_validate(
            {**key.record.model_dump(mode="json"), "public_key_base64": alias_key}
        )

    statement, _ = key.sign_input(_accept_input())
    alias_signature = _noncanonical_base64_alias(statement.signature_base64)
    with pytest.raises(ValidationError, match="canonical"):
        OwnerSignedDecisionStatementV1.model_validate(
            {
                **statement.model_dump(mode="json"),
                "signature_base64": alias_signature,
            }
        )


def test_r1_calendar_invalid_iso_date_returns_rejected_dossier():
    """A date with correct syntax but impossible day must not raise ValueError."""
    key = _FixtureKey()
    invalid_date_input = _accept_input(decided_at="2026-02-30")
    statement, signed_bytes = key.sign_input(invalid_date_input)
    verification = verify_owner_provenance(
        decision_input_bytes=signed_bytes,
        statement=statement,
        registry=_registry(key),
    )
    assert verification.verification_status == "REJECTED"
    assert verification.key_validity == "UNKNOWN"
    assert "KEY_VALIDITY_WINDOW" in _failed_names(verification)


def test_r1_signed_decision_does_not_authorize_a_forged_source_revision(tmp_path):
    """All record provenance fields derived from signed input must match it."""
    _key, _statement, signed_bytes, verifier = _signed_accept_fixture()
    validation = validate_owner_decision(
        decision_input=_accept_input(),
        decision_source_bytes=signed_bytes,
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        policy_exceptions=[_policy_exception()],
        verifier=verifier,
    )
    assert validation.record is not None
    forged = OwnerPolicyDecisionRecordV1.build(
        decision_input=_accept_input(),
        provenance=DecisionProvenanceV1(
            source_kind="LOCAL_UNSIGNED_JSON",
            source_revision="altered-after-signature",
            source_content_sha256=hashlib.sha256(signed_bytes).hexdigest(),
        ),
        authority=validation.record.authority,
    )
    assessment = verifier.verify_decision_authority(
        declared_owner_identity=forged.declared_owner_identity,
        provenance=forged.provenance,
        decision_source_bytes=_record_bytes(forged),
    )
    assert assessment.authority_status == "OWNER_AUTHORITY_REJECTED"
    assert assessment.reason_code == "OWNER_PROVENANCE_RECORD_INPUT_BINDING_MISMATCH"
    plan = _plan(tmp_path, records=[forged], verifier=verifier)
    assert plan.plan_state == "BLOCKED"
    assert "OWNER_AUTHORITY_REVERIFICATION_REJECTED" in plan.blockers
    assert plan.execution_performed is False


def test_r1_unsigned_supersession_cannot_resolve_ambiguity_to_ready(tmp_path):
    """A genuine signature never authorizes an unsigned record supersession."""
    _key, _statement, signed_bytes, verifier = _signed_accept_fixture()
    submitted = _accept_input()
    validation = validate_owner_decision(
        decision_input=submitted,
        decision_source_bytes=signed_bytes,
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        policy_exceptions=[_policy_exception()],
        verifier=verifier,
    )
    assert validation.record is not None
    earlier = OwnerPolicyDecisionRecordV1.build(
        decision_input=_accept_input(
            rationale="Earlier unsigned decision, intentionally separate from this one."
        ),
        provenance=DecisionProvenanceV1(
            source_kind="LOCAL_UNSIGNED_JSON",
            source_revision="earlier-submission",
            source_content_sha256="0" * 64,
        ),
        authority=OwnerAuthorityAssessmentV1(
            authority_status="OWNER_AUTHORITY_UNVERIFIED",
            verification_method="NO_AUTHENTICATED_SOURCE",
            reason_code="UNVERIFIED_FIXTURE",
            detail="Earlier unverified decision; cannot authorize replacement.",
        ),
    )
    forged = OwnerPolicyDecisionRecordV1.build(
        decision_input=submitted,
        provenance=validation.record.provenance,
        authority=validation.record.authority,
        supersedes_decision_record_id=earlier.decision_record_id,
    )
    assessment = verifier.verify_decision_authority(
        declared_owner_identity=forged.declared_owner_identity,
        provenance=forged.provenance,
        decision_source_bytes=_record_bytes(forged),
    )
    assert assessment.authority_status == "OWNER_AUTHORITY_REJECTED"
    assert assessment.reason_code == "OWNER_PROVENANCE_UNSIGNED_SUPERSESSION"
    plan = _plan(tmp_path, records=[earlier, forged], verifier=verifier)
    assert plan.plan_state == "BLOCKED"
    assert "OWNER_AUTHORITY_REVERIFICATION_REJECTED" in plan.blockers
    assert plan.execution_performed is False


def _unverified_reject_record() -> OwnerPolicyDecisionRecordV1:
    """A separately recorded, unsigned REJECT decision."""

    return OwnerPolicyDecisionRecordV1.build(
        decision_input=_reject_input(),
        provenance=DecisionProvenanceV1(
            source_kind="LOCAL_UNSIGNED_JSON",
            source_revision="separate-reject-submission",
            source_content_sha256=hashlib.sha256(b"separate-reject").hexdigest(),
        ),
        authority=OwnerAuthorityAssessmentV1(
            authority_status="OWNER_AUTHORITY_UNVERIFIED",
            verification_method="NO_AUTHENTICATED_SOURCE",
            reason_code="NO_AUTHENTICATED_SOURCE_AVAILABLE",
            detail="Unverified separate REJECT; never authorizes anything.",
        ),
    )


def _revocation_of(record: OwnerPolicyDecisionRecordV1) -> OwnerPolicyDecisionRevocationV1:
    return OwnerPolicyDecisionRevocationV1.build(
        revoked_decision_record_id=record.decision_record_id,
        target_profile_id=record.target_profile_id,
        target_profile_sha256=record.target_profile_sha256,
        revoked_by=OWNER_IDENTITY,
        revoked_at="2026-10-14",
        rationale="Unsigned revocation; no authenticated protocol exists yet.",
        provenance=DecisionProvenanceV1(
            source_kind="LOCAL_UNSIGNED_JSON",
            source_revision="revocation-submission",
            source_content_sha256=hashlib.sha256(b"revocation-src").hexdigest(),
        ),
        authority=OwnerAuthorityAssessmentV1(
            authority_status="OWNER_AUTHORITY_UNVERIFIED",
            verification_method="NO_AUTHENTICATED_SOURCE",
            reason_code="NO_AUTHENTICATED_SOURCE_AVAILABLE",
            detail="Revocation is unauthenticated bookkeeping, never authority.",
        ),
    )


def test_r1_forged_revocation_cannot_unblock_a_conflicting_set(tmp_path):
    """An unsigned revocation must not remove a conflicting REJECT to reach READY.

    Without this boundary the resolver applies every structurally valid
    revocation at face value, so a forged revocation of the dissenting REJECT
    collapses a CONFLICTING set onto the single signed ACCEPT and the plan
    reaches READY — the same unsigned-metadata escalation class as supersession.
    """
    _key, _statement, signed_bytes, verifier = _signed_accept_fixture()
    accept_record = OwnerPolicyDecisionRecordV1.build(
        decision_input=_accept_input(),
        provenance=DecisionProvenanceV1(
            source_kind="LOCAL_UNSIGNED_JSON",
            source_revision="c3a-test",
            source_content_sha256=hashlib.sha256(signed_bytes).hexdigest(),
        ),
        authority=OwnerAuthorityAssessmentV1(
            authority_status="OWNER_AUTHORITY_VERIFIED",
            verification_method="INJECTED_VERIFIER",
            verifier_kind=verifier.kind,
            allowlist_matched=True,
            reason_code="ED25519_OWNER_PROVENANCE_VERIFIED",
            detail="record-time capture",
        ),
    )
    reject_record = _unverified_reject_record()

    # Control: the conflicting set without any revocation stays blocked.
    control = _plan(tmp_path, records=[accept_record, reject_record], verifier=verifier)
    assert control.plan_state == "BLOCKED"
    assert "DECISIONS_CONFLICTING" in control.blockers

    # A forged revocation of the REJECT must not convert that into READY.
    forged = _revocation_of(reject_record)
    plan = _plan(
        tmp_path,
        records=[accept_record, reject_record],
        verifier=verifier,
        revocations=[forged],
    )
    assert plan.plan_state == "BLOCKED"
    assert "OWNER_REVOCATION_AUTHORITY_UNVERIFIED" in plan.blockers
    assert plan.execution_performed is False


def test_r1_effective_revocation_blocks_the_plan_until_a_signed_protocol_exists(
    tmp_path,
):
    """Even a genuine unauthenticated revocation cannot shape a plan.

    Until a versioned signed revocation protocol exists (C3-B), any revocation
    that withdraws a current record of the planned target fails the plan
    closed; withdrawing a decision must never be able to *increase* what the
    remaining set authorizes.
    """
    _key, _statement, signed_bytes, verifier = _signed_accept_fixture()
    accept_record = OwnerPolicyDecisionRecordV1.build(
        decision_input=_accept_input(),
        provenance=DecisionProvenanceV1(
            source_kind="LOCAL_UNSIGNED_JSON",
            source_revision="c3a-test",
            source_content_sha256=hashlib.sha256(signed_bytes).hexdigest(),
        ),
        authority=OwnerAuthorityAssessmentV1(
            authority_status="OWNER_AUTHORITY_VERIFIED",
            verification_method="INJECTED_VERIFIER",
            verifier_kind=verifier.kind,
            allowlist_matched=True,
            reason_code="ED25519_OWNER_PROVENANCE_VERIFIED",
            detail="record-time capture",
        ),
    )
    plan = _plan(
        tmp_path,
        records=[accept_record],
        verifier=verifier,
        revocations=[_revocation_of(accept_record)],
    )
    assert plan.plan_state == "BLOCKED"
    assert "OWNER_REVOCATION_AUTHORITY_UNVERIFIED" in plan.blockers
    assert "ALL_CURRENT_DECISIONS_REVOKED" in plan.blockers
    assert plan.execution_performed is False


def test_r1_revocation_of_a_stale_target_record_does_not_block_the_plan(tmp_path):
    """A revocation that cannot touch this plan's target is inert bookkeeping."""
    _key, _statement, signed_bytes, verifier = _signed_accept_fixture()
    accept_record = OwnerPolicyDecisionRecordV1.build(
        decision_input=_accept_input(),
        provenance=DecisionProvenanceV1(
            source_kind="LOCAL_UNSIGNED_JSON",
            source_revision="c3a-test",
            source_content_sha256=hashlib.sha256(signed_bytes).hexdigest(),
        ),
        authority=OwnerAuthorityAssessmentV1(
            authority_status="OWNER_AUTHORITY_VERIFIED",
            verification_method="INJECTED_VERIFIER",
            verifier_kind=verifier.kind,
            allowlist_matched=True,
            reason_code="ED25519_OWNER_PROVENANCE_VERIFIED",
            detail="record-time capture",
        ),
    )
    stale_target = OwnerPolicyDecisionRecordV1.build(
        decision_input=OwnerPolicyDecisionInputV1.model_validate(
            _accept_payload(
                base_profile_id="strict-v1",
                target_profile_id="strict-v3",
                target_profile_sha256="a" * 64,
                rationale=(
                    "Decision about a hypothetical different target profile; "
                    "kept stale for this plan."
                ),
            )
        ),
        provenance=DecisionProvenanceV1(
            source_kind="LOCAL_UNSIGNED_JSON",
            source_revision="other-target",
            source_content_sha256=hashlib.sha256(b"other-target").hexdigest(),
        ),
        authority=OwnerAuthorityAssessmentV1(
            authority_status="OWNER_AUTHORITY_UNVERIFIED",
            verification_method="NO_AUTHENTICATED_SOURCE",
            reason_code="NO_AUTHENTICATED_SOURCE_AVAILABLE",
            detail="Stale-target record.",
        ),
    )
    stale_revocation = OwnerPolicyDecisionRevocationV1.build(
        revoked_decision_record_id=stale_target.decision_record_id,
        target_profile_id="strict-v3",
        target_profile_sha256="a" * 64,
        revoked_by=OWNER_IDENTITY,
        revoked_at="2026-10-14",
        rationale="Revoking the stale-target decision; unrelated to this plan.",
        provenance=DecisionProvenanceV1(
            source_kind="LOCAL_UNSIGNED_JSON",
            source_revision="other-target-revocation",
            source_content_sha256=hashlib.sha256(b"other-revocation").hexdigest(),
        ),
        authority=OwnerAuthorityAssessmentV1(
            authority_status="OWNER_AUTHORITY_UNVERIFIED",
            verification_method="NO_AUTHENTICATED_SOURCE",
            reason_code="NO_AUTHENTICATED_SOURCE_AVAILABLE",
            detail="Unverified.",
        ),
    )
    plan = _plan(
        tmp_path,
        records=[accept_record, stale_target],
        verifier=verifier,
        revocations=[stale_revocation],
    )
    assert plan.plan_state == "READY_FOR_EXPLICIT_OWNER_EXECUTION"
    assert "OWNER_REVOCATION_AUTHORITY_UNVERIFIED" not in plan.blockers


def test_r1_registry_validity_dates_are_classified_validation_errors():
    """Impossible registry validity dates fail as ValidationError, never raw."""
    key = _FixtureKey()
    for bad_field in ("valid_from", "valid_until"):
        payload = key.record.model_dump(mode="json")
        payload[bad_field] = "2026-02-30"
        with pytest.raises(ValidationError):
            OwnerProvenanceKeyRecordV1.model_validate(payload)


def test_r1_forged_supersession_chain_stays_ambiguous(tmp_path):
    """A forged superseding record always leaves a forged active leaf.

    The resolver keeps every superseder itself active, so forged supersession
    cannot shrink a conflicting set onto the genuine signed record: the
    forged leaf stays active and the resolution fails closed as AMBIGUOUS.
    """
    _key, _statement, signed_bytes, verifier = _signed_accept_fixture()
    accept_record = OwnerPolicyDecisionRecordV1.build(
        decision_input=_accept_input(),
        provenance=DecisionProvenanceV1(
            source_kind="LOCAL_UNSIGNED_JSON",
            source_revision="c3a-test",
            source_content_sha256=hashlib.sha256(signed_bytes).hexdigest(),
        ),
        authority=OwnerAuthorityAssessmentV1(
            authority_status="OWNER_AUTHORITY_VERIFIED",
            verification_method="INJECTED_VERIFIER",
            verifier_kind=verifier.kind,
            allowlist_matched=True,
            reason_code="ED25519_OWNER_PROVENANCE_VERIFIED",
            detail="record-time capture",
        ),
    )
    reject_record = _unverified_reject_record()
    forged_mid = OwnerPolicyDecisionRecordV1.build(
        decision_input=_accept_input(),
        provenance=DecisionProvenanceV1(
            source_kind="LOCAL_UNSIGNED_JSON",
            source_revision="forged-mid",
            source_content_sha256=hashlib.sha256(b"forged-mid").hexdigest(),
        ),
        authority=OwnerAuthorityAssessmentV1(
            authority_status="OWNER_AUTHORITY_VERIFIED",
            verification_method="INJECTED_VERIFIER",
            verifier_kind=verifier.kind,
            allowlist_matched=True,
            reason_code="CLAIM",
            detail="Forged VERIFIED claim; never trusted at plan time.",
        ),
        supersedes_decision_record_id=reject_record.decision_record_id,
    )
    plan = _plan(
        tmp_path,
        records=[accept_record, reject_record, forged_mid],
        verifier=verifier,
    )
    assert plan.plan_state == "BLOCKED"
    assert "DECISIONS_AMBIGUOUS" in plan.blockers
    assert plan.execution_performed is False


# ---------------------------------------------------------------------------
# 7. C3-A-R2: trust-root snapshot binding
# ---------------------------------------------------------------------------


def _two_trust_roots():
    """One throwaway key registered under two valid trust contents.

    Same key set (therefore the same derived ``registry_id``), different
    validity windows that both cover ``decided_at`` 2026-10-14 — the minimal
    pair proving that ``registry_id`` alone is not a trust-content identity.
    """

    key = _FixtureKey()
    long_record = OwnerProvenanceKeyRecordV1(
        key_id=key.key_id,
        algorithm=PROVENANCE_ALGORITHM,
        public_key_base64=key.public_base64,
        owner_identity=OWNER_IDENTITY,
        authorized_decisions=["ACCEPT_WITH_EXCEPTION", "REJECT"],
        valid_from="2026-01-01",
        valid_until="2027-12-31",
    )
    return key, _registry(key), build_owner_provenance_key_registry([long_record])


def test_r2_registry_id_alone_is_not_a_trust_content_identity():
    _key, registry_short, registry_long = _two_trust_roots()
    assert registry_short.registry_id == registry_long.registry_id
    assert registry_short.content_sha256 != registry_long.content_sha256


def test_r2_dossier_binds_the_registry_content_snapshot():
    key, registry_short, registry_long = _two_trust_roots()
    statement, input_bytes = key.sign_input(_accept_input())
    dossier_short = verify_owner_provenance(
        decision_input_bytes=input_bytes, statement=statement, registry=registry_short
    )
    dossier_long = verify_owner_provenance(
        decision_input_bytes=input_bytes, statement=statement, registry=registry_long
    )
    assert dossier_short.verification_status == "VERIFIED"
    assert dossier_long.verification_status == "VERIFIED"
    # The exact trust-root content is recorded as a dossier value...
    assert dossier_short.registry_content_sha256 == registry_short.content_sha256
    assert dossier_long.registry_content_sha256 == registry_long.content_sha256
    # ...and separates the verification identities of the two trust roots.
    assert dossier_short.verification_id != dossier_long.verification_id
    assert dossier_short.content_sha256 != dossier_long.content_sha256


def test_r2_dossier_schema_requires_the_trust_root_snapshot():
    schema = json.loads(
        (ROOT / "schemas" / "owner-provenance-verification.schema.json").read_text(
            encoding="utf-8"
        )
    )
    props = schema["properties"]
    assert "registry_content_sha256" in props
    assert "registry_content_sha256" in schema["required"]


def test_r2_record_authority_captures_structured_trust_root():
    key, registry_short, _registry_long = _two_trust_roots()
    statement, input_bytes = key.sign_input(_accept_input())
    validation = validate_owner_decision(
        decision_input=_accept_input(),
        decision_source_bytes=input_bytes,
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        policy_exceptions=[_policy_exception()],
        verifier=SignedOwnerProvenanceVerifier(
            registry=registry_short,
            statement=statement,
            decision_input_bytes=input_bytes,
        ),
    )
    assert validation.record is not None
    authority = validation.record.authority
    assert authority.authority_status == "OWNER_AUTHORITY_VERIFIED"
    assert authority.attested_key_id == key.key_id
    assert authority.attested_registry_id == registry_short.registry_id
    assert (
        authority.attested_registry_content_sha256 == registry_short.content_sha256
    )


def test_r2_rejected_assessment_still_records_the_trust_root():
    key = _FixtureKey(revoked=True)
    statement, input_bytes = key.sign_input(_accept_input())
    verifier = SignedOwnerProvenanceVerifier(
        registry=_registry(key), statement=statement, decision_input_bytes=input_bytes
    )
    provenance = DecisionProvenanceV1(
        source_kind="LOCAL_UNSIGNED_JSON",
        source_revision="c3a-test",
        source_content_sha256=hashlib.sha256(input_bytes).hexdigest(),
    )
    assessment = verifier.verify_decision_authority(
        declared_owner_identity=OWNER_IDENTITY,
        provenance=provenance,
        decision_source_bytes=input_bytes,
    )
    assert assessment.authority_status == "OWNER_AUTHORITY_REJECTED"
    assert assessment.attested_key_id == key.key_id
    assert assessment.attested_registry_id == verifier.registry.registry_id
    assert (
        assessment.attested_registry_content_sha256
        == verifier.registry.content_sha256
    )


def _captured_record():
    """Capture one VERIFIED record under the short-window trust root.

    Returns the record, both registries, the statement and the signed bytes
    so callers can re-attest plans under either trust root.
    """

    key, registry_short, registry_long = _two_trust_roots()
    statement, input_bytes = key.sign_input(_accept_input())
    validation = validate_owner_decision(
        decision_input=_accept_input(),
        decision_source_bytes=input_bytes,
        base_profile_path=BASE_PROFILE_PATH,
        target_profile_path=TARGET_PROFILE_PATH,
        release_manifest_path=MANIFEST_PATH,
        policy_exceptions=[_policy_exception()],
        verifier=SignedOwnerProvenanceVerifier(
            registry=registry_short,
            statement=statement,
            decision_input_bytes=input_bytes,
        ),
    )
    assert validation.record is not None
    return validation.record, registry_short, registry_long, statement, input_bytes


def test_r2_plan_binds_the_fresh_reattestation_trust_root(tmp_path):
    record, registry_short, registry_long, statement, input_bytes = (
        _captured_record()
    )
    plan_short = _plan(
        tmp_path,
        records=[record],
        verifier=SignedOwnerProvenanceVerifier(
            registry=registry_short,
            statement=statement,
            decision_input_bytes=input_bytes,
        ),
    )
    plan_long = _plan(
        tmp_path,
        records=[record],
        verifier=SignedOwnerProvenanceVerifier(
            registry=registry_long,
            statement=statement,
            decision_input_bytes=input_bytes,
        ),
    )
    assert plan_short.plan_state == "READY_FOR_EXPLICIT_OWNER_EXECUTION"
    assert plan_long.plan_state == "READY_FOR_EXPLICIT_OWNER_EXECUTION"
    # The plan names the trust root that re-attested the authority...
    assert plan_short.authority_reverification_registry_id == (
        registry_short.registry_id
    )
    assert (
        plan_short.authority_reverification_registry_content_sha256
        == registry_short.content_sha256
    )
    assert (
        plan_long.authority_reverification_registry_content_sha256
        == registry_long.content_sha256
    )
    # ...so two different trust roots can never share one plan identity.
    assert plan_short.plan_id != plan_long.plan_id
    assert plan_short.content_sha256 != plan_long.content_sha256
    # The record itself was captured under registry_short; the plan under
    # registry_long binds registry_long — the fresh verifier is authoritative.
    assert record.authority.attested_registry_content_sha256 == (
        registry_short.content_sha256
    )


def test_r2_forged_record_attestation_claims_are_inert(tmp_path):
    record, registry_short, _registry_long, statement, input_bytes = (
        _captured_record()
    )
    foreign_hash = "ab" * 32
    dump = record.model_dump(mode="json")
    dump["authority"]["attested_registry_content_sha256"] = foreign_hash
    dump["authority"]["attested_registry_id"] = "owner-provenance-key-reg-forged"
    payload = {key: value for key, value in dump.items() if key != "content_sha256"}
    forged = OwnerPolicyDecisionRecordV1.model_validate(
        {**payload, "content_sha256": hashlib.sha256(canonical_json_bytes(payload)).hexdigest()}
    )
    assert forged.authority.attested_registry_content_sha256 == foreign_hash
    plan = _plan(
        tmp_path,
        records=[forged],
        verifier=SignedOwnerProvenanceVerifier(
            registry=registry_short,
            statement=statement,
            decision_input_bytes=input_bytes,
        ),
    )
    # The persisted claim never becomes the plan's trust-root binding.
    assert plan.authority_reverification_registry_content_sha256 == (
        registry_short.content_sha256
    )
    assert plan.authority_reverification_registry_id == registry_short.registry_id
    serialized = json.dumps(plan.model_dump(mode="json"))
    assert foreign_hash not in serialized
    assert "owner-provenance-key-reg-forged" not in serialized


def test_r2_plan_trust_root_fields_are_supplied_together_or_not_at_all(tmp_path):
    record, registry_short, _registry_long, statement, input_bytes = (
        _captured_record()
    )
    plan = _plan(
        tmp_path,
        records=[record],
        verifier=SignedOwnerProvenanceVerifier(
            registry=registry_short,
            statement=statement,
            decision_input_bytes=input_bytes,
        ),
    )
    schema = json.loads(
        (ROOT / "schemas" / "profile-activation-plan.schema.json").read_text(
            encoding="utf-8"
        )
    )
    props = schema["properties"]
    assert "authority_reverification_registry_id" in props
    assert "authority_reverification_registry_content_sha256" in props
    assert "authority_reverification_registry_id" not in schema["required"]
    # A half-bound trust root (id without content hash) is incoherent.
    dump = plan.model_dump(mode="json")
    dump["authority_reverification_registry_content_sha256"] = None
    with pytest.raises(Exception):
        ProfileActivationPlanV1.model_validate(dump)
    dump = plan.model_dump(mode="json")
    dump["authority_reverification_registry_id"] = None
    with pytest.raises(Exception):
        ProfileActivationPlanV1.model_validate(dump)
