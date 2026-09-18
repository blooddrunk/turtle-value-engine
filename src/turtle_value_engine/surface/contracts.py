"""Versioned, read-only research-surface contracts.

The surface models are deliberately smaller than the source artifacts.  They
contain the values a consumer needs to display or explain, but do not contain
provider payloads, filing bytes, credentials, or arbitrary source-model extras.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    model_validator,
)

from turtle_value_engine.models import (
    BusinessQuality,
    Company,
    DataQuality,
    Decision,
    ValuationResult,
)
from turtle_value_engine.models.common import ConfidenceLevel, FactValue
from turtle_value_engine.providers.models import canonical_json_bytes

SURFACE_CONTRACT = "research_surface_snapshot_v1"
SURFACE_SCHEMA_VERSION = "1.0.0"
_HASH_PATTERN = r"^[0-9a-f]{64}$"


class SurfaceArtifactReference(BaseModel):
    """Safe identity-only reference to one frozen source artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_type: Literal[
        "COMPANY_ANALYSIS",
        "DECISION_TRACE",
        "RESEARCH_REPORT",
        "HISTORICAL_MANIFEST",
        "HISTORICAL_ACCEPTANCE",
        "HISTORICAL_READINESS",
        "HISTORICAL_VALIDATION",
    ]
    artifact_id: StrictStr = Field(min_length=1)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    as_of: date | None = None


class SurfaceGateRule(BaseModel):
    """A compact, safe projection of one deterministic gate rule."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: StrictStr = Field(min_length=1)
    status: StrictStr = Field(min_length=1)
    actual: FactValue = None
    threshold: FactValue = None
    evidence_ids: list[StrictStr] = Field(default_factory=list)
    message: StrictStr | None = None


class SurfaceGate(BaseModel):
    """One hard-gate result copied from ``CompanyAnalysis``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: StrictStr = Field(min_length=1)
    rules: list[SurfaceGateRule] = Field(default_factory=list)
    blocking_reasons: list[StrictStr] = Field(default_factory=list)
    confidence: ConfidenceLevel | None = None


class SurfaceGates(BaseModel):
    """The six fixed gate names in the deterministic analysis contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    universe: SurfaceGate
    balance_sheet: SurfaceGate
    cdc: SurfaceGate
    through_return: SurfaceGate
    business_quality: SurfaceGate
    governance_data_quality: SurfaceGate


class SurfaceCDCMetric(BaseModel):
    """Allowlisted CDC output fields; unknown CDC extras are not published."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reported_cfo: float | None = None
    adjusted_cfo: float | None = None
    economic_gross_capex: float | None = None
    lease_principal_outside_cfo: float | None = None
    core_cdc: float | None = None
    parent_core_cdc: float | None = None
    normalized_core_cdc: float | None = None
    normalized_parent_core_cdc: float | None = None
    cdc_yield: float | None = None
    positive_years_5y: int | None = None
    cumulative_core_cdc_5y: float | None = None
    all_in_cdc: float | None = None
    all_in_cdc_5y: float | None = None
    flags: list[StrictStr] = Field(default_factory=list)
    confidence: ConfidenceLevel | None = None


class SurfaceNetCashMetric(BaseModel):
    """Allowlisted Net Cash output fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    book_cash: float | None = None
    strict_cash: float | None = None
    owner_accessible_cash: float | None = None
    financial_debt: float | None = None
    lease_debt: float | None = None
    debt_equivalent: float | None = None
    financial_net_cash: float | None = None
    obligation_adjusted_net_cash: float | None = None
    owner_debt_equivalent: float | None = None
    book_net_cash: float | None = None
    strict_net_cash: float | None = None
    owner_realizable_net_cash: float | None = None
    valuation_net_cash: float | None = None
    adjusted_ev: float | None = None
    ex_cash_cdc_yield: float | None = None
    owner_net_cash_ratio: float | None = None
    liquidity_coverage: float | None = None
    stress_coverage: float | None = None
    net_debt_to_ebitda: float | None = None
    interest_coverage: float | None = None
    source_evidence_ids: dict[str, list[StrictStr]] = Field(default_factory=dict)
    flags: list[StrictStr] = Field(default_factory=list)
    confidence: ConfidenceLevel | None = None


class SurfaceThroughReturnMetric(BaseModel):
    """Allowlisted Through Return output fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    normalized_parent_profit: float | None = None
    normalized_parent_core_cdc: float | None = None
    distributable_base: float | None = None
    payout_policy_floor: float | None = None
    conservative_payout_ratio: float | None = None
    dividend_through_return: float | None = None
    normalized_net_share_reduction: float | None = None
    through_return: float | None = None
    special_return: float | None = None
    flags: list[StrictStr] = Field(default_factory=list)
    policy_confidence: ConfidenceLevel | None = None
    confidence: ConfidenceLevel | None = None
    verified_recurring_buyback_cash: float = Field(default=0, ge=0)
    buyback_credit_eligible: StrictBool = False
    buyback_history_years: int | None = Field(default=None, ge=0)
    source_evidence_ids: dict[str, list[StrictStr]] = Field(default_factory=dict)


class SurfaceMetrics(BaseModel):
    """Deterministic metrics copied from the validated analysis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cdc: SurfaceCDCMetric
    net_cash: SurfaceNetCashMetric
    through_return: SurfaceThroughReturnMetric


class SurfaceAnalysisView(BaseModel):
    """Safe read model of a ``CompanyAnalysis``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    analysis_id: StrictStr = Field(min_length=1)
    as_of: date
    profile_id: StrictStr = Field(min_length=1)
    company: Company
    data_quality: DataQuality
    metrics: SurfaceMetrics
    gates: SurfaceGates
    valuation: ValuationResult
    decision: Decision
    business_quality: BusinessQuality | None = None
    business_quality_status: Literal["VALIDATED", "NOT_EVALUATED"]
    flags: list[StrictStr] = Field(default_factory=list)
    evidence_ids: list[StrictStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_business_quality_state(self) -> Self:
        if self.business_quality_status == "NOT_EVALUATED" and self.business_quality is not None:
            raise ValueError("NOT_EVALUATED surface Business Quality must be null")
        if self.business_quality_status == "VALIDATED" and self.business_quality is None:
            raise ValueError("VALIDATED surface Business Quality must be present")
        return self


class SurfaceTargetScope(BaseModel):
    """Non-sensitive historical target scope copied from a manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_id: StrictStr = Field(min_length=1)
    target_name: StrictStr = Field(min_length=1)
    universe_id: StrictStr = Field(min_length=1)
    markets: list[StrictStr] = Field(min_length=1)
    listing_ids: list[StrictStr] = Field(min_length=1)
    start_date: date
    end_date: date
    membership_claim: StrictStr = Field(min_length=1)
    coverage_claim: StrictStr = Field(min_length=1)
    required_source_kinds: list[StrictStr] = Field(min_length=1)


class SurfaceCoverageRecord(BaseModel):
    """Compact coverage/freshness information already computed upstream."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_kind: StrictStr = Field(min_length=1)
    listing_id: StrictStr = Field(min_length=1)
    period_start: date
    period_end: date
    expected_session_count: StrictInt = Field(ge=0)
    observed_session_count: StrictInt = Field(ge=0)
    missing_date_count: StrictInt = Field(ge=0)
    source_artifact_ids: list[StrictStr] = Field(min_length=1)
    status: StrictStr = Field(min_length=1)
    terminal_outcome: StrictStr | None = None
    evidence_basis: StrictStr | None = None


class SurfaceAcceptanceStatus(BaseModel):
    """Identity and exact blockers from the offline A6 report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["NOT_AVAILABLE", "ACCEPTED", "BLOCKED"]
    plan_id: StrictStr | None = None
    target_id: StrictStr | None = None
    dataset_id: StrictStr | None = None
    probe_report_id: StrictStr | None = None
    probe_network_used: StrictBool | None = None
    offline_replay_verified: StrictBool | None = None
    accepted: StrictBool | None = None
    checks: dict[StrictStr, Literal["PASS", "BLOCKED"]] = Field(default_factory=dict)
    blockers: list[StrictStr] = Field(default_factory=list)
    report_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)


class SurfaceReadinessStatus(BaseModel):
    """Identity and readiness flags from an existing readiness report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["NOT_AVAILABLE", "AVAILABLE"]
    report_id: StrictStr | None = None
    plan_id: StrictStr | None = None
    generated_at: datetime | None = None
    readiness: StrictStr | None = None
    network_used: StrictBool | None = None
    acquisition_ready: StrictBool | None = None
    personal_research_ready: StrictBool | None = None
    production_eligible: StrictBool | None = None
    batch_ids: list[StrictStr] = Field(default_factory=list)
    compiled_dataset_id: StrictStr | None = None
    probe_report_ids: list[StrictStr] = Field(default_factory=list)
    blockers: list[StrictStr] = Field(default_factory=list)
    warnings: list[StrictStr] = Field(default_factory=list)
    report_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)


class SurfaceValidationStatus(BaseModel):
    """Safe projection of a deterministic historical validation summary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["NOT_AVAILABLE", "AVAILABLE"]
    dataset_id: StrictStr | None = None
    valid: StrictBool | None = None
    production_eligible: StrictBool | None = None
    shard_rows: dict[StrictStr, StrictInt] = Field(default_factory=dict)
    coverage_status: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    production_blockers: list[StrictStr] = Field(default_factory=list)
    errors: list[StrictStr] = Field(default_factory=list)
    warnings: list[StrictStr] = Field(default_factory=list)
    content_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)


class SurfaceSourceFreshness(BaseModel):
    """Safe source coverage/freshness summary from a historical manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: StrictStr = Field(min_length=1)
    source_kind: StrictStr = Field(min_length=1)
    coverage_start: date
    coverage_end: date
    retrieved_at: datetime
    coverage_listing_count: StrictInt = Field(ge=0)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)


class SurfaceHistoricalStatus(BaseModel):
    """Read-only historical/A6 status; absence is explicit, never green."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    availability: Literal["NOT_AVAILABLE", "AVAILABLE"]
    claim_state: Literal[
        "NOT_AVAILABLE",
        "UNKNOWN",
        "PARTIAL",
        "BLOCKED",
        "READY",
        "PRODUCTION_ELIGIBLE",
    ]
    dataset_id: StrictStr | None = None
    dataset_version: StrictStr | None = None
    manifest_sha256: StrictStr | None = Field(default=None, pattern=_HASH_PATTERN)
    target_scope: SurfaceTargetScope | None = None
    coverage: list[SurfaceCoverageRecord] = Field(default_factory=list)
    source_freshness: list[SurfaceSourceFreshness] = Field(default_factory=list)
    acceptance: SurfaceAcceptanceStatus
    readiness: SurfaceReadinessStatus
    validation: SurfaceValidationStatus
    production_eligible: StrictBool | None = None
    blockers: list[StrictStr] = Field(default_factory=list)
    warnings: list[StrictStr] = Field(default_factory=list)
    limitations: list[StrictStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_availability(self) -> Self:
        if self.availability == "NOT_AVAILABLE":
            if self.claim_state != "NOT_AVAILABLE":
                raise ValueError("unavailable historical status must be NOT_AVAILABLE")
            if any(
                value is not None
                for value in (self.dataset_id, self.dataset_version, self.manifest_sha256)
            ):
                raise ValueError("unavailable historical status cannot contain dataset identity")
            if self.target_scope is not None or self.coverage:
                raise ValueError("unavailable historical status cannot contain scope/coverage")
        return self


class ResearchSurfaceSnapshotV1(BaseModel):
    """Versioned deterministic read-only projection for agents and APIs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["research_surface_snapshot_v1"] = SURFACE_CONTRACT
    schema_version: Literal["1.0.0"] = SURFACE_SCHEMA_VERSION
    surface_id: StrictStr = Field(pattern=_HASH_PATTERN)
    content_sha256: StrictStr = Field(pattern=_HASH_PATTERN)
    analysis_id: StrictStr = Field(min_length=1)
    as_of: date
    profile_id: StrictStr = Field(min_length=1)
    company: Company
    analysis: SurfaceAnalysisView
    source_artifacts: list[SurfaceArtifactReference] = Field(min_length=1)
    decision_trace_reference: SurfaceArtifactReference | None = None
    research_report_reference: SurfaceArtifactReference | None = None
    accepted_adjustment_ids: list[StrictStr] = Field(default_factory=list)
    historical_status: SurfaceHistoricalStatus

    @model_validator(mode="after")
    def validate_projection_identity(self) -> Self:
        if self.analysis_id != self.analysis.analysis_id:
            raise ValueError("surface analysis_id does not match analysis view")
        if self.as_of != self.analysis.as_of:
            raise ValueError("surface as_of does not match analysis view")
        if self.profile_id != self.analysis.profile_id:
            raise ValueError("surface profile_id does not match analysis view")
        if self.company != self.analysis.company:
            raise ValueError("surface company does not match analysis view")
        reference_types = {item.artifact_type for item in self.source_artifacts}
        if "COMPANY_ANALYSIS" not in reference_types:
            raise ValueError("surface source_artifacts must include COMPANY_ANALYSIS")
        if self.decision_trace_reference is not None and "DECISION_TRACE" not in reference_types:
            raise ValueError("surface trace reference is missing from source_artifacts")
        if self.research_report_reference is not None and "RESEARCH_REPORT" not in reference_types:
            raise ValueError("surface report reference is missing from source_artifacts")
        payload = self.model_dump(
            mode="json",
            exclude={"surface_id", "content_sha256"},
            warnings=False,
        )
        expected = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        if self.surface_id != expected or self.content_sha256 != expected:
            raise ValueError("surface identity does not match canonical snapshot content")
        return self

    @classmethod
    def build(cls, **values: object) -> ResearchSurfaceSnapshotV1:
        """Build and validate a snapshot with its deterministic content hash."""

        payload = dict(values)
        candidate = cls.model_construct(
            **payload,
            surface_id="0" * 64,
            content_sha256="0" * 64,
        )
        identity_payload = candidate.model_dump(
            mode="json",
            exclude={"surface_id", "content_sha256"},
            warnings=False,
        )
        identity = hashlib.sha256(canonical_json_bytes(identity_payload)).hexdigest()
        payload["surface_id"] = identity
        payload["content_sha256"] = identity
        return cls.model_validate(payload)

    def canonical_bytes(self) -> bytes:
        """Return canonical persisted JSON bytes for this snapshot."""

        return canonical_json_bytes(self.model_dump(mode="json", warnings=False))

    @property
    def snapshot_id(self) -> str:
        """Compatibility alias for consumers that call the identity a snapshot ID."""

        return self.surface_id

    @property
    def metrics(self) -> SurfaceMetrics:
        return self.analysis.metrics

    @property
    def gates(self) -> SurfaceGates:
        return self.analysis.gates

    @property
    def valuation(self) -> ValuationResult:
        return self.analysis.valuation

    @property
    def decision(self) -> Decision:
        return self.analysis.decision

    @property
    def business_quality(self) -> BusinessQuality | None:
        return self.analysis.business_quality


__all__ = [
    "SURFACE_CONTRACT",
    "SURFACE_SCHEMA_VERSION",
    "ResearchSurfaceSnapshotV1",
    "SurfaceAcceptanceStatus",
    "SurfaceAnalysisView",
    "SurfaceArtifactReference",
    "SurfaceCDCMetric",
    "SurfaceCoverageRecord",
    "SurfaceGate",
    "SurfaceGateRule",
    "SurfaceGates",
    "SurfaceHistoricalStatus",
    "SurfaceMetrics",
    "SurfaceNetCashMetric",
    "SurfaceReadinessStatus",
    "SurfaceSourceFreshness",
    "SurfaceTargetScope",
    "SurfaceThroughReturnMetric",
    "SurfaceValidationStatus",
]
