"""Deterministic candidate-only ``RuleProfile`` projection (Phase 7-B1).

This is the pure projection boundary between an admitted
``CandidateProfileProposal`` and candidate-only rule-profile *bytes*.  It
reads the exact base-profile bytes supplied by the caller, verifies them
against the proposal identity, parses them through the ordinary YAML ->
``RuleProfile`` validation path, applies only the frozen registered scalar
overrides to an in-memory copy, assigns deterministic candidate-only
metadata, validates the complete resulting profile again and serializes
canonical candidate bytes.

It never writes a file, never touches ``rules/`` and never assigns the human
release name ``strict-v2``: the candidate id is the proposal's deterministic
``candidate_profile_id``.  Only registered rule targets are applied; there is
no caller-provided path surface, and structural (list/object) targets are not
representable in the frozen semantics contract.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import yaml

from turtle_value_engine.backtest.contracts import CandidateProfileProposal
from turtle_value_engine.backtest.materialization_semantics import (
    MaterializableParameterSemanticsSetV1,
)
from turtle_value_engine.config.models import RuleProfile
from turtle_value_engine.providers.models import canonical_json_bytes

_CANDIDATE_PROFILE_STATUS = "candidate-proposal"


class CandidateProjectionError(ValueError):
    """Raised when a candidate profile cannot be projected fail-closed."""


@dataclass(frozen=True)
class RuleLeafChange:
    """One registered rule leaf changed by the projection."""

    target_key: str
    profile_path: str
    before: float | int | str | bool
    after: float | int | str | bool


@dataclass(frozen=True)
class ProfileMetadataChange:
    """One candidate-only metadata field changed by the projection."""

    field: str
    before: str
    after: str


@dataclass(frozen=True)
class ProjectedCandidate:
    """The deterministic output of one candidate projection."""

    base_profile: RuleProfile
    profile: RuleProfile
    candidate_bytes: bytes
    candidate_content_sha256: str
    rule_changes: tuple[RuleLeafChange, ...]
    metadata_changes: tuple[ProfileMetadataChange, ...]


def _load_profile_dict(base_profile_bytes: bytes) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(base_profile_bytes.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise CandidateProjectionError(f"base profile is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise CandidateProjectionError("base profile must contain a YAML object")
    return raw


def _leaf_owner(
    payload: dict[str, Any], profile_path: str
) -> tuple[dict[str, Any], str, float | int | str | bool]:
    """Resolve a registered dotted path to its scalar leaf, fail-closed.

    Structural targets cannot resolve: every intermediate segment must index
    a mapping and the final segment must address a scalar (never a list or
    mapping).  The path always comes from the frozen semantics registry —
    no caller-provided path ever reaches this function.
    """

    segments = profile_path.split(".")
    owner: dict[str, Any] = payload
    for segment in segments[:-1]:
        nested = owner.get(segment)
        if not isinstance(nested, dict):
            raise CandidateProjectionError(
                f"registered target path {profile_path!r} does not address a "
                "scalar leaf in the base profile"
            )
        owner = nested
    leaf = segments[-1]
    if leaf not in owner:
        raise CandidateProjectionError(
            f"registered target path {profile_path!r} is absent from the base "
            "profile; the semantics registry does not match the supplied bytes"
        )
    value = owner[leaf]
    if isinstance(value, (dict, list)) or value is None:
        raise CandidateProjectionError(
            f"registered target path {profile_path!r} addresses a structural or "
            "missing value; only scalar rule leaves are materializable"
        )
    return owner, leaf, value


def candidate_metadata(
    proposal: CandidateProfileProposal,
    semantics: MaterializableParameterSemanticsSetV1,
    base_profile: RuleProfile,
    base_profile_sha256: str,
) -> dict[str, str]:
    """Deterministic candidate-only ``profile`` metadata block."""

    return {
        "id": proposal.candidate_profile_id,
        "name": (
            f"Candidate {proposal.candidate_profile_id} of {base_profile.profile.name}"
        ),
        "status": _CANDIDATE_PROFILE_STATUS,
        "description": (
            "Candidate-only projection of profile "
            f"{proposal.base_profile_id} (sha256 {base_profile_sha256}) from "
            f"proposal {proposal.proposal_id} under materialization semantics "
            f"{semantics.semantics_id} v{semantics.semantics_version}. "
            "Review artifact generated by Phase 7-B1; requires human approval, "
            "is never applied automatically and is not an installed rule profile."
        ),
    }


def _candidate_yaml_bytes(payload: dict[str, Any]) -> bytes:
    return yaml.safe_dump(
        payload,
        sort_keys=True,
        allow_unicode=True,
        default_flow_style=False,
        width=4_096,
    ).encode("utf-8")


def project_candidate_profile(
    *,
    base_profile_bytes: bytes,
    proposal: CandidateProfileProposal,
    semantics: MaterializableParameterSemanticsSetV1,
) -> ProjectedCandidate:
    """Project one admitted proposal into candidate-only profile bytes.

    Every step fail-closes before any candidate byte exists: base-byte hash,
    base-profile identity, registration and value contracts of every
    override, scalar-leaf resolution and full post-mutation validation.  The
    serialized candidate bytes are proven to round-trip through the ordinary
    loader validation before they are returned.
    """

    base_sha256 = hashlib.sha256(base_profile_bytes).hexdigest()
    if base_sha256 != proposal.base_profile_sha256:
        raise CandidateProjectionError(
            "supplied base-profile bytes hash to "
            f"{base_sha256}, but the proposal froze {proposal.base_profile_sha256}"
        )

    payload = _load_profile_dict(base_profile_bytes)
    try:
        base_profile = RuleProfile.model_validate(payload)
    except Exception as exc:
        raise CandidateProjectionError(
            f"base profile bytes do not validate as a RuleProfile: {exc}"
        ) from exc
    if base_profile.profile.id != proposal.base_profile_id:
        raise CandidateProjectionError(
            "base profile id disagrees with the proposal (profile declares "
            f"{base_profile.profile.id!r}, proposal froze "
            f"{proposal.base_profile_id!r})"
        )

    rule_changes: list[RuleLeafChange] = []
    applied_paths: set[str] = set()
    for key in sorted(proposal.parameter_overrides):
        parameter = semantics.parameters.get(key)
        if parameter is None:
            raise CandidateProjectionError(
                f"proposal override {key!r} is not registered in the frozen "
                f"materialization semantics {semantics.semantics_id}"
            )
        target = parameter.target
        if target.profile_path in applied_paths:
            raise CandidateProjectionError(
                f"registered target path {target.profile_path!r} would be applied "
                "twice; one rule leaf may receive at most one override"
            )
        applied_paths.add(target.profile_path)
        normalized = target.validate_candidate_value(proposal.parameter_overrides[key])
        owner, leaf, before = _leaf_owner(payload, target.profile_path)
        if target.leaf_type == "INT":
            if not isinstance(before, int) or isinstance(before, bool):
                raise CandidateProjectionError(
                    f"registered target {target.target_key} expects an integer leaf "
                    f"but the base profile carries {before!r}"
                )
        else:
            if isinstance(before, bool) or not isinstance(before, (int, float)):
                raise CandidateProjectionError(
                    f"registered target {target.target_key} expects a numeric leaf "
                    f"but the base profile carries {before!r}"
                )
        owner[leaf] = normalized
        rule_changes.append(
            RuleLeafChange(
                target_key=target.target_key,
                profile_path=target.profile_path,
                before=before,
                after=normalized,
            )
        )

    metadata = candidate_metadata(proposal, semantics, base_profile, base_sha256)
    metadata_changes = [
        ProfileMetadataChange(field=field, before=str(before), after=str(after))
        for field, (before, after) in {
            "id": (base_profile.profile.id, metadata["id"]),
            "name": (base_profile.profile.name, metadata["name"]),
            "status": (base_profile.profile.status, metadata["status"]),
            "description": (base_profile.profile.description, metadata["description"]),
        }.items()
    ]
    payload["profile"] = metadata

    try:
        candidate_profile = RuleProfile.model_validate(payload)
    except Exception as exc:
        raise CandidateProjectionError(
            f"projected candidate profile does not validate as a RuleProfile: {exc}"
        ) from exc
    if candidate_profile.profile.id == "strict-v2":
        raise CandidateProjectionError(
            "candidate projection must never assign the human release name strict-v2"
        )

    candidate_bytes = _candidate_yaml_bytes(
        candidate_profile.model_dump(mode="json", warnings=False, by_alias=True)
    )
    round_trip = _load_profile_dict(candidate_bytes)
    try:
        replayed = RuleProfile.model_validate(round_trip)
    except Exception as exc:
        raise CandidateProjectionError(
            f"candidate bytes do not round-trip through profile validation: {exc}"
        ) from exc
    if replayed != candidate_profile:
        raise CandidateProjectionError(
            "candidate bytes do not round-trip to the projected profile model"
        )

    return ProjectedCandidate(
        base_profile=base_profile,
        profile=candidate_profile,
        candidate_bytes=candidate_bytes,
        candidate_content_sha256=hashlib.sha256(candidate_bytes).hexdigest(),
        rule_changes=tuple(sorted(rule_changes, key=lambda item: item.profile_path)),
        metadata_changes=tuple(metadata_changes),
    )


def candidate_payload_digest(model: RuleProfile) -> str:
    """Deterministic digest of a projected profile's typed payload."""

    return hashlib.sha256(
        canonical_json_bytes(model.model_dump(mode="json", warnings=False, by_alias=True))
    ).hexdigest()


__all__ = [
    "CandidateProjectionError",
    "ProfileMetadataChange",
    "ProjectedCandidate",
    "RuleLeafChange",
    "candidate_metadata",
    "candidate_payload_digest",
    "project_candidate_profile",
]
