import { useQuery } from "@tanstack/react-query";
import type { ReactElement } from "react";

import {
  fetchMonitoringOperations,
  type MonitoringOperationsDelivery,
  type MonitoringOperationsJob,
  type MonitoringOperationsProjection,
} from "../api/client";
import {
  ErrorState,
  HashValue,
  LoadingState,
  PillList,
  Section,
  StatusBadge,
  TechnicalDetails,
} from "../components";
import { formatBoolean, formatScalar, useCopy, useLocale, type Copy } from "../presentation";

function StateRow({ label, value }: { label: string; value: string | null | undefined }): ReactElement {
  return (
    <div className="field-row">
      <dt>{label}</dt>
      <dd>
        <StatusBadge value={value} />
      </dd>
    </div>
  );
}

function ScalarRow({ label, value, mono = false }: { label: string; value: unknown; mono?: boolean }): ReactElement {
  const locale = useLocale();
  return (
    <div className="field-row">
      <dt>{label}</dt>
      <dd className={mono ? "mono-value" : undefined}>{formatScalar(value, locale)}</dd>
    </div>
  );
}

function JobCard({ job, copy }: { job: MonitoringOperationsJob; copy: Copy }): ReactElement {
  return (
    <article className="monitoring-card">
      <dl className="field-list">
        <ScalarRow label={copy.monitoringJobListing} value={job.listing_id} mono />
        <StateRow label={copy.monitoringJobImpact} value={job.impact} />
        <StateRow label={copy.monitoringJobDisposition} value={job.disposition_status ?? null} />
        <StateRow label={copy.monitoringJobResolution} value={job.resolution} />
        {job.job ? (
          <>
            <StateRow label={copy.monitoringJobStatus} value={job.job.status} />
            <ScalarRow label={copy.monitoringJobFailureCode} value={job.job.failure_code ?? null} mono />
            <ScalarRow label={copy.monitoringJobMessage} value={job.job.message ?? null} />
          </>
        ) : null}
        {job.disposition_failure_code ? (
          <ScalarRow label={copy.monitoringJobFailureCode} value={job.disposition_failure_code} mono />
        ) : null}
        {job.job?.evidence_codes?.length ? (
          <div className="field-row">
            <dt>{copy.monitoringJobEvidence}</dt>
            <dd>
              <PillList items={job.job.evidence_codes} />
            </dd>
          </div>
        ) : null}
      </dl>
    </article>
  );
}

function DeliveryCard({
  delivery,
  copy,
}: {
  delivery: MonitoringOperationsDelivery;
  copy: Copy;
}): ReactElement {
  const locale = useLocale();
  const state = delivery.state;
  const unresolved = delivery.unresolved_claim_numbers ?? [];
  return (
    <article className="monitoring-card">
      <dl className="field-list">
        <ScalarRow label={copy.monitoringDeliveryDestination} value={delivery.destination_id} mono />
        <ScalarRow label={copy.monitoringDeliveryTransport} value={delivery.transport} mono />
        <StateRow label={copy.monitoringDeliveryStatus} value={state.status} />
        <ScalarRow label={copy.monitoringDeliveryAttemptCount} value={state.attempt_count} />
        <ScalarRow label={copy.monitoringDeliveryDispatchClaimCount} value={delivery.dispatch_claim_count} />
        <div className="field-row">
          <dt>{copy.monitoringDeliveryUnresolvedSlots}</dt>
          <dd>
            {unresolved.length ? (
              <PillList items={unresolved.map((slot) => String(slot))} />
            ) : (
              <span className="muted-copy">{copy.stringListEmpty}</span>
            )}
          </dd>
        </div>
        <ScalarRow label={copy.monitoringDeliveryLastHttpStatus} value={state.last_http_status ?? null} />
        <div className="field-row">
          <dt>{copy.monitoringDeliveryLastError}</dt>
          <dd>
            {state.last_error_code ? (
              <StatusBadge value={state.last_error_code} />
            ) : (
              <span className="muted-copy">{formatScalar(null, locale)}</span>
            )}
          </dd>
        </div>
        <StateRow label={copy.monitoringDeliveryPointerStatus} value={delivery.pointer_status} />
        <ScalarRow label={copy.monitoringDeliveryNextRetry} value={state.next_attempt_not_before ?? null} />
      </dl>
      <p className="muted-copy monitoring-counts-note">{copy.monitoringDeliveryCountsNote}</p>
      {delivery.attempts?.length ? (
        <TechnicalDetails summary={copy.monitoringDeliveryAttemptsSummary}>
          <div className="table-frame">
            <table className="surface-table">
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">{copy.monitoringJobStatus}</th>
                  <th scope="col">{copy.monitoringDeliveryLastHttpStatus}</th>
                  <th scope="col">{copy.monitoringDeliveryLastError}</th>
                  <th scope="col">{copy.monitoringDeliveryNextRetry}</th>
                </tr>
              </thead>
              <tbody>
                {delivery.attempts.map((attempt) => (
                  <tr key={attempt.attempt_number}>
                    <td className="mono-value">{attempt.attempt_number}</td>
                    <td>
                      <StatusBadge value={attempt.classification} />
                    </td>
                    <td className="mono-value">{formatScalar(attempt.http_status ?? null, locale)}</td>
                    <td className="mono-value">{formatScalar(attempt.error_code ?? null, locale)}</td>
                    <td className="mono-value">{formatScalar(attempt.retry_not_before ?? null, locale)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </TechnicalDetails>
      ) : null}
    </article>
  );
}

function OverviewSection({
  projection,
  copy,
}: {
  projection: MonitoringOperationsProjection;
  copy: Copy;
}): ReactElement {
  const locale = useLocale();
  const runner = projection.runner;
  const activation = projection.activation ?? null;
  const cycle = projection.cycle ?? null;
  const unfinished = runner.unfinished_activation_ids?.length ?? 0;
  return (
    <Section title={copy.monitoringOverviewSection}>
      <dl className="field-list">
        <StateRow label={copy.monitoringWatchlistAvailability} value={projection.watchlist.availability} />
        <ScalarRow label={copy.monitoringRunnerId} value={runner.runner_id} mono />
        <StateRow label={copy.monitoringLeaseState} value={runner.lease_state} />
        {runner.lease_corrupt ? (
          <ScalarRow label={copy.monitoringLeaseCorrupt} value={formatBoolean(true, locale)} />
        ) : null}
        {runner.lease_record ? (
          <>
            <ScalarRow label={copy.monitoringLeaseHeartbeat} value={runner.lease_record.heartbeat_at} />
            <ScalarRow label={copy.monitoringLeaseTtl} value={runner.lease_record.lease_ttl_seconds} />
          </>
        ) : null}
        {unfinished > 0 ? (
          <p className="muted-copy">{copy.monitoringUnfinishedActivations(unfinished)}</p>
        ) : null}
      </dl>

      {activation ? (
        <dl className="field-list">
          <StateRow label={copy.monitoringActivationKind} value={activation.kind} />
          <ScalarRow label={copy.monitoringActivationAsOf} value={activation.as_of} />
          <ScalarRow label={copy.monitoringActivationCreatedAt} value={activation.created_at} />
        </dl>
      ) : (
        <div className="state-panel empty-panel">
          <StatusBadge value="NOT_AVAILABLE" />
          <h2>{copy.monitoringNoActivationTitle}</h2>
          <p>{copy.monitoringNoActivationBody}</p>
        </div>
      )}

      {activation ? (
        cycle ? (
          <dl className="field-list">
            <StateRow label={copy.monitoringCycleStatus} value={cycle.status} />
            <ScalarRow label={copy.monitoringCycleAsOf} value={cycle.as_of} />
            <ScalarRow label={copy.monitoringCycleFailureCode} value={cycle.failure_code ?? null} mono />
            <ScalarRow label={copy.monitoringCycleMessage} value={cycle.message ?? null} />
            <ScalarRow label={copy.monitoringAlertsHeading} value={cycle.alert_count} />
            <ScalarRow
              label={copy.monitoringCyclePointerPublished}
              value={formatBoolean(cycle.pointer_published, locale)}
            />
          </dl>
        ) : (
          <div className="state-panel empty-panel">
            <StatusBadge value="ACTIVE" />
            <h2>{copy.monitoringNoCycleTitle}</h2>
            <p>{copy.monitoringNoCycleBody}</p>
          </div>
        )
      ) : null}

      {cycle?.alerts?.length ? (
        <div className="monitoring-alerts">
          <h3>{copy.monitoringAlertsHeading}</h3>
          <ul className="plain-list">
            {cycle.alerts.map((alert) => (
              <li key={alert.alert_id}>
                <StatusBadge value={alert.kind} /> <span>{alert.message}</span>{" "}
                <code className="hash-value">{alert.reason_code}</code>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Section>
  );
}

function AuditSection({
  projection,
  copy,
}: {
  projection: MonitoringOperationsProjection;
  copy: Copy;
}): ReactElement {
  const watchlist = projection.watchlist;
  const activation = projection.activation ?? null;
  const cycle = projection.cycle ?? null;
  const jobs = projection.jobs ?? [];
  const deliveries = projection.deliveries ?? [];
  const rows: { label: string; value: string | null | undefined }[] = [
    { label: copy.monitoringAuditProjectionContract, value: `${projection.contract} @ ${projection.schema_version}` },
    { label: copy.monitoringAuditWatchlistId, value: watchlist.watchlist_id },
    { label: copy.monitoringAuditStateId, value: watchlist.state_id ?? null },
    { label: copy.monitoringAuditLastRunId, value: watchlist.last_committed_run_id ?? null },
    { label: copy.monitoringAuditActivationId, value: activation?.activation_id ?? null },
    { label: copy.monitoringAuditIntentHash, value: activation?.intent_content_sha256 ?? null },
    { label: copy.monitoringAuditReceiptHash, value: activation?.receipt?.content_sha256 ?? null },
    { label: copy.monitoringAuditCycleId, value: cycle?.cycle_id ?? null },
    { label: copy.monitoringAuditResultHash, value: cycle?.result_content_sha256 ?? null },
    { label: copy.monitoringAuditAlertBatchId, value: cycle?.alert_batch_id ?? null },
    { label: copy.monitoringAuditAlertBatchHash, value: cycle?.alert_batch_content_sha256 ?? null },
    { label: copy.monitoringAuditRunId, value: cycle?.monitoring_run_id ?? null },
    { label: copy.monitoringAuditEventBatchId, value: cycle?.event_batch_id ?? null },
    { label: copy.monitoringAuditNextStateId, value: cycle?.next_state_id ?? null },
  ];
  return (
    <Section title={copy.monitoringAuditSection}>
      <dl className="field-list">
        {rows.map((row) => (
          <div className="field-row" key={row.label}>
            <dt>{row.label}</dt>
            <dd>
              <HashValue value={row.value} />
            </dd>
          </div>
        ))}
      </dl>
      {jobs.length ? (
        <dl className="field-list">
          {jobs.map((job) => (
            <div className="field-row" key={job.job_id}>
              <dt>
                {copy.monitoringAuditJobId} <HashValue value={job.job_id} />
              </dt>
              <dd>
                <HashValue value={job.job_content_sha256 ?? null} />
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
      {deliveries.length ? (
        <dl className="field-list">
          {deliveries.map((delivery) => (
            <div className="field-row" key={delivery.delivery_id}>
              <dt>
                {copy.monitoringAuditDeliveryId} <HashValue value={delivery.delivery_id} />
              </dt>
              <dd>
                <HashValue value={delivery.payload_sha256} />{" "}
                <span className="muted-copy">
                  {copy.monitoringAuditIdempotencyKey}: <HashValue value={delivery.delivery_id} />
                </span>
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
    </Section>
  );
}

export function MonitoringPage(): ReactElement {
  const copy = useCopy();
  const query = useQuery({
    queryKey: ["monitoring-operations"],
    queryFn: fetchMonitoringOperations,
  });
  const projection = query.data ?? null;
  const jobs = projection?.jobs ?? [];
  const deliveries = projection?.deliveries ?? [];

  return (
    <div className="page page-monitoring">
      <div className="page-heading">
        <div>
          <h1>{copy.monitoringTitle}</h1>
          <p className="lede">{copy.monitoringLede}</p>
        </div>
        <div className="heading-meta">
          <StatusBadge value="READ_ONLY" />
          <button className="button button-quiet" onClick={() => void query.refetch()} type="button">
            {copy.refreshData}
          </button>
        </div>
      </div>

      {query.isPending ? <LoadingState label={copy.loadingMonitoring} /> : null}
      {query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} /> : null}

      {projection ? (
        <>
          <OverviewSection projection={projection} copy={copy} />

          <Section title={copy.monitoringJobsSection}>
            <span className="table-count">{copy.monitoringJobsCount(jobs.length)}</span>
            {jobs.length === 0 ? (
              <div className="state-panel empty-panel">
                <StatusBadge value="NO_ACTION" />
                <h2>{copy.monitoringNoJobsTitle}</h2>
                <p>{copy.monitoringNoJobsBody}</p>
              </div>
            ) : (
              jobs.map((job) => <JobCard copy={copy} job={job} key={job.job_id} />)
            )}
          </Section>

          <Section title={copy.monitoringDeliveriesSection}>
            <span className="table-count">{copy.monitoringDeliveriesCount(deliveries.length)}</span>
            {!projection.deliveries_configured ? (
              <div className="state-panel empty-panel">
                <StatusBadge value="NOT_AVAILABLE" />
                <h2>{copy.monitoringDeliveriesNotConfiguredTitle}</h2>
                <p>{copy.monitoringDeliveriesNotConfiguredBody}</p>
              </div>
            ) : deliveries.length === 0 ? (
              <div className="state-panel empty-panel">
                <StatusBadge value="NOOP" />
                <h2>{copy.monitoringNoDeliveriesTitle}</h2>
                <p>{copy.monitoringNoDeliveriesBody}</p>
              </div>
            ) : (
              deliveries.map((delivery) => (
                <DeliveryCard copy={copy} delivery={delivery} key={delivery.delivery_id} />
              ))
            )}
          </Section>

          <AuditSection projection={projection} copy={copy} />
        </>
      ) : null}
    </div>
  );
}
