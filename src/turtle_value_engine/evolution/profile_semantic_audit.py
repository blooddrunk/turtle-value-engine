"""Offline, read-only versioned-profile semantic audit (Phase 7-C1).

The audit answers three separable questions for one published base -> target
profile pair such as ``strict-v1 -> strict-v2``:

1. is the pair well-formed and reproducible (identities, byte hashes,
   version lineage, release-manifest integrity, registered rule changes)?
2. is the target semantically coherent for activation (band orderings and
   eligibility-gate/valuation-tier relationships, with explicit versioned
   policy exceptions)?
3. has a human accepted the economic policy?  (Detection only: the audit
   never verifies, synthesizes or records an approval, and never treats a
   green CI run or a release manifest as one.)

The boundary evidence replays the actual deterministic engine — the real
``evaluate_cdc_gate`` at exact threshold/epsilon yields and the real
``run_analyze`` end-to-end pipeline on boundary-derived inputs — so every
reported gate status, valuation state and final decision is engine output,
never a restatement of the thresholds.

The audit constructs no provider, model, transport or network client, and
never writes a rule profile, configuration or approval state.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, Self, TypeAlias

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

from turtle_value_engine.calculations.business_quality import (
    BUSINESS_QUALITY_DIMENSIONS,
    calculate_business_quality_from_normalized_input,
)
from turtle_value_engine.config.models import RuleProfile
from turtle_value_engine.gates.cdc import evaluate_cdc_gate
from turtle_value_engine.models import (
    BusinessQualityDimension,
    CDCResult,
    ConfidenceLevel,
    Evidence,
    Fact,
    NormalizedCompanyInput,
)
from turtle_value_engine.pipeline import run_analyze
from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.providers.normalization import deterministic_id

from .materialization_pair import _regular_file_bytes
from .profile_release import VersionedProfileReleaseCandidateV1, _changes, _rules

HASH_PATTERN = r"^[0-9a-f]{64}$"
STATUS_PATTERN = r"^[A-Z][A-Z0-9_]*$"

CHECK_BASE_PROFILE_VALID = "BASE_PROFILE_VALID"
CHECK_TARGET_PROFILE_VALID = "TARGET_PROFILE_VALID"
CHECK_VERSION_LINEAGE_NEXT = "VERSION_LINEAGE_NEXT"
CHECK_RELEASE_MANIFEST_VALID = "RELEASE_MANIFEST_VALID"
CHECK_BASE_PROFILE_BYTES_HASH = "BASE_PROFILE_BYTES_HASH"
CHECK_TARGET_PROFILE_BYTES_HASH = "TARGET_PROFILE_BYTES_HASH"
CHECK_TARGET_PROFILE_IDENTITY = "TARGET_PROFILE_IDENTITY"
CHECK_RULE_CHANGES_REGISTERED = "RULE_CHANGES_REGISTERED"
CHECK_CDC_BAND_ORDER = "CDC_BAND_ORDER"
CHECK_CDC_GATE_TIER_COHERENCE = "CDC_GATE_TIER_COHERENCE"
CHECK_THROUGH_RETURN_BAND_ORDER = "THROUGH_RETURN_BAND_ORDER"
CHECK_VALUATION_TIER_ORDER = "VALUATION_TIER_ORDER"
CHECK_BOUNDARY_REPLAY_REPRODUCIBLE = "BOUNDARY_REPLAY_REPRODUCIBLE"
CHECK_POLICY_EXCEPTIONS_VALID = "POLICY_EXCEPTIONS_VALID"

#: The one canonical ordered check sequence for ``profile_semantic_audit_v1``.
#: Each entry pins the check name and its scope; a persisted audit is valid
#: only when its checks are exactly this sequence — no omission, duplicate,
#: unknown substitution or reordering.
REQUIRED_SEMANTIC_AUDIT_CHECKS: tuple[tuple[str, str], ...] = (
    (CHECK_BASE_PROFILE_VALID, "base"),
    (CHECK_TARGET_PROFILE_VALID, "target"),
    (CHECK_VERSION_LINEAGE_NEXT, "pair"),
    (CHECK_RELEASE_MANIFEST_VALID, "pair"),
    (CHECK_BASE_PROFILE_BYTES_HASH, "pair"),
    (CHECK_TARGET_PROFILE_BYTES_HASH, "pair"),
    (CHECK_TARGET_PROFILE_IDENTITY, "pair"),
    (CHECK_RULE_CHANGES_REGISTERED, "pair"),
    (CHECK_CDC_BAND_ORDER, "base"),
    (CHECK_CDC_BAND_ORDER, "target"),
    (CHECK_CDC_GATE_TIER_COHERENCE, "base"),
    (CHECK_CDC_GATE_TIER_COHERENCE, "target"),
    (CHECK_THROUGH_RETURN_BAND_ORDER, "base"),
    (CHECK_THROUGH_RETURN_BAND_ORDER, "target"),
    (CHECK_VALUATION_TIER_ORDER, "base"),
    (CHECK_VALUATION_TIER_ORDER, "target"),
    (CHECK_BOUNDARY_REPLAY_REPRODUCIBLE, "pair"),
    (CHECK_POLICY_EXCEPTIONS_VALID, "pair"),
)

SemanticAuditCheckName: TypeAlias = Literal[
    "BASE_PROFILE_VALID",
    "TARGET_PROFILE_VALID",
    "VERSION_LINEAGE_NEXT",
    "RELEASE_MANIFEST_VALID",
    "BASE_PROFILE_BYTES_HASH",
    "TARGET_PROFILE_BYTES_HASH",
    "TARGET_PROFILE_IDENTITY",
    "RULE_CHANGES_REGISTERED",
    "CDC_BAND_ORDER",
    "CDC_GATE_TIER_COHERENCE",
    "THROUGH_RETURN_BAND_ORDER",
    "VALUATION_TIER_ORDER",
    "BOUNDARY_REPLAY_REPRODUCIBLE",
    "POLICY_EXCEPTIONS_VALID",
]

_TIER_NAMES = ("observation", "acceptable", "turtle_entry", "extreme_safety")
_WITHHOLDING_VALUATION_FLAGS = frozenset(
    {"NON_PRICE_GATES_NOT_PASSED", "NON_PRICE_GATES_UNRESOLVED"}
)
_GATE_EPSILON = 1e-9
_PIPELINE_DELTA = 1e-6
_OUTER_PROBE_OFFSET = 0.005
_MARKET_CAP_FACT_FIELDS = frozenset(
    {
        "current_market_cap",
        "actual_aggregate_company_market_cap",
        "listing_equivalent_market_cap",
    }
)


class ProfileSemanticAuditError(ValueError):
    """Raised when the audit cannot be executed from the supplied inputs."""


# ---------------------------------------------------------------------------
# Policy-exception and approval-claim contracts
# ---------------------------------------------------------------------------


class VersionedPolicyExceptionV1(BaseModel):
    """One explicit, versioned, human-authored policy-exception declaration.

    An exception never changes engine behavior.  It records that a specific
    cross-field semantic anomaly of one exact profile (bound by id and byte
    hash) is an intended economic policy, so the audit can mark the matching
    finding as covered instead of uncovered.  Only the narrow registered
    codes are accepted; the audit never infers coverage from prose.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["versioned_policy_exception_v1"] = "versioned_policy_exception_v1"
    exception_id: StrictStr = Field(min_length=1)
    profile_id: StrictStr = Field(min_length=1)
    profile_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    rule_path: StrictStr = Field(min_length=1)
    exception_code: Literal["CDC_GATE_ABOVE_S_BAND_PERMITTED"]
    rationale: StrictStr = Field(min_length=20, max_length=4_000)
    declared_by: StrictStr = Field(min_length=1)
    content_sha256: StrictStr = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_exception(self) -> Self:
        if self.rule_path != "cdc.yield_bands.pass":
            raise ValueError(
                "exception code CDC_GATE_ABOVE_S_BAND_PERMITTED applies only to "
                "cdc.yield_bands.pass"
            )
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        if self.content_sha256 != expected:
            raise ValueError("policy exception content_sha256 does not match content")
        expected_id = deterministic_id(
            "versioned-policy-exception",
            self.profile_id,
            self.profile_sha256,
            self.rule_path,
            self.exception_code,
        )
        if self.exception_id != expected_id:
            raise ValueError("policy exception id disagrees with bound content")
        return self

    @classmethod
    def build(cls, **fields: object) -> Self:
        """Construct one exception with its deterministic id and content hash."""

        fields["exception_id"] = deterministic_id(
            "versioned-policy-exception",
            fields["profile_id"],
            fields["profile_sha256"],
            fields["rule_path"],
            fields["exception_code"],
        )
        fields["content_sha256"] = "0" * 64
        temporary = cls.model_construct(**fields)
        payload = temporary.model_dump(mode="json")
        payload["content_sha256"] = hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in payload.items() if key != "content_sha256"}
            )
        ).hexdigest()
        return cls.model_validate(payload)


class PolicyApprovalClaimV1(BaseModel):
    """Detection-only record of a claimed human economic-policy decision.

    The audit validates only the claim's shape and its binding to the exact
    target profile bytes.  Verifying that a real human made the decision is
    outside the offline audit boundary, so no audit status ever becomes a
    verified approval and no claim can enable activation.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["policy_approval_claim_v1"] = "policy_approval_claim_v1"
    target_profile_id: StrictStr = Field(min_length=1)
    target_profile_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    decision: Literal["ACCEPTED", "REJECTED"]
    decided_by: StrictStr = Field(min_length=1)
    decided_at: StrictStr = Field(min_length=1)
    rationale: StrictStr = Field(min_length=1, max_length=4_000)


# ---------------------------------------------------------------------------
# Audit result contracts
# ---------------------------------------------------------------------------


class SemanticAuditCheckV1(BaseModel):
    """One machine-readable audit check with a stable name, scope and code."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: SemanticAuditCheckName
    scope: Literal["base", "target", "pair"]
    status: Literal["PASS", "FINDING", "BLOCKED"]
    code: StrictStr = Field(pattern=STATUS_PATTERN)
    detail: StrictStr = Field(min_length=1, max_length=2_000)


class SemanticFindingV1(BaseModel):
    """One semantic-coherence anomaly attributed to one exact profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: Literal[
        "CDC_BAND_ORDER_VIOLATION",
        "CDC_GATE_TIER_COHERENCE_VIOLATION",
        "THROUGH_RETURN_BAND_ORDER_VIOLATION",
        "VALUATION_TIER_ORDER_VIOLATION",
    ]
    profile_id: StrictStr = Field(min_length=1)
    rule_path: StrictStr = Field(min_length=1)
    covered_by_policy_exception: StrictBool
    covering_exception_id: StrictStr | None = Field(default=None, min_length=1)
    description: StrictStr = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def validate_finding(self) -> Self:
        if self.covered_by_policy_exception != (self.covering_exception_id is not None):
            raise ValueError("coverage flag and covering exception id must agree")
        return self


class GateBoundaryRowV1(BaseModel):
    """One exact-yield CDC gate outcome under both audited profiles."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cdc_yield: StrictFloat = Field(gt=0)
    base_gate_status: StrictStr = Field(pattern=STATUS_PATTERN)
    target_gate_status: StrictStr = Field(pattern=STATUS_PATTERN)
    diverges: StrictBool

    @model_validator(mode="after")
    def validate_row(self) -> Self:
        if self.diverges != (self.base_gate_status != self.target_gate_status):
            raise ValueError("diverges must reflect the gate status comparison")
        return self


class PipelineBoundaryRowV1(BaseModel):
    """One end-to-end engine outcome under both audited profiles."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_cdc_yield: StrictFloat = Field(gt=0)
    actual_cdc_yield: StrictFloat | None = None
    base_gate_status: StrictStr = Field(pattern=STATUS_PATTERN)
    target_gate_status: StrictStr = Field(pattern=STATUS_PATTERN)
    base_valuation_state: StrictStr = Field(pattern=STATUS_PATTERN)
    target_valuation_state: StrictStr = Field(pattern=STATUS_PATTERN)
    base_decision_state: StrictStr = Field(pattern=STATUS_PATTERN)
    target_decision_state: StrictStr = Field(pattern=STATUS_PATTERN)
    base_auto_decision_allowed: StrictBool
    target_auto_decision_allowed: StrictBool
    decision_changed: StrictBool
    gate_divergences: list[StrictStr] = Field(max_length=200)
    withheld_valuation_reasons: list[StrictStr] = Field(max_length=50)

    @model_validator(mode="after")
    def validate_row(self) -> Self:
        if self.decision_changed != (
            self.base_decision_state != self.target_decision_state
        ):
            raise ValueError("decision_changed must reflect the decision comparison")
        return self


def _canonical_check_sequence_json_schema_extra() -> dict[str, object]:
    """Exact Draft 2020-12 sequence constraint for the canonical check set.

    Derived at class-definition time from the check model and the canonical
    (name, scope) sequence, following the Phase 7-A-R2 pattern: per-position
    ``const`` pins on both ``name`` and ``scope`` plus ``items: false`` so
    schema-only validation rejects reordered, truncated, duplicated or
    extended check lists exactly like the model validator.
    """

    item_schema = SemanticAuditCheckV1.model_json_schema()
    prefix_items: list[dict[str, object]] = []
    for name, scope in REQUIRED_SEMANTIC_AUDIT_CHECKS:
        position = dict(item_schema)
        position["properties"] = {
            **item_schema["properties"],  # type: ignore[arg-type]
            "name": {"const": name},
            "scope": {"const": scope},
        }
        prefix_items.append(position)
    return {"prefixItems": prefix_items, "items": False}


class ProfileSemanticAuditV1(BaseModel):
    """Immutable semantic-audit and activation-readiness dossier.

    ``activation_readiness`` separates structural invalidity
    (``BLOCKED_FOR_ACTIVATION``) from uncovered semantic policy anomalies
    (``POLICY_DECISION_REQUIRED``) from machine-clean pairs
    (``READY_FOR_POLICY_DECISION``).  The last state still means the human
    economic-policy decision is outstanding: publication, a green CI run and
    this audit are never approval to activate a profile.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["profile_semantic_audit_v1"] = "profile_semantic_audit_v1"
    audit_id: StrictStr = Field(min_length=1)
    base_profile_id: StrictStr = Field(min_length=1)
    base_profile_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    target_profile_id: StrictStr = Field(min_length=1)
    target_profile_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    release_manifest_id: StrictStr = Field(min_length=1)
    release_manifest_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    boundary_input_analysis_id: StrictStr = Field(min_length=1)
    boundary_input_content_sha256: StrictStr = Field(pattern=HASH_PATTERN)
    gate_boundary_rows: list[GateBoundaryRowV1] = Field(min_length=1, max_length=2_000)
    pipeline_boundary_rows: list[PipelineBoundaryRowV1] = Field(
        min_length=1, max_length=2_000
    )
    gate_divergence_count: StrictInt = Field(ge=0)
    decision_divergence_count: StrictInt = Field(ge=0)
    checks: list[SemanticAuditCheckV1] = Field(
        min_length=len(REQUIRED_SEMANTIC_AUDIT_CHECKS),
        max_length=len(REQUIRED_SEMANTIC_AUDIT_CHECKS),
        json_schema_extra=_canonical_check_sequence_json_schema_extra(),
    )
    semantic_findings: list[SemanticFindingV1] = Field(max_length=200)
    policy_exception_ids: list[StrictStr] = Field(max_length=64)
    policy_approval_status: Literal[
        "ABSENT",
        "UNVERIFIED_ACCEPTANCE_CLAIM",
        "UNVERIFIED_REJECTION_CLAIM",
        "MISMATCHED_CLAIM",
    ]
    activation_readiness: Literal[
        "BLOCKED_FOR_ACTIVATION",
        "POLICY_DECISION_REQUIRED",
        "READY_FOR_POLICY_DECISION",
    ]
    blocking_checks: list[StrictStr] = Field(max_length=64)
    policy_decision_reasons: list[StrictStr] = Field(max_length=64)
    requires_human_policy_approval: Literal[True] = True
    automatic_activation_allowed: Literal[False] = False
    publication_is_not_activation_approval: Literal[True] = True
    content_sha256: StrictStr = Field(pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def validate_audit(self) -> Self:
        expected_sequence = [(check.name, check.scope) for check in self.checks]
        if expected_sequence != [tuple(item) for item in REQUIRED_SEMANTIC_AUDIT_CHECKS]:
            raise ValueError(
                "audit checks must contain exactly the canonical required check "
                "sequence for this contract version, in canonical order (expected "
                f"{len(REQUIRED_SEMANTIC_AUDIT_CHECKS)} checks, got "
                f"{len(self.checks)})"
            )
        if self.gate_divergence_count != sum(
            1 for row in self.gate_boundary_rows if row.diverges
        ):
            raise ValueError("gate_divergence_count must equal the diverging rows")
        if self.decision_divergence_count != sum(
            1 for row in self.pipeline_boundary_rows if row.decision_changed
        ):
            raise ValueError(
                "decision_divergence_count must equal the changed-decision rows"
            )
        blocked = sorted(
            {
                f"{check.name}:{check.scope}"
                for check in self.checks
                if check.status == "BLOCKED"
            }
        )
        uncovered = sorted(
            f"{finding.code}:{finding.profile_id}"
            for finding in self.semantic_findings
            if not finding.covered_by_policy_exception
        )
        if self.activation_readiness == "BLOCKED_FOR_ACTIVATION":
            if not blocked:
                raise ValueError("BLOCKED_FOR_ACTIVATION requires a BLOCKED check")
            if self.blocking_checks != blocked:
                raise ValueError("blocking_checks must list exactly the blocked checks")
            if self.policy_decision_reasons:
                raise ValueError("BLOCKED_FOR_ACTIVATION carries no policy reasons")
        elif self.activation_readiness == "POLICY_DECISION_REQUIRED":
            if blocked:
                raise ValueError("blocked checks require BLOCKED_FOR_ACTIVATION")
            if not uncovered:
                raise ValueError(
                    "POLICY_DECISION_REQUIRED requires at least one uncovered finding"
                )
            if self.policy_decision_reasons != uncovered:
                raise ValueError(
                    "policy_decision_reasons must list exactly the uncovered findings"
                )
            if self.blocking_checks:
                raise ValueError("POLICY_DECISION_REQUIRED carries no blocked checks")
        else:
            if blocked or uncovered:
                raise ValueError(
                    "READY_FOR_POLICY_DECISION requires every check to pass and "
                    "every finding to be covered"
                )
            if self.blocking_checks or self.policy_decision_reasons:
                raise ValueError("READY_FOR_POLICY_DECISION carries no blockers")
        expected_audit_id = deterministic_id(
            "profile-semantic-audit",
            self.base_profile_id,
            self.base_profile_sha256,
            self.target_profile_id,
            self.target_profile_sha256,
            self.release_manifest_id,
            self.release_manifest_content_sha256,
            self.boundary_input_analysis_id,
            self.boundary_input_content_sha256,
            sorted(self.policy_exception_ids),
            self.policy_approval_status,
        )
        if self.audit_id != expected_audit_id:
            raise ValueError("audit_id does not match the bound audit identities")
        payload = self.model_dump(mode="json", warnings=False, exclude={"content_sha256"})
        expected_content = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        if self.content_sha256 != expected_content:
            raise ValueError("audit content_sha256 does not match content")
        return self


# ---------------------------------------------------------------------------
# Boundary replay helpers
# ---------------------------------------------------------------------------


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_profile(raw_bytes: bytes) -> tuple[RuleProfile | None, str]:
    try:
        loaded = yaml.safe_load(raw_bytes)
    except yaml.YAMLError as exc:
        return None, f"invalid YAML: {exc}"
    if not isinstance(loaded, dict):
        return None, "profile must contain a YAML object"
    try:
        return RuleProfile.model_validate(loaded), ""
    except Exception as exc:  # Pydantic's validation error is public message text.
        return None, str(exc)[:400]


def _load_default_boundary_input() -> NormalizedCompanyInput:
    """Resolve the checked-in synthetic boundary template like the CLI does."""

    from turtle_value_engine.input_loader import parse_normalized_input

    candidates = [
        Path.cwd() / "fixtures" / "healthy_cash_cow.json",
        Path(__file__).resolve().parents[3] / "fixtures" / "healthy_cash_cow.json",
    ]
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise ProfileSemanticAuditError(
            "BOUNDARY_INPUT_UNAVAILABLE: no boundary input supplied and the "
            "default template healthy_cash_cow.json was not found"
        )
    return parse_normalized_input(path.read_bytes())


def _collect_cdc_thresholds(profiles: Sequence[RuleProfile]) -> list[float]:
    """Union of CDC gate and valuation-tier CDC hurdles of valid profiles."""

    values: set[float] = set()
    for profile in profiles:
        bands = profile.cdc.yield_bands
        values.update({bands.s, bands.a, bands.pass_, bands.watch, bands.fail_below})
        for name in _TIER_NAMES:
            tier = profile.valuation.tiers.get(name)
            if tier is not None:
                values.add(tier.cdc_yield)
    ordered = sorted(values)
    if not ordered or ordered[0] <= 0:
        raise ProfileSemanticAuditError(
            "BOUNDARY_THRESHOLD_DERIVATION_FAILED: audited profiles expose no "
            "positive CDC thresholds for boundary derivation"
        )
    return ordered


def _gate_probe_values(thresholds: Sequence[float]) -> list[float]:
    """Exact boundary and epsilon probe yields for the real CDC gate."""

    values: list[float] = []
    for threshold in thresholds:
        values.extend([threshold - _GATE_EPSILON, threshold, threshold + _GATE_EPSILON])
    for earlier, later in zip(thresholds, thresholds[1:]):
        values.append((earlier + later) / 2)
    return sorted(value for value in set(values) if value > 0)


def _pipeline_probe_values(thresholds: Sequence[float]) -> list[float]:
    """Market-cap-derived probe yields for the real end-to-end pipeline."""

    values: list[float] = []
    for threshold in thresholds:
        values.extend([threshold - _PIPELINE_DELTA, threshold + _PIPELINE_DELTA])
    for earlier, later in zip(thresholds, thresholds[1:]):
        values.append((earlier + later) / 2)
    values.append(max(thresholds[0] / 2, thresholds[0] - _OUTER_PROBE_OFFSET))
    values.append(thresholds[-1] + _OUTER_PROBE_OFFSET)
    return sorted(value for value in set(values) if value > 0)


def _synthetic_cdc_result(cdc_yield: float) -> CDCResult:
    return CDCResult(
        cdc_yield=cdc_yield,
        positive_years_5y=5,
        cumulative_core_cdc_5y=100.0,
        normalized_parent_core_cdc=10.0,
        confidence=ConfidenceLevel.HIGH,
    )


def _cdc_yield_gate_status(analysis: object) -> str:
    gate = getattr(analysis, "gates").cdc
    return next(rule.status.value for rule in gate.rules if rule.rule_id == "CDC.YIELD")


def _audit_dimension_specs() -> list[tuple[str, str, str, str]]:
    """Deterministic synthetic evidence ids per fixed business dimension."""

    return [
        (
            dimension,
            f"profile-audit-bq-{dimension}-support-annual",
            f"profile-audit-bq-{dimension}-support-operating",
            f"profile-audit-bq-{dimension}-counter",
        )
        for dimension in BUSINESS_QUALITY_DIMENSIONS
    ]


def _augment_with_audit_business_quality(
    boundary_input: NormalizedCompanyInput,
) -> tuple[NormalizedCompanyInput, list[BusinessQualityDimension]]:
    known = {evidence.id for evidence in boundary_input.evidence_index}
    if "profile-audit-bq-hard-rule-evidence" in known:
        raise ProfileSemanticAuditError(
            "BOUNDARY_TEMPLATE_EVIDENCE_COLLISION: boundary input already "
            "defines synthetic audit evidence IDs"
        )
    evidence: list[Evidence] = [
        Evidence(
            id="profile-audit-bq-hard-rule-evidence",
            direction="SUPPORT",
            strength="E3",
            statement=(
                "Synthetic Phase 7-C1 boundary evidence for business hard-rule "
                "inputs."
            ),
            source={
                "type": "ANNUAL_REPORT",
                "title": "Synthetic audit evidence (business hard rules)",
            },
            confidence=1,
        )
    ]
    dimensions: list[BusinessQualityDimension] = []
    for dimension, strong, operating, counter in _audit_dimension_specs():
        if {strong, operating, counter} & known:
            raise ProfileSemanticAuditError(
                "BOUNDARY_TEMPLATE_EVIDENCE_COLLISION: boundary input already "
                "defines synthetic audit evidence IDs"
            )
        evidence.extend(
            [
                Evidence(
                    id=strong,
                    direction="SUPPORT",
                    strength="E3",
                    statement=f"Synthetic Phase 7-C1 boundary evidence for {dimension}.",
                    source={
                        "type": "ANNUAL_REPORT",
                        "title": f"Synthetic audit evidence {dimension} (annual)",
                    },
                    confidence=1,
                ),
                Evidence(
                    id=operating,
                    direction="SUPPORT",
                    strength="E2",
                    statement=(
                        f"Synthetic Phase 7-C1 operating evidence for {dimension}."
                    ),
                    source={
                        "type": "ANNUAL_REPORT",
                        "title": f"Synthetic audit evidence {dimension} (operating)",
                    },
                    confidence=1,
                ),
                Evidence(
                    id=counter,
                    direction="COUNTER",
                    strength="E1",
                    statement=(
                        f"Synthetic Phase 7-C1 counter-evidence for {dimension}; "
                        "checked and not material."
                    ),
                    source={
                        "type": "ANNUAL_REPORT",
                        "title": f"Synthetic audit evidence {dimension} (counter)",
                    },
                    confidence=1,
                ),
            ]
        )
        dimensions.append(
            BusinessQualityDimension(
                dimension=dimension,
                score=5,
                supporting_evidence_ids=[strong, operating],
                counter_evidence_ids=[counter],
                confidence="HIGH",
            )
        )
    # The business hard-rule gates stay PASS only when the template supplies
    # their inputs; otherwise the audit adds the explicitly synthetic
    # clean-fact pattern so the full green path is observable in the replay.
    # Fields already present in the template keep their own values.
    existing_fields = {fact.field for fact in boundary_input.facts}
    as_of_period = f"AS_OF_{boundary_input.as_of.isoformat()}"
    hard_rule_facts: list[Fact] = []
    for fact_id, field, value in (
        ("profile-audit-core-profit-ratio", "core_profit_ratio", 0.9),
        ("profile-audit-core-cash-generation", "core_business_cash_generation", True),
        ("profile-audit-structural-disruption", "structural_disruption", False),
    ):
        if field in existing_fields:
            continue
        hard_rule_facts.append(
            Fact(
                id=fact_id,
                field=field,
                value=value,
                period=as_of_period,
                source_evidence_ids=["profile-audit-bq-hard-rule-evidence"],
                confidence=1,
            )
        )
    augmented = boundary_input.model_copy(
        update={
            "evidence_index": [*boundary_input.evidence_index, *evidence],
            "facts": [*boundary_input.facts, *hard_rule_facts],
        }
    )
    return augmented, dimensions


def _boundary_input_at_yield(
    augmented: NormalizedCompanyInput, market_cap: float
) -> NormalizedCompanyInput:
    """Rescale every market-cap/price fact to the derived CDC yield."""

    shares = next(
        (
            fact.value
            for fact in augmented.facts
            if fact.field == "normalized_diluted_economic_shares"
            and isinstance(fact.value, (int, float))
            and fact.value > 0
        ),
        None,
    )
    facts = []
    for fact in augmented.facts:
        if fact.field in _MARKET_CAP_FACT_FIELDS:
            facts.append(fact.model_copy(update={"value": market_cap}))
        elif fact.field == "current_price" and shares is not None:
            facts.append(fact.model_copy(update={"value": market_cap / float(shares)}))
        else:
            facts.append(fact.model_copy())
    return augmented.model_copy(update={"facts": facts})


def _gate_divergences(base_analysis: object, target_analysis: object) -> list[str]:
    """Rule-level status differences across all six hard gates."""

    gate_names = (
        "universe",
        "balance_sheet",
        "cdc",
        "through_return",
        "business_quality",
        "governance_data_quality",
    )
    divergences: list[str] = []
    for name in gate_names:
        base_gate = getattr(getattr(base_analysis, "gates"), name)
        target_gate = getattr(getattr(target_analysis, "gates"), name)
        target_rules = {rule.rule_id: rule for rule in target_gate.rules}
        for rule in base_gate.rules:
            other = target_rules.get(rule.rule_id)
            if other is not None and rule.status != other.status:
                divergences.append(
                    f"{rule.rule_id}:{rule.status.value}->{other.status.value}"
                )
    return sorted(divergences)


def _withheld_valuation_reasons(
    base_analysis: object, target_analysis: object
) -> list[str]:
    """Withholding flags present only in the target valuation."""

    base_flags = set(getattr(base_analysis, "valuation").flags)
    return sorted(
        flag
        for flag in getattr(target_analysis, "valuation").flags
        if flag in _WITHHOLDING_VALUATION_FLAGS and flag not in base_flags
    )


def _compute_boundary_rows(
    *,
    base_profile: RuleProfile,
    target_profile: RuleProfile,
    boundary_input: NormalizedCompanyInput,
) -> tuple[list[GateBoundaryRowV1], list[PipelineBoundaryRowV1]]:
    if boundary_input.profile_id != base_profile.profile.id:
        raise ProfileSemanticAuditError(
            "BOUNDARY_TEMPLATE_PROFILE_MISMATCH: boundary input declares profile "
            f"{boundary_input.profile_id!r}, not the audited base profile "
            f"{base_profile.profile.id!r}"
        )
    base_reference = run_analyze(boundary_input, profile=base_profile)
    normalized_cdc = base_reference.metrics.cdc.normalized_parent_core_cdc
    if normalized_cdc is None or normalized_cdc <= 0:
        raise ProfileSemanticAuditError(
            "BOUNDARY_TEMPLATE_CDC_UNAVAILABLE: boundary input produces no "
            "positive normalized parent Core CDC for yield derivation"
        )

    thresholds = _collect_cdc_thresholds([base_profile, target_profile])

    gate_rows: list[GateBoundaryRowV1] = []
    for value in _gate_probe_values(thresholds):
        base_gate = evaluate_cdc_gate(_synthetic_cdc_result(value), base_profile)
        target_gate = evaluate_cdc_gate(_synthetic_cdc_result(value), target_profile)
        base_status = next(
            rule.status.value for rule in base_gate.rules if rule.rule_id == "CDC.YIELD"
        )
        target_status = next(
            rule.status.value
            for rule in target_gate.rules
            if rule.rule_id == "CDC.YIELD"
        )
        gate_rows.append(
            GateBoundaryRowV1(
                cdc_yield=value,
                base_gate_status=base_status,
                target_gate_status=target_status,
                diverges=base_status != target_status,
            )
        )

    augmented, dimensions = _augment_with_audit_business_quality(boundary_input)
    # Scored once under the base profile: business-quality rules are identical
    # between the audited profiles (any rule change is registered in the
    # release manifest), so one assessment keeps that gate identical across
    # profiles inside every boundary row while every deterministic cap and
    # coverage rule still applies to the synthetic evidence pattern.
    business_quality = calculate_business_quality_from_normalized_input(
        augmented, dimensions, base_profile
    )
    target_profile_id = target_profile.profile.id

    pipeline_rows: list[PipelineBoundaryRowV1] = []
    for target_yield in _pipeline_probe_values(thresholds):
        market_cap = normalized_cdc / target_yield
        probe_input = _boundary_input_at_yield(augmented, market_cap)
        base_analysis = run_analyze(
            probe_input, profile=base_profile, business_quality=business_quality
        )
        target_analysis = run_analyze(
            probe_input.model_copy(update={"profile_id": target_profile_id}),
            profile=target_profile,
            business_quality=business_quality,
        )
        base_decision = base_analysis.decision.state.value
        target_decision = target_analysis.decision.state.value
        pipeline_rows.append(
            PipelineBoundaryRowV1(
                target_cdc_yield=target_yield,
                actual_cdc_yield=base_analysis.metrics.cdc.cdc_yield,
                base_gate_status=_cdc_yield_gate_status(base_analysis),
                target_gate_status=_cdc_yield_gate_status(target_analysis),
                base_valuation_state=(
                    base_analysis.valuation.current_valuation_state.value
                ),
                target_valuation_state=(
                    target_analysis.valuation.current_valuation_state.value
                ),
                base_decision_state=base_decision,
                target_decision_state=target_decision,
                base_auto_decision_allowed=base_analysis.decision.auto_decision_allowed,
                target_auto_decision_allowed=(
                    target_analysis.decision.auto_decision_allowed
                ),
                decision_changed=base_decision != target_decision,
                gate_divergences=_gate_divergences(base_analysis, target_analysis),
                withheld_valuation_reasons=_withheld_valuation_reasons(
                    base_analysis, target_analysis
                ),
            )
        )
    return gate_rows, pipeline_rows


# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------


def _pass(name: str, scope: str, detail: str) -> SemanticAuditCheckV1:
    return SemanticAuditCheckV1(
        name=name,  # type: ignore[arg-type]
        scope=scope,  # type: ignore[arg-type]
        status="PASS",
        code="OK",
        detail=detail[:2_000],
    )


def _blocked(name: str, scope: str, code: str, detail: str) -> SemanticAuditCheckV1:
    return SemanticAuditCheckV1(
        name=name,  # type: ignore[arg-type]
        scope=scope,  # type: ignore[arg-type]
        status="BLOCKED",
        code=code,
        detail=detail[:2_000],
    )


def _finding(name: str, scope: str, code: str, detail: str) -> SemanticAuditCheckV1:
    return SemanticAuditCheckV1(
        name=name,  # type: ignore[arg-type]
        scope=scope,  # type: ignore[arg-type]
        status="FINDING",
        code=code,
        detail=detail[:2_000],
    )


def _band_order_ok(bands: object) -> bool:
    return bands.s >= bands.a >= bands.pass_ >= bands.watch >= bands.fail_below > 0


def _gate_above_band_anomaly(bands: object) -> bool:
    """The one registered anomaly pattern: gate threshold above the S band.

    Every other pairwise ordering stays canonical; only ``pass`` sits above
    ``s`` (and therefore above ``a``).  This exact pattern is what the
    ``CDC_GATE_ABOVE_S_BAND_PERMITTED`` policy exception may cover.
    """

    return (
        bands.pass_ > bands.s
        and bands.s >= bands.a >= bands.watch >= bands.fail_below
        and bands.fail_below > 0
    )


def _tiers_present(profile: RuleProfile) -> bool:
    return all(name in profile.valuation.tiers for name in _TIER_NAMES)


def _tier_order_ok(profile: RuleProfile) -> bool:
    configs = [profile.valuation.tiers[name] for name in _TIER_NAMES]
    return all(
        earlier.cdc_yield <= later.cdc_yield
        and earlier.recurring_shareholder_cash_yield
        <= later.recurring_shareholder_cash_yield
        for earlier, later in zip(configs, configs[1:])
    )


def _band_order_finding(
    scope: str,
    label: str,
    rule_path: str,
    bands: object,
    violation_code: str,
) -> tuple[SemanticAuditCheckV1, SemanticFindingV1 | None]:
    if _band_order_ok(bands):
        return (
            _pass(
                "CDC_BAND_ORDER"
                if rule_path.startswith("cdc")
                else "THROUGH_RETURN_BAND_ORDER",
                scope,
                f"{label} yield bands are monotonically ordered.",
            ),
            None,
        )
    if rule_path.startswith("cdc") and _gate_above_band_anomaly(bands):
        description = (
            f"{label} sets pass={bands.pass_} above the S band s={bands.s}: the "
            "eligibility gate is stricter than its own S-grade diagnostic band "
            "(the gate-above-band anomaly)."
        )
    else:
        description = (
            f"{label} yield bands are not monotonically ordered (s={bands.s}, "
            f"a={bands.a}, pass={bands.pass_}, watch={bands.watch}, "
            f"fail_below={bands.fail_below})."
        )
    finding = SemanticFindingV1(
        code=violation_code,  # type: ignore[arg-type]
        profile_id=label,
        rule_path=rule_path,
        covered_by_policy_exception=False,
        description=description,
    )
    return (
        _finding(
            "CDC_BAND_ORDER" if rule_path.startswith("cdc") else "THROUGH_RETURN_BAND_ORDER",
            scope,
            violation_code,
            description,
        ),
        finding,
    )


def _semantic_checks_for_profile(
    profile: RuleProfile | None,
    scope: str,
    findings: list[SemanticFindingV1],
) -> tuple[
    SemanticAuditCheckV1,
    SemanticAuditCheckV1,
    SemanticAuditCheckV1,
    SemanticAuditCheckV1,
]:
    """The four semantic checks of one profile, in canonical sub-order."""

    if profile is None:
        not_evaluable = "profile failed structural validation; semantics cannot be evaluated"
        return (
            _blocked(CHECK_CDC_BAND_ORDER, scope, "PROFILE_NOT_EVALUABLE", not_evaluable),
            _blocked(
                CHECK_CDC_GATE_TIER_COHERENCE,
                scope,
                "PROFILE_NOT_EVALUABLE",
                not_evaluable,
            ),
            _blocked(
                CHECK_THROUGH_RETURN_BAND_ORDER,
                scope,
                "PROFILE_NOT_EVALUABLE",
                not_evaluable,
            ),
            _blocked(
                CHECK_VALUATION_TIER_ORDER,
                scope,
                "PROFILE_NOT_EVALUABLE",
                not_evaluable,
            ),
        )
    profile_id = profile.profile.id
    bands = profile.cdc.yield_bands

    cdc_check, cdc_finding = _band_order_finding(
        scope, profile_id, "cdc.yield_bands", bands, "CDC_BAND_ORDER_VIOLATION"
    )
    if cdc_finding is not None:
        findings.append(cdc_finding)

    extreme = profile.valuation.tiers.get("extreme_safety")
    if extreme is None:
        coherence_check = _blocked(
            CHECK_CDC_GATE_TIER_COHERENCE,
            scope,
            "VALUATION_TIERS_MISSING",
            f"{profile_id} is missing the extreme_safety valuation tier, so "
            "gate/tier coherence cannot be evaluated.",
        )
    elif bands.pass_ <= extreme.cdc_yield:
        coherence_check = _pass(
            CHECK_CDC_GATE_TIER_COHERENCE,
            scope,
            f"CDC gate pass threshold {bands.pass_} does not exceed the "
            f"extreme_safety tier hurdle {extreme.cdc_yield} for {profile_id}.",
        )
    else:
        description = (
            f"{profile_id} CDC eligibility gate pass={bands.pass_} exceeds the "
            f"extreme_safety valuation tier CDC hurdle {extreme.cdc_yield}: yields "
            "that satisfy the top valuation tier can still be held at WATCH by "
            "the gate."
        )
        findings.append(
            SemanticFindingV1(
                code="CDC_GATE_TIER_COHERENCE_VIOLATION",
                profile_id=profile_id,
                rule_path="cdc.yield_bands.pass",
                covered_by_policy_exception=False,
                description=description,
            )
        )
        coherence_check = _finding(
            CHECK_CDC_GATE_TIER_COHERENCE,
            scope,
            "CDC_GATE_TIER_COHERENCE_VIOLATION",
            description,
        )

    through_check, through_finding = _band_order_finding(
        scope,
        profile_id,
        "through_return.yield_bands",
        profile.through_return.yield_bands,
        "THROUGH_RETURN_BAND_ORDER_VIOLATION",
    )
    if through_finding is not None:
        findings.append(through_finding)

    if not _tiers_present(profile):
        tier_check = _blocked(
            CHECK_VALUATION_TIER_ORDER,
            scope,
            "VALUATION_TIERS_MISSING",
            f"{profile_id} is missing one of the four canonical valuation tiers "
            "(observation, acceptable, turtle_entry, extreme_safety).",
        )
    elif _tier_order_ok(profile):
        tier_check = _pass(
            CHECK_VALUATION_TIER_ORDER,
            scope,
            f"Valuation tier hurdles are non-decreasing for {profile_id}.",
        )
    else:
        description = (
            f"{profile_id} valuation tier hurdles are not non-decreasing across "
            "observation -> acceptable -> turtle_entry -> extreme_safety."
        )
        findings.append(
            SemanticFindingV1(
                code="VALUATION_TIER_ORDER_VIOLATION",
                profile_id=profile_id,
                rule_path="valuation.tiers",
                covered_by_policy_exception=False,
                description=description,
            )
        )
        tier_check = _finding(
            CHECK_VALUATION_TIER_ORDER,
            scope,
            "VALUATION_TIER_ORDER_VIOLATION",
            description,
        )
    return cdc_check, coherence_check, through_check, tier_check


# ---------------------------------------------------------------------------
# Public audit entry point
# ---------------------------------------------------------------------------


def audit_profile_semantics(
    *,
    base_profile_path: str | Path,
    target_profile_path: str | Path,
    release_manifest_path: str | Path,
    boundary_input: NormalizedCompanyInput | None = None,
    policy_exceptions: Sequence[VersionedPolicyExceptionV1] = (),
    approval_claim: PolicyApprovalClaimV1 | None = None,
) -> ProfileSemanticAuditV1:
    """Audit one published base -> target profile pair; read-only, offline.

    Structural/integrity failures produce ``BLOCKED`` checks and
    ``BLOCKED_FOR_ACTIVATION``; cross-field semantic anomalies produce
    ``FINDING`` checks and ``POLICY_DECISION_REQUIRED`` unless an explicit
    versioned policy exception covers them; a machine-clean pair yields
    ``READY_FOR_POLICY_DECISION``.  No outcome approves or activates
    anything: the human economic-policy decision is always outstanding.

    Raises :class:`ProfileSemanticAuditError` only when no dossier can exist
    at all (neither profile parses, or the boundary template is unusable in
    a way that leaves no derivable evidence rows); every auditable defect is
    reported inside the dossier instead.
    """

    base_path = Path(base_profile_path)
    target_path = Path(target_profile_path)
    manifest_path = Path(release_manifest_path)

    base_bytes = _regular_file_bytes(base_path)
    target_bytes = _regular_file_bytes(target_path)
    manifest_bytes = _regular_file_bytes(manifest_path)

    base_profile, base_error = _parse_profile(base_bytes)
    target_profile, target_error = _parse_profile(target_bytes)
    manifest: VersionedProfileReleaseCandidateV1 | None = None
    manifest_error = ""
    try:
        manifest = VersionedProfileReleaseCandidateV1.model_validate(
            json.loads(manifest_bytes)
        )
    except Exception as exc:
        manifest_error = str(exc)[:400]

    if base_profile is None and target_profile is None:
        raise ProfileSemanticAuditError(
            "AUDIT_INPUTS_UNEVALUABLE: neither profile parses as a RuleProfile "
            f"(base: {base_error}; target: {target_error})"
        )
    if boundary_input is None:
        boundary_input = _load_default_boundary_input()

    base_sha = _sha256_hex(base_bytes)
    target_sha = _sha256_hex(target_bytes)
    checks: list[SemanticAuditCheckV1] = []
    findings: list[SemanticFindingV1] = []

    # 1/2. Structural profile validity.
    checks.append(
        _pass(
            CHECK_BASE_PROFILE_VALID,
            "base",
            f"Base profile {base_path.name} validates as a complete RuleProfile.",
        )
        if base_profile is not None
        else _blocked(
            CHECK_BASE_PROFILE_VALID,
            "base",
            "BASE_PROFILE_INVALID",
            f"Base profile cannot be validated: {base_error}",
        )
    )
    checks.append(
        _pass(
            CHECK_TARGET_PROFILE_VALID,
            "target",
            f"Target profile {target_path.name} validates as a complete RuleProfile.",
        )
        if target_profile is not None
        else _blocked(
            CHECK_TARGET_PROFILE_VALID,
            "target",
            "TARGET_PROFILE_INVALID",
            f"Target profile cannot be validated: {target_error}",
        )
    )

    # 3. Version lineage (from the manifest, the authoritative publication).
    if manifest is None:
        checks.append(
            _blocked(
                CHECK_VERSION_LINEAGE_NEXT,
                "pair",
                "RELEASE_MANIFEST_INVALID",
                f"Release manifest cannot be validated: {manifest_error}",
            )
        )
    else:
        base_match = re.fullmatch(r"strict-v([1-9][0-9]*)", manifest.base_profile_id)
        target_match = re.fullmatch(r"strict-v([1-9][0-9]*)", manifest.target_profile_id)
        if (
            base_match is None
            or target_match is None
            or int(target_match.group(1)) != int(base_match.group(1)) + 1
        ):
            checks.append(
                _blocked(
                    CHECK_VERSION_LINEAGE_NEXT,
                    "pair",
                    "VERSION_LINEAGE_NOT_NEXT",
                    f"Target {manifest.target_profile_id!r} is not exactly the next "
                    f"strict version after base {manifest.base_profile_id!r}.",
                )
            )
        else:
            checks.append(
                _pass(
                    CHECK_VERSION_LINEAGE_NEXT,
                    "pair",
                    f"Target {manifest.target_profile_id} is exactly the next strict "
                    f"version after base {manifest.base_profile_id}.",
                )
            )

    # 4. Release manifest validity (its fixed literals are enforced by the model).
    checks.append(
        _pass(
            CHECK_RELEASE_MANIFEST_VALID,
            "pair",
            f"Release manifest {manifest.release_candidate_id} validates with its "
            "fixed no-automatic-approval literals intact.",
        )
        if manifest is not None
        else _blocked(
            CHECK_RELEASE_MANIFEST_VALID,
            "pair",
            "RELEASE_MANIFEST_INVALID",
            f"Release manifest cannot be validated: {manifest_error}",
        )
    )

    # 5/6. Published byte hashes.
    if manifest is None:
        checks.append(
            _blocked(
                CHECK_BASE_PROFILE_BYTES_HASH,
                "pair",
                "RELEASE_MANIFEST_INVALID",
                "Release manifest unavailable for base-profile hash comparison.",
            )
        )
        checks.append(
            _blocked(
                CHECK_TARGET_PROFILE_BYTES_HASH,
                "pair",
                "RELEASE_MANIFEST_INVALID",
                "Release manifest unavailable for target-profile hash comparison.",
            )
        )
    else:
        checks.append(
            _pass(
                CHECK_BASE_PROFILE_BYTES_HASH,
                "pair",
                f"Base profile bytes match the manifest hash {base_sha}.",
            )
            if base_sha == manifest.base_profile_sha256
            else _blocked(
                CHECK_BASE_PROFILE_BYTES_HASH,
                "pair",
                "BASE_PROFILE_BYTES_MISMATCH",
                f"Base profile bytes hash to {base_sha}, not the manifest's "
                f"{manifest.base_profile_sha256}.",
            )
        )
        checks.append(
            _pass(
                CHECK_TARGET_PROFILE_BYTES_HASH,
                "pair",
                f"Target profile bytes match the manifest hash {target_sha}.",
            )
            if target_sha == manifest.release_profile_sha256
            else _blocked(
                CHECK_TARGET_PROFILE_BYTES_HASH,
                "pair",
                "TARGET_PROFILE_BYTES_MISMATCH",
                f"Target profile bytes hash to {target_sha}, not the manifest's "
                f"{manifest.release_profile_sha256}.",
            )
        )

    # 7. Target identity: id, canonical filename and rule payload digest.
    if manifest is None or target_profile is None:
        checks.append(
            _blocked(
                CHECK_TARGET_PROFILE_IDENTITY,
                "pair",
                "TARGET_IDENTITY_INPUTS_UNAVAILABLE",
                "Target profile or release manifest unavailable for identity "
                "comparison.",
            )
        )
    elif (
        target_profile.profile.id == manifest.target_profile_id
        and target_path.name == f"{manifest.target_profile_id}.yaml"
        and _sha256_hex(canonical_json_bytes(_rules(target_profile)))
        == manifest.release_rule_payload_sha256
    ):
        checks.append(
            _pass(
                CHECK_TARGET_PROFILE_IDENTITY,
                "pair",
                "Target profile identity, canonical filename and rule payload "
                f"digest all match the manifest for {manifest.target_profile_id}.",
            )
        )
    else:
        checks.append(
            _blocked(
                CHECK_TARGET_PROFILE_IDENTITY,
                "pair",
                "TARGET_IDENTITY_MISMATCH",
                "Target profile id, canonical filename or rule payload digest "
                "differs from the release manifest.",
            )
        )

    # 8. Registered rule changes.
    if manifest is None or base_profile is None or target_profile is None:
        checks.append(
            _blocked(
                CHECK_RULE_CHANGES_REGISTERED,
                "pair",
                "RULE_DIFF_INPUTS_UNAVAILABLE",
                "Base profile, target profile or release manifest unavailable for "
                "rule-diff comparison.",
            )
        )
    else:
        try:
            actual = _changes(_rules(base_profile), _rules(target_profile))
        except Exception:
            actual = None
            checks.append(
                _blocked(
                    CHECK_RULE_CHANGES_REGISTERED,
                    "pair",
                    "STRUCTURAL_RULE_CHANGE_UNREGISTERED",
                    "Base to target rule structure differs; structural changes are "
                    "outside any registered materialization.",
                )
            )
        if actual is not None:
            expected = sorted(
                [
                    (change.profile_path, change.before, change.after)
                    for change in manifest.rule_changes
                ],
                key=lambda item: item[0],
            )
            checks.append(
                _pass(
                    CHECK_RULE_CHANGES_REGISTERED,
                    "pair",
                    "The re-derived base-to-target rule diff equals the manifest's "
                    f"registered changes ({len(actual)} leaf/leaves).",
                )
                if actual == expected
                else _blocked(
                    CHECK_RULE_CHANGES_REGISTERED,
                    "pair",
                    "RULE_CHANGES_MISMATCH",
                    "The re-derived base-to-target rule diff differs from the "
                    "release manifest's registered rule changes.",
                )
            )

    # 9-16. Per-profile semantic coherence, interleaved in canonical order.
    base_semantic = _semantic_checks_for_profile(base_profile, "base", findings)
    target_semantic = _semantic_checks_for_profile(target_profile, "target", findings)
    for base_check, target_check in zip(base_semantic, target_semantic):
        checks.append(base_check)
        checks.append(target_check)

    # 17. Boundary replay through the real engine, proven reproducible.
    gate_rows: list[GateBoundaryRowV1] = []
    pipeline_rows: list[PipelineBoundaryRowV1] = []
    if base_profile is None or target_profile is None:
        checks.append(
            _blocked(
                CHECK_BOUNDARY_REPLAY_REPRODUCIBLE,
                "pair",
                "PROFILE_NOT_EVALUABLE",
                "A structurally invalid profile cannot be boundary-replayed.",
            )
        )
    else:
        try:
            first_rows = _compute_boundary_rows(
                base_profile=base_profile,
                target_profile=target_profile,
                boundary_input=boundary_input,
            )
            second_rows = _compute_boundary_rows(
                base_profile=base_profile,
                target_profile=target_profile,
                boundary_input=boundary_input,
            )
        except ProfileSemanticAuditError as exc:
            checks.append(
                _blocked(
                    CHECK_BOUNDARY_REPLAY_REPRODUCIBLE,
                    "pair",
                    str(exc).split(":", 1)[0].strip() or "BOUNDARY_REPLAY_ERROR",
                    str(exc),
                )
            )
        else:
            if first_rows == second_rows:
                gate_rows, pipeline_rows = first_rows
                checks.append(
                    _pass(
                        CHECK_BOUNDARY_REPLAY_REPRODUCIBLE,
                        "pair",
                        f"Boundary replay is deterministic and reproducible "
                        f"({len(gate_rows)} gate rows, {len(pipeline_rows)} "
                        "pipeline rows through the real engine).",
                    )
                )
            else:
                checks.append(
                    _blocked(
                        CHECK_BOUNDARY_REPLAY_REPRODUCIBLE,
                        "pair",
                        "BOUNDARY_REPLAY_NON_DETERMINISTIC",
                        "Two identical boundary replays produced different rows.",
                    )
                )
    if not gate_rows or not pipeline_rows:
        # A blocked replay must still serialize one valid contract, so derive
        # gate-only sentinel rows from whichever profile still parses; they
        # carry no comparative evidence by construction.
        valid_profiles = [
            profile for profile in (base_profile, target_profile) if profile is not None
        ]
        thresholds = _collect_cdc_thresholds(valid_profiles)
        reference = valid_profiles[0]
        for value in _gate_probe_values(thresholds):
            status = next(
                rule.status.value
                for rule in evaluate_cdc_gate(
                    _synthetic_cdc_result(value), reference
                ).rules
                if rule.rule_id == "CDC.YIELD"
            )
            gate_rows.append(
                GateBoundaryRowV1(
                    cdc_yield=value,
                    base_gate_status=status,
                    target_gate_status=status,
                    diverges=False,
                )
            )
        pipeline_rows = [
            PipelineBoundaryRowV1(
                target_cdc_yield=row.cdc_yield,
                actual_cdc_yield=row.cdc_yield,
                base_gate_status=row.base_gate_status,
                target_gate_status=row.target_gate_status,
                base_valuation_state="NOT_EVALUATED",
                target_valuation_state="NOT_EVALUATED",
                base_decision_state="NOT_EVALUATED",
                target_decision_state="NOT_EVALUATED",
                base_auto_decision_allowed=False,
                target_auto_decision_allowed=False,
                decision_changed=False,
                gate_divergences=[],
                withheld_valuation_reasons=[],
            )
            for row in gate_rows
        ]

    # 18. Policy exceptions validity/applicability and finding coverage.
    target_id_for_binding = (
        target_profile.profile.id
        if target_profile is not None
        else (manifest.target_profile_id if manifest is not None else "")
    )
    applicable_exceptions = [
        exception
        for exception in policy_exceptions
        if exception.profile_id == target_id_for_binding
        and exception.profile_sha256 == target_sha
    ]
    applicable_exception_ids = sorted(
        exception.exception_id for exception in applicable_exceptions
    )
    if not policy_exceptions:
        checks.append(
            _pass(
                CHECK_POLICY_EXCEPTIONS_VALID,
                "pair",
                "No policy exceptions declared; every semantic finding is "
                "evaluated as uncovered.",
            )
        )
    elif len(applicable_exceptions) == len(policy_exceptions):
        checks.append(
            _pass(
                CHECK_POLICY_EXCEPTIONS_VALID,
                "pair",
                f"{len(applicable_exceptions)} declared policy exception(s) bind "
                "the exact audited target profile bytes.",
            )
        )
    else:
        inapplicable = sorted(
            exception.exception_id
            for exception in policy_exceptions
            if exception not in applicable_exceptions
        )
        checks.append(
            _finding(
                CHECK_POLICY_EXCEPTIONS_VALID,
                "pair",
                "POLICY_EXCEPTION_NOT_APPLICABLE",
                "Supplied policy exception(s) "
                f"{', '.join(inapplicable)} do not bind the audited target "
                "profile bytes and are not counted as coverage.",
            )
        )
    if applicable_exceptions and target_profile is not None:
        gate_anomaly = _gate_above_band_anomaly(target_profile.cdc.yield_bands)
        covered_findings: list[SemanticFindingV1] = []
        for finding in findings:
            if (
                finding.profile_id == target_id_for_binding
                and finding.code
                in {"CDC_GATE_TIER_COHERENCE_VIOLATION", "CDC_BAND_ORDER_VIOLATION"}
                and (
                    finding.code == "CDC_GATE_TIER_COHERENCE_VIOLATION" or gate_anomaly
                )
            ):
                covered_findings.append(
                    finding.model_copy(
                        update={
                            "covered_by_policy_exception": True,
                            "covering_exception_id": applicable_exceptions[
                                0
                            ].exception_id,
                        }
                    )
                )
            else:
                covered_findings.append(finding)
        findings = covered_findings

    # Approval-claim detection (never verification, never activation).
    if approval_claim is None:
        approval_status = "ABSENT"
    elif (
        target_profile is not None
        and approval_claim.target_profile_id == target_profile.profile.id
        and approval_claim.target_profile_sha256 == target_sha
    ):
        approval_status = (
            "UNVERIFIED_ACCEPTANCE_CLAIM"
            if approval_claim.decision == "ACCEPTED"
            else "UNVERIFIED_REJECTION_CLAIM"
        )
    else:
        approval_status = "MISMATCHED_CLAIM"

    blocking = [check for check in checks if check.status == "BLOCKED"]
    uncovered = [finding for finding in findings if not finding.covered_by_policy_exception]
    if blocking:
        # Structural repair dominates: the semantic findings stay visible in
        # ``semantic_findings``, but no policy reason is issued while the pair
        # is not even well-formed/reproducible.
        readiness: Literal[
            "BLOCKED_FOR_ACTIVATION", "POLICY_DECISION_REQUIRED", "READY_FOR_POLICY_DECISION"
        ] = "BLOCKED_FOR_ACTIVATION"
        uncovered = []
    elif uncovered:
        readiness = "POLICY_DECISION_REQUIRED"
    else:
        readiness = "READY_FOR_POLICY_DECISION"

    boundary_content_sha = _sha256_hex(
        canonical_json_bytes(boundary_input.model_dump(mode="json", warnings=False))
    )
    base_id = (
        base_profile.profile.id
        if base_profile is not None
        else (manifest.base_profile_id if manifest is not None else "unknown-base")
    )
    target_id = (
        target_profile.profile.id
        if target_profile is not None
        else (manifest.target_profile_id if manifest is not None else "unknown-target")
    )
    audit = ProfileSemanticAuditV1.model_construct(
        contract="profile_semantic_audit_v1",
        audit_id="pending",
        base_profile_id=base_id,
        base_profile_sha256=base_sha,
        target_profile_id=target_id,
        target_profile_sha256=target_sha,
        release_manifest_id=(
            manifest.release_candidate_id if manifest is not None else "unknown-manifest"
        ),
        release_manifest_content_sha256=(
            manifest.content_sha256 if manifest is not None else "0" * 64
        ),
        boundary_input_analysis_id=boundary_input.analysis_id,
        boundary_input_content_sha256=boundary_content_sha,
        gate_boundary_rows=gate_rows,
        pipeline_boundary_rows=pipeline_rows,
        gate_divergence_count=sum(1 for row in gate_rows if row.diverges),
        decision_divergence_count=sum(
            1 for row in pipeline_rows if row.decision_changed
        ),
        checks=checks,
        semantic_findings=findings,
        policy_exception_ids=applicable_exception_ids,
        policy_approval_status=approval_status,
        activation_readiness=readiness,
        blocking_checks=sorted(
            {
                f"{check.name}:{check.scope}"
                for check in checks
                if check.status == "BLOCKED"
            }
        ),
        policy_decision_reasons=sorted(
            f"{finding.code}:{finding.profile_id}" for finding in uncovered
        ),
        requires_human_policy_approval=True,
        automatic_activation_allowed=False,
        publication_is_not_activation_approval=True,
        content_sha256="0" * 64,
    )
    payload = audit.model_dump(mode="json", warnings=False)
    components = {key: value for key, value in payload.items() if key != "content_sha256"}
    components["audit_id"] = deterministic_id(
        "profile-semantic-audit",
        base_id,
        base_sha,
        target_id,
        target_sha,
        payload["release_manifest_id"],
        payload["release_manifest_content_sha256"],
        boundary_input.analysis_id,
        boundary_content_sha,
        sorted(exception.exception_id for exception in policy_exceptions),
        approval_status,
    )
    payload["audit_id"] = deterministic_id(
        "profile-semantic-audit",
        base_id,
        base_sha,
        target_id,
        target_sha,
        payload["release_manifest_id"],
        payload["release_manifest_content_sha256"],
        boundary_input.analysis_id,
        boundary_content_sha,
        applicable_exception_ids,
        approval_status,
    )
    payload["content_sha256"] = hashlib.sha256(
        canonical_json_bytes(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
    ).hexdigest()
    return ProfileSemanticAuditV1.model_validate(payload)


__all__ = [
    "CHECK_BASE_PROFILE_BYTES_HASH",
    "CHECK_BASE_PROFILE_VALID",
    "CHECK_BOUNDARY_REPLAY_REPRODUCIBLE",
    "CHECK_CDC_BAND_ORDER",
    "CHECK_CDC_GATE_TIER_COHERENCE",
    "CHECK_POLICY_EXCEPTIONS_VALID",
    "CHECK_RELEASE_MANIFEST_VALID",
    "CHECK_RULE_CHANGES_REGISTERED",
    "CHECK_TARGET_PROFILE_BYTES_HASH",
    "CHECK_TARGET_PROFILE_IDENTITY",
    "CHECK_TARGET_PROFILE_VALID",
    "CHECK_THROUGH_RETURN_BAND_ORDER",
    "CHECK_VALUATION_TIER_ORDER",
    "CHECK_VERSION_LINEAGE_NEXT",
    "GateBoundaryRowV1",
    "PipelineBoundaryRowV1",
    "PolicyApprovalClaimV1",
    "ProfileSemanticAuditError",
    "ProfileSemanticAuditV1",
    "REQUIRED_SEMANTIC_AUDIT_CHECKS",
    "SemanticAuditCheckV1",
    "SemanticFindingV1",
    "VersionedPolicyExceptionV1",
    "audit_profile_semantics",
]
