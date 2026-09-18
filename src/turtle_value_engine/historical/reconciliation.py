"""Independent-reference return/price reconciliation."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import date

from turtle_value_engine.backtest import MarketBar
from turtle_value_engine.backtest.contracts import PriceBasis

from .contracts import (
    RECONCILIATION_SOURCE_INDEPENDENCE_UNPROVEN,
    HistoricalDatasetManifest,
    HistoricalReconciliationReport,
    HistoricalReconciliationSampleSpec,
    HistoricalSourceDescriptor,
    HistoricalSourceKind,
    ReconciliationComparison,
    ReconciliationSourceIdentity,
    ShardArtifactKind,
)
from .store import HistoricalArtifactStore


class ReconciliationSourceIndependenceError(ValueError):
    """Raised when a second source cannot be proven independent."""

    blocker = RECONCILIATION_SOURCE_INDEPENDENCE_UNPROVEN


class HistoricalArtifactReconciliationError(ValueError):
    """Raised when frozen manifest/store inputs cannot satisfy the M4 boundary."""


_UNRESOLVED_IDENTITIES = frozenset(
    {"", "unknown", "unresolved", "not_proven", "not-proven", "none", "null"}
)
_AGGREGATOR_IDENTITIES = frozenset(
    {
        "akshare",
        "fqgate",
        "fqgate-local",
        "fqgate-local-session",
        "eastmoney-wrapper",
        "market-data-aggregator",
    }
)


def _identity_value(value: object, name: str) -> str | None:
    if isinstance(value, Mapping):
        raw = value.get(name)
    else:
        raw = getattr(value, name, None)
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()


def _source_identity(
    source: object | None,
    *,
    source_id: str | None,
    adapter_id: str | None,
    provider_id: str | None,
    upstream_id: str | None,
) -> ReconciliationSourceIdentity:
    if source is not None:
        source_id = source_id or _identity_value(source, "source_id")
        adapter_id = adapter_id or _identity_value(source, "adapter_id")
        provider_id = provider_id or _identity_value(source, "provider_id")
        upstream_id = upstream_id or _identity_value(source, "upstream_id")
        upstream_id = upstream_id or _identity_value(source, "upstream_provider_id")
    return ReconciliationSourceIdentity(
        source_id=source_id or "unresolved-source",
        adapter_id=adapter_id or "unresolved-adapter",
        provider_id=provider_id,
        upstream_id=upstream_id,
    )


def _normalized_identity(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    return None if normalized in _UNRESOLVED_IDENTITIES else normalized


def assert_reconciliation_source_independence(
    canonical_source: object | None = None,
    independent_source: object | None = None,
    *,
    canonical_source_id: str | None = None,
    canonical_adapter_id: str | None = None,
    canonical_provider_id: str | None = None,
    canonical_upstream_id: str | None = None,
    independent_source_id: str | None = None,
    independent_adapter_id: str | None = None,
    independent_provider_id: str | None = None,
    independent_upstream_id: str | None = None,
) -> tuple[ReconciliationSourceIdentity, ReconciliationSourceIdentity]:
    """Require distinct, resolved provider/upstream identities.

    Different source or adapter IDs are intentionally insufficient.  The
    caller must persist the actual upstream identity; an unresolved wrapper
    (for example an AKShare aggregation layer without its upstream) remains a
    stable fail-closed blocker.
    """

    canonical = _source_identity(
        canonical_source,
        source_id=canonical_source_id,
        adapter_id=canonical_adapter_id,
        provider_id=canonical_provider_id,
        upstream_id=canonical_upstream_id,
    )
    independent = _source_identity(
        independent_source,
        source_id=independent_source_id,
        adapter_id=independent_adapter_id,
        provider_id=independent_provider_id,
        upstream_id=independent_upstream_id,
    )
    if canonical.source_id == independent.source_id:
        raise ReconciliationSourceIndependenceError(
            f"{RECONCILIATION_SOURCE_INDEPENDENCE_UNPROVEN}: source IDs must differ"
        )

    canonical_provider = _normalized_identity(canonical.provider_id)
    independent_provider = _normalized_identity(independent.provider_id)
    canonical_upstream = _normalized_identity(canonical.upstream_id)
    independent_upstream = _normalized_identity(independent.upstream_id)
    if (
        canonical_provider is None
        or independent_provider is None
        or canonical_upstream is None
        or independent_upstream is None
    ):
        raise ReconciliationSourceIndependenceError(
            f"{RECONCILIATION_SOURCE_INDEPENDENCE_UNPROVEN}: provider/upstream "
            "identity is unresolved"
        )
    if (
        canonical_provider in _AGGREGATOR_IDENTITIES
        or independent_provider in _AGGREGATOR_IDENTITIES
    ) and (canonical_upstream is None or independent_upstream is None):
        raise ReconciliationSourceIndependenceError(
            f"{RECONCILIATION_SOURCE_INDEPENDENCE_UNPROVEN}: aggregation upstream is unresolved"
        )
    if canonical_provider == independent_provider or canonical_upstream == independent_upstream:
        raise ReconciliationSourceIndependenceError(
            f"{RECONCILIATION_SOURCE_INDEPENDENCE_UNPROVEN}: sources share "
            "provider/upstream identity"
        )
    return canonical, independent


validate_reconciliation_source_independence = assert_reconciliation_source_independence


def _validate_value_scope(
    values: Mapping[tuple[str, date], float | None],
    *,
    sample: HistoricalReconciliationSampleSpec,
) -> None:
    allowed_listings = set(sample.listing_ids)
    for key, value in values.items():
        if not isinstance(key, tuple) or len(key) != 2:
            raise ValueError("reconciliation observation key must be (listing_id, date)")
        listing_id, observation_date = key
        if listing_id not in allowed_listings:
            raise ValueError("reconciliation observation lies outside sampled listings")
        if not isinstance(observation_date, date):
            raise ValueError("reconciliation observation date is invalid")
        if not sample.start_date <= observation_date <= sample.end_date:
            raise ValueError("reconciliation observation lies outside sampled date range")
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("reconciliation observation value is not numeric")
            if not math.isfinite(float(value)):
                raise ValueError("reconciliation observation value is not finite")


def _bar_values(
    bars: Iterable[MarketBar],
    *,
    sample: HistoricalReconciliationSampleSpec,
    expected_basis: PriceBasis,
) -> dict[tuple[str, date], float | None]:
    values: dict[tuple[str, date], float | None] = {}
    for raw_bar in bars:
        try:
            bar = raw_bar if isinstance(raw_bar, MarketBar) else MarketBar.model_validate(raw_bar)
        except (TypeError, ValueError) as exc:
            raise ValueError("sampled market bar failed canonical validation") from exc
        if bar.listing_id not in sample.listing_ids:
            raise ValueError("sampled market bar lies outside sampled listings")
        if not sample.start_date <= bar.trading_date <= sample.end_date:
            raise ValueError("sampled market bar lies outside sampled date range")
        if bar.market.value != "A" or bar.currency != sample.currency:
            raise ValueError("sampled market bar must be an A-share CNY observation")
        if bar.price_basis is not expected_basis:
            raise ValueError("sampled market bars have incompatible price basis")
        key = (bar.listing_id, bar.trading_date)
        if key in values:
            raise ValueError("duplicate sampled market-bar natural key")
        values[key] = bar.close
    return values


def reconcile_observations(
    *,
    target_id: str,
    canonical_source_id: str,
    independent_source_id: str,
    canonical_values: Mapping[tuple[str, date], float | None],
    independent_values: Mapping[tuple[str, date], float | None],
    absolute_tolerance: float,
    relative_tolerance: float,
    canonical_price_basis: PriceBasis = PriceBasis.UNADJUSTED,
    return_semantics: str = "PRICE_RETURN",
    explicit_actions_used: bool = False,
    report_id: str = "reconciliation",
    independent_price_basis: PriceBasis | None = None,
    canonical_currency: str | None = None,
    independent_currency: str | None = None,
    canonical_source: object | None = None,
    independent_source: object | None = None,
    canonical_provider_id: str | None = None,
    independent_provider_id: str | None = None,
    canonical_upstream_id: str | None = None,
    independent_upstream_id: str | None = None,
) -> HistoricalReconciliationReport:
    """Compare two cached series and persist missingness as MISSING rows."""

    if return_semantics not in {"PRICE_RETURN", "TOTAL_RETURN"}:
        raise ValueError("return_semantics must be PRICE_RETURN or TOTAL_RETURN")
    if absolute_tolerance < 0 or relative_tolerance < 0:
        raise ValueError("reconciliation tolerances must be non-negative")
    if independent_price_basis is not None and independent_price_basis is not canonical_price_basis:
        raise ValueError("reconciliation sources have incompatible price basis")
    if canonical_currency is not None or independent_currency is not None:
        if canonical_currency != "CNY" or independent_currency != "CNY":
            raise ValueError("sampled price reconciliation requires matching CNY units")
    if (
        canonical_source is not None
        or independent_source is not None
        or canonical_provider_id is not None
        or independent_provider_id is not None
        or canonical_upstream_id is not None
        or independent_upstream_id is not None
    ):
        assert_reconciliation_source_independence(
            canonical_source,
            independent_source,
            canonical_source_id=canonical_source_id,
            canonical_provider_id=canonical_provider_id,
            canonical_upstream_id=canonical_upstream_id,
            independent_source_id=independent_source_id,
            independent_provider_id=independent_provider_id,
            independent_upstream_id=independent_upstream_id,
        )
    keys = sorted(
        set(canonical_values) | set(independent_values),
        key=lambda item: (item[0], item[1]),
    )
    comparisons = [
        ReconciliationComparison(
            comparison_id=f"{listing_id}:{observation_date.isoformat()}",
            listing_id=listing_id,
            observation_date=observation_date,
            canonical_value=canonical_values.get((listing_id, observation_date)),
            independent_value=independent_values.get((listing_id, observation_date)),
            absolute_tolerance=absolute_tolerance,
            relative_tolerance=relative_tolerance,
            canonical_source_id=canonical_source_id,
            independent_source_id=independent_source_id,
        )
        for listing_id, observation_date in keys
    ]
    return HistoricalReconciliationReport.build(
        report_id=report_id,
        target_id=target_id,
        canonical_source_id=canonical_source_id,
        independent_source_id=independent_source_id,
        canonical_price_basis=canonical_price_basis,
        return_semantics=return_semantics,
        explicit_actions_used=explicit_actions_used,
        comparisons=comparisons,
    )


def reconcile_sampled_prices(
    *,
    sample: HistoricalReconciliationSampleSpec,
    canonical_values: Mapping[tuple[str, date], float | None],
    independent_values: Mapping[tuple[str, date], float | None],
    report_id: str | None = None,
) -> HistoricalReconciliationReport:
    """Reconcile a persisted M4 close-price sample without mutating inputs."""

    if sample.compared_field != "close":
        raise ValueError("M4 sampled price reconciliation only supports close")
    if (
        sample.canonical_price_basis is not PriceBasis.UNADJUSTED
        or sample.independent_price_basis is not PriceBasis.UNADJUSTED
    ):
        raise ValueError("M4 sampled price reconciliation requires unadjusted prices")
    _validate_value_scope(canonical_values, sample=sample)
    _validate_value_scope(independent_values, sample=sample)
    assert_reconciliation_source_independence(
        sample.canonical_source,
        sample.independent_source,
    )
    return reconcile_observations(
        target_id=sample.target_id,
        canonical_source_id=sample.canonical_source_id,
        independent_source_id=sample.independent_source_id,
        canonical_values=canonical_values,
        independent_values=independent_values,
        absolute_tolerance=sample.absolute_tolerance,
        relative_tolerance=sample.relative_tolerance,
        canonical_price_basis=sample.canonical_price_basis,
        return_semantics=sample.return_semantics,
        report_id=report_id or f"reconciliation-{sample.sample_id}",
        canonical_source=sample.canonical_source,
        independent_source=sample.independent_source,
        independent_price_basis=sample.independent_price_basis,
        canonical_currency=sample.currency,
        independent_currency=sample.currency,
    )


def reconcile_sampled_market_bars(
    *,
    sample: HistoricalReconciliationSampleSpec,
    canonical_bars: Iterable[MarketBar],
    independent_bars: Iterable[MarketBar],
    report_id: str | None = None,
) -> HistoricalReconciliationReport:
    """Validate frozen A-share bars and reconcile their close prices."""

    canonical_values = _bar_values(
        canonical_bars,
        sample=sample,
        expected_basis=sample.canonical_price_basis,
    )
    independent_values = _bar_values(
        independent_bars,
        sample=sample,
        expected_basis=sample.independent_price_basis,
    )
    return reconcile_sampled_prices(
        sample=sample,
        canonical_values=canonical_values,
        independent_values=independent_values,
        report_id=report_id,
    )


def _manifest_source_for_sample(
    manifest: HistoricalDatasetManifest,
    sample: HistoricalReconciliationSampleSpec,
    *,
    canonical: bool,
) -> HistoricalSourceDescriptor:
    """Validate one frozen manifest's target and declared source identity."""

    side = "canonical" if canonical else "independent"
    source_id = sample.canonical_source_id if canonical else sample.independent_source_id
    adapter_id = sample.canonical_adapter_id if canonical else sample.independent_adapter_id
    provider_id = sample.canonical_provider_id if canonical else sample.independent_provider_id
    upstream_id = sample.canonical_upstream_id if canonical else sample.independent_upstream_id

    if manifest.target.target_id != sample.target_id:
        raise HistoricalArtifactReconciliationError(
            f"{side} manifest target does not match reconciliation sample"
        )
    if not set(sample.listing_ids).issubset(manifest.target.listing_ids):
        raise HistoricalArtifactReconciliationError(
            f"{side} manifest target does not cover sampled listings"
        )
    if (
        sample.start_date < manifest.target.start_date
        or sample.end_date > manifest.target.end_date
    ):
        raise HistoricalArtifactReconciliationError(
            f"{side} manifest target does not cover sampled dates"
        )
    if any(
        manifest.target.listing_markets.get(listing_id) is not None
        and manifest.target.listing_markets[listing_id].value != "A"
        for listing_id in sample.listing_ids
    ):
        raise HistoricalArtifactReconciliationError(
            f"{side} manifest target contains a non-A sampled listing"
        )

    descriptors = [
        descriptor
        for descriptor in manifest.source_descriptors
        if descriptor.source_id == source_id
    ]
    if len(descriptors) != 1:
        raise HistoricalArtifactReconciliationError(
            f"{side} manifest must contain exactly one declared source {source_id!r}"
        )
    descriptor = descriptors[0]
    if descriptor.source_kind is not HistoricalSourceKind.PRICES:
        raise HistoricalArtifactReconciliationError(
            f"{side} source is not declared as PRICES"
        )
    if not set(sample.listing_ids).issubset(descriptor.coverage_listing_ids):
        raise HistoricalArtifactReconciliationError(
            f"{side} source descriptor does not cover sampled listings"
        )
    if (
        sample.start_date < descriptor.coverage_start
        or sample.end_date > descriptor.coverage_end
    ):
        raise HistoricalArtifactReconciliationError(
            f"{side} source descriptor does not cover sampled dates"
        )
    if descriptor.adapter_id != adapter_id:
        raise HistoricalArtifactReconciliationError(
            f"{side} source adapter identity does not match sample"
        )
    if descriptor.provider_id != provider_id:
        raise HistoricalArtifactReconciliationError(
            f"{side} source provider identity does not match sample"
        )
    if descriptor.upstream_id != upstream_id:
        raise HistoricalArtifactReconciliationError(
            f"{side} source upstream identity does not match sample"
        )
    if provider_id is None or upstream_id is None:
        raise ReconciliationSourceIndependenceError(
            f"{RECONCILIATION_SOURCE_INDEPENDENCE_UNPROVEN}: "
            f"{side} sample identity is unresolved"
        )
    return descriptor


def _sampled_bars_from_manifest(
    manifest: HistoricalDatasetManifest,
    store: HistoricalArtifactStore,
    *,
    source_id: str,
    sample: HistoricalReconciliationSampleSpec,
) -> list[MarketBar]:
    """Read and scope only MARKET_BAR rows belonging to one frozen source."""

    source_shards = [
        shard
        for shard in manifest.shards
        if shard.source_artifact_id == source_id
        and shard.artifact_kind is ShardArtifactKind.MARKET_BAR
    ]
    if not source_shards:
        raise HistoricalArtifactReconciliationError(
            f"manifest has no MARKET_BAR shard for source {source_id!r}"
        )
    if any(shard.schema_version != "market-bar-v1" for shard in source_shards):
        raise HistoricalArtifactReconciliationError(
            f"source {source_id!r} has an unsupported MARKET_BAR schema"
        )

    allowed_listings = set(sample.listing_ids)
    scoped: list[MarketBar] = []
    for shard in source_shards:
        rows = store.read_shard(shard, model_type=MarketBar)
        scoped.extend(
            row
            for row in rows
            if row.listing_id in allowed_listings
            and sample.start_date <= row.trading_date <= sample.end_date
        )
    return scoped


def reconcile_sampled_market_bars_from_artifacts(
    *,
    sample: HistoricalReconciliationSampleSpec,
    canonical_manifest: HistoricalDatasetManifest,
    canonical_store: HistoricalArtifactStore,
    independent_manifest: HistoricalDatasetManifest,
    independent_store: HistoricalArtifactStore,
    report_store: HistoricalArtifactStore | None = None,
    report_id: str | None = None,
) -> HistoricalReconciliationReport:
    """Reconcile two frozen ``MARKET_BAR`` sources under a persisted M4 spec.

    The two manifest/store pairs are read-only inputs.  Rows outside the
    persisted listing/date sample are ignored before the existing sampled
    comparator validates A/CNY/UNADJUSTED semantics and computes the v1 report.
    When ``report_store`` is supplied, the unchanged report contract is also
    frozen as a content-addressed JSON artifact.
    """

    if sample.currency != "CNY":
        raise HistoricalArtifactReconciliationError(
            "M4 artifact-backed reconciliation requires CNY"
        )
    if (
        sample.canonical_price_basis is not PriceBasis.UNADJUSTED
        or sample.independent_price_basis is not PriceBasis.UNADJUSTED
    ):
        raise HistoricalArtifactReconciliationError(
            "M4 artifact-backed reconciliation requires unadjusted prices"
        )

    canonical_descriptor = _manifest_source_for_sample(
        canonical_manifest,
        sample,
        canonical=True,
    )
    independent_descriptor = _manifest_source_for_sample(
        independent_manifest,
        sample,
        canonical=False,
    )
    assert_reconciliation_source_independence(
        canonical_descriptor,
        independent_descriptor,
    )

    report = reconcile_sampled_market_bars(
        sample=sample,
        canonical_bars=_sampled_bars_from_manifest(
            canonical_manifest,
            canonical_store,
            source_id=sample.canonical_source_id,
            sample=sample,
        ),
        independent_bars=_sampled_bars_from_manifest(
            independent_manifest,
            independent_store,
            source_id=sample.independent_source_id,
            sample=sample,
        ),
        report_id=report_id,
    )
    if report_store is not None:
        report_store.freeze_json_artifact(report)
    return report


# Compatibility-friendly descriptive names for callers implementing the M4
# fixed-price path.
reconcile_price_bars = reconcile_sampled_market_bars
reconcile_sampled_price_closes = reconcile_sampled_market_bars


__all__ = [
    "RECONCILIATION_SOURCE_INDEPENDENCE_UNPROVEN",
    "HistoricalArtifactReconciliationError",
    "ReconciliationSourceIndependenceError",
    "assert_reconciliation_source_independence",
    "reconcile_observations",
    "reconcile_price_bars",
    "reconcile_sampled_market_bars",
    "reconcile_sampled_price_closes",
    "reconcile_sampled_prices",
    "reconcile_sampled_market_bars_from_artifacts",
    "validate_reconciliation_source_independence",
]
