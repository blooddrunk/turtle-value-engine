"""Explicit source binding helpers for the monitoring operations projection.

The projection never discovers state by scanning a working directory: it is
always bound to one explicit ``RunnerConfigV1`` (the same typed non-secret
input the unattended runner uses) plus an optional delivery ledger root from
the typed ``[monitoring.delivery]`` project configuration.
"""

from __future__ import annotations

from turtle_value_engine.monitoring_runner import RunnerConfigV1

from .contracts import MonitoringOperationsSourcesV1

__all__ = ["sources_from_runner_config"]


def sources_from_runner_config(
    config: RunnerConfigV1,
    *,
    delivery_root: str | None = None,
) -> MonitoringOperationsSourcesV1:
    """Bind projection sources to exactly the stores the runner config names."""

    if not isinstance(config, RunnerConfigV1):
        raise TypeError("config must be a RunnerConfigV1")
    return MonitoringOperationsSourcesV1(
        runner_id=config.runner_id,
        watchlist_path=config.watchlist_path,
        monitoring_workspace_root=config.monitoring_workspace_root,
        reanalysis_job_root=config.reanalysis_job_root,
        cycle_store_root=config.cycle_store_root,
        runner_root=config.runner_root,
        delivery_root=delivery_root,
        lease_ttl_seconds=config.lease_ttl_seconds,
    )
