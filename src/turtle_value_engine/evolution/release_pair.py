"""Read-only complete-release resolver; the manifest is the authority marker."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from turtle_value_engine.config.models import RuleProfile

from .materialization_pair import _regular_file_bytes
from .profile_release import (
    ProfileReleaseBundle,
    ProfileReleaseError,
    VersionedProfileReleaseCandidateV1,
    _digest,
    _rules,
)


def resolve_complete_profile_release(
    profile_path: str | Path, manifest_path: str | Path
) -> ProfileReleaseBundle:
    """Validate both regular files and every identity on each read, without repair."""

    try:
        manifest_bytes = _regular_file_bytes(Path(manifest_path))
        profile_bytes = _regular_file_bytes(Path(profile_path))
        manifest = VersionedProfileReleaseCandidateV1.model_validate(json.loads(manifest_bytes))
        profile = RuleProfile.model_validate(yaml.safe_load(profile_bytes))
    except Exception as exc:
        raise ProfileReleaseError("release bundle is missing, non-regular or invalid") from exc
    if hashlib.sha256(profile_bytes).hexdigest() != manifest.release_profile_sha256:
        raise ProfileReleaseError("release profile bytes do not match manifest")
    if profile.profile.id != manifest.target_profile_id:
        raise ProfileReleaseError("release profile identity does not match manifest")
    if _digest(_rules(profile)) != manifest.release_rule_payload_sha256:
        raise ProfileReleaseError("release rules do not match manifest")
    if Path(profile_path).name != f"{manifest.target_profile_id}.yaml":
        raise ProfileReleaseError("release output filename does not match target identity")
    return ProfileReleaseBundle(profile_bytes, profile, manifest)
