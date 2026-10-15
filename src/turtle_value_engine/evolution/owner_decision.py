"""Typed owner policy-decision records and authority resolution (Phase 7-C2).

This module records an *explicitly supplied* owner decision about one audited
versioned-profile pair (for example the published ``strict-v1 -> strict-v2``
policy question), verifies its artifact bindings against freshly re-run
evidence, and resolves sets of records into one unambiguous authority state.
It never activates anything: a recorded decision is review/audit state, and
every contract here fixes ``automatic_application_allowed=False``.

Artifact validity is deliberately separated from real authority.  An unsigned
local JSON file, an EnvironmentFile username, Git author text, a green CI run
or a publication manifest proves neither human authorship nor permission:

* the declared owner identity is matched against an explicit allowlist, and
  an allowlist is *not* authentication — it only rejects identities the
  configuration never admitted;
* actual authority is assessed only through the injected
  :class:`OwnerDecisionVerifier` trust-model interface.  The production CLI
  constructs no verifier and exposes no flag that could select one (fake
  verifiers are test fixtures only), so every CLI-recorded decision stays
  visibly ``OWNER_AUTHORITY_UNVERIFIED`` until a real authenticated source is
  wired in a later, separately selected package.

Expiry is binding-relative, not wall-clock: a decision is valid only for the
exact byte hashes it binds (profiles, release manifest, fresh audit,
exception), so any later byte change makes it stale and the resolver reports
the stale records instead of silently picking a newer file.

The boundary constructs no provider, model, transport or network client and
never writes a rule profile, runtime configuration or approval state.
"""

from __future__ import annotations

import hashlib
import json
import os
from abc import ABC, abstractmethod
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import ClassVar, Literal, Self, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    model_validator,
)

from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.providers.normalization import deterministic_id

from .materialization_pair import _regular_file_bytes
from .profile_semantic_audit import (
    VersionedPolicyExceptionV1,
    audit_profile_semantics,
)

HASH_PATTERN = r"^[0-9a-f]{64}$"

#: Decision values admitted by the current strict-v2 policy question.
OwnerPolicyDecision: TypeAlias = Literal["ACCEPT_WITH_EXCEPTION", "REJECT"]

#: Authority states.  Only ``OWNER_AUTHORITY_VERIFIED`` combined with
#: ``ACCEPT_WITH_EXCEPTION`` can ever feed an activation plan, and even then
#: the plan itself stays read-only.
OwnerAuthorityStatus: TypeAlias = Literal[
    "OWNER_AUTHORITY_UNVERIFIED",
    "OWNER_AUTHORITY_VERIFIED",
    "OWNER_AUTHORITY_REJECTED",
]


class OwnerDecisionError(ValueError):
    """Raised when decision inputs or record sets cannot be processed at all."""


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Provenance and authority contracts
# ---------------------------------------------------------------------------


class DecisionProvenanceV1(BaseModel):
    """Where the decision came from, bound by bytes.

    ``LOCAL_UNSIGNED_JSON`` records that the decision was submitted as a plain
    unsigned local file whose exact bytes hash to ``source_content_sha256``;
    that binding makes later tampering of the source file detectable, but it
    is provenance bookkeeping — it never authenticates the submitter.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_kind: Literal["LOCAL_UNSIGNED_JSON", "VERIFIER_CAPTURED_EVIDENCE"]
    source_revision: StrictStr = Field(min_length=1, max_length=256)
    source_content_sha256: StrictStr | None = Field(default=None, pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        if self.source_kind == "VERIFIER_CAPTURED_EVIDENCE" and (
            self.source_content_sha256 is None
        ):
            raise ValueError(
                "verifier-captured provenance must bind its evidence content hash"
            )
        return self


class OwnerAuthorityAssessmentV1(BaseModel):
    """Machine-readable authority assessment of one declared decision.

    ``allowlist_matched`` is ``None`` when no allowlist was configured at all
    (the boundary then cannot even allowlist-check the identity); matching an
    allowlist is necessary but never sufficient for ``VERIFIED``.

    The additive ``attested_*`` fields are structured bookkeeping of the
    trust root a verifier actually used (key id, registry id, registry
    content hash).  They are captured evidence metadata, never authority:
    a forged record claiming foreign attested fields changes nothing,
    because plan-time authority always comes from a fresh injected-verifier
    assessment whose own attested fields are the ones bound into the plan.
    Verifiers without a registry trust model leave them ``None``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    authority_status: OwnerAuthorityStatus
    verification_method: Literal["NO_AUTHENTICATED_SOURCE", "INJECTED_VERIFIER"]
    verifier_kind: StrictStr | None = Field(default=None, min_length=1, max_length=128)
    allowlist_matched: StrictBool | None = None
    reason_code: StrictStr = Field(min_length=1, max_length=128)
    detail: StrictStr = Field(min_length=1, max_length=2_000)
    evidence_content_sha256: StrictStr | None = Field(default=None, pattern=HASH_PATTERN)
    attested_key_id: StrictStr | None = Field(
        default=None, min_length=1, max_length=128
    )
    attested_registry_id: StrictStr | None = Field(
        default=None, min_length=1, max_length=128
    )
    attested_registry_content_sha256: StrictStr | None = Field(
        default=None, pattern=HASH_PATTERN
    )


class OwnerDecisionVerifier(ABC):
    """Explicit trust-model interface for authenticated owner provenance.

    A real implementation verifies an authenticated source (for example a
    signature over the submitted decision bytes by a key bound to the owner
    identity) and returns a captured, immutable evidence assessment.  No
    implementation ships with the production CLI on purpose: until one exists
    every recorded decision remains visibly unverified, and the fake verifiers
    used by the deterministic tests are test fixtures injected through this
    library boundary, never a CLI-selectable option.
    """

    kind: ClassVar[str]

    @abstractmethod
    def verify_decision_authority(
        self,
        *,
        declared_owner_identity: str,
        provenance: DecisionProvenanceV1,
        decision_source_bytes: bytes,
    ) -> OwnerAuthorityAssessmentV1:
        """Assess whether the authenticated source confirms this submitter."""


# ---------------------------------------------------------------------------
# Decision input and record contracts
# ---------------------------------------------------------------------------


class OwnerPolicyDecisionInputV1(BaseModel):
    """The explicitly supplied, human-authored decision submission.

    Shape-valid only: this contract states a decision and the exact artifact
    identities it is about.  Whether the declared bindings are true, whether
    the audit is fresh and whether the submitter actually holds owner
    authority are answered by :func:`validate_owner_decision`, never by this
    model.  A C1 :class:`PolicyApprovalClaimV1` is a different contract and is
    never silently mapped onto this one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["owner_policy_decision_input_v1"] = "owner_policy_decision_input_v1"
    decision: OwnerPolicyDecision
    base_profile_id: StrictStr = Field(min_length=1)
    base_profile_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    target_profile_id: StrictStr = Field(min_length=1)
    target_profile_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    release_manifest_id: StrictStr = Field(min_length=1)
    release_manifest_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    audit_id: StrictStr = Field(min_length=1)
    audit_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    exception_id: StrictStr | None = Field(default=None, min_length=1)
    exception_content_sha256: StrictStr | None = Field(default=None, pattern=HASH_PATTERN)
    rationale: StrictStr = Field(min_length=20, max_length=4_000)
    declared_owner_identity: StrictStr = Field(min_length=1, max_length=256)
    decided_at: StrictStr = Field(min_length=10, max_length=32)
    source_revision: StrictStr = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.decision == "ACCEPT_WITH_EXCEPTION":
            if self.exception_id is None or self.exception_content_sha256 is None:
                raise ValueError(
                    "ACCEPT_WITH_EXCEPTION must bind exactly one policy exception "
                    "(exception id and content hash)"
                )
        elif self.exception_id is not None or self.exception_content_sha256 is not None:
            raise ValueError(
                "REJECT is a terminal non-activation outcome and must not bind a "
                "policy exception"
            )
        if self.base_profile_id == self.target_profile_id:
            raise ValueError("base and target profile identities must differ")
        return self


class OwnerPolicyDecisionRecordV1(BaseModel):
    """Immutable record of one owner decision with complete artifact bindings.

    The record binds the exact base/target profile byte hashes, the release
    manifest id/content hash, the fresh audit id/content hash, the policy
    exception by BOTH deterministic id and full content hash (C1 exception ids
    omit rationale/declarer, so the id alone is not a content identity), the
    provenance source revision and the authority assessment.  The
    deterministic ``decision_record_id`` includes every bound field including
    the rationale, so any edit anywhere yields a different record identity
    that the resolver treats as ambiguity rather than silently accepting.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["owner_policy_decision_record_v1"] = "owner_policy_decision_record_v1"
    decision_record_id: StrictStr = Field(min_length=1)
    decision: OwnerPolicyDecision
    base_profile_id: StrictStr = Field(min_length=1)
    base_profile_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    target_profile_id: StrictStr = Field(min_length=1)
    target_profile_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    release_manifest_id: StrictStr = Field(min_length=1)
    release_manifest_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    audit_id: StrictStr = Field(min_length=1)
    audit_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    exception_id: StrictStr | None = Field(default=None, min_length=1)
    exception_content_sha256: StrictStr | None = Field(default=None, pattern=HASH_PATTERN)
    rationale: StrictStr = Field(min_length=20, max_length=4_000)
    declared_owner_identity: StrictStr = Field(min_length=1, max_length=256)
    decided_at: StrictStr = Field(min_length=10, max_length=32)
    provenance: DecisionProvenanceV1
    authority: OwnerAuthorityAssessmentV1
    supersedes_decision_record_id: StrictStr | None = Field(
        default=None, min_length=1, max_length=128
    )
    requires_authenticated_owner_authority: Literal[True] = True
    automatic_application_allowed: Literal[False] = False
    decision_is_not_execution_request: Literal[True] = True
    content_sha256: StrictStr = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        if self.decision == "ACCEPT_WITH_EXCEPTION" and (
            self.exception_id is None or self.exception_content_sha256 is None
        ):
            raise ValueError("an accepted decision must bind its policy exception")
        if self.decision == "REJECT" and (
            self.exception_id is not None or self.exception_content_sha256 is not None
        ):
            raise ValueError("a rejected decision must not bind a policy exception")
        expected_id = deterministic_id(
            "owner-policy-decision",
            self.decision,
            self.base_profile_id,
            self.base_profile_sha256,
            self.target_profile_id,
            self.target_profile_sha256,
            self.release_manifest_id,
            self.release_manifest_content_sha256,
            self.audit_id,
            self.audit_content_sha256,
            self.exception_id or "",
            self.exception_content_sha256 or "",
            self.rationale,
            self.declared_owner_identity,
            self.decided_at,
            self.provenance.source_kind,
            self.provenance.source_revision,
            self.provenance.source_content_sha256 or "",
            self.authority.authority_status,
            self.authority.verification_method,
            self.supersedes_decision_record_id or "",
        )
        if self.decision_record_id != expected_id:
            raise ValueError("decision record id disagrees with the bound content")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected_content = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        if self.content_sha256 != expected_content:
            raise ValueError("decision record content_sha256 does not match content")
        return self

    @classmethod
    def build(
        cls,
        *,
        decision_input: OwnerPolicyDecisionInputV1,
        provenance: DecisionProvenanceV1,
        authority: OwnerAuthorityAssessmentV1,
        supersedes_decision_record_id: str | None = None,
    ) -> Self:
        """Construct one record with its deterministic id and content hash."""

        fields = decision_input.model_dump(mode="json")
        fields.pop("contract")
        fields.pop("source_revision")
        fields.update(
            {
                "provenance": provenance.model_dump(mode="json"),
                "authority": authority.model_dump(mode="json"),
                "supersedes_decision_record_id": supersedes_decision_record_id,
                "requires_authenticated_owner_authority": True,
                "automatic_application_allowed": False,
                "decision_is_not_execution_request": True,
                "content_sha256": "0" * 64,
            }
        )
        temporary = cls.model_construct(**fields)
        payload = temporary.model_dump(mode="json", warnings=False)
        payload["decision_record_id"] = deterministic_id(
            "owner-policy-decision",
            payload["decision"],
            payload["base_profile_id"],
            payload["base_profile_sha256"],
            payload["target_profile_id"],
            payload["target_profile_sha256"],
            payload["release_manifest_id"],
            payload["release_manifest_content_sha256"],
            payload["audit_id"],
            payload["audit_content_sha256"],
            payload["exception_id"] or "",
            payload["exception_content_sha256"] or "",
            payload["rationale"],
            payload["declared_owner_identity"],
            payload["decided_at"],
            payload["provenance"]["source_kind"],
            payload["provenance"]["source_revision"],
            payload["provenance"]["source_content_sha256"] or "",
            payload["authority"]["authority_status"],
            payload["authority"]["verification_method"],
            payload["supersedes_decision_record_id"] or "",
        )
        payload["content_sha256"] = hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in payload.items() if key != "content_sha256"}
            )
        ).hexdigest()
        return cls.model_validate(payload)


class OwnerPolicyDecisionRevocationV1(BaseModel):
    """Immutable record withdrawing one previously recorded decision.

    A revocation is itself a recorded authority claim with the same
    provenance/authority separation as a decision: structurally valid is not
    verified.  The resolver treats any structurally valid revocation of a
    current record as removing that record, so a forged revocation can only
    make authority ambiguous (fail-closed), never silently redirect it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["owner_policy_decision_revocation_v1"] = (
        "owner_policy_decision_revocation_v1"
    )
    revocation_id: StrictStr = Field(min_length=1)
    revoked_decision_record_id: StrictStr = Field(min_length=1, max_length=128)
    target_profile_id: StrictStr = Field(min_length=1)
    target_profile_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    revoked_by: StrictStr = Field(min_length=1, max_length=256)
    revoked_at: StrictStr = Field(min_length=10, max_length=32)
    rationale: StrictStr = Field(min_length=20, max_length=4_000)
    provenance: DecisionProvenanceV1
    authority: OwnerAuthorityAssessmentV1
    revocation_is_not_execution: Literal[True] = True
    content_sha256: StrictStr = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_revocation(self) -> Self:
        expected_id = deterministic_id(
            "owner-policy-decision-revocation",
            self.revoked_decision_record_id,
            self.target_profile_id,
            self.target_profile_sha256,
            self.revoked_by,
            self.revoked_at,
            self.rationale,
            self.provenance.source_kind,
            self.provenance.source_revision,
            self.provenance.source_content_sha256 or "",
            self.authority.authority_status,
        )
        if self.revocation_id != expected_id:
            raise ValueError("revocation id disagrees with the bound content")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected_content = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        if self.content_sha256 != expected_content:
            raise ValueError("revocation content_sha256 does not match content")
        return self

    @classmethod
    def build(
        cls,
        *,
        revoked_decision_record_id: str,
        target_profile_id: str,
        target_profile_sha256: str,
        revoked_by: str,
        revoked_at: str,
        rationale: str,
        provenance: DecisionProvenanceV1,
        authority: OwnerAuthorityAssessmentV1,
    ) -> Self:
        fields = {
            "revoked_decision_record_id": revoked_decision_record_id,
            "target_profile_id": target_profile_id,
            "target_profile_sha256": target_profile_sha256,
            "revoked_by": revoked_by,
            "revoked_at": revoked_at,
            "rationale": rationale,
            "provenance": provenance.model_dump(mode="json"),
            "authority": authority.model_dump(mode="json"),
            "revocation_is_not_execution": True,
            "content_sha256": "0" * 64,
        }
        temporary = cls.model_construct(**fields)
        payload = temporary.model_dump(mode="json", warnings=False)
        payload["revocation_id"] = deterministic_id(
            "owner-policy-decision-revocation",
            payload["revoked_decision_record_id"],
            payload["target_profile_id"],
            payload["target_profile_sha256"],
            payload["revoked_by"],
            payload["revoked_at"],
            payload["rationale"],
            payload["provenance"]["source_kind"],
            payload["provenance"]["source_revision"],
            payload["provenance"]["source_content_sha256"] or "",
            payload["authority"]["authority_status"],
        )
        payload["content_sha256"] = hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in payload.items() if key != "content_sha256"}
            )
        ).hexdigest()
        return cls.model_validate(payload)


# ---------------------------------------------------------------------------
# Validation contract and entry point
# ---------------------------------------------------------------------------

CHECK_DECISION_SHAPE_VALID = "DECISION_SHAPE_VALID"
CHECK_INPUT_BINDINGS_MATCH_BYTES = "INPUT_BINDINGS_MATCH_BYTES"
CHECK_AUDIT_FRESH_AND_MATCHING = "AUDIT_FRESH_AND_MATCHING"
CHECK_EXCEPTION_BINDING_EXACT = "EXCEPTION_BINDING_EXACT"
CHECK_EXCEPTION_COVERS_ALL_FINDINGS = "EXCEPTION_COVERS_ALL_FINDINGS"
CHECK_PROVENANCE_BOUND = "PROVENANCE_BOUND"

#: The one canonical ordered check sequence for
#: ``owner_policy_decision_validation_v1``.
REQUIRED_DECISION_VALIDATION_CHECKS: tuple[tuple[str, str], ...] = (
    (CHECK_DECISION_SHAPE_VALID, "decision"),
    (CHECK_INPUT_BINDINGS_MATCH_BYTES, "bindings"),
    (CHECK_AUDIT_FRESH_AND_MATCHING, "audit"),
    (CHECK_EXCEPTION_BINDING_EXACT, "exception"),
    (CHECK_EXCEPTION_COVERS_ALL_FINDINGS, "exception"),
    (CHECK_PROVENANCE_BOUND, "provenance"),
)

DecisionValidationCheckName: TypeAlias = Literal[
    "DECISION_SHAPE_VALID",
    "INPUT_BINDINGS_MATCH_BYTES",
    "AUDIT_FRESH_AND_MATCHING",
    "EXCEPTION_BINDING_EXACT",
    "EXCEPTION_COVERS_ALL_FINDINGS",
    "PROVENANCE_BOUND",
]


class DecisionValidationCheckV1(BaseModel):
    """One machine-readable decision-validation check."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: DecisionValidationCheckName
    scope: Literal["decision", "bindings", "audit", "exception", "provenance"]
    status: Literal["PASS", "BLOCKED"]
    code: StrictStr = Field(min_length=1, max_length=128, pattern=r"^[A-Z][A-Z0-9_]*$")
    detail: StrictStr = Field(min_length=1, max_length=2_000)


def _decision_validation_sequence_schema_extra() -> dict[str, object]:
    """Exact Draft 2020-12 per-position sequence constraint (C1 pattern)."""

    item_schema = DecisionValidationCheckV1.model_json_schema()
    prefix_items: list[dict[str, object]] = []
    for name, scope in REQUIRED_DECISION_VALIDATION_CHECKS:
        position = dict(item_schema)
        position["properties"] = {
            **item_schema["properties"],  # type: ignore[arg-type]
            "name": {"const": name},
            "scope": {"const": scope},
        }
        prefix_items.append(position)
    return {"prefixItems": prefix_items, "items": False}


class OwnerPolicyDecisionValidationV1(BaseModel):
    """Immutable decision-validation dossier; the record exists only when VALID.

    ``state`` is ``VALID`` exactly when every canonical check passes; the
    would-be record is then embedded with its authority assessment (possibly
    still visibly unverified — validity of artifacts is separate from real
    authority).  ``state`` ``INVALID`` carries the failing check codes as
    ``blockers`` and embeds no record.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["owner_policy_decision_validation_v1"] = (
        "owner_policy_decision_validation_v1"
    )
    validation_id: StrictStr = Field(min_length=1)
    decision: OwnerPolicyDecision
    declared_owner_identity: StrictStr = Field(min_length=1, max_length=256)
    fresh_audit_id: StrictStr = Field(min_length=1)
    fresh_audit_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    fresh_audit_activation_readiness: StrictStr = Field(min_length=1, max_length=64)
    checks: list[DecisionValidationCheckV1] = Field(
        min_length=len(REQUIRED_DECISION_VALIDATION_CHECKS),
        max_length=len(REQUIRED_DECISION_VALIDATION_CHECKS),
        json_schema_extra=_decision_validation_sequence_schema_extra(),
    )
    blockers: list[StrictStr] = Field(max_length=32)
    state: Literal["VALID", "INVALID"]
    record: OwnerPolicyDecisionRecordV1 | None = None
    authority_status: OwnerAuthorityStatus
    content_sha256: StrictStr = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_dossier(self) -> Self:
        expected_sequence = [(check.name, check.scope) for check in self.checks]
        if expected_sequence != [
            tuple(item) for item in REQUIRED_DECISION_VALIDATION_CHECKS
        ]:
            raise ValueError(
                "decision validation checks must contain exactly the canonical "
                "required check sequence in canonical order (expected "
                f"{len(REQUIRED_DECISION_VALIDATION_CHECKS)} checks)"
            )
        blocked = sorted(
            {
                f"{check.name}:{check.code}"
                for check in self.checks
                if check.status == "BLOCKED"
            }
        )
        # Authority rejections are not artifact-validity checks; they surface
        # as ``AUTHORITY:<reason>`` blockers only.
        authority_blockers = sorted(
            item for item in self.blockers if item.startswith("AUTHORITY:")
        )
        if self.state == "VALID":
            if blocked:
                raise ValueError("VALID requires every check to pass")
            if self.blockers:
                raise ValueError("VALID carries no blockers")
            if self.record is None:
                raise ValueError("VALID embeds the produced decision record")
            if self.authority_status != self.record.authority.authority_status:
                raise ValueError("dossier authority must mirror the record authority")
        else:
            if not blocked and not authority_blockers:
                raise ValueError(
                    "INVALID requires a BLOCKED check or an authority rejection "
                    "blocker"
                )
            if sorted(self.blockers) != sorted({*blocked, *authority_blockers}):
                raise ValueError(
                    "blockers must list exactly the blocked checks and authority "
                    "rejections"
                )
            if self.record is not None:
                raise ValueError("INVALID embeds no decision record")
        expected_id = deterministic_id(
            "owner-policy-decision-validation",
            self.decision,
            self.declared_owner_identity,
            self.fresh_audit_id,
            self.fresh_audit_content_sha256,
            self.state,
            self.authority_status,
        )
        if self.validation_id != expected_id:
            raise ValueError("validation id disagrees with the bound identities")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected_content = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        if self.content_sha256 != expected_content:
            raise ValueError("validation content_sha256 does not match content")
        return self


def _assess_decision_authority(
    *,
    decision_input: OwnerPolicyDecisionInputV1,
    provenance: DecisionProvenanceV1,
    decision_source_bytes: bytes,
    owner_allowlist: Collection[str] | None,
    verifier: OwnerDecisionVerifier | None,
) -> OwnerAuthorityAssessmentV1:
    """Assess authority: allowlist first (not authentication), then verifier."""

    if owner_allowlist is not None:
        allowed = sorted(set(owner_allowlist))
        if decision_input.declared_owner_identity not in allowed:
            return OwnerAuthorityAssessmentV1(
                authority_status="OWNER_AUTHORITY_REJECTED",
                verification_method="NO_AUTHENTICATED_SOURCE",
                verifier_kind=None,
                allowlist_matched=False,
                reason_code="OWNER_IDENTITY_NOT_ALLOWLISTED",
                detail=(
                    "Declared owner identity is not in the configured allowlist; "
                    "an allowlist is not authentication, and an unknown identity "
                    "cannot even be considered for authority."
                ),
            )
        allowlist_matched = True
    else:
        allowlist_matched = None

    if verifier is None:
        return OwnerAuthorityAssessmentV1(
            authority_status="OWNER_AUTHORITY_UNVERIFIED",
            verification_method="NO_AUTHENTICATED_SOURCE",
            verifier_kind=None,
            allowlist_matched=allowlist_matched,
            reason_code="NO_AUTHENTICATED_SOURCE_AVAILABLE",
            detail=(
                "No authenticated provenance source is configured in this offline "
                "boundary; the unsigned local submission, any EnvironmentFile "
                "username, Git author text, CI success and the release "
                "publication prove neither authorship nor permission.  The "
                "decision stays recorded but visibly unverified."
                if allowlist_matched is None
                else "The declared identity is allowlisted but no authenticated "
                "provenance source confirmed authorship; an allowlist is not "
                "authentication."
            ),
        )
    assessment = verifier.verify_decision_authority(
        declared_owner_identity=decision_input.declared_owner_identity,
        provenance=provenance,
        decision_source_bytes=decision_source_bytes,
    )
    if assessment.allowlist_matched is None:
        assessment = assessment.model_copy(update={"allowlist_matched": allowlist_matched})
    return assessment


def validate_owner_decision(
    *,
    decision_input: OwnerPolicyDecisionInputV1,
    decision_source_bytes: bytes,
    base_profile_path: str | Path,
    target_profile_path: str | Path,
    release_manifest_path: str | Path,
    boundary_input=None,
    policy_exceptions: Sequence[VersionedPolicyExceptionV1] = (),
    owner_allowlist: Collection[str] | None = None,
    verifier: OwnerDecisionVerifier | None = None,
    supersedes_decision_record_id: str | None = None,
) -> OwnerPolicyDecisionValidationV1:
    """Validate one supplied decision against freshly re-run evidence.

    The C1 audit is always re-executed from the supplied profile/manifest/
    template bytes together with the supplied policy exceptions; a previous
    dossier's self-reported readiness is never trusted or even read.  The
    declared audit id/content hash must equal that fresh audit, the declared
    profile/manifest hashes must equal the actual bytes, and an accepted
    decision's exception must match by BOTH id and full content hash while
    leaving the fresh audit with no uncovered finding and no structural
    blocker.
    """

    from turtle_value_engine.evolution.profile_release import (
        VersionedProfileReleaseCandidateV1,
    )

    base_bytes = _regular_file_bytes(Path(base_profile_path))
    target_bytes = _regular_file_bytes(Path(target_profile_path))
    manifest_bytes = _regular_file_bytes(Path(release_manifest_path))
    base_sha = _sha256_hex(base_bytes)
    target_sha = _sha256_hex(target_bytes)
    try:
        manifest = VersionedProfileReleaseCandidateV1.model_validate(
            json.loads(manifest_bytes)
        )
    except Exception as exc:
        raise OwnerDecisionError(
            f"RELEASE_MANIFEST_UNREADABLE: {str(exc)[:300]}"
        ) from exc

    checks: list[DecisionValidationCheckV1] = []
    blockers: list[str] = []

    def pass_check(name: str, scope: str, detail: str) -> None:
        checks.append(
            DecisionValidationCheckV1(
                name=name,  # type: ignore[arg-type]
                scope=scope,  # type: ignore[arg-type]
                status="PASS",
                code="OK",
                detail=detail[:2_000],
            )
        )

    def block_check(name: str, scope: str, code: str, detail: str) -> None:
        checks.append(
            DecisionValidationCheckV1(
                name=name,  # type: ignore[arg-type]
                scope=scope,  # type: ignore[arg-type]
                status="BLOCKED",
                code=code,
                detail=detail[:2_000],
            )
        )
        blockers.append(f"{name}:{code}")

    # 1. Decision shape (the model already enforces the base contract; the
    # remaining shape rule here is exception-supply consistency).
    exception_supply_ok = (
        len(policy_exceptions) == 1
        if decision_input.decision == "ACCEPT_WITH_EXCEPTION"
        else len(policy_exceptions) == 0
    )
    if exception_supply_ok:
        pass_check(
            CHECK_DECISION_SHAPE_VALID,
            "decision",
            "Decision shape is consistent with the supplied exception material.",
        )
    else:
        block_check(
            CHECK_DECISION_SHAPE_VALID,
            "decision",
            "EXCEPTION_SUPPLY_MISMATCH",
            "ACCEPT_WITH_EXCEPTION requires exactly one supplied policy exception "
            "file; REJECT requires none.",
        )

    # 2. Declared bindings against the actual bytes.
    binding_errors: list[str] = []
    if decision_input.base_profile_sha256 != base_sha:
        binding_errors.append(
            f"base profile bytes hash to {base_sha}, not the declared "
            f"{decision_input.base_profile_sha256}"
        )
    if decision_input.target_profile_sha256 != target_sha:
        binding_errors.append(
            f"target profile bytes hash to {target_sha}, not the declared "
            f"{decision_input.target_profile_sha256}"
        )
    if decision_input.release_manifest_content_sha256 != manifest.content_sha256:
        binding_errors.append(
            f"release manifest content hashes to {manifest.content_sha256}, not "
            f"the declared {decision_input.release_manifest_content_sha256}"
        )
    if decision_input.release_manifest_id != manifest.release_candidate_id:
        binding_errors.append(
            f"release manifest id is {manifest.release_candidate_id}, not the "
            f"declared {decision_input.release_manifest_id}"
        )
    if not binding_errors:
        pass_check(
            CHECK_INPUT_BINDINGS_MATCH_BYTES,
            "bindings",
            "Declared base/target/manifest identities match the supplied bytes.",
        )
    else:
        block_check(
            CHECK_INPUT_BINDINGS_MATCH_BYTES,
            "bindings",
            "DECLARED_BINDINGS_STALE",
            "; ".join(binding_errors),
        )

    # 3. Fresh audit re-run and comparison with the declared audit identity.
    fresh_audit = audit_profile_semantics(
        base_profile_path=base_profile_path,
        target_profile_path=target_profile_path,
        release_manifest_path=release_manifest_path,
        boundary_input=boundary_input,
        policy_exceptions=policy_exceptions,
    )
    if (
        decision_input.audit_id == fresh_audit.audit_id
        and decision_input.audit_content_sha256 == fresh_audit.content_sha256
    ):
        pass_check(
            CHECK_AUDIT_FRESH_AND_MATCHING,
            "audit",
            "The declared audit identity equals the freshly re-run audit "
            f"({fresh_audit.audit_id}).",
        )
    else:
        block_check(
            CHECK_AUDIT_FRESH_AND_MATCHING,
            "audit",
            "DECLARED_AUDIT_STALE",
            "The decision binds audit "
            f"{decision_input.audit_id}/{decision_input.audit_content_sha256[:12]}… "
            "but the fresh re-run from the supplied bytes produced "
            f"{fresh_audit.audit_id}/{fresh_audit.content_sha256[:12]}…; the "
            "decision was authored against different bytes or a different "
            "exception set.",
        )

    # 4. Exception binding exactness (id AND full content hash AND target bytes).
    if decision_input.decision == "REJECT":
        pass_check(
            CHECK_EXCEPTION_BINDING_EXACT,
            "exception",
            "REJECT binds no policy exception.",
        )
        pass_check(
            CHECK_EXCEPTION_COVERS_ALL_FINDINGS,
            "exception",
            "REJECT is a terminal non-activation outcome; no finding needs "
            "coverage.  Correction of the policy requires a new release through "
            "the unchanged evolution chain.",
        )
    else:
        exception = policy_exceptions[0] if policy_exceptions else None
        exception_errors: list[str] = []
        if exception is None:
            exception_errors.append("no policy exception was supplied")
        else:
            if exception.exception_id != decision_input.exception_id:
                exception_errors.append(
                    f"supplied exception id {exception.exception_id} differs from "
                    f"the bound {decision_input.exception_id}"
                )
            if exception.content_sha256 != decision_input.exception_content_sha256:
                exception_errors.append(
                    "supplied exception content hash differs from the bound hash "
                    "(the C1 exception id omits rationale/declarer, so an "
                    "unchanged id with altered content is exactly this blocker)"
                )
            if (
                exception.profile_id != decision_input.target_profile_id
                or exception.profile_sha256 != target_sha
            ):
                exception_errors.append(
                    "supplied exception does not bind the audited target profile "
                    "bytes"
                )
        if exception_errors:
            block_check(
                CHECK_EXCEPTION_BINDING_EXACT,
                "exception",
                "EXCEPTION_BINDING_MISMATCH",
                "; ".join(exception_errors),
            )
            block_check(
                CHECK_EXCEPTION_COVERS_ALL_FINDINGS,
                "exception",
                "EXCEPTION_COVERAGE_NOT_EVALUABLE",
                "Coverage cannot be evaluated against a mismatched exception "
                "binding.",
            )
        elif fresh_audit.activation_readiness == "READY_FOR_POLICY_DECISION" and not (
            fresh_audit.blocking_checks or fresh_audit.policy_decision_reasons
        ):
            pass_check(
                CHECK_EXCEPTION_BINDING_EXACT,
                "exception",
                "The supplied exception matches the bound id AND full content "
                "hash and binds the audited target bytes.",
            )
            pass_check(
                CHECK_EXCEPTION_COVERS_ALL_FINDINGS,
                "exception",
                "The fresh audit with the bound exception leaves no uncovered "
                "finding and no structural blocker "
                f"({fresh_audit.activation_readiness}).",
            )
        else:
            pass_check(
                CHECK_EXCEPTION_BINDING_EXACT,
                "exception",
                "The supplied exception matches the bound id AND full content "
                "hash and binds the audited target bytes.",
            )
            block_check(
                CHECK_EXCEPTION_COVERS_ALL_FINDINGS,
                "exception",
                "UNCOVERED_FINDINGS_REMAIN",
                "The fresh audit with the bound exception still reports "
                f"{fresh_audit.activation_readiness} with blockers "
                f"{fresh_audit.blocking_checks} and uncovered findings "
                f"{fresh_audit.policy_decision_reasons}; the exception does not "
                "cover everything.",
            )

    # 5. Provenance bound to the exact submitted bytes.
    provenance = DecisionProvenanceV1(
        source_kind="LOCAL_UNSIGNED_JSON",
        source_revision=decision_input.source_revision,
        source_content_sha256=_sha256_hex(decision_source_bytes),
    )
    pass_check(
        CHECK_PROVENANCE_BOUND,
        "provenance",
        "Provenance binds the unsigned local submission bytes and the declared "
        f"source revision {decision_input.source_revision!r}; provenance is "
        "bookkeeping, never authentication.",
    )

    authority = _assess_decision_authority(
        decision_input=decision_input,
        provenance=provenance,
        decision_source_bytes=decision_source_bytes,
        owner_allowlist=owner_allowlist,
        verifier=verifier,
    )
    authority_blocks = authority.authority_status == "OWNER_AUTHORITY_REJECTED"

    state: Literal["VALID", "INVALID"] = (
        "INVALID" if (blockers or authority_blocks) else "VALID"
    )
    if authority_blocks:
        blockers.append(f"AUTHORITY:{authority.reason_code}")
    record = (
        None
        if state == "INVALID"
        else OwnerPolicyDecisionRecordV1.build(
            decision_input=decision_input,
            provenance=provenance,
            authority=authority,
            supersedes_decision_record_id=supersedes_decision_record_id,
        )
    )
    validation_id = deterministic_id(
        "owner-policy-decision-validation",
        decision_input.decision,
        decision_input.declared_owner_identity,
        fresh_audit.audit_id,
        fresh_audit.content_sha256,
        state,
        authority.authority_status,
    )
    dossier = OwnerPolicyDecisionValidationV1.model_construct(
        contract="owner_policy_decision_validation_v1",
        validation_id=validation_id,
        decision=decision_input.decision,
        declared_owner_identity=decision_input.declared_owner_identity,
        fresh_audit_id=fresh_audit.audit_id,
        fresh_audit_content_sha256=fresh_audit.content_sha256,
        fresh_audit_activation_readiness=fresh_audit.activation_readiness,
        checks=checks,
        blockers=sorted(blockers),
        state=state,
        record=record,
        authority_status=authority.authority_status,
        content_sha256="0" * 64,
    )
    payload = dossier.model_dump(mode="json", warnings=False)
    payload["content_sha256"] = hashlib.sha256(
        canonical_json_bytes(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
    ).hexdigest()
    return OwnerPolicyDecisionValidationV1.model_validate(payload)


# ---------------------------------------------------------------------------
# Authority resolution over record sets
# ---------------------------------------------------------------------------


class DecisionAuthorityResolutionV1(BaseModel):
    """Fail-closed resolution of every recorded decision for one exact target.

    Stale records (binding other than the current target bytes) are reported,
    never silently discarded or preferred; revoked and superseded records are
    listed; ambiguity and conflict are terminal states rather than a newest-
    file-wins selection.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["owner_decision_authority_resolution_v1"] = (
        "owner_decision_authority_resolution_v1"
    )
    resolution_id: StrictStr = Field(min_length=1)
    target_profile_id: StrictStr = Field(min_length=1)
    target_profile_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    supplied_record_count: StrictInt = Field(ge=0)
    stale_record_ids: list[StrictStr] = Field(max_length=256)
    revoked_record_ids: list[StrictStr] = Field(max_length=256)
    superseded_record_ids: list[StrictStr] = Field(max_length=256)
    resolved_state: Literal[
        "ACCEPT_VERIFIED",
        "ACCEPT_UNVERIFIED",
        "ACCEPT_AUTHORITY_REJECTED",
        "REJECTED",
        "NO_DECISION",
        "AMBIGUOUS",
        "CONFLICTING",
    ]
    active_decision: OwnerPolicyDecision | None = None
    active_decision_record_id: StrictStr | None = Field(default=None, min_length=1)
    active_decision_record_content_sha256: StrictStr | None = Field(
        default=None, pattern=HASH_PATTERN
    )
    active_authority_status: OwnerAuthorityStatus | None = None
    active_exception_id: StrictStr | None = Field(default=None, min_length=1)
    blockers: list[StrictStr] = Field(max_length=64)
    content_sha256: StrictStr = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_resolution(self) -> Self:
        terminal = {"NO_DECISION", "AMBIGUOUS", "CONFLICTING"}
        if self.resolved_state in terminal:
            if (
                self.active_decision is not None
                or self.active_decision_record_id is not None
                or self.active_authority_status is not None
                or self.active_exception_id is not None
            ):
                raise ValueError("terminal resolution states carry no active record")
            if not self.blockers:
                raise ValueError("terminal resolution states require blockers")
        else:
            if self.active_decision is None or self.active_decision_record_id is None:
                raise ValueError("non-terminal resolution requires the active record")
            if self.active_decision == "REJECT" and self.resolved_state != "REJECTED":
                raise ValueError("a rejected decision resolves to REJECTED")
            if self.active_decision == "ACCEPT_WITH_EXCEPTION":
                if self.active_exception_id is None:
                    raise ValueError("an accepted decision carries its exception id")
                expected: Literal[
                    "ACCEPT_VERIFIED", "ACCEPT_UNVERIFIED", "ACCEPT_AUTHORITY_REJECTED"
                ] = {
                    "OWNER_AUTHORITY_VERIFIED": "ACCEPT_VERIFIED",
                    "OWNER_AUTHORITY_UNVERIFIED": "ACCEPT_UNVERIFIED",
                    "OWNER_AUTHORITY_REJECTED": "ACCEPT_AUTHORITY_REJECTED",
                }[self.active_authority_status or ""]
                if self.resolved_state != expected:
                    raise ValueError("resolved state must mirror the authority status")
            if self.blockers:
                raise ValueError("non-terminal resolution carries no blockers")
        expected_id = deterministic_id(
            "owner-decision-authority-resolution",
            self.target_profile_id,
            self.target_profile_sha256,
            self.resolved_state,
            self.active_decision_record_id or "",
            self.active_decision_record_content_sha256 or "",
            sorted(self.stale_record_ids),
            sorted(self.revoked_record_ids),
            sorted(self.superseded_record_ids),
            sorted(self.blockers),
        )
        if self.resolution_id != expected_id:
            raise ValueError("resolution id disagrees with the bound content")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected_content = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        if self.content_sha256 != expected_content:
            raise ValueError("resolution content_sha256 does not match content")
        return self


def load_decision_record(path: str | Path) -> OwnerPolicyDecisionRecordV1:
    """Load and fully validate one decision record file (fail-closed)."""

    try:
        return OwnerPolicyDecisionRecordV1.model_validate(
            json.loads(_regular_file_bytes(Path(path)))
        )
    except OwnerDecisionError:
        raise
    except Exception as exc:
        raise OwnerDecisionError(
            f"decision record is not a valid owner_policy_decision_record_v1: "
            f"{path}: {str(exc)[:300]}"
        ) from exc


def load_decision_revocation(path: str | Path) -> OwnerPolicyDecisionRevocationV1:
    """Load and fully validate one revocation file (fail-closed)."""

    try:
        return OwnerPolicyDecisionRevocationV1.model_validate(
            json.loads(_regular_file_bytes(Path(path)))
        )
    except OwnerDecisionError:
        raise
    except Exception as exc:
        raise OwnerDecisionError(
            f"revocation is not a valid owner_policy_decision_revocation_v1: "
            f"{path}: {str(exc)[:300]}"
        ) from exc


def resolve_owner_decision_authority(
    *,
    target_profile_id: str,
    target_profile_sha256: str,
    records: Sequence[OwnerPolicyDecisionRecordV1],
    revocations: Sequence[OwnerPolicyDecisionRevocationV1] = (),
) -> DecisionAuthorityResolutionV1:
    """Resolve all records for one exact target identity, fail-closed."""

    by_id: dict[str, OwnerPolicyDecisionRecordV1] = {}
    for record in records:
        previous = by_id.get(record.decision_record_id)
        if previous is not None and previous != record:
            raise OwnerDecisionError(
                "conflicting records share one decision_record_id: "
                f"{record.decision_record_id}"
            )
        by_id[record.decision_record_id] = record

    for revocation in revocations:
        revoked = by_id.get(revocation.revoked_decision_record_id)
        if revoked is None:
            raise OwnerDecisionError(
                "revocation references an unknown decision record: "
                f"{revocation.revoked_decision_record_id}"
            )
        if (
            revoked.target_profile_id != revocation.target_profile_id
            or revoked.target_profile_sha256 != revocation.target_profile_sha256
        ):
            raise OwnerDecisionError(
                "revocation target binding differs from the revoked record: "
                f"{revocation.revocation_id}"
            )

    superseded: set[str] = set()
    for record in by_id.values():
        target_id = record.supersedes_decision_record_id
        if target_id is None:
            continue
        superseded_record = by_id.get(target_id)
        if superseded_record is None:
            raise OwnerDecisionError(
                "supersession references an unknown decision record: "
                f"{record.decision_record_id} -> {target_id}"
            )
        if (
            superseded_record.target_profile_id != record.target_profile_id
            or superseded_record.target_profile_sha256 != record.target_profile_sha256
        ):
            raise OwnerDecisionError(
                "supersession crosses target bindings: "
                f"{record.decision_record_id} -> {target_id}"
            )
        if target_id == record.decision_record_id:
            raise OwnerDecisionError("a record cannot supersede itself")
        superseded.add(target_id)
    for record in by_id.values():
        seen = {record.decision_record_id}
        cursor = record
        while cursor.supersedes_decision_record_id is not None:
            following = by_id[cursor.supersedes_decision_record_id]
            if following.decision_record_id in seen:
                raise OwnerDecisionError("supersession chain contains a cycle")
            seen.add(following.decision_record_id)
            cursor = following
    superseder_counts: dict[str, int] = {}
    for record in by_id.values():
        if record.supersedes_decision_record_id is not None:
            superseder_counts[record.supersedes_decision_record_id] = (
                superseder_counts.get(record.supersedes_decision_record_id, 0) + 1
            )
    doubly_superseded = {key for key, count in superseder_counts.items() if count > 1}
    if doubly_superseded:
        raise OwnerDecisionError(
            "multiple records supersede the same decision record: "
            f"{', '.join(sorted(doubly_superseded))}"
        )

    revoked_ids = {item.revoked_decision_record_id for item in revocations}
    current = [
        record
        for record in by_id.values()
        if record.target_profile_id == target_profile_id
        and record.target_profile_sha256 == target_profile_sha256
    ]
    stale_ids = sorted(
        record.decision_record_id
        for record in by_id.values()
        if record not in current
    )
    active = [
        record
        for record in current
        if record.decision_record_id not in revoked_ids
        and record.decision_record_id not in superseded
    ]

    resolved_state: Literal[
        "ACCEPT_VERIFIED",
        "ACCEPT_UNVERIFIED",
        "ACCEPT_AUTHORITY_REJECTED",
        "REJECTED",
        "NO_DECISION",
        "AMBIGUOUS",
        "CONFLICTING",
    ]
    blockers: list[str] = []
    active_record: OwnerPolicyDecisionRecordV1 | None = None

    if not by_id:
        resolved_state = "NO_DECISION"
        blockers.append("NO_OWNER_DECISION_RECORD")
    elif not current:
        resolved_state = "NO_DECISION"
        blockers.append("ALL_RECORDS_STALE")
    elif not active:
        resolved_state = "NO_DECISION"
        if revoked_ids and all(
            record.decision_record_id in revoked_ids for record in current
        ):
            blockers.append("ALL_CURRENT_RECORDS_REVOKED")
        else:
            blockers.append("ALL_CURRENT_RECORDS_SUPERSEDED_OR_REVOKED")
    elif len(active) > 1:
        decisions = {record.decision for record in active}
        if len(decisions) > 1:
            resolved_state = "CONFLICTING"
            blockers.append("CONFLICTING_DECISIONS")
        else:
            resolved_state = "AMBIGUOUS"
            blockers.append("AMBIGUOUS_MULTIPLE_ACTIVE_RECORDS")
    else:
        active_record = active[0]
        if active_record.decision == "REJECT":
            resolved_state = "REJECTED"
        else:
            resolved_state = {
                "OWNER_AUTHORITY_VERIFIED": "ACCEPT_VERIFIED",
                "OWNER_AUTHORITY_UNVERIFIED": "ACCEPT_UNVERIFIED",
                "OWNER_AUTHORITY_REJECTED": "ACCEPT_AUTHORITY_REJECTED",
            }[active_record.authority.authority_status]

    resolution = DecisionAuthorityResolutionV1.model_construct(
        contract="owner_decision_authority_resolution_v1",
        resolution_id="pending",
        target_profile_id=target_profile_id,
        target_profile_sha256=target_profile_sha256,
        supplied_record_count=len(records),
        stale_record_ids=stale_ids,
        revoked_record_ids=sorted(revoked_ids & set(by_id)),
        superseded_record_ids=sorted(superseded),
        resolved_state=resolved_state,
        active_decision=active_record.decision if active_record else None,
        active_decision_record_id=(
            active_record.decision_record_id if active_record else None
        ),
        active_decision_record_content_sha256=(
            active_record.content_sha256 if active_record else None
        ),
        active_authority_status=(
            active_record.authority.authority_status if active_record else None
        ),
        active_exception_id=(
            active_record.exception_id
            if active_record and active_record.exception_id is not None
            else None
        ),
        blockers=blockers,
        content_sha256="0" * 64,
    )
    payload = resolution.model_dump(mode="json", warnings=False)
    payload["resolution_id"] = deterministic_id(
        "owner-decision-authority-resolution",
        payload["target_profile_id"],
        payload["target_profile_sha256"],
        payload["resolved_state"],
        payload["active_decision_record_id"] or "",
        payload["active_decision_record_content_sha256"] or "",
        sorted(payload["stale_record_ids"]),
        sorted(payload["revoked_record_ids"]),
        sorted(payload["superseded_record_ids"]),
        sorted(payload["blockers"]),
    )
    payload["content_sha256"] = hashlib.sha256(
        canonical_json_bytes(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
    ).hexdigest()
    return DecisionAuthorityResolutionV1.model_validate(payload)


def record_owner_decision_file(
    record: OwnerPolicyDecisionRecordV1, output_path: str | Path
) -> Literal["CREATED", "IDEMPOTENT"]:
    """Persist one decision record create-only; byte-identical reruns are no-ops.

    A different record at the same path is refused rather than overwritten.
    """

    path = Path(output_path)
    if path.is_symlink():
        raise OwnerDecisionError(f"decision record output must not be a symlink: {path}")
    serialized = (
        json.dumps(
            record.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        )
        + "\n"
    ).encode("utf-8")
    if path.exists():
        if path.read_bytes() == serialized:
            return "IDEMPOTENT"
        raise OwnerDecisionError(
            "a different decision record already exists at this path (records are "
            "immutable; write a new path, or supersede/revoke explicitly): "
            f"{path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    # O_EXCL publication: never overwrite a racing writer.  A competing create
    # between the existence check and this open surfaces the same classified
    # immutability error (byte-identical racing writes are idempotent), never
    # a raw FileExistsError and never an overwrite.  fdopen takes ownership of
    # the descriptor; on failure only the file this call itself created
    # exclusively is removed, proven by inode so a racing replacement at the
    # same path is never deleted by mistake.
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        if path.is_symlink():
            raise OwnerDecisionError(
                f"decision record output must not be a symlink: {path}"
            ) from None
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise OwnerDecisionError(
                f"a decision record output appeared at this path and cannot be "
                f"read (records are immutable): {path}"
            ) from exc
        if existing == serialized:
            return "IDEMPOTENT"
        raise OwnerDecisionError(
            "a different decision record already exists at this path (records are "
            "immutable; write a new path, or supersede/revoke explicitly): "
            f"{path}"
        ) from None
    created_ino = os.fstat(descriptor).st_ino
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            if os.stat(path).st_ino == created_ino:
                path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return "CREATED"


__all__ = [
    "CHECK_AUDIT_FRESH_AND_MATCHING",
    "CHECK_DECISION_SHAPE_VALID",
    "CHECK_EXCEPTION_BINDING_EXACT",
    "CHECK_EXCEPTION_COVERS_ALL_FINDINGS",
    "CHECK_INPUT_BINDINGS_MATCH_BYTES",
    "CHECK_PROVENANCE_BOUND",
    "DecisionAuthorityResolutionV1",
    "DecisionProvenanceV1",
    "DecisionValidationCheckV1",
    "OwnerAuthorityAssessmentV1",
    "OwnerDecisionError",
    "OwnerDecisionVerifier",
    "OwnerPolicyDecisionInputV1",
    "OwnerPolicyDecisionRecordV1",
    "OwnerPolicyDecisionRevocationV1",
    "OwnerPolicyDecisionValidationV1",
    "REQUIRED_DECISION_VALIDATION_CHECKS",
    "load_decision_record",
    "load_decision_revocation",
    "record_owner_decision_file",
    "resolve_owner_decision_authority",
    "validate_owner_decision",
]
