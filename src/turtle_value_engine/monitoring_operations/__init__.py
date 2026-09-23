"""Phase 6-D3 read-only monitoring operations projection package.

This package builds a versioned, framework-neutral, secret-free
``MonitoringOperationsProjectionV1`` over explicitly configured local
monitoring stores.  It is strictly read-only: it never invokes a provider,
model, research or analysis runtime, never executes a cycle, never dispatches
or retries a delivery, and never repairs or publishes any pointer.
"""

from .contracts import (
    MONITORING_OPERATIONS_PROJECTION_CONTRACT,
    MONITORING_OPERATIONS_SCHEMA_VERSION,
    MONITORING_OPERATIONS_SOURCES_CONTRACT,
    MonitoringOperationsActivationV1,
    MonitoringOperationsCycleV1,
    MonitoringOperationsDeliveryAttemptV1,
    MonitoringOperationsDeliveryV1,
    MonitoringOperationsJobDetailV1,
    MonitoringOperationsJobV1,
    MonitoringOperationsLeaseRecordV1,
    MonitoringOperationsProjectionV1,
    MonitoringOperationsReceiptV1,
    MonitoringOperationsRunnerV1,
    MonitoringOperationsSourcesV1,
    MonitoringOperationsUnresolvedClaimV1,
)
from .projection import (
    MonitoringOperationsConflictError,
    MonitoringOperationsError,
    MonitoringOperationsSourcesError,
    build_monitoring_operations_projection,
)
from .service import MonitoringOperationsReadService
from .sources import sources_from_runner_config

__all__ = [
    "MONITORING_OPERATIONS_PROJECTION_CONTRACT",
    "MONITORING_OPERATIONS_SCHEMA_VERSION",
    "MONITORING_OPERATIONS_SOURCES_CONTRACT",
    "MonitoringOperationsActivationV1",
    "MonitoringOperationsConflictError",
    "MonitoringOperationsCycleV1",
    "MonitoringOperationsDeliveryAttemptV1",
    "MonitoringOperationsDeliveryV1",
    "MonitoringOperationsError",
    "MonitoringOperationsJobDetailV1",
    "MonitoringOperationsJobV1",
    "MonitoringOperationsLeaseRecordV1",
    "MonitoringOperationsProjectionV1",
    "MonitoringOperationsReadService",
    "MonitoringOperationsReceiptV1",
    "MonitoringOperationsRunnerV1",
    "MonitoringOperationsSourcesError",
    "MonitoringOperationsSourcesV1",
    "MonitoringOperationsUnresolvedClaimV1",
    "build_monitoring_operations_projection",
    "sources_from_runner_config",
]
