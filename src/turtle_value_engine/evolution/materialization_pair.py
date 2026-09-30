"""Read-only authority check for a published candidate/materialization pair."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from turtle_value_engine.config.models import RuleProfile

from .materialize import CandidateProfileMaterializationV1


class MaterializationPairError(ValueError):
    """A candidate and its final authority record do not form a valid pair."""


@dataclass(frozen=True)
class CompleteMaterializationPair:
    candidate_bytes: bytes
    candidate_profile: RuleProfile
    record: CandidateProfileMaterializationV1


def _regular_file_bytes(path: Path) -> bytes:
    if path.is_symlink():
        raise MaterializationPairError(f"materialization artifact is a symlink: {path}")
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise MaterializationPairError(f"materialization artifact is unavailable: {path}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise MaterializationPairError(
                f"materialization artifact is not a regular file: {path}"
            )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            return handle.read()
    finally:
        os.close(descriptor)


def resolve_complete_materialization_pair(
    candidate_path: str | Path, record_path: str | Path
) -> CompleteMaterializationPair:
    """Admit only a complete immutable review pair with exact candidate bytes.

    An orphan candidate from process death is not a materialization.  The
    final record is the authority marker, and both files must validate on
    every read before any downstream B2 use.
    """

    record_bytes = _regular_file_bytes(Path(record_path))
    candidate_bytes = _regular_file_bytes(Path(candidate_path))
    try:
        record = CandidateProfileMaterializationV1.model_validate(
            json.loads(record_bytes)
        )
        candidate = RuleProfile.model_validate(yaml.safe_load(candidate_bytes))
    except (ValueError, ValidationError, yaml.YAMLError, UnicodeDecodeError) as exc:
        raise MaterializationPairError("invalid materialization record or candidate") from exc
    if hashlib.sha256(candidate_bytes).hexdigest() != record.candidate_content_sha256:
        raise MaterializationPairError("candidate bytes do not match the materialization hash")
    if candidate.profile.id != record.candidate_profile_id:
        raise MaterializationPairError("candidate profile id does not match the record")
    return CompleteMaterializationPair(candidate_bytes, candidate, record)
