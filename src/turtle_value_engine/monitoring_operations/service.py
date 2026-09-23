"""Framework-neutral read service for the monitoring operations projection.

The service is deliberately constructed from one explicit, typed
``MonitoringOperationsSourcesV1`` binding.  It exposes exactly one read
operation; every store access inside it is strictly read-only and it owns no
provider, model, research, cycle, delivery, repair or mutation path.
"""

from __future__ import annotations

from .contracts import MonitoringOperationsProjectionV1, MonitoringOperationsSourcesV1
from .projection import build_monitoring_operations_projection

__all__ = ["MonitoringOperationsReadService"]


class MonitoringOperationsReadService:
    """Read-only application service independent of any HTTP framework."""

    def __init__(self, sources: MonitoringOperationsSourcesV1) -> None:
        if not isinstance(sources, MonitoringOperationsSourcesV1):
            raise TypeError("sources must be a MonitoringOperationsSourcesV1")
        self._sources = sources

    @property
    def sources(self) -> MonitoringOperationsSourcesV1:
        return self._sources

    def operations_projection(self) -> MonitoringOperationsProjectionV1:
        """Build the current point-in-time projection from local stores only."""

        return build_monitoring_operations_projection(self._sources)
