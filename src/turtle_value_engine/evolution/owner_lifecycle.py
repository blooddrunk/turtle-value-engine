"""Authenticated decision lifecycle: signed revocation and supersession (Phase 7-C3-B).

Phase 7-C3-A-R1 established that unsigned revocation and supersession
metadata can never change effective authorization: the signature covers the
decision input only, so replacement metadata fails closed everywhere.  This
module adds the narrowly versioned *signed* protocols for exactly those two
lifecycle operations, parallel to the C3-A decision statement:

* **Revocation** — domain ``turtle-value-engine:owner-decision-revocation:v1``
  over one :class:`OwnerRevocationPayloadV1` binding the exact revoked
  record id AND content SHA-256, the target profile binding, the revoking
  owner identity, ``revoked_at``, a rationale and the source revision.
* **Supersession** — domain ``turtle-value-engine:owner-decision-supersession:v1``
  over one :class:`OwnerSupersessionPayloadV1` binding BOTH the superseded
  and the superseding record by exact id and content SHA-256 plus their
  shared target binding.

Verification is pure, offline and deterministic — the same trust root
(:class:`OwnerProvenanceKeyRegistryV1`), the same Ed25519 detached-signature
machinery and the same canonical-bytes anti-malleability rule as C3-A, with
its own pinned canonical check sequence per lifecycle kind.  A key may sign
lifecycle statements when it is enrolled in the trust root, bound to the
declared owner identity, inside its validity window (compared against the
statement's own ``revoked_at``/``superseded_at`` date, never a wall clock)
and not revoked; the key's decision-value scope (``authorized_decisions``)
governs which *decisions* a key may make, not lifecycle withdrawal, which
can only ever reduce or restate authorization.

Production code never signs and never holds private key material.  The
verified statement feeds the resolver/plan boundary only through the
content-bound carriers in :mod:`turtle_value_engine.evolution.owner_decision`
(``AuthenticatedRevocationBindingV1`` /
``AuthenticatedSupersessionBindingV1``), and the plan boundary re-verifies
every statement freshly against the supplied trust root before any
authenticated removal may shape an activation plan.
"""

from __future__ import annotations

import base64
import hashlib
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
    AuthenticatedRevocationBindingV1,
    AuthenticatedSupersessionBindingV1,
)
from .owner_provenance import (
    BASE64_PATTERN,
    HASH_PATTERN,
    ISO_DATE_PATTERN,
    PROVENANCE_ALGORITHM,
    OwnerProvenanceKeyRegistryV1,
    _decode_base64,
    _ed25519_verify,
)

#: Domain-separated purpose literals.  A signature produced for any other
#: purpose (including an owner policy decision) can never verify here.
LIFECYCLE_REVOCATION_PURPOSE = "turtle-value-engine:owner-decision-revocation:v1"
LIFECYCLE_SUPERSESSION_PURPOSE = "turtle-value-engine:owner-decision-supersession:v1"

#: Canonical check sequences of the lifecycle verification dossiers, in
#: canonical order.  The persisted dossiers carry exactly these checks and
#: the generated schemas pin the per-position names (Draft 2020-12
#: ``prefixItems`` with ``items: false``).
REQUIRED_REVOCATION_CHECK_NAMES: tuple[str, ...] = (
    "ALGORITHM_SUPPORTED",
    "KEY_RESOLUTION",
    "KEY_IDENTITY_BINDING",
    "KEY_VALIDITY_WINDOW",
    "KEY_NOT_REVOKED",
    "PAYLOAD_CONTENT_BINDING",
    "PURPOSE_BINDING",
    "SIGNATURE_VERIFIED",
)
REQUIRED_SUPERSESSION_CHECK_NAMES: tuple[str, ...] = REQUIRED_REVOCATION_CHECK_NAMES


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Revocation protocol
# ---------------------------------------------------------------------------


class OwnerRevocationPayloadV1(BaseModel):
    """The canonical bytes an owner signs to withdraw one recorded decision.

    Binds the exact revoked record by id AND full content SHA-256 plus the
    target profile binding, so the authenticated withdrawal cannot be
    replayed against a different or tampered record.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["owner_signed_revocation_payload_v1"] = (
        "owner_signed_revocation_payload_v1"
    )
    revoked_decision_record_id: StrictStr = Field(min_length=1, max_length=128)
    revoked_record_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    target_profile_id: StrictStr = Field(min_length=1)
    target_profile_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    revoked_by: StrictStr = Field(min_length=1, max_length=256)
    revoked_at: StrictStr = Field(min_length=10, max_length=32)
    rationale: StrictStr = Field(min_length=20, max_length=4_000)
    source_revision: StrictStr = Field(min_length=1, max_length=256)


class OwnerSignedRevocationStatementV1(BaseModel):
    """Immutable Ed25519 signature evidence over one revocation payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["owner_signed_revocation_statement_v1"] = (
        "owner_signed_revocation_statement_v1"
    )
    schema_version: StrictStr = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    purpose: Literal[LIFECYCLE_REVOCATION_PURPOSE]
    algorithm: Literal["ED25519"] = "ED25519"
    key_id: StrictStr = Field(min_length=1, max_length=128)
    signature_base64: StrictStr = Field(pattern=BASE64_PATTERN)
    payload_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
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


def owner_revocation_signature_message(payload: OwnerRevocationPayloadV1) -> bytes:
    """The exact bytes an owner signs for one revocation payload."""

    canonical = canonical_json_bytes(payload.model_dump(mode="json"))
    return LIFECYCLE_REVOCATION_PURPOSE.encode("utf-8") + b"\x00" + canonical


def build_owner_signed_revocation_statement(
    *,
    signature: bytes,
    key_id: str,
    payload: OwnerRevocationPayloadV1,
) -> OwnerSignedRevocationStatementV1:
    """Assemble the evidence statement from a raw signature (id/hash derived).

    Deterministic assembly, **not** signing: it never touches a private key.
    """

    message = owner_revocation_signature_message(payload)
    fields = {
        "purpose": LIFECYCLE_REVOCATION_PURPOSE,
        "algorithm": PROVENANCE_ALGORITHM,
        "key_id": key_id,
        "signature_base64": base64.b64encode(signature).decode("ascii"),
        "payload_content_sha256": _sha256_hex(
            canonical_json_bytes(payload.model_dump(mode="json"))
        ),
        "signed_content_sha256": _sha256_hex(message),
        "declared_owner_identity": payload.revoked_by,
    }
    content = _sha256_hex(
        canonical_json_bytes(
            {
                "contract": "owner_signed_revocation_statement_v1",
                "schema_version": "1.0.0",
                **fields,
            }
        )
    )
    return OwnerSignedRevocationStatementV1(**fields, content_sha256=content)


class OwnerSignedRevocationEvidenceV1(BaseModel):
    """Payload plus statement as one verifiable unit (submission contract)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["owner_signed_revocation_evidence_v1"] = (
        "owner_signed_revocation_evidence_v1"
    )
    payload: OwnerRevocationPayloadV1
    statement: OwnerSignedRevocationStatementV1

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        canonical = _sha256_hex(
            canonical_json_bytes(self.payload.model_dump(mode="json"))
        )
        if self.statement.payload_content_sha256 != canonical:
            raise ValueError(
                "the statement does not bind this payload's canonical bytes"
            )
        if self.statement.declared_owner_identity != self.payload.revoked_by:
            raise ValueError(
                "the statement and payload declare different owner identities"
            )
        return self


# ---------------------------------------------------------------------------
# Supersession protocol
# ---------------------------------------------------------------------------


class OwnerSupersessionPayloadV1(BaseModel):
    """The canonical bytes an owner signs to replace one recorded decision.

    Binds BOTH the superseded and the superseding record by exact id and
    full content SHA-256 plus their shared target binding, so the
    authenticated replacement cannot be redirected onto other records.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["owner_signed_supersession_payload_v1"] = (
        "owner_signed_supersession_payload_v1"
    )
    superseded_decision_record_id: StrictStr = Field(min_length=1, max_length=128)
    superseded_record_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    superseding_decision_record_id: StrictStr = Field(min_length=1, max_length=128)
    superseding_record_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    target_profile_id: StrictStr = Field(min_length=1)
    target_profile_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    superseded_by: StrictStr = Field(min_length=1, max_length=256)
    superseded_at: StrictStr = Field(min_length=10, max_length=32)
    rationale: StrictStr = Field(min_length=20, max_length=4_000)
    source_revision: StrictStr = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_payload(self) -> Self:
        if (
            self.superseded_decision_record_id
            == self.superseding_decision_record_id
        ):
            raise ValueError("a record cannot supersede itself")
        return self


class OwnerSignedSupersessionStatementV1(BaseModel):
    """Immutable Ed25519 signature evidence over one supersession payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["owner_signed_supersession_statement_v1"] = (
        "owner_signed_supersession_statement_v1"
    )
    schema_version: StrictStr = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    purpose: Literal[LIFECYCLE_SUPERSESSION_PURPOSE]
    algorithm: Literal["ED25519"] = "ED25519"
    key_id: StrictStr = Field(min_length=1, max_length=128)
    signature_base64: StrictStr = Field(pattern=BASE64_PATTERN)
    payload_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
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


def owner_supersession_signature_message(payload: OwnerSupersessionPayloadV1) -> bytes:
    """The exact bytes an owner signs for one supersession payload."""

    canonical = canonical_json_bytes(payload.model_dump(mode="json"))
    return LIFECYCLE_SUPERSESSION_PURPOSE.encode("utf-8") + b"\x00" + canonical


def build_owner_signed_supersession_statement(
    *,
    signature: bytes,
    key_id: str,
    payload: OwnerSupersessionPayloadV1,
) -> OwnerSignedSupersessionStatementV1:
    """Assemble the evidence statement from a raw signature (id/hash derived)."""

    message = owner_supersession_signature_message(payload)
    fields = {
        "purpose": LIFECYCLE_SUPERSESSION_PURPOSE,
        "algorithm": PROVENANCE_ALGORITHM,
        "key_id": key_id,
        "signature_base64": base64.b64encode(signature).decode("ascii"),
        "payload_content_sha256": _sha256_hex(
            canonical_json_bytes(payload.model_dump(mode="json"))
        ),
        "signed_content_sha256": _sha256_hex(message),
        "declared_owner_identity": payload.superseded_by,
    }
    content = _sha256_hex(
        canonical_json_bytes(
            {
                "contract": "owner_signed_supersession_statement_v1",
                "schema_version": "1.0.0",
                **fields,
            }
        )
    )
    return OwnerSignedSupersessionStatementV1(**fields, content_sha256=content)


class OwnerSignedSupersessionEvidenceV1(BaseModel):
    """Payload plus statement as one verifiable unit (submission contract)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["owner_signed_supersession_evidence_v1"] = (
        "owner_signed_supersession_evidence_v1"
    )
    payload: OwnerSupersessionPayloadV1
    statement: OwnerSignedSupersessionStatementV1

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        canonical = _sha256_hex(
            canonical_json_bytes(self.payload.model_dump(mode="json"))
        )
        if self.statement.payload_content_sha256 != canonical:
            raise ValueError(
                "the statement does not bind this payload's canonical bytes"
            )
        if self.statement.declared_owner_identity != self.payload.superseded_by:
            raise ValueError(
                "the statement and payload declare different owner identities"
            )
        return self


# ---------------------------------------------------------------------------
# Verification dossiers
# ---------------------------------------------------------------------------


class LifecycleVerificationCheckV1(BaseModel):
    """One named lifecycle verification check with its outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: StrictStr = Field(min_length=1, max_length=64)
    passed: StrictBool
    reason: StrictStr = Field(min_length=1, max_length=2_000)


def _lifecycle_sequence_schema_extra(required: tuple[str, ...]) -> dict:
    """Inline per-position name pin for the canonical check sequence."""

    prefix_items = [
        {"type": "object", "properties": {"name": {"const": name}}, "required": ["name"]}
        for name in required
    ]
    return {"prefixItems": prefix_items, "items": False}


class OwnerRevocationVerificationV1(BaseModel):
    """The deterministic dossier of one signed-revocation verification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["owner_revocation_verification_v1"] = (
        "owner_revocation_verification_v1"
    )
    schema_version: StrictStr = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    verification_id: StrictStr = Field(min_length=1, max_length=128)
    purpose: Literal[LIFECYCLE_REVOCATION_PURPOSE]
    registry_id: StrictStr = Field(min_length=1, max_length=128)
    registry_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    key_id: StrictStr | None = Field(default=None, min_length=1, max_length=128)
    algorithm: Literal["ED25519"] = "ED25519"
    verification_status: Literal["VERIFIED", "REJECTED"]
    key_validity: Literal["WITHIN_WINDOW", "OUTSIDE_WINDOW", "UNKNOWN"]
    revoked_record_id: StrictStr = Field(min_length=1, max_length=128)
    payload_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    reason_code: StrictStr = Field(min_length=1, max_length=128)
    detail: StrictStr = Field(min_length=1, max_length=2_000)
    checks: list[LifecycleVerificationCheckV1] = Field(
        min_length=len(REQUIRED_REVOCATION_CHECK_NAMES),
        max_length=len(REQUIRED_REVOCATION_CHECK_NAMES),
        json_schema_extra=_lifecycle_sequence_schema_extra(
            REQUIRED_REVOCATION_CHECK_NAMES
        ),
    )
    content_sha256: StrictStr = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_dossier(self) -> Self:
        names = tuple(check.name for check in self.checks)
        if names != REQUIRED_REVOCATION_CHECK_NAMES:
            raise ValueError(
                "verification checks must contain exactly the canonical "
                "required check sequence in canonical order (expected "
                f"{len(REQUIRED_REVOCATION_CHECK_NAMES)} checks)"
            )
        failed = [check.name for check in self.checks if not check.passed]
        if self.verification_status == "VERIFIED":
            if failed:
                raise ValueError("VERIFIED requires every check to pass")
            if self.key_id is None:
                raise ValueError("VERIFIED names the verified key")
        elif not failed:
            raise ValueError("REJECTED requires at least one failed check")
        expected_id = deterministic_id(
            "owner-revocation-verification",
            self.registry_id,
            self.registry_content_sha256,
            self.key_id or "",
            self.revoked_record_id,
            self.payload_content_sha256,
            self.verification_status,
            *[f"{check.name}:{int(check.passed)}" for check in self.checks],
        )
        if self.verification_id != expected_id:
            raise ValueError("verification id disagrees with the bound content")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected_content = _sha256_hex(canonical_json_bytes(payload))
        if self.content_sha256 != expected_content:
            raise ValueError("verification content_sha256 does not match content")
        return self


class OwnerSupersessionVerificationV1(BaseModel):
    """The deterministic dossier of one signed-supersession verification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["owner_supersession_verification_v1"] = (
        "owner_supersession_verification_v1"
    )
    schema_version: StrictStr = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    verification_id: StrictStr = Field(min_length=1, max_length=128)
    purpose: Literal[LIFECYCLE_SUPERSESSION_PURPOSE]
    registry_id: StrictStr = Field(min_length=1, max_length=128)
    registry_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    key_id: StrictStr | None = Field(default=None, min_length=1, max_length=128)
    algorithm: Literal["ED25519"] = "ED25519"
    verification_status: Literal["VERIFIED", "REJECTED"]
    key_validity: Literal["WITHIN_WINDOW", "OUTSIDE_WINDOW", "UNKNOWN"]
    superseded_record_id: StrictStr = Field(min_length=1, max_length=128)
    superseding_record_id: StrictStr = Field(min_length=1, max_length=128)
    payload_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    reason_code: StrictStr = Field(min_length=1, max_length=128)
    detail: StrictStr = Field(min_length=1, max_length=2_000)
    checks: list[LifecycleVerificationCheckV1] = Field(
        min_length=len(REQUIRED_SUPERSESSION_CHECK_NAMES),
        max_length=len(REQUIRED_SUPERSESSION_CHECK_NAMES),
        json_schema_extra=_lifecycle_sequence_schema_extra(
            REQUIRED_SUPERSESSION_CHECK_NAMES
        ),
    )
    content_sha256: StrictStr = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_dossier(self) -> Self:
        names = tuple(check.name for check in self.checks)
        if names != REQUIRED_SUPERSESSION_CHECK_NAMES:
            raise ValueError(
                "verification checks must contain exactly the canonical "
                "required check sequence in canonical order (expected "
                f"{len(REQUIRED_SUPERSESSION_CHECK_NAMES)} checks)"
            )
        failed = [check.name for check in self.checks if not check.passed]
        if self.verification_status == "VERIFIED":
            if failed:
                raise ValueError("VERIFIED requires every check to pass")
            if self.key_id is None:
                raise ValueError("VERIFIED names the verified key")
        elif not failed:
            raise ValueError("REJECTED requires at least one failed check")
        expected_id = deterministic_id(
            "owner-supersession-verification",
            self.registry_id,
            self.registry_content_sha256,
            self.key_id or "",
            self.superseded_record_id,
            self.superseding_record_id,
            self.payload_content_sha256,
            self.verification_status,
            *[f"{check.name}:{int(check.passed)}" for check in self.checks],
        )
        if self.verification_id != expected_id:
            raise ValueError("verification id disagrees with the bound content")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected_content = _sha256_hex(canonical_json_bytes(payload))
        if self.content_sha256 != expected_content:
            raise ValueError("verification content_sha256 does not match content")
        return self


# ---------------------------------------------------------------------------
# Pure offline verification
# ---------------------------------------------------------------------------


def _lifecycle_outcomes(
    *,
    purpose: str,
    statement_purpose: str,
    statement_key_id: str,
    signature_base64: str,
    statement_signed_content_sha256: str,
    statement_identity: str,
    payload_identity: str,
    payload_content_sha256: str,
    payload_canonical: bytes,
    lifecycle_date: str,
    registry: OwnerProvenanceKeyRegistryV1,
) -> tuple[list[tuple[str, bool, str]], str]:
    """Evaluate the canonical checks shared by both lifecycle protocols.

    Returns the ordered outcomes plus the resolved key-validity window
    state (``UNKNOWN`` when it cannot be proven).
    """

    outcomes: list[tuple[str, bool, str]] = []

    algorithm_ok = statement_purpose == purpose  # model fixes ED25519 anyway
    outcomes.append(
        ("ALGORITHM_SUPPORTED", algorithm_ok, "signature algorithm is 'ED25519'")
    )

    key = next(
        (item for item in registry.keys if item.key_id == statement_key_id), None
    )
    key_resolved = key is not None
    outcomes.append(
        (
            "KEY_RESOLUTION",
            key_resolved,
            (
                f"key {statement_key_id!r} resolved in registry "
                f"{registry.registry_id!r}"
                if key_resolved
                else f"key {statement_key_id!r} is not registered in registry "
                f"{registry.registry_id!r}"
            ),
        )
    )

    identity_ok = (
        key is not None
        and key.owner_identity == statement_identity
        and statement_identity == payload_identity
    )
    outcomes.append(
        (
            "KEY_IDENTITY_BINDING",
            identity_ok,
            (
                f"key, statement and payload all bind owner identity "
                f"{statement_identity!r}"
                if identity_ok
                else "the signing key is not bound to the payload's declared "
                "owner identity"
                if key is not None
                else "key unresolved; identity binding cannot be proven"
            ),
        )
    )

    window_state = "UNKNOWN"
    if key is not None and re.fullmatch(ISO_DATE_PATTERN, lifecycle_date):
        try:
            event_date = date.fromisoformat(lifecycle_date)
            start_date = date.fromisoformat(key.valid_from)
            end_date = date.fromisoformat(key.valid_until)
        except ValueError:
            pass  # An impossible calendar date must fail closed as UNKNOWN.
        else:
            window_state = (
                "WITHIN_WINDOW"
                if start_date <= event_date <= end_date
                else "OUTSIDE_WINDOW"
            )
    window_ok = window_state == "WITHIN_WINDOW"
    outcomes.append(
        (
            "KEY_VALIDITY_WINDOW",
            window_ok,
            (
                f"lifecycle date {lifecycle_date!r} is within the key validity "
                f"window [{key.valid_from}, {key.valid_until}]"
                if window_ok and key is not None
                else "key validity window is not proven to cover the lifecycle "
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

    content_ok = _sha256_hex(payload_canonical) == payload_content_sha256
    outcomes.append(
        (
            "PAYLOAD_CONTENT_BINDING",
            content_ok,
            (
                "statement binds the exact canonical payload bytes "
                f"({payload_content_sha256})"
                if content_ok
                else "the payload's canonical bytes are not what the statement "
                "binds"
            ),
        )
    )

    purpose_ok = statement_purpose == purpose
    outcomes.append(
        (
            "PURPOSE_BINDING",
            purpose_ok,
            (
                f"signature purpose is the fixed {purpose} domain"
                if purpose_ok
                else f"signature purpose {statement_purpose!r} is not the "
                f"expected {purpose} domain"
            ),
        )
    )

    message = purpose.encode("utf-8") + b"\x00" + payload_canonical
    signature_ok = (
        key is not None
        and algorithm_ok
        and purpose_ok
        and content_ok
        and _sha256_hex(message) == statement_signed_content_sha256
        and _ed25519_verify(
            base64.b64decode(key.public_key_base64, validate=True),
            base64.b64decode(signature_base64, validate=True),
            message,
        )
    )
    outcomes.append(
        (
            "SIGNATURE_VERIFIED",
            signature_ok,
            (
                "Ed25519 signature verifies over the exact domain-separated "
                "lifecycle message"
                if signature_ok
                else "Ed25519 signature does not verify over the exact "
                "domain-separated lifecycle message"
            ),
        )
    )
    return outcomes, window_state


def _lifecycle_dossier_fields(
    *,
    contract: str,
    purpose: str,
    registry: OwnerProvenanceKeyRegistryV1,
    statement_key_id: str,
    key_resolved: bool,
    window_state: str,
    status: str,
    reason_code: str,
    detail: str,
    checks: list[LifecycleVerificationCheckV1],
    extra_bindings: dict[str, str],
    payload_content_sha256: str,
    id_namespace: str,
) -> dict:
    checks_dump = [check.model_dump(mode="json") for check in checks]
    verification_id = deterministic_id(
        id_namespace,
        registry.registry_id,
        registry.content_sha256,
        statement_key_id if key_resolved else "",
        *[extra_bindings[key] for key in sorted(extra_bindings)],
        payload_content_sha256,
        status,
        *[f"{check.name}:{int(check.passed)}" for check in checks],
    )
    return {
        "contract": contract,
        "schema_version": "1.0.0",
        "algorithm": PROVENANCE_ALGORITHM,
        "purpose": purpose,
        "verification_id": verification_id,
        "registry_id": registry.registry_id,
        "registry_content_sha256": registry.content_sha256,
        "key_id": statement_key_id if key_resolved else None,
        "verification_status": status,
        "key_validity": window_state,
        "reason_code": reason_code,
        "detail": detail,
        "checks": checks_dump,
        **extra_bindings,
        "payload_content_sha256": payload_content_sha256,
    }


def _checks_from_outcomes(
    outcomes: list[tuple[str, bool, str]]
) -> list[LifecycleVerificationCheckV1]:
    return [
        LifecycleVerificationCheckV1(name=name, passed=passed, reason=reason)
        for name, passed, reason in outcomes
    ]


def _summarize(checks: list[LifecycleVerificationCheckV1]) -> tuple[str, str, str]:
    failed = [check.name for check in checks if not check.passed]
    status = "VERIFIED" if not failed else "REJECTED"
    reason_code = "ALL_LIFECYCLE_CHECKS_PASSED" if not failed else failed[0]
    detail = (
        "Every canonical lifecycle check passed for the exact bound lifecycle "
        "content; this dossier is cryptographic verification evidence, never "
        "an execution."
        if not failed
        else "Lifecycle verification failed closed; the failing canonical "
        f"checks are: {', '.join(failed)}."
    )
    return status, reason_code, detail


def verify_owner_revocation(
    *,
    payload: OwnerRevocationPayloadV1,
    statement: OwnerSignedRevocationStatementV1,
    registry: OwnerProvenanceKeyRegistryV1,
    declared_owner_identity: str | None = None,
) -> OwnerRevocationVerificationV1:
    """Verify one signed revocation against one trusted registry (pure/offline)."""

    if declared_owner_identity is not None and (
        declared_owner_identity != payload.revoked_by
        or declared_owner_identity != statement.declared_owner_identity
    ):
        # Fail closed through the identity check without inventing outcomes.
        payload_identity = declared_owner_identity
    else:
        payload_identity = payload.revoked_by
    outcomes, window_state = _lifecycle_outcomes(
        purpose=LIFECYCLE_REVOCATION_PURPOSE,
        statement_purpose=statement.purpose,
        statement_key_id=statement.key_id,
        signature_base64=statement.signature_base64,
        statement_signed_content_sha256=statement.signed_content_sha256,
        statement_identity=statement.declared_owner_identity,
        payload_identity=payload_identity,
        payload_content_sha256=statement.payload_content_sha256,
        payload_canonical=canonical_json_bytes(payload.model_dump(mode="json")),
        lifecycle_date=payload.revoked_at,
        registry=registry,
    )
    checks = _checks_from_outcomes(outcomes)
    status, reason_code, detail = _summarize(checks)
    key_resolved = any(
        name == "KEY_RESOLUTION" and passed for name, passed, _ in outcomes
    )
    payload_canonical = canonical_json_bytes(payload.model_dump(mode="json"))
    fields = _lifecycle_dossier_fields(
        contract="owner_revocation_verification_v1",
        purpose=LIFECYCLE_REVOCATION_PURPOSE,
        registry=registry,
        statement_key_id=statement.key_id,
        key_resolved=key_resolved,
        window_state=window_state,
        status=status,
        reason_code=reason_code,
        detail=detail,
        checks=checks,
        extra_bindings={
            "revoked_record_id": payload.revoked_decision_record_id,
        },
        payload_content_sha256=_sha256_hex(payload_canonical),
        id_namespace="owner-revocation-verification",
    )
    return OwnerRevocationVerificationV1(
        **fields,
        content_sha256=_sha256_hex(canonical_json_bytes(fields)),
    )


def verify_owner_supersession(
    *,
    payload: OwnerSupersessionPayloadV1,
    statement: OwnerSignedSupersessionStatementV1,
    registry: OwnerProvenanceKeyRegistryV1,
    declared_owner_identity: str | None = None,
) -> OwnerSupersessionVerificationV1:
    """Verify one signed supersession against one trusted registry (pure/offline)."""

    if declared_owner_identity is not None and (
        declared_owner_identity != payload.superseded_by
        or declared_owner_identity != statement.declared_owner_identity
    ):
        payload_identity = declared_owner_identity
    else:
        payload_identity = payload.superseded_by
    outcomes, window_state = _lifecycle_outcomes(
        purpose=LIFECYCLE_SUPERSESSION_PURPOSE,
        statement_purpose=statement.purpose,
        statement_key_id=statement.key_id,
        signature_base64=statement.signature_base64,
        statement_signed_content_sha256=statement.signed_content_sha256,
        statement_identity=statement.declared_owner_identity,
        payload_identity=payload_identity,
        payload_content_sha256=statement.payload_content_sha256,
        payload_canonical=canonical_json_bytes(payload.model_dump(mode="json")),
        lifecycle_date=payload.superseded_at,
        registry=registry,
    )
    checks = _checks_from_outcomes(outcomes)
    status, reason_code, detail = _summarize(checks)
    key_resolved = any(
        name == "KEY_RESOLUTION" and passed for name, passed, _ in outcomes
    )
    payload_canonical = canonical_json_bytes(payload.model_dump(mode="json"))
    fields = _lifecycle_dossier_fields(
        contract="owner_supersession_verification_v1",
        purpose=LIFECYCLE_SUPERSESSION_PURPOSE,
        registry=registry,
        statement_key_id=statement.key_id,
        key_resolved=key_resolved,
        window_state=window_state,
        status=status,
        reason_code=reason_code,
        detail=detail,
        checks=checks,
        extra_bindings={
            "superseded_record_id": payload.superseded_decision_record_id,
            "superseding_record_id": payload.superseding_decision_record_id,
        },
        payload_content_sha256=_sha256_hex(payload_canonical),
        id_namespace="owner-supersession-verification",
    )
    return OwnerSupersessionVerificationV1(
        **fields,
        content_sha256=_sha256_hex(canonical_json_bytes(fields)),
    )


def revocation_binding_from_payload(
    payload: OwnerRevocationPayloadV1,
) -> AuthenticatedRevocationBindingV1:
    """The resolver carrier for one cryptographically verified payload."""

    return AuthenticatedRevocationBindingV1.model_validate(
        payload.model_dump(
            mode="json",
            include={
                "revoked_decision_record_id",
                "revoked_record_content_sha256",
                "target_profile_id",
                "target_profile_sha256",
                "revoked_by",
                "revoked_at",
            },
        )
    )


def supersession_binding_from_payload(
    payload: OwnerSupersessionPayloadV1,
) -> AuthenticatedSupersessionBindingV1:
    """The resolver carrier for one cryptographically verified payload."""

    return AuthenticatedSupersessionBindingV1.model_validate(
        payload.model_dump(
            mode="json",
            include={
                "superseded_decision_record_id",
                "superseded_record_content_sha256",
                "superseding_decision_record_id",
                "superseding_record_content_sha256",
                "target_profile_id",
                "target_profile_sha256",
                "superseded_by",
                "superseded_at",
            },
        )
    )


class SignedLifecycleVerifier:
    """Fresh lifecycle verification against one explicit trust root.

    Library-only helper for hosting boundaries (the CLI, tests): verifies
    revocation/supersession evidence and returns the resolver carriers.
    A failed verification returns ``None`` plus the dossier so callers can
    report the exact reason; it never relaxes into a binding.
    """

    kind: ClassVar[str] = "ed25519-signed-owner-lifecycle"

    def __init__(
        self, *, registry: OwnerProvenanceKeyRegistryV1
    ) -> None:
        if not isinstance(registry, OwnerProvenanceKeyRegistryV1):
            raise ValueError(
                "registry must be an OwnerProvenanceKeyRegistryV1"
            )
        self._registry = registry

    @property
    def registry(self) -> OwnerProvenanceKeyRegistryV1:
        return self._registry  # type: ignore[no-any-return]

    def verify_revocation(
        self, evidence: OwnerSignedRevocationEvidenceV1
    ) -> tuple[AuthenticatedRevocationBindingV1 | None, OwnerRevocationVerificationV1]:
        dossier = verify_owner_revocation(
            payload=evidence.payload,
            statement=evidence.statement,
            registry=self._registry,
        )
        if dossier.verification_status != "VERIFIED":
            return None, dossier
        return revocation_binding_from_payload(evidence.payload), dossier

    def verify_supersession(
        self, evidence: OwnerSignedSupersessionEvidenceV1
    ) -> (
        tuple[AuthenticatedSupersessionBindingV1 | None, OwnerSupersessionVerificationV1]
    ):
        dossier = verify_owner_supersession(
            payload=evidence.payload,
            statement=evidence.statement,
            registry=self._registry,
        )
        if dossier.verification_status != "VERIFIED":
            return None, dossier
        return supersession_binding_from_payload(evidence.payload), dossier


__all__ = [
    "LIFECYCLE_REVOCATION_PURPOSE",
    "LIFECYCLE_SUPERSESSION_PURPOSE",
    "REQUIRED_REVOCATION_CHECK_NAMES",
    "REQUIRED_SUPERSESSION_CHECK_NAMES",
    "LifecycleVerificationCheckV1",
    "OwnerRevocationPayloadV1",
    "OwnerRevocationVerificationV1",
    "OwnerSignedRevocationEvidenceV1",
    "OwnerSignedRevocationStatementV1",
    "OwnerSignedSupersessionEvidenceV1",
    "OwnerSignedSupersessionStatementV1",
    "OwnerSupersessionPayloadV1",
    "OwnerSupersessionVerificationV1",
    "SignedLifecycleVerifier",
    "build_owner_signed_revocation_statement",
    "build_owner_signed_supersession_statement",
    "owner_revocation_signature_message",
    "owner_supersession_signature_message",
    "revocation_binding_from_payload",
    "supersession_binding_from_payload",
    "verify_owner_revocation",
    "verify_owner_supersession",
]
