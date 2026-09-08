"""Load and validate versioned YAML rule profiles."""

from pathlib import Path
from typing import Any

import yaml

from .models import RuleProfile


class ProfileLoadError(ValueError):
    """Raised when a rule profile cannot be located or validated."""


def _candidate_profile_paths(profile: str | Path, rules_dir: Path | None) -> list[Path]:
    requested = Path(profile)
    if requested.exists() or requested.suffix in {".yaml", ".yml"}:
        return [requested]

    profile_name = str(profile)
    filename = f"{profile_name}.yaml"
    candidates: list[Path] = []
    if rules_dir is not None:
        candidates.append(rules_dir / filename)
    candidates.extend(
        [
            Path.cwd() / "rules" / filename,
            Path(__file__).resolve().parents[3] / "rules" / filename,
        ]
    )
    return candidates


def load_profile(
    profile: str | Path = "strict-v1", *, rules_dir: Path | None = None
) -> RuleProfile:
    """Load a named or explicit YAML profile and validate every known field.

    Named profiles are resolved from ``rules_dir``, the current repository's
    ``rules/`` directory, or the repository root relative to this package.  An
    explicit YAML path is used directly.  Unknown YAML fields are rejected by
    the Pydantic model so rule drift cannot silently change runtime behavior.
    """

    candidates = _candidate_profile_paths(profile, rules_dir)
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        searched = ", ".join(str(candidate) for candidate in candidates)
        raise ProfileLoadError(f"rule profile not found; searched: {searched}")

    try:
        with path.open("r", encoding="utf-8") as handle:
            raw: Any = yaml.safe_load(handle)
    except OSError as exc:
        raise ProfileLoadError(f"cannot read rule profile {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ProfileLoadError(f"invalid YAML in rule profile {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ProfileLoadError(f"rule profile {path} must contain a YAML object")

    try:
        loaded = RuleProfile.model_validate(raw)
    except Exception as exc:  # Pydantic's validation error is part of the public message.
        raise ProfileLoadError(f"invalid rule profile {path}: {exc}") from exc

    requested_name = str(profile)
    if not Path(profile).exists() and Path(profile).suffix not in {".yaml", ".yml"}:
        if loaded.profile.id != requested_name:
            raise ProfileLoadError(
                f"requested profile {requested_name!r} but file declares {loaded.profile.id!r}"
            )
    return loaded
