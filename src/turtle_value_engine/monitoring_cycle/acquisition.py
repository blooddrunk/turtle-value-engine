"""Default Phase 6-B adapter used by the D1 cycle boundary."""

from __future__ import annotations

from pathlib import Path

from turtle_value_engine.monitoring_acquisition import (
    AcquisitionWindow,
    acquire_filing_events,
)
from turtle_value_engine.providers.cache import FilesystemRawResponseCache
from turtle_value_engine.providers.cninfo_disclosure import (
    UrllibCninfoHttpTransport,
    cninfo_disclosure_source_client,
    cninfo_filing_provider_version,
)
from turtle_value_engine.providers.filings import FilingSource, OfficialFilingDiscoveryProvider

from .service import CycleAcquisitionOutcome, CycleAcquisitionRequest


class CninfoCycleAcquisition:
    """Compose D1 with the already-proven, deny-by-default CNINFO service.

    This class only constructs the existing Phase 6-B provider boundary.  It
    intentionally contains no source normalization, taxonomy or cache logic.
    """

    def __init__(
        self,
        cache_dir: str | Path,
        *,
        timeout_seconds: float = 15.0,
        max_response_bytes: int = 512 * 1024,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes

    def acquire(self, request: CycleAcquisitionRequest) -> CycleAcquisitionOutcome:
        spec = request.spec
        if spec.source_id != FilingSource.CNINFO.value:
            raise ValueError("D1 default acquisition supports only the closed CNINFO source")
        adapter_version = spec.adapter_version
        transport = UrllibCninfoHttpTransport(
            timeout_seconds=self.timeout_seconds,
            max_response_bytes=self.max_response_bytes,
        )
        provider = OfficialFilingDiscoveryProvider(
            {
                FilingSource.CNINFO: cninfo_disclosure_source_client(transport),
            },
            provider_version=cninfo_filing_provider_version(),
        )
        outcome = acquire_filing_events(
            provider=provider,
            listings=[entry.listing_id for entry in request.watchlist.entries if entry.enabled],
            window=AcquisitionWindow(
                published_from=spec.published_from,
                published_to=spec.published_to,
            ),
            source_id=spec.source_id,
            adapter_version=adapter_version,
            cache=FilesystemRawResponseCache(self.cache_dir),
            limit=spec.acquisition_limit,
            as_of=spec.as_of,
            network_allowed=spec.network_allowed,
            offline=spec.offline_replay,
        )
        return CycleAcquisitionOutcome(
            batch=outcome.batch,
            retrieval_mode="CACHE_REPLAY" if spec.offline_replay else "LIVE",
        )


__all__ = ["CninfoCycleAcquisition"]
