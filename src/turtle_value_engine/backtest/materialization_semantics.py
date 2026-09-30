"""Versioned materializable-parameter semantics for calibration candidates.

Phase 7-B1 freezes the only sanctioned bridge from a calibration parameter to
a concrete ``RuleProfile`` scalar leaf.  A parameter is materializable exactly
when the calibration search space carries a reference to one *installed*
semantics set whose deterministic identity (``semantics_id``, version and
content hash) is therefore covered by the experiment identity and, through the
unchanged Phase 7-A-R2 chain, by the authoritative calibration freeze.

Nothing here interprets a parameter *name*.  The binding from parameter key to
rule leaf is data frozen inside the registry, validated at
``CalibrationRunner`` construction — before any trial is scored — so a
semantics mapping first supplied at materialization time can never match.  A
reference that does not resolve to an installed set (post-hoc substitution,
unknown version, drifted content) fails closed.

The registry in this module is deliberately pure data: parameter keys,
operator/feature identities and concrete dotted rule-leaf targets with a
scalar type/range contract.  Applying a target to a real ``RuleProfile`` is
the separate projection boundary in ``turtle_value_engine.evolution``; this
module never imports the profile model, so the calibration layer stays
independent of rule-profile loading.
"""

from __future__ import annotations

import hashlib
import math
from typing import TYPE_CHECKING, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictStr,
    model_validator,
)

from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.providers.normalization import deterministic_id

if TYPE_CHECKING:
    from .contracts import CalibrationSearchSpace

SEMANTICS_CONTRACT_VERSION = "materializable-parameter-semantics-v1"
MATERIALIZABLE_SEMANTICS_NAMESPACE = "materializable-parameter-semantics"
_SEMANTICS_ID_PATTERN = r"^materializable-parameter-semantics-[0-9a-f]{24}$"
_HASH_PATTERN = r"^[0-9a-f]{64}$"

#: The operator prefixes the canonical built-in calibration scorer derives
#: from parameter names.  A materializable parameter must declare which of
#: these generic feature-filter operators the calibration applied to it, and
#: its key must be exactly the prefix plus the declared observation feature,
#: so the frozen semantics describe the scorer behavior that actually ran.
OPERATOR_PREFIXES: dict[str, str] = {
    "MIN_FEATURE_THRESHOLD": "min_",
    "MAX_FEATURE_THRESHOLD": "max_",
    "EQUALS_FEATURE_VALUE": "equals_",
}


class MaterializationSemanticsError(ValueError):
    """Raised when materialization semantics cannot be resolved or honored."""


class RegisteredRuleTargetV1(BaseModel):
    """One concrete scalar ``RuleProfile`` leaf a parameter may materialize into.

    ``profile_path`` is the dotted path of YAML-visible field names from the
    profile root to the scalar leaf (for example ``cdc.yield_bands.pass``).
    Structural targets — lists, objects or paths that do not resolve to a
    scalar leaf — are not representable in this contract and fail closed at
    projection time.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["registered_rule_target_v1"] = "registered_rule_target_v1"
    target_key: StrictStr = Field(min_length=1)
    profile_path: StrictStr = Field(min_length=3)
    leaf_type: Literal["FLOAT", "INT"]
    minimum: StrictFloat | None = None
    maximum: StrictFloat | None = None
    exclusive_minimum: StrictBool = False
    exclusive_maximum: StrictBool = False

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        segments = self.profile_path.split(".")
        if len(segments) < 2 or not all(
            segment and segment.replace("_", "").isalnum() for segment in segments
        ):
            raise ValueError(
                "registered rule target profile_path must be a dotted path of "
                f"identifier segments: {self.profile_path!r}"
            )
        if self.minimum is not None and not math.isfinite(self.minimum):
            raise ValueError("registered rule target minimum must be finite")
        if self.maximum is not None and not math.isfinite(self.maximum):
            raise ValueError("registered rule target maximum must be finite")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("registered rule target minimum exceeds maximum")
        return self

    def validate_candidate_value(self, value: float | int | str | bool) -> float | int:
        """Validate one candidate value against the frozen type/range contract.

        Returns the value coerced to the contract's scalar type.  Booleans are
        rejected for both leaf types (a bool is an ``equals_`` filter operand,
        never a numeric rule threshold), ``INT`` leaves require a true integer
        (no silent float truncation) and ``FLOAT`` leaves accept finite
        integers and floats only.
        """

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MaterializationSemanticsError(
                f"target {self.target_key} requires a "
                f"{'integer' if self.leaf_type == 'INT' else 'numeric'} candidate "
                f"value, got {value!r}"
            )
        if self.leaf_type == "INT":
            if not isinstance(value, int):
                raise MaterializationSemanticsError(
                    f"target {self.target_key} requires an integer candidate value, "
                    f"got {value!r}"
                )
            number: float | int = value
        else:
            number = float(value)
        if not math.isfinite(number):
            raise MaterializationSemanticsError(
                f"target {self.target_key} requires a finite candidate value"
            )
        if self.minimum is not None:
            # An exclusive minimum demands strictly greater values, so the
            # rejected band includes the boundary itself.
            below = number <= self.minimum if self.exclusive_minimum else number < self.minimum
            if below:
                edge = "above" if self.exclusive_minimum else "at or above"
                raise MaterializationSemanticsError(
                    f"candidate value {value!r} for target {self.target_key} must be "
                    f"{edge} {self.minimum}"
                )
        if self.maximum is not None:
            above = number >= self.maximum if self.exclusive_maximum else number > self.maximum
            if above:
                edge = "below" if self.exclusive_maximum else "at or below"
                raise MaterializationSemanticsError(
                    f"candidate value {value!r} for target {self.target_key} must be "
                    f"{edge} {self.maximum}"
                )
        return number


class MaterializableParameterSemanticsV1(BaseModel):
    """The frozen semantics of one materializable calibration parameter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["materializable_parameter_semantics_v1"] = (
        "materializable_parameter_semantics_v1"
    )
    parameter_key: StrictStr = Field(min_length=1)
    operator: Literal["MIN_FEATURE_THRESHOLD", "MAX_FEATURE_THRESHOLD", "EQUALS_FEATURE_VALUE"]
    observation_feature: StrictStr = Field(min_length=1)
    target: RegisteredRuleTargetV1

    @model_validator(mode="after")
    def validate_parameter(self) -> Self:
        prefix = OPERATOR_PREFIXES[self.operator]
        if self.parameter_key != prefix + self.observation_feature:
            raise ValueError(
                "materializable parameter key must be the operator prefix plus the "
                f"observation feature (expected {prefix + self.observation_feature!r}, "
                f"got {self.parameter_key!r})"
            )
        return self


class MaterializationSemanticsReferenceV1(BaseModel):
    """The calibration-time reference to one frozen semantics set.

    This is the additive field ``CalibrationSearchSpace.materialization_semantics``.
    Because the search space is part of the deterministic experiment identity,
    a semantics-bearing search space freezes its semantics identity before any
    trial is scored; the reference resolves only against an installed set.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["materialization_semantics_reference_v1"] = (
        "materialization_semantics_reference_v1"
    )
    semantics_id: StrictStr = Field(pattern=_SEMANTICS_ID_PATTERN)
    semantics_version: StrictStr = Field(min_length=1)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)


class MaterializableParameterSemanticsSetV1(BaseModel):
    """One versioned, installed set of materializable-parameter semantics.

    The set recomputes its deterministic ``semantics_id`` from its version and
    parameter payload, and its ``content_sha256`` over the full persisted
    payload, so any change to a binding, target path, type or range contract
    changes the identity a search-space reference must match exactly.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["materializable_parameter_semantics_set_v1"] = (
        "materializable_parameter_semantics_set_v1"
    )
    semantics_id: StrictStr = Field(pattern=_SEMANTICS_ID_PATTERN)
    semantics_version: StrictStr = Field(min_length=1)
    parameters: dict[str, MaterializableParameterSemanticsV1] = Field(
        min_length=1, max_length=64
    )
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_set(self) -> Self:
        for key, parameter in self.parameters.items():
            if key != parameter.parameter_key:
                raise ValueError(
                    f"semantics parameter map key {key!r} must equal parameter_key"
                )
        expected_id = deterministic_id(
            MATERIALIZABLE_SEMANTICS_NAMESPACE,
            self.semantics_version,
            self._parameter_payload(self.parameters),
        )
        if self.semantics_id != expected_id:
            raise ValueError(
                "semantics_id does not match the deterministic identity of the "
                "parameter payload"
            )
        payload = self.model_dump(mode="json", warnings=False, exclude={"content_sha256"})
        expected = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        if self.content_sha256 != expected:
            raise ValueError("semantics content_sha256 does not match content")
        return self

    def reference(self) -> MaterializationSemanticsReferenceV1:
        """The calibration-time reference to this exact set."""

        return MaterializationSemanticsReferenceV1(
            semantics_id=self.semantics_id,
            semantics_version=self.semantics_version,
            content_sha256=self.content_sha256,
        )

    @staticmethod
    def _parameter_payload(
        parameters: dict[str, MaterializableParameterSemanticsV1],
    ) -> dict[str, dict]:
        return {
            key: value.model_dump(mode="json", warnings=False)
            for key, value in sorted(parameters.items())
        }

    @classmethod
    def build(
        cls,
        *,
        semantics_version: str,
        parameters: dict[str, MaterializableParameterSemanticsV1],
    ) -> MaterializableParameterSemanticsSetV1:
        """Construct a semantics set with its deterministic id and content hash."""

        semantics_id = deterministic_id(
            MATERIALIZABLE_SEMANTICS_NAMESPACE,
            semantics_version,
            cls._parameter_payload(parameters),
        )
        candidate = cls.model_construct(
            contract="materializable_parameter_semantics_set_v1",
            semantics_id=semantics_id,
            semantics_version=semantics_version,
            parameters=parameters,
            content_sha256="0" * 64,
        )
        payload = candidate.model_dump(mode="json", warnings=False)
        payload["content_sha256"] = hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in payload.items() if key != "content_sha256"}
            )
        ).hexdigest()
        return cls.model_validate(payload)


def _built_in_semantics_v1() -> MaterializableParameterSemanticsSetV1:
    """The one installed Phase 7-B1 registry of materializable parameters.

    Every target below is a real scalar leaf of ``rules/strict-v1.yaml``
    whose model contract is mirrored here (``cdc.yield_bands.pass`` and
    ``through_return.formal_candidate_threshold`` are floats greater than
    zero; the business-quality bands are integers).  The canonical fixture
    parameter ``min_quality`` is deliberately absent: no pre-B1 experiment
    froze semantics for it, and B1 never invents a mapping for it.
    """

    targets = {
        "cdc-yield-bands-pass": RegisteredRuleTargetV1(
            target_key="cdc-yield-bands-pass",
            profile_path="cdc.yield_bands.pass",
            leaf_type="FLOAT",
            minimum=0,
            exclusive_minimum=True,
        ),
        "business-quality-score-bands-pass": RegisteredRuleTargetV1(
            target_key="business-quality-score-bands-pass",
            profile_path="business_quality.score_bands.pass",
            leaf_type="INT",
            minimum=0,
            maximum=40,
        ),
        "business-quality-evidence-score-4-min-strong": RegisteredRuleTargetV1(
            target_key="business-quality-evidence-score-4-min-strong",
            profile_path="business_quality.evidence_requirements.score_4_min_strong_evidence",
            leaf_type="INT",
            minimum=0,
            maximum=10,
        ),
        "net-cash-leverage-max-net-debt-to-ebitda-pass": RegisteredRuleTargetV1(
            target_key="net-cash-leverage-max-net-debt-to-ebitda-pass",
            profile_path="net_cash.leverage.max_net_debt_to_ebitda_pass",
            leaf_type="FLOAT",
        ),
        "through-return-formal-candidate-threshold": RegisteredRuleTargetV1(
            target_key="through-return-formal-candidate-threshold",
            profile_path="through_return.formal_candidate_threshold",
            leaf_type="FLOAT",
            minimum=0,
            exclusive_minimum=True,
        ),
    }

    def _parameter(
        key: str,
        operator: str,
        feature: str,
        target_key: str,
    ) -> MaterializableParameterSemanticsV1:
        return MaterializableParameterSemanticsV1(
            parameter_key=key,
            operator=operator,  # type: ignore[arg-type]
            observation_feature=feature,
            target=targets[target_key],
        )

    return MaterializableParameterSemanticsSetV1.build(
        semantics_version="b1-v1",
        parameters={
            "min_cdc_yield": _parameter(
                "min_cdc_yield",
                "MIN_FEATURE_THRESHOLD",
                "cdc_yield",
                "cdc-yield-bands-pass",
            ),
            "min_business_quality_score": _parameter(
                "min_business_quality_score",
                "MIN_FEATURE_THRESHOLD",
                "business_quality_score",
                "business-quality-score-bands-pass",
            ),
            "max_net_debt_to_ebitda": _parameter(
                "max_net_debt_to_ebitda",
                "MAX_FEATURE_THRESHOLD",
                "net_debt_to_ebitda",
                "net-cash-leverage-max-net-debt-to-ebitda-pass",
            ),
            "min_through_return_yield": _parameter(
                "min_through_return_yield",
                "MIN_FEATURE_THRESHOLD",
                "through_return_yield",
                "through-return-formal-candidate-threshold",
            ),
        },
    )


#: The installed semantics sets.  A search-space reference resolves against
#: exactly these; version drift, content drift or an unknown id fails closed.
INSTALLED_MATERIALIZATION_SEMANTICS: tuple[MaterializableParameterSemanticsSetV1, ...] = (
    _built_in_semantics_v1(),
)


def resolve_materialization_semantics(
    reference: MaterializationSemanticsReferenceV1,
) -> MaterializableParameterSemanticsSetV1:
    """Resolve a frozen reference against the installed semantics sets.

    The id, version and content hash must all match one installed set exactly.
    A mismatched triple — a mutated registry, an unknown version or a foreign
    id — is a post-hoc semantics substitution and fails closed.
    """

    for installed in INSTALLED_MATERIALIZATION_SEMANTICS:
        if (
            installed.semantics_id == reference.semantics_id
            and installed.semantics_version == reference.semantics_version
            and installed.content_sha256 == reference.content_sha256
        ):
            return installed
    raise MaterializationSemanticsError(
        "materialization semantics reference does not resolve to an installed "
        f"set (semantics_id={reference.semantics_id}, version="
        f"{reference.semantics_version}, content={reference.content_sha256}); "
        "post-hoc semantics substitution is not admissible"
    )


def validate_materializable_search_space(
    search_space: CalibrationSearchSpace,
) -> MaterializableParameterSemanticsSetV1 | None:
    """Validate a search space's frozen semantics before any trial is scored.

    Returns the resolved installed set when the search space declares
    ``materialization_semantics``, or ``None`` for a legacy/unbound search
    space (readable and evaluable history, never materializable).  When a
    reference is present, every search-space parameter must be registered in
    the resolved set and every candidate value must satisfy the registered
    type/range contract — fail closed at the calibration boundary, long
    before any winner is known.
    """

    reference = search_space.materialization_semantics
    if reference is None:
        return None
    semantics = resolve_materialization_semantics(reference)
    for name, values in sorted(search_space.parameters.items()):
        if name not in semantics.parameters:
            raise MaterializationSemanticsError(
                f"search-space parameter {name!r} is not registered in the frozen "
                f"materialization semantics {semantics.semantics_id} "
                f"(v{semantics.semantics_version}); a semantics-bearing search "
                "space may calibrate only registered parameters"
            )
        target = semantics.parameters[name].target
        for value in values:
            target.validate_candidate_value(value)
    return semantics


__all__ = [
    "INSTALLED_MATERIALIZATION_SEMANTICS",
    "MATERIALIZABLE_SEMANTICS_NAMESPACE",
    "MaterializationSemanticsError",
    "MaterializationSemanticsReferenceV1",
    "MaterializableParameterSemanticsSetV1",
    "MaterializableParameterSemanticsV1",
    "OPERATOR_PREFIXES",
    "RegisteredRuleTargetV1",
    "SEMANTICS_CONTRACT_VERSION",
    "resolve_materialization_semantics",
    "validate_materializable_search_space",
]
