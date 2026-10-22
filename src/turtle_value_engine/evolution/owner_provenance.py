"""Authenticated owner provenance: Ed25519-signed decision verification (Phase 7-C3-A).

This module provides the first real implementation of the Phase 7-C2
``OwnerDecisionVerifier`` trust-model interface.  It turns "who authored this
decision?" from a persisted self-consistent claim (which C2-R1 already
refuses to trust) into an offline cryptographic fact: the owner signs the
exact canonical bytes of one :class:`OwnerPolicyDecisionInputV1` with a
registered Ed25519 key, and verification proves the signature, the key, the
identity binding, the authorization scope, the validity window, the
non-revocation and the byte-exact content binding before any ``VERIFIED``
assessment can exist.

Trust model, made explicit:

* the **trust root** is an explicitly supplied
  :class:`OwnerProvenanceKeyRegistryV1` — an independent registry of public
  keys whose identities are derived only from the key material, never from
  the decision files it verifies.  Supplying a different registry is a
  visible operator action, not a silent substitution;
* the **signature** is a detached Ed25519 (RFC 8032) signature over the
  fixed domain prefix ``turtle-value-engine:owner-policy-decision:v1`` +
  NUL + the exact canonical decision-input bytes.  The domain prefix
  prevents reusing one purpose's signature for another; the decision input
  itself already binds both profile ids and byte hashes, the release
  manifest id/content hash, the fresh audit id/content hash, the exception
  id/content hash, the rationale, the owner identity and ``decided_at``, so
  a signature cannot be replayed across profiles, versions or decisions;
* an allowlist, an EnvironmentFile username, Git author text, CI success or
  a publication manifest is **not** a signature and never becomes one here.

What this boundary deliberately does *not* do: it constructs no provider,
model, transport or network client; it writes no rule profile, project
configuration or approval state; the production CLI constructs no verifier
and exposes no selector, flag or environment override (the class is a
library boundary for a hosting process, exactly like the C2 test fixtures —
except that a VERIFIED assessment now requires actual cryptography to pass);
key provisioning, evidence capture tooling, revocation workflow and record
integration are the separately selected C3-B package; and no activation
executor exists anywhere in this module.  ``execution_performed=false`` /
``automatic_activation_allowed=false`` remain fixed literals of the plan
contract this verifier feeds.

Expiry is deterministic, never wall-clock: a key's validity window is
compared against the signed decision's own ``decided_at`` date, so the same
evidence always verifies identically offline.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import date
from typing import ClassVar, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    model_validator,
)

from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.providers.normalization import deterministic_id

from .owner_decision import (
    DecisionProvenanceV1,
    OwnerAuthorityAssessmentV1,
    OwnerDecisionVerifier,
    OwnerPolicyDecisionInputV1,
    OwnerPolicyDecisionRecordV1,
)

HASH_PATTERN = r"^[0-9a-f]{64}$"
BASE64_PATTERN = r"^[A-Za-z0-9+/]+={0,2}$"
ISO_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

#: Fixed domain-separation literal: every signed message starts with this
#: purpose string so a signature produced for any other purpose, format or
#: contract version can never verify as an owner policy decision.
PROVENANCE_PURPOSE = "turtle-value-engine:owner-policy-decision:v1"

#: The only supported signature algorithm (RFC 8032 Ed25519, pure).
PROVENANCE_ALGORITHM = "ED25519"

#: The fixed reason code of a VERIFIED authority assessment produced by
#: :class:`SignedOwnerProvenanceVerifier` at record time and at plan-time
#: re-attestation.  Capture-consistency consumers reconcile persisted
#: records against exactly this value (R3).
ED25519_OWNER_PROVENANCE_VERIFIED_REASON = "ED25519_OWNER_PROVENANCE_VERIFIED"

#: Canonical check sequence of one provenance verification, in canonical
#: order.  The persisted dossier carries exactly these checks, and the
#: generated schema pins per-position names (Draft 2020-12 ``prefixItems``).
REQUIRED_PROVENANCE_CHECK_NAMES: tuple[str, ...] = (
    "ALGORITHM_SUPPORTED",
    "KEY_RESOLUTION",
    "KEY_IDENTITY_BINDING",
    "KEY_SCOPE_AUTHORIZED",
    "KEY_VALIDITY_WINDOW",
    "KEY_NOT_REVOKED",
    "DECISION_CONTENT_BINDING",
    "PURPOSE_BINDING",
    "SIGNATURE_VERIFIED",
)

#: The exact decision-content fields a signed decision input and the record
#: presented at plan time must agree on byte-for-byte semantic content.
_DECISION_CONTENT_FIELDS: tuple[str, ...] = (
    "decision",
    "base_profile_id",
    "base_profile_sha256",
    "target_profile_id",
    "target_profile_sha256",
    "release_manifest_id",
    "release_manifest_content_sha256",
    "audit_id",
    "audit_content_sha256",
    "exception_id",
    "exception_content_sha256",
    "rationale",
    "declared_owner_identity",
    "decided_at",
)


class OwnerProvenanceError(ValueError):
    """Raised when provenance inputs cannot be processed at all."""


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _decode_base64(value: str, *, length: int, label: str) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise OwnerProvenanceError(f"{label} is not valid base64") from exc
    if len(raw) != length:
        raise OwnerProvenanceError(
            f"{label} must decode to exactly {length} bytes (got {len(raw)})"
        )
    if base64.b64encode(raw).decode("ascii") != value:
        raise OwnerProvenanceError(f"{label} must use canonical base64 encoding")
    return raw


def owner_decision_input_signature_message(
    decision_input: OwnerPolicyDecisionInputV1,
) -> bytes:
    """The exact bytes an owner signs for one decision input.

    Deterministic canonical serialization prefixed with the fixed purpose
    domain separator; no timestamps, no machine-local data.  The owner's
    signing tool must sign exactly this message (the architecture document
    records a copy-paste example).
    """

    canonical = canonical_json_bytes(decision_input.model_dump(mode="json"))
    return PROVENANCE_PURPOSE.encode("utf-8") + b"\x00" + canonical


def _parse_canonical_decision_input(
    decision_input_bytes: bytes,
) -> OwnerPolicyDecisionInputV1 | None:
    """Parse decision-input bytes, accepting only the canonical byte form."""

    try:
        parsed = OwnerPolicyDecisionInputV1.model_validate(
            json.loads(decision_input_bytes)
        )
    except Exception:
        return None
    canonical = canonical_json_bytes(parsed.model_dump(mode="json"))
    if canonical != decision_input_bytes:
        return None
    return parsed


# ---------------------------------------------------------------------------
# Trust root: registered public keys
# ---------------------------------------------------------------------------


def owner_provenance_key_id(*, algorithm: str, public_key_base64: str) -> str:
    """Content-derived key identity: algorithm + key material only."""

    _decode_base64(public_key_base64, length=32, label="Ed25519 public key")
    return deterministic_id("owner-provenance-key", algorithm, public_key_base64)


class OwnerProvenanceKeyRecordV1(BaseModel):
    """One registered trusted Ed25519 public key with its authorization scope.

    The key identity is derived only from the key material — never from any
    decision file — so a registry entry cannot be forged by editing a
    decision.  ``valid_from``/``valid_until`` are owner-declared ISO dates
    compared against the signed decision's ``decided_at`` (deterministic;
    no wall-clock anywhere).  Revocation is an explicit record with a
    mandatory reference.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    key_id: StrictStr = Field(min_length=1, max_length=128)
    algorithm: Literal["ED25519"] = "ED25519"
    public_key_base64: StrictStr = Field(pattern=BASE64_PATTERN)
    owner_identity: StrictStr = Field(min_length=1, max_length=256)
    authorized_decisions: list[Literal["ACCEPT_WITH_EXCEPTION", "REJECT"]] = Field(
        min_length=1, max_length=2
    )
    valid_from: StrictStr = Field(pattern=ISO_DATE_PATTERN)
    valid_until: StrictStr = Field(pattern=ISO_DATE_PATTERN)
    revoked: StrictBool = False
    revocation_reference: StrictStr | None = Field(
        default=None, min_length=1, max_length=2_048
    )

    @model_validator(mode="after")
    def validate_key_record(self) -> Self:
        _decode_base64(
            self.public_key_base64, length=32, label="Ed25519 public key"
        )
        if self.key_id != owner_provenance_key_id(
            algorithm=self.algorithm, public_key_base64=self.public_key_base64
        ):
            raise ValueError(
                "key_id must be derived from the algorithm and public key "
                "material only"
            )
        if date.fromisoformat(self.valid_from) > date.fromisoformat(self.valid_until):
            raise ValueError("valid_from must not be after valid_until")
        if self.revoked and self.revocation_reference is None:
            raise ValueError("a revoked key must carry a revocation reference")
        if len(set(self.authorized_decisions)) != len(self.authorized_decisions):
            raise ValueError("authorized_decisions must not repeat")
        return self


class OwnerProvenanceKeyRegistryV1(BaseModel):
    """The independent trust root: an explicitly supplied key registry.

    Nothing here references the decision files it verifies; the registry is
    supplied by the hosting process/operator as its own trust decision.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["owner_provenance_key_registry_v1"] = (
        "owner_provenance_key_registry_v1"
    )
    schema_version: StrictStr = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    registry_id: StrictStr = Field(min_length=1, max_length=128)
    keys: list[OwnerProvenanceKeyRecordV1] = Field(min_length=1, max_length=64)
    content_sha256: StrictStr = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_registry(self) -> Self:
        key_ids = [item.key_id for item in self.keys]
        if len(set(key_ids)) != len(key_ids):
            raise ValueError("registry key ids must be unique")
        public_keys = [item.public_key_base64 for item in self.keys]
        if len(set(public_keys)) != len(public_keys):
            raise ValueError("registry public key material must be unique")
        expected_id = deterministic_id("owner-provenance-key-registry", *key_ids)
        if self.registry_id != expected_id:
            raise ValueError("registry_id disagrees with the registered keys")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected_content = _sha256_hex(canonical_json_bytes(payload))
        if self.content_sha256 != expected_content:
            raise ValueError("registry content_sha256 does not match content")
        return self


def build_owner_provenance_key_registry(
    keys: list[OwnerProvenanceKeyRecordV1],
) -> OwnerProvenanceKeyRegistryV1:
    """Assemble a registry from validated key records (id/hash derived)."""

    key_ids = [item.key_id for item in keys]
    payload = {
        "contract": "owner_provenance_key_registry_v1",
        "schema_version": "1.0.0",
        "registry_id": deterministic_id("owner-provenance-key-registry", *key_ids),
        "keys": [item.model_dump(mode="json") for item in keys],
    }
    return OwnerProvenanceKeyRegistryV1(
        **payload,
        content_sha256=_sha256_hex(canonical_json_bytes(payload)),
    )


# ---------------------------------------------------------------------------
# Signature evidence
# ---------------------------------------------------------------------------


class OwnerSignedDecisionStatementV1(BaseModel):
    """Immutable Ed25519 signature evidence over one decision input.

    ``decision_input_content_sha256`` binds the exact canonical
    decision-input bytes; ``signed_content_sha256`` binds the exact
    domain-separated message that was signed.  Both are recomputed and
    checked during verification — a statement is evidence, not authority.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["owner_signed_decision_statement_v1"] = (
        "owner_signed_decision_statement_v1"
    )
    schema_version: StrictStr = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    purpose: Literal[PROVENANCE_PURPOSE]
    algorithm: Literal["ED25519"] = "ED25519"
    key_id: StrictStr = Field(min_length=1, max_length=128)
    signature_base64: StrictStr = Field(pattern=BASE64_PATTERN)
    decision_input_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    signed_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    declared_owner_identity: StrictStr = Field(min_length=1, max_length=256)
    content_sha256: StrictStr = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_statement(self) -> Self:
        _decode_base64(self.signature_base64, length=64, label="Ed25519 signature")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected_content = _sha256_hex(canonical_json_bytes(payload))
        if self.content_sha256 != expected_content:
            raise ValueError("statement content_sha256 does not match content")
        return self


def build_owner_signed_decision_statement(
    *,
    signature: bytes,
    key_id: str,
    decision_input: OwnerPolicyDecisionInputV1,
) -> OwnerSignedDecisionStatementV1:
    """Assemble the evidence statement from a raw signature (id/hash derived).

    This helper is deterministic assembly, **not** signing: it never touches
    a private key.  The owner's signing tool produces ``signature`` outside
    this repository; tests produce it with throwaway fixture keys.
    """

    message = owner_decision_input_signature_message(decision_input)
    fields = {
        "purpose": PROVENANCE_PURPOSE,
        "algorithm": PROVENANCE_ALGORITHM,
        "key_id": key_id,
        "signature_base64": base64.b64encode(signature).decode("ascii"),
        "decision_input_content_sha256": _sha256_hex(
            canonical_json_bytes(decision_input.model_dump(mode="json"))
        ),
        "signed_content_sha256": _sha256_hex(message),
        "declared_owner_identity": decision_input.declared_owner_identity,
    }
    content = _sha256_hex(
        canonical_json_bytes(
            {
                "contract": "owner_signed_decision_statement_v1",
                "schema_version": "1.0.0",
                **fields,
            }
        )
    )
    return OwnerSignedDecisionStatementV1(**fields, content_sha256=content)


# ---------------------------------------------------------------------------
# Verification dossier
# ---------------------------------------------------------------------------


class OwnerProvenanceVerificationCheckV1(BaseModel):
    """One named verification check with its outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: StrictStr = Field(min_length=1, max_length=64)
    passed: StrictBool
    reason: StrictStr = Field(min_length=1, max_length=2_000)


def _provenance_sequence_schema_extra() -> dict:
    """Inline per-position name pin for the canonical check sequence.

    Kept inline (no external ``$ref``) because Draft 2020-12 resolution of
    ``json_schema_extra`` references is not available in this codebase's
    schema export path.
    """

    prefix_items = [
        {"type": "object", "properties": {"name": {"const": name}}, "required": ["name"]}
        for name in REQUIRED_PROVENANCE_CHECK_NAMES
    ]
    return {"prefixItems": prefix_items, "items": False}


class OwnerProvenanceVerificationV1(BaseModel):
    """The deterministic result dossier of one signature verification.

    ``VERIFIED`` requires every canonical check to pass; any failure keeps
    the dossier ``REJECTED`` naming the failing checks.  The dossier binds
    the registry by id **and** exact ``content_sha256`` (``registry_id`` is
    derived from key ids only and is not a trust-content identity: the same
    key set re-windowed, re-scoped, revoked or un-revoked keeps the id while
    changing the content), plus the key, statement and decision-content
    identities, carries no wall-clock field, and is reproducible
    byte-for-byte offline.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["owner_provenance_verification_v1"] = (
        "owner_provenance_verification_v1"
    )
    schema_version: StrictStr = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    verification_id: StrictStr = Field(min_length=1, max_length=128)
    registry_id: StrictStr = Field(min_length=1, max_length=128)
    registry_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    key_id: StrictStr | None = Field(default=None, min_length=1, max_length=128)
    algorithm: Literal["ED25519"] = "ED25519"
    verification_status: Literal["VERIFIED", "REJECTED"]
    revocation_status: Literal["NOT_REVOKED", "REVOKED", "UNKNOWN"]
    key_validity: Literal["WITHIN_WINDOW", "OUTSIDE_WINDOW", "UNKNOWN"]
    decision_input_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    evidence_content_sha256: StrictStr | None = Field(
        default=None, pattern=HASH_PATTERN
    )
    reason_code: StrictStr = Field(min_length=1, max_length=128)
    detail: StrictStr = Field(min_length=1, max_length=2_000)
    checks: list[OwnerProvenanceVerificationCheckV1] = Field(
        min_length=len(REQUIRED_PROVENANCE_CHECK_NAMES),
        max_length=len(REQUIRED_PROVENANCE_CHECK_NAMES),
        json_schema_extra=_provenance_sequence_schema_extra(),
    )
    content_sha256: StrictStr = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_dossier(self) -> Self:
        names = tuple(check.name for check in self.checks)
        if names != REQUIRED_PROVENANCE_CHECK_NAMES:
            raise ValueError(
                "verification checks must contain exactly the canonical "
                "required check sequence in canonical order (expected "
                f"{len(REQUIRED_PROVENANCE_CHECK_NAMES)} checks)"
            )
        failed = [check.name for check in self.checks if not check.passed]
        if self.verification_status == "VERIFIED":
            if failed:
                raise ValueError("VERIFIED requires every check to pass")
            if self.key_id is None:
                raise ValueError("VERIFIED names the verified key")
        else:
            if not failed:
                raise ValueError("REJECTED requires at least one failed check")
        expected_id = deterministic_id(
            "owner-provenance-verification",
            self.registry_id,
            self.registry_content_sha256,
            self.key_id or "",
            self.decision_input_content_sha256,
            self.verification_status,
            *[f"{check.name}:{int(check.passed)}" for check in self.checks],
        )
        if self.verification_id != expected_id:
            raise ValueError("verification_id disagrees with the bound content")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected_content = _sha256_hex(canonical_json_bytes(payload))
        if self.content_sha256 != expected_content:
            raise ValueError("verification content_sha256 does not match content")
        return self


# ---------------------------------------------------------------------------
# Pure offline verification
# ---------------------------------------------------------------------------


def _ed25519_verify(public_key_bytes: bytes, signature: bytes, message: bytes) -> bool:
    """Ed25519 verify with a lazy, fail-closed cryptography import."""

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
    except ImportError as exc:  # pragma: no cover - exercised via injection
        raise OwnerProvenanceError(
            "the optional 'cryptography' package is required for Ed25519 "
            "provenance verification (install the [provenance] extra)"
        ) from exc
    try:
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(signature, message)
    except Exception:
        return False
    return True


def verify_owner_provenance(
    *,
    decision_input_bytes: bytes,
    statement: OwnerSignedDecisionStatementV1,
    registry: OwnerProvenanceKeyRegistryV1,
    declared_owner_identity: str | None = None,
) -> OwnerProvenanceVerificationV1:
    """Verify one signed decision statement against one trusted registry.

    Pure, offline and deterministic: no clock, no network, no filesystem
    beyond the supplied objects.  Every canonical check is evaluated and
    recorded; ``VERIFIED`` requires all of them to pass.
    """

    outcomes: list[tuple[str, bool, str]] = []

    algorithm_ok = statement.algorithm == PROVENANCE_ALGORITHM
    outcomes.append(
        (
            "ALGORITHM_SUPPORTED",
            algorithm_ok,
            f"signature algorithm is {statement.algorithm!r}",
        )
    )

    key = next((item for item in registry.keys if item.key_id == statement.key_id), None)
    key_resolved = key is not None
    outcomes.append(
        (
            "KEY_RESOLUTION",
            key_resolved,
            (
                f"key {statement.key_id!r} resolved in registry "
                f"{registry.registry_id!r}"
                if key_resolved
                else f"key {statement.key_id!r} is not registered in registry "
                f"{registry.registry_id!r}"
            ),
        )
    )

    parsed_input = _parse_canonical_decision_input(decision_input_bytes)

    identity_ok = (
        key is not None
        and parsed_input is not None
        and key.owner_identity == statement.declared_owner_identity
        and parsed_input.declared_owner_identity == statement.declared_owner_identity
        and (
            declared_owner_identity is None
            or declared_owner_identity == statement.declared_owner_identity
        )
    )
    if not key_resolved:
        identity_reason = "key unresolved; identity binding cannot be proven"
    elif parsed_input is None:
        identity_reason = "decision input unusable; identity binding cannot be proven"
    elif key.owner_identity != statement.declared_owner_identity:
        identity_reason = (
            f"key is bound to owner identity {key.owner_identity!r}, statement "
            f"declares {statement.declared_owner_identity!r}"
        )
    else:
        identity_reason = (
            f"key, statement and decision input all bind owner identity "
            f"{statement.declared_owner_identity!r}"
        )
    outcomes.append(("KEY_IDENTITY_BINDING", identity_ok, identity_reason))

    scope_ok = (
        key is not None
        and parsed_input is not None
        and parsed_input.decision in key.authorized_decisions
    )
    outcomes.append(
        (
            "KEY_SCOPE_AUTHORIZED",
            scope_ok,
            (
                f"decision {parsed_input.decision!r} is within the key's "
                "authorized scope"
                if scope_ok
                else "the signing key is not authorized for this decision value"
            ),
        )
    )

    decided_at = parsed_input.decided_at if parsed_input is not None else None
    window_state: str = "UNKNOWN"
    if key is not None and decided_at is not None and re.fullmatch(
        ISO_DATE_PATTERN, decided_at
    ):
        try:
            signing_date = date.fromisoformat(decided_at)
            start_date = date.fromisoformat(key.valid_from)
            end_date = date.fromisoformat(key.valid_until)
        except ValueError:
            pass  # An impossible calendar date must fail closed as UNKNOWN.
        else:
            window_state = (
                "WITHIN_WINDOW"
                if start_date <= signing_date <= end_date
                else "OUTSIDE_WINDOW"
            )
    window_ok = window_state == "WITHIN_WINDOW"
    outcomes.append(
        (
            "KEY_VALIDITY_WINDOW",
            window_ok,
            (
                f"decision date {decided_at!r} is within the key validity window "
                f"[{key.valid_from}, {key.valid_until}]"
                if window_ok
                else f"key validity window is not proven to cover the decision "
                f"date (window state {window_state!r})"
            ),
        )
    )

    not_revoked = key is not None and not key.revoked
    outcomes.append(
        (
            "KEY_NOT_REVOKED",
            not_revoked,
            (
                "signing key is not revoked in the trusted registry"
                if not_revoked
                else "the signing key is revoked"
                if key is not None and key.revoked
                else "key unresolved; non-revocation cannot be proven"
            ),
        )
    )

    content_ok = (
        parsed_input is not None
        and _sha256_hex(decision_input_bytes) == statement.decision_input_content_sha256
    )
    outcomes.append(
        (
            "DECISION_CONTENT_BINDING",
            content_ok,
            (
                "statement binds the exact canonical decision-input bytes "
                f"({statement.decision_input_content_sha256})"
                if content_ok
                else "supplied bytes are not the canonical decision input the "
                "statement binds"
            ),
        )
    )

    purpose_ok = statement.purpose == PROVENANCE_PURPOSE
    outcomes.append(
        (
            "PURPOSE_BINDING",
            purpose_ok,
            (
                "signature purpose is the fixed owner-policy-decision domain"
                if purpose_ok
                else f"signature purpose {statement.purpose!r} is not the "
                f"owner-policy-decision domain"
            ),
        )
    )

    message = PROVENANCE_PURPOSE.encode("utf-8") + b"\x00" + decision_input_bytes
    signature_ok = (
        algorithm_ok
        and key_resolved
        and purpose_ok
        and parsed_input is not None
        and _sha256_hex(message) == statement.signed_content_sha256
        and _ed25519_verify(
            base64.b64decode(key.public_key_base64, validate=True),
            base64.b64decode(statement.signature_base64, validate=True),
            message,
        )
    )
    outcomes.append(
        (
            "SIGNATURE_VERIFIED",
            signature_ok,
            (
                "Ed25519 signature verifies over the exact domain-separated "
                "decision-input message"
                if signature_ok
                else "Ed25519 signature does not verify over the exact "
                "domain-separated decision-input message"
            ),
        )
    )

    assert len(outcomes) == len(REQUIRED_PROVENANCE_CHECK_NAMES)
    checks = [
        OwnerProvenanceVerificationCheckV1(name=name, passed=passed, reason=reason)
        for name, passed, reason in outcomes
    ]
    failed = [check.name for check in checks if not check.passed]
    status = "VERIFIED" if not failed else "REJECTED"
    reason_code = "ALL_PROVENANCE_CHECKS_PASSED" if not failed else failed[0]
    detail = (
        "Every canonical provenance check passed for the exact bound decision "
        "content; this dossier is cryptographic verification evidence, never "
        "an activation."
        if not failed
        else "Provenance verification failed closed; the failing canonical "
        f"checks are: {', '.join(failed)}."
    )
    verification_id = deterministic_id(
        "owner-provenance-verification",
        registry.registry_id,
        registry.content_sha256,
        statement.key_id if key_resolved else "",
        statement.decision_input_content_sha256,
        status,
        *[f"{check.name}:{int(check.passed)}" for check in checks],
    )
    payload = {
        "contract": "owner_provenance_verification_v1",
        "schema_version": "1.0.0",
        "algorithm": PROVENANCE_ALGORITHM,
        "registry_id": registry.registry_id,
        "registry_content_sha256": registry.content_sha256,
        "key_id": statement.key_id if key_resolved else None,
        "verification_status": status,
        "revocation_status": (
            "NOT_REVOKED"
            if not_revoked
            else "REVOKED"
            if key is not None and key.revoked
            else "UNKNOWN"
        ),
        "key_validity": window_state,
        "decision_input_content_sha256": statement.decision_input_content_sha256,
        "evidence_content_sha256": None,
        "reason_code": reason_code,
        "detail": detail,
        "checks": [check.model_dump(mode="json") for check in checks],
        "verification_id": verification_id,
    }
    return OwnerProvenanceVerificationV1(
        **payload,
        content_sha256=_sha256_hex(canonical_json_bytes(payload)),
    )


# ---------------------------------------------------------------------------
# The real OwnerDecisionVerifier implementation (library-only)
# ---------------------------------------------------------------------------


class SignedOwnerProvenanceVerifier(OwnerDecisionVerifier):
    """A real verifier: Ed25519 owner provenance against a trusted registry.

    Constructed by a hosting process with three explicit inputs — the
    trusted key registry (independent trust root), the signature statement
    and the exact signed decision-input bytes.  The production CLI
    constructs none of these; there is no flag, environment variable or
    file convention that silently selects this class.
    """

    kind: ClassVar[str] = "ed25519-signed-owner-provenance"

    def __init__(
        self,
        *,
        registry: OwnerProvenanceKeyRegistryV1,
        statement: OwnerSignedDecisionStatementV1,
        decision_input_bytes: bytes,
    ) -> None:
        if not isinstance(registry, OwnerProvenanceKeyRegistryV1):
            raise OwnerProvenanceError("registry must be an OwnerProvenanceKeyRegistryV1")
        if not isinstance(statement, OwnerSignedDecisionStatementV1):
            raise OwnerProvenanceError(
                "statement must be an OwnerSignedDecisionStatementV1"
            )
        if not isinstance(decision_input_bytes, (bytes, bytearray)):
            raise OwnerProvenanceError("decision_input_bytes must be bytes")
        self._registry = registry
        self._statement = statement
        self._decision_input_bytes = bytes(decision_input_bytes)

    @property
    def registry(self) -> OwnerProvenanceKeyRegistryV1:
        return self._registry  # type: ignore[no-any-return]

    @property
    def statement(self) -> OwnerSignedDecisionStatementV1:
        return self._statement  # type: ignore[no-any-return]

    @property
    def decision_input_bytes(self) -> bytes:
        return self._decision_input_bytes  # type: ignore[no-any-return]

    def verify_decision_authority(
        self,
        *,
        declared_owner_identity: str,
        provenance: DecisionProvenanceV1,
        decision_source_bytes: bytes,
    ) -> OwnerAuthorityAssessmentV1:
        signed_bytes = self._decision_input_bytes
        signed_hash = _sha256_hex(signed_bytes)

        # The C2 boundary calls this interface at two deterministic points,
        # distinguished by the *contract* of the presented bytes (never by
        # heuristic): record time passes the submitted decision-input bytes,
        # plan time (C2-R1 reverification) passes the canonical record bytes.
        record = None
        try:
            record = OwnerPolicyDecisionRecordV1.model_validate(
                json.loads(decision_source_bytes)
            )
        except Exception:
            record = None

        verification = verify_owner_provenance(
            decision_input_bytes=signed_bytes,
            statement=self._statement,
            registry=self._registry,
            declared_owner_identity=declared_owner_identity,
        )
        identity_passed = next(
            check.passed
            for check in verification.checks
            if check.name == "KEY_IDENTITY_BINDING"
        )

        if record is None:
            # Record-time capture: the presented bytes must be the exact
            # signed submission; provenance kind is bookkeeping, the content
            # hash is the binding (C2: provenance is bookkeeping, never
            # authentication).
            if _sha256_hex(decision_source_bytes) != signed_hash:
                return self._rejected(
                    verification=verification,
                    identity_passed=identity_passed,
                    decision_source_bytes=decision_source_bytes,
                    reason_code="OWNER_PROVENANCE_SOURCE_BYTES_MISMATCH",
                    detail=(
                        "the submitted decision bytes are not the exact signed "
                        "submission this verifier was constructed with"
                    ),
                )
            if verification.verification_status == "VERIFIED":
                return OwnerAuthorityAssessmentV1(
                    authority_status="OWNER_AUTHORITY_VERIFIED",
                    verification_method="INJECTED_VERIFIER",
                    verifier_kind=self.kind,
                    allowlist_matched=True,
                    reason_code=ED25519_OWNER_PROVENANCE_VERIFIED_REASON,
                    detail=(
                        "Ed25519 signature by registered key "
                        f"{verification.key_id!r} verified over the exact "
                        "submitted decision-input bytes."
                    ),
                    evidence_content_sha256=_sha256_hex(decision_source_bytes),
                    attested_key_id=verification.key_id,
                    attested_registry_id=self._registry.registry_id,
                    attested_registry_content_sha256=self._registry.content_sha256,
                )
            return self._rejected(
                verification=verification,
                identity_passed=identity_passed,
                decision_source_bytes=decision_source_bytes,
                reason_code=f"OWNER_PROVENANCE_{verification.reason_code}",
                detail=verification.detail,
            )

        # Plan-time re-attestation: the presented record must be *about* the
        # signed submission — its provenance binds the source content hash —
        # and must *embed* the signed submission's exact decision content: a
        # record that swaps an ACCEPT for a signed REJECT (or any binding,
        # rationale or date edit) is rejected here.
        parsed_input = _parse_canonical_decision_input(signed_bytes)
        record_mismatches: list[str] = []
        if parsed_input is None:
            record_mismatches.append("SIGNED_INPUT_UNUSABLE")
        else:
            input_dump = parsed_input.model_dump(mode="json")
            record_dump = record.model_dump(mode="json")
            record_mismatches = [
                field
                for field in _DECISION_CONTENT_FIELDS
                if input_dump.get(field) != record_dump.get(field)
            ]
        provenance_bound = provenance.source_content_sha256 == signed_hash
        if parsed_input is not None and (
            provenance.source_revision != parsed_input.source_revision
            or record.provenance.source_revision != parsed_input.source_revision
        ):
            record_mismatches.append("source_revision")
        # Supersession is not part of the signed decision-input contract.
        # A valid signature alone cannot authorize replacing an older record.
        unsigned_supersession = record.supersedes_decision_record_id is not None
        record_binding_ok = (
            provenance_bound and not record_mismatches and not unsigned_supersession
        )

        if verification.verification_status == "VERIFIED" and record_binding_ok:
            return OwnerAuthorityAssessmentV1(
                authority_status="OWNER_AUTHORITY_VERIFIED",
                verification_method="INJECTED_VERIFIER",
                verifier_kind=self.kind,
                allowlist_matched=True,
                reason_code=ED25519_OWNER_PROVENANCE_VERIFIED_REASON,
                detail=(
                    "Ed25519 signature by registered key "
                    f"{verification.key_id!r} verified over the exact canonical "
                    "decision-input bytes; record provenance and embedded "
                    "decision content bind the same submission."
                ),
                evidence_content_sha256=_sha256_hex(decision_source_bytes),
                attested_key_id=verification.key_id,
                attested_registry_id=self._registry.registry_id,
                attested_registry_content_sha256=self._registry.content_sha256,
            )
        if not record_binding_ok:
            if unsigned_supersession:
                reason_code = "OWNER_PROVENANCE_UNSIGNED_SUPERSESSION"
                detail = (
                    "record supersession is not covered by the signed "
                    "decision-input contract and cannot be authenticated"
                )
            elif record_mismatches:
                reason_code = "OWNER_PROVENANCE_RECORD_INPUT_BINDING_MISMATCH"
                detail = (
                    "the presented record does not embed the signed "
                    "submission's decision content (mismatched: "
                    f"{', '.join(record_mismatches)})"
                )
            else:
                reason_code = "OWNER_PROVENANCE_PROVENANCE_HASH_MISMATCH"
                detail = (
                    "record provenance does not bind the signed submission "
                    "bytes"
                )
        else:
            reason_code = f"OWNER_PROVENANCE_{verification.reason_code}"
            detail = verification.detail
        return self._rejected(
            verification=verification,
            identity_passed=identity_passed,
            decision_source_bytes=decision_source_bytes,
            reason_code=reason_code,
            detail=detail,
        )

    def _rejected(
        self,
        *,
        verification: OwnerProvenanceVerificationV1,
        identity_passed: bool,
        decision_source_bytes: bytes,
        reason_code: str,
        detail: str,
    ) -> OwnerAuthorityAssessmentV1:
        return OwnerAuthorityAssessmentV1(
            authority_status="OWNER_AUTHORITY_REJECTED",
            verification_method="INJECTED_VERIFIER",
            verifier_kind=SignedOwnerProvenanceVerifier.kind,
            allowlist_matched=identity_passed,
            reason_code=reason_code,
            detail=detail,
            evidence_content_sha256=_sha256_hex(decision_source_bytes),
            attested_key_id=verification.key_id,
            attested_registry_id=self._registry.registry_id,
            attested_registry_content_sha256=self._registry.content_sha256,
        )


__all__ = [
    "ED25519_OWNER_PROVENANCE_VERIFIED_REASON",
    "PROVENANCE_ALGORITHM",
    "PROVENANCE_PURPOSE",
    "REQUIRED_PROVENANCE_CHECK_NAMES",
    "OwnerProvenanceError",
    "OwnerProvenanceKeyRecordV1",
    "OwnerProvenanceKeyRegistryV1",
    "OwnerProvenanceVerificationCheckV1",
    "OwnerProvenanceVerificationV1",
    "OwnerSignedDecisionStatementV1",
    "SignedOwnerProvenanceVerifier",
    "build_owner_provenance_key_registry",
    "build_owner_signed_decision_statement",
    "owner_decision_input_signature_message",
    "owner_provenance_key_id",
    "verify_owner_provenance",
]
