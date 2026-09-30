"""Offline, review-only versioned profile release projection (Phase 7-B2-A)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from turtle_value_engine.config.models import RuleProfile
from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.providers.normalization import deterministic_id

from .candidate_projection import _candidate_yaml_bytes
from .materialize import (
    CandidateMetadataChangeV1,
    CandidateProfileMaterializationV1,
    CandidateRuleLeafChangeV1,
)

HASH = r"^[0-9a-f]{64}$"


class ProfileReleaseError(ValueError):
    """Release evidence or lineage does not meet the frozen B2-A contract."""


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _rules(profile: RuleProfile) -> dict:
    payload = profile.model_dump(mode="json", by_alias=True)
    del payload["profile"]
    return payload


def _changes(before: object, after: object, path: str = "") -> list[tuple[str, object, object]]:
    if isinstance(before, dict) and isinstance(after, dict):
        if before.keys() != after.keys():
            raise ProfileReleaseError("rule structure differs from the frozen base")
        return [
            change
            for key in sorted(before)
            for change in _changes(before[key], after[key], f"{path}.{key}" if path else key)
        ]
    if isinstance(before, list) or isinstance(after, list):
        if before != after:
            raise ProfileReleaseError(
                "structural rule change is outside the registered materialization"
            )
        return []
    return [(path, before, after)] if before != after else []


class VersionedProfileReleaseCandidateV1(BaseModel):
    """Immutable provenance and review state for exact PR-ready profile bytes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["versioned_profile_release_candidate_v1"] = (
        "versioned_profile_release_candidate_v1"
    )
    release_candidate_id: StrictStr = Field(min_length=1)
    source_materialization_id: StrictStr = Field(min_length=1)
    source_materialization_content_sha256: StrictStr = Field(pattern=HASH)
    evaluation_id: StrictStr = Field(min_length=1)
    evaluation_content_sha256: StrictStr = Field(pattern=HASH)
    freeze_anchor_id: StrictStr = Field(min_length=1)
    freeze_anchor_sha256: StrictStr = Field(pattern=HASH)
    evidence_binding_id: StrictStr = Field(min_length=1)
    evidence_binding_sha256: StrictStr = Field(pattern=HASH)
    experiment_id: StrictStr = Field(min_length=1)
    experiment_content_sha256: StrictStr = Field(pattern=HASH)
    proposal_id: StrictStr = Field(min_length=1)
    proposal_payload_sha256: StrictStr = Field(pattern=HASH)
    base_profile_id: StrictStr = Field(min_length=1)
    base_profile_sha256: StrictStr = Field(pattern=HASH)
    candidate_profile_id: StrictStr = Field(min_length=1)
    candidate_content_sha256: StrictStr = Field(pattern=HASH)
    target_profile_id: StrictStr = Field(min_length=1)
    intended_target_path: StrictStr = Field(min_length=1)
    release_profile_sha256: StrictStr = Field(pattern=HASH)
    candidate_rule_payload_sha256: StrictStr = Field(pattern=HASH)
    release_rule_payload_sha256: StrictStr = Field(pattern=HASH)
    metadata_changes: list[CandidateMetadataChangeV1] = Field(min_length=1, max_length=4)
    rule_changes: list[CandidateRuleLeafChangeV1] = Field(min_length=1, max_length=64)
    review_state: Literal["READY_FOR_HUMAN_PR_REVIEW"] = "READY_FOR_HUMAN_PR_REVIEW"
    requires_human_approval: Literal[True] = True
    automatic_merge_allowed: Literal[False] = False
    automatic_application_allowed: Literal[False] = False
    content_sha256: StrictStr = Field(pattern=HASH)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        base = re.fullmatch(r"strict-v([1-9][0-9]*)", self.base_profile_id)
        if base is None or self.target_profile_id != f"strict-v{int(base.group(1)) + 1}":
            raise ValueError("release manifest target is not the next strict version")
        if self.candidate_profile_id in {self.base_profile_id, self.target_profile_id}:
            raise ValueError("release candidate must be distinct from base and target")
        if self.candidate_rule_payload_sha256 != self.release_rule_payload_sha256:
            raise ValueError("candidate and release rule payload identities differ")
        if self.intended_target_path != f"rules/{self.target_profile_id}.yaml":
            raise ValueError("intended target path differs from target profile id")
        if self.release_candidate_id != deterministic_id(
            "versioned-profile-release-candidate",
            self.source_materialization_id,
            self.source_materialization_content_sha256,
            self.target_profile_id,
            self.release_profile_sha256,
        ):
            raise ValueError("release candidate id disagrees with bound artifacts")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        if self.content_sha256 != _digest(payload):
            raise ValueError("release candidate content hash disagrees with content")
        return self

    @classmethod
    def build(cls, **fields: object) -> Self:
        fields["release_candidate_id"] = deterministic_id(
            "versioned-profile-release-candidate",
            fields["source_materialization_id"],
            fields["source_materialization_content_sha256"],
            fields["target_profile_id"],
            fields["release_profile_sha256"],
        )
        fields["content_sha256"] = "0" * 64
        temporary = cls.model_construct(**fields)
        payload = temporary.model_dump(mode="json")
        payload["content_sha256"] = _digest(
            {k: v for k, v in payload.items() if k != "content_sha256"}
        )
        return cls.model_validate(payload)


@dataclass(frozen=True)
class ProfileReleaseBundle:
    profile_bytes: bytes
    profile: RuleProfile
    manifest: VersionedProfileReleaseCandidateV1


def build_profile_release(
    *,
    candidate_bytes: bytes,
    candidate: RuleProfile,
    materialization: CandidateProfileMaterializationV1,
    base_profile_bytes: bytes,
    target_profile_id: str,
) -> ProfileReleaseBundle:
    """Project exact B1 candidate into the next strict lineage, without I/O."""

    match = re.fullmatch(r"strict-v([1-9][0-9]*)", materialization.base_profile_id)
    if match is None or target_profile_id != f"strict-v{int(match.group(1)) + 1}":
        raise ProfileReleaseError("target must be exactly the next strict profile version")
    if hashlib.sha256(candidate_bytes).hexdigest() != materialization.candidate_content_sha256:
        raise ProfileReleaseError("candidate bytes differ from materialization")
    if candidate.profile.id != materialization.candidate_profile_id:
        raise ProfileReleaseError("candidate identity differs from materialization")
    if hashlib.sha256(base_profile_bytes).hexdigest() != materialization.base_profile_sha256:
        raise ProfileReleaseError("base profile bytes differ from materialization")
    try:
        base = RuleProfile.model_validate(yaml.safe_load(base_profile_bytes))
    except Exception as exc:
        raise ProfileReleaseError("base profile cannot be validated") from exc
    if base.profile.id != materialization.base_profile_id:
        raise ProfileReleaseError("base profile id differs from materialization")
    payload = candidate.model_dump(mode="json", by_alias=True)
    payload["profile"] = {
        "id": target_profile_id,
        "name": f"Turtle Value Engine Strict v{int(match.group(1)) + 1}",
        "status": base.profile.status,
        "description": base.profile.description,
    }
    release = RuleProfile.model_validate(payload)
    release_bytes = _candidate_yaml_bytes(release.model_dump(mode="json", by_alias=True))
    if RuleProfile.model_validate(yaml.safe_load(release_bytes)) != release:
        raise ProfileReleaseError("release profile round-trip failed")
    if _rules(candidate) != _rules(release):
        raise ProfileReleaseError("candidate to release changed rule-bearing fields")
    actual = _changes(_rules(base), _rules(release))
    expected = sorted(
        [
            (change.profile_path, change.before, change.after)
            for change in materialization.rule_changes
        ],
        key=lambda item: item[0],
    )
    if actual != expected:
        raise ProfileReleaseError("base to release rule changes differ from materialization")
    metadata = [
        CandidateMetadataChangeV1(
            field=key, before=getattr(candidate.profile, key), after=getattr(release.profile, key)
        )
        for key in ("id", "name", "status", "description")
        if getattr(candidate.profile, key) != getattr(release.profile, key)
    ]
    rules_digest = _digest(_rules(candidate))
    manifest = VersionedProfileReleaseCandidateV1.build(
        source_materialization_id=materialization.materialization_id,
        source_materialization_content_sha256=materialization.content_sha256,
        evaluation_id=materialization.evaluation_id,
        evaluation_content_sha256=materialization.evaluation_content_sha256,
        freeze_anchor_id=materialization.freeze_anchor_id,
        freeze_anchor_sha256=materialization.freeze_anchor_sha256,
        evidence_binding_id=materialization.evidence_binding_id,
        evidence_binding_sha256=materialization.evidence_binding_sha256,
        experiment_id=materialization.experiment_id,
        experiment_content_sha256=materialization.experiment_content_sha256,
        proposal_id=materialization.proposal_id,
        proposal_payload_sha256=materialization.proposal_payload_sha256,
        base_profile_id=materialization.base_profile_id,
        base_profile_sha256=materialization.base_profile_sha256,
        candidate_profile_id=materialization.candidate_profile_id,
        candidate_content_sha256=materialization.candidate_content_sha256,
        target_profile_id=target_profile_id,
        intended_target_path=f"rules/{target_profile_id}.yaml",
        release_profile_sha256=hashlib.sha256(release_bytes).hexdigest(),
        candidate_rule_payload_sha256=rules_digest,
        release_rule_payload_sha256=_digest(_rules(release)),
        metadata_changes=metadata,
        rule_changes=materialization.rule_changes,
    )
    return ProfileReleaseBundle(release_bytes, release, manifest)
