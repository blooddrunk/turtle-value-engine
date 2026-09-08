"""Shared enums and JSON-compatible scalar types for the engine contracts."""

from enum import StrEnum
from typing import TypeAlias

from pydantic import StrictBool, StrictFloat, StrictStr


class ConfidenceLevel(StrEnum):
    """Qualitative confidence used by metrics, gates and decisions."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class GateStatus(StrEnum):
    """Status of one independent gate or one rule inside a gate."""

    PASS = "PASS"
    WATCH = "WATCH"
    FAIL = "FAIL"
    SPECIAL_REVIEW = "SPECIAL_REVIEW"
    NOT_EVALUATED = "NOT_EVALUATED"


class DecisionState(StrEnum):
    """States allowed by the CompanyAnalysis decision contract."""

    PASS = "PASS"
    WATCH = "WATCH"
    FAIL = "FAIL"
    SPECIAL_REVIEW = "SPECIAL_REVIEW"
    ACCEPTABLE = "ACCEPTABLE"
    TURTLE_ENTRY = "TURTLE_ENTRY"
    EXTREME_SAFETY = "EXTREME_SAFETY"
    TOO_EXPENSIVE_FOR_STRICT_MODEL = "TOO_EXPENSIVE_FOR_STRICT_MODEL"
    NO_NORMAL_VALUATION = "NO_NORMAL_VALUATION"


class ValuationState(StrEnum):
    """States specific to the valuation-result contract."""

    EXTREME_SAFETY = "EXTREME_SAFETY"
    TURTLE_ENTRY = "TURTLE_ENTRY"
    ACCEPTABLE = "ACCEPTABLE"
    WATCH = "WATCH"
    TOO_EXPENSIVE_FOR_STRICT_MODEL = "TOO_EXPENSIVE_FOR_STRICT_MODEL"
    NO_NORMAL_VALUATION = "NO_NORMAL_VALUATION"
    SPECIAL_REVIEW = "SPECIAL_REVIEW"


class EvidenceDirection(StrEnum):
    """Whether evidence supports, challenges or contextualizes a claim."""

    SUPPORT = "SUPPORT"
    COUNTER = "COUNTER"
    CONTEXT = "CONTEXT"


class EvidenceStrength(StrEnum):
    """Evidence quality level defined by the repository specification."""

    E3 = "E3"
    E2 = "E2"
    E1 = "E1"
    E0 = "E0"


class SourceType(StrEnum):
    """Source types permitted by evidence.schema.json."""

    ANNUAL_REPORT = "ANNUAL_REPORT"
    INTERIM_REPORT = "INTERIM_REPORT"
    EXCHANGE_FILING = "EXCHANGE_FILING"
    COMPANY_ANNOUNCEMENT = "COMPANY_ANNOUNCEMENT"
    COMPANY_OPERATING_DISCLOSURE = "COMPANY_OPERATING_DISCLOSURE"
    GOVERNMENT = "GOVERNMENT"
    REGULATOR = "REGULATOR"
    INDUSTRY_ASSOCIATION = "INDUSTRY_ASSOCIATION"
    STRUCTURED_DATA_VENDOR = "STRUCTURED_DATA_VENDOR"
    RESEARCH_PROVIDER = "RESEARCH_PROVIDER"
    NEWS = "NEWS"
    OTHER = "OTHER"


class AdjustmentType(StrEnum):
    """Adjustment types permitted by the data contract."""

    RECLASSIFY = "RECLASSIFY"
    EXCLUDE = "EXCLUDE"
    INCLUDE = "INCLUDE"
    HAIRCUT = "HAIRCUT"
    OWNERSHIP_ADJUST = "OWNERSHIP_ADJUST"
    UPSTREAMABILITY_ADJUST = "UPSTREAMABILITY_ADJUST"
    NORMALIZE = "NORMALIZE"
    OTHER = "OTHER"


class AdjustmentStatus(StrEnum):
    """Lifecycle state of an adjustment proposal."""

    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ProposedBy(StrEnum):
    """Actor that proposed an adjustment."""

    RULE_ENGINE = "RULE_ENGINE"
    LLM = "LLM"
    HUMAN = "HUMAN"


class ApprovedBy(StrEnum):
    """Actor that approved an adjustment."""

    RULE_ENGINE = "RULE_ENGINE"
    HUMAN = "HUMAN"


FactValue: TypeAlias = StrictFloat | StrictStr | StrictBool | None
