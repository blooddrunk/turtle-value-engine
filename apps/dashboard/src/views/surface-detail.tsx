import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import type { ReactElement } from "react";

import { fetchSurface, type SurfaceSnapshot } from "../api/client";
import {
  ErrorState,
  FieldList,
  LoadingState,
  PillList,
  Section,
  StatusBadge,
  StringList,
  TechnicalDetails,
} from "../components";
import {
  businessDimensionLabel,
  formatScalar,
  gateLabels,
  metricGroups,
  statePresentation,
  tierPresentation,
  useCopy,
  useLocale,
} from "../presentation";
import type { components } from "../generated/surface-api";

type SurfaceGate = components["schemas"]["SurfaceGate"];
type SurfaceGates = components["schemas"]["SurfaceGates"];
type MetricRecord = Record<string, unknown>;

function MetricGroup({
  metric,
  title,
  rows,
}: {
  metric: MetricRecord;
  title: string;
  rows: readonly { key: string; label: string }[];
}): ReactElement {
  const locale = useLocale();
  return (
    <article className="metric-group">
      <h3>{title}</h3>
      <dl className="metric-list">
        {rows.map(({ label, key }) => (
          <div className="metric-row" key={key}>
            <dt>{label}</dt>
            <dd>{formatScalar(metric[key], locale)}</dd>
          </div>
        ))}
      </dl>
      <PillList
        items={
          Array.isArray(metric.flags) ? metric.flags.filter((item): item is string => typeof item === "string") : undefined
        }
      />
    </article>
  );
}

function GateCard({ label, gate }: { label: string; gate: SurfaceGate }): ReactElement {
  const copy = useCopy();
  return (
    <article className="gate-card">
      <div className="gate-heading">
        <h3>{label}</h3>
        <StatusBadge value={gate.status} />
      </div>
      {gate.confidence ? (
        <p className="compact-meta">
          {copy.confidenceLabel}：<StatusBadge value={gate.confidence} />
        </p>
      ) : null}
      <div className="gate-blockers">
        <h4>{copy.gateBlockingReasons}</h4>
        <StringList items={gate.blocking_reasons} />
      </div>
      {gate.rules?.length ? (
        <details className="gate-rules">
          <summary>{copy.gateRulesSummary(gate.rules.length)}</summary>
          <div className="rule-list">
            {gate.rules.map((rule) => (
              <div className="rule-row" key={rule.rule_id}>
                <div>
                  <strong>{rule.rule_id}</strong>
                  {rule.message ? <p>{rule.message}</p> : null}
                </div>
                <StatusBadge value={rule.status} />
              </div>
            ))}
          </div>
        </details>
      ) : null}
    </article>
  );
}

function DecisionAndValuation({ surface }: { surface: SurfaceSnapshot }): ReactElement {
  const copy = useCopy();
  const locale = useLocale();
  const { decision, valuation } = surface.analysis;
  return (
    <Section title={copy.decisionSection} className="decision-section">
      <div className="decision-grid">
        <div className="decision-callout">
          <span className="small-label">{copy.deterministicDecision}</span>
          <StatusBadge value={decision.state} />
          <p>{decision.summary}</p>
          <FieldList
            rows={[
              { label: copy.autoDecisionAllowed, value: decision.auto_decision_allowed },
              { label: copy.decisionConfidence, value: decision.confidence, state: true },
              { label: copy.blockingReasonsCount, value: decision.blocking_reasons.length },
            ]}
          />
        </div>
        <div className="valuation-block">
          <div className="subsection-heading">
            <h3>{copy.valuationState}</h3>
            <StatusBadge value={valuation.current_valuation_state} />
          </div>
          <FieldList
            rows={[
              { label: copy.listingLabel, value: valuation.listing },
              { label: copy.asOfLabel, value: valuation.as_of },
              { label: copy.valuationCurrency, value: valuation.valuation_currency },
              { label: copy.currentPrice, value: valuation.current_price },
              { label: copy.normalizedParentCoreCdc, value: valuation.normalized_parent_core_cdc },
              { label: copy.recurringShareholderCash, value: valuation.recurring_shareholder_cash },
              { label: copy.valuationNetCash, value: valuation.valuation_net_cash },
            ]}
          />
        </div>
      </div>
      <div className="tier-table-frame">
        <table className="tier-table">
          <caption>{copy.tiersCaption}</caption>
          <thead>
            <tr>
              <th scope="col">{copy.tierColumn}</th>
              <th scope="col">{copy.cdcHurdle}</th>
              <th scope="col">{copy.returnHurdle}</th>
              <th scope="col">{copy.priceColumn}</th>
              <th scope="col">{copy.marketCapColumn}</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(valuation.tiers).map(([tier, values]) => {
              const presentation = tierPresentation(tier, locale);
              return (
                <tr key={tier}>
                  <th scope="row">
                    {presentation.label} <span className="raw-suffix">{presentation.raw}</span>
                  </th>
                  <td>{formatScalar(values.cdc_hurdle, locale)}</td>
                  <td>{formatScalar(values.return_hurdle, locale)}</td>
                  <td>{formatScalar(values.price, locale)}</td>
                  <td>{formatScalar(values.market_cap, locale)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <PillList items={valuation.flags} />
    </Section>
  );
}

function BusinessQuality({ surface }: { surface: SurfaceSnapshot }): ReactElement {
  const copy = useCopy();
  const locale = useLocale();
  const view = surface.analysis;
  return (
    <Section title={copy.bqSection}>
      <div className="status-line">
        <span>{copy.bqValidationState}</span>
        <StatusBadge value={view.business_quality_status} />
      </div>
      {view.business_quality_status === "NOT_EVALUATED" || !view.business_quality ? (
        <div className="not-evaluated-note">
          <StatusBadge value="NOT_EVALUATED" />
          <p>{copy.bqNotEvaluatedBody}</p>
        </div>
      ) : (
        <>
          <div className="quality-summary">
            <FieldList
              rows={[
                { label: copy.bqScore, value: view.business_quality.score },
                { label: copy.bqGrade, value: view.business_quality.grade },
                { label: copy.bqConfidence, value: view.business_quality.confidence, state: true },
                { label: copy.bqEvidenceCoverage, value: view.business_quality.evidence_coverage },
              ]}
            />
          </div>
          <div className="dimension-grid">
            {view.business_quality.dimension_results?.map((dimension) => (
              <article className="dimension-card" key={dimension.dimension}>
                <div className="dimension-heading">
                  <h3>{businessDimensionLabel(dimension.dimension, locale)}</h3>
                  <strong>{dimension.score}/5</strong>
                </div>
                <p className="compact-meta">
                  {copy.confidenceLabel}：<StatusBadge value={dimension.confidence} />
                </p>
                <p>{dimension.reasoning_summary ?? statePresentation("NOT_AVAILABLE", locale).label}</p>
                <div className="evidence-columns">
                  <div>
                    <h4>{copy.supportingEvidence}</h4>
                    <StringList items={dimension.supporting_evidence_ids} />
                  </div>
                  <div>
                    <h4>{copy.counterEvidence}</h4>
                    <StringList items={dimension.counter_evidence_ids} />
                  </div>
                </div>
              </article>
            ))}
          </div>
          <div className="two-column-notes">
            <div>
              <h3>{copy.criticalWeaknesses}</h3>
              <StringList items={view.business_quality.critical_weaknesses} />
            </div>
            <div>
              <h3>{copy.unresolvedQuestions}</h3>
              <StringList items={view.business_quality.unresolved_questions} />
            </div>
          </div>
        </>
      )}
    </Section>
  );
}

function HistoricalStatus({ surface }: { surface: SurfaceSnapshot }): ReactElement {
  const copy = useCopy();
  const locale = useLocale();
  const historical = surface.historical_status;
  return (
    <Section title={copy.historicalSection}>
      <div className="status-grid">
        <div className="status-cell">
          <span>{copy.availability}</span>
          <StatusBadge value={historical.availability} />
        </div>
        <div className="status-cell">
          <span>{copy.claimState}</span>
          <StatusBadge value={historical.claim_state} />
        </div>
        <div className="status-cell">
          <span>{copy.acceptance}</span>
          <StatusBadge value={historical.acceptance.status} />
        </div>
        <div className="status-cell">
          <span>{copy.readiness}</span>
          <StatusBadge value={historical.readiness.status} />
        </div>
        <div className="status-cell">
          <span>{copy.validation}</span>
          <StatusBadge value={historical.validation.status} />
        </div>
        <div className="status-cell">
          <span>{copy.productionEligible}</span>
          <span className="value-text">{formatScalar(historical.production_eligible, locale)}</span>
        </div>
      </div>
      <div className="status-notes-grid">
        <div>
          <h3>{copy.blockers}</h3>
          <StringList items={historical.blockers} />
          <StringList items={historical.acceptance.blockers} />
          <StringList items={historical.readiness.blockers} />
          <StringList items={historical.validation.production_blockers} />
        </div>
        <div>
          <h3>{copy.warnings}</h3>
          <StringList items={historical.warnings} />
          <StringList items={historical.readiness.warnings} />
          <StringList items={historical.validation.warnings} />
        </div>
        <div>
          <h3>{copy.limitations}</h3>
          <StringList items={historical.limitations} />
        </div>
      </div>
      {historical.target_scope ? (
        <div className="scope-box">
          <h3>{copy.targetScope}</h3>
          <FieldList
            rows={[
              { label: copy.scopeTarget, value: historical.target_scope.target_name },
              { label: copy.scopeUniverse, value: historical.target_scope.universe_id },
              { label: copy.scopeMarkets, value: historical.target_scope.markets.join(", ") },
              { label: copy.scopePeriod, value: `${historical.target_scope.start_date} → ${historical.target_scope.end_date}` },
              { label: copy.membershipClaim, value: historical.target_scope.membership_claim },
              { label: copy.coverageClaim, value: historical.target_scope.coverage_claim },
            ]}
          />
        </div>
      ) : null}
    </Section>
  );
}

function TechnicalAuditDetails({ surface }: { surface: SurfaceSnapshot }): ReactElement {
  const copy = useCopy();
  const references = [
    ...surface.source_artifacts,
    ...(surface.decision_trace_reference ? [surface.decision_trace_reference] : []),
    ...(surface.research_report_reference ? [surface.research_report_reference] : []),
  ];
  const unique = references.filter(
    (reference, index) =>
      references.findIndex((item) => item.artifact_id === reference.artifact_id) === index,
  );
  const historical = surface.historical_status;
  return (
    <TechnicalDetails className="detail-technical" summary={copy.technicalSectionSummary}>
      <p className="section-description">{copy.technicalIntro}</p>
      <FieldList
        rows={[
          { label: copy.snapshotContractLabel, value: surface.contract, mono: true },
          { label: copy.schemaVersionLabel, value: surface.schema_version, mono: true },
          {
            label: copy.endpointLabel,
            value: `GET /api/v1/surfaces/${surface.surface_id}`,
            mono: true,
          },
          { label: copy.analysisIdLabel, value: surface.analysis_id, mono: true },
          { label: copy.surfaceIdLabel, value: surface.surface_id, mono: true },
          { label: copy.contentHashLabel, value: surface.content_sha256, mono: true },
        ]}
      />
      <h4>{copy.sourceArtifactsLabel}</h4>
      <div className="artifact-list">
        {unique.map((reference) => (
          <div className="artifact-row" key={reference.artifact_id}>
            <div>
              <strong>{reference.artifact_type}</strong>
              <span>{reference.artifact_id}</span>
            </div>
            <code className="hash-value">{reference.content_sha256}</code>
          </div>
        ))}
      </div>
      <h4>{copy.historicalIdentitiesLabel}</h4>
      <FieldList
        className="historical-identities"
        rows={[
          { label: copy.datasetIdLabel, value: historical.dataset_id, mono: true },
          { label: copy.datasetVersionLabel, value: historical.dataset_version, mono: true },
          { label: copy.manifestHashLabel, value: historical.manifest_sha256, mono: true },
          { label: copy.acceptanceHashLabel, value: historical.acceptance.report_sha256, mono: true },
          { label: copy.readinessHashLabel, value: historical.readiness.report_sha256, mono: true },
          { label: copy.validationHashLabel, value: historical.validation.content_sha256, mono: true },
        ]}
      />
    </TechnicalDetails>
  );
}

export function SurfaceDetailPage(): ReactElement {
  const copy = useCopy();
  const locale = useLocale();
  const { surfaceId } = useParams({ from: "/surfaces/$surfaceId" });
  const surface = useQuery({
    queryKey: ["surface", surfaceId],
    queryFn: () => fetchSurface(surfaceId),
  });

  if (surface.isPending) return <LoadingState label={copy.loadingDetail} />;
  if (surface.isError || !surface.data) {
    return (
      <div className="page page-detail">
        <Link className="back-link" to="/">
          {copy.backToList}
        </Link>
        <ErrorState error={surface.error} onRetry={() => void surface.refetch()} />
      </div>
    );
  }

  const data = surface.data;
  const view = data.analysis;
  const gates = gateLabels(locale);
  const identityRows: { label: string; value: unknown }[] = [
    { label: copy.listingLabel, value: data.company.primary_listing },
    { label: copy.asOfLabel, value: data.as_of },
    { label: copy.profileLabel, value: data.profile_id },
  ];
  if (data.company.sector) identityRows.push({ label: copy.sectorLabel, value: data.company.sector });
  if (data.company.reporting_currency) {
    identityRows.push({ label: copy.reportingCurrencyLabel, value: data.company.reporting_currency });
  }
  if (data.company.other_listings?.length) {
    identityRows.push({
      label: copy.otherListingsLabel,
      value: data.company.other_listings.join("、"),
    });
  }

  return (
    <div className="page page-detail">
      <Link className="back-link" to="/">
        {copy.backToList}
      </Link>
      <header className="detail-heading">
        <div>
          <h1>{data.company.name}</h1>
          <p className="lede">
            {data.company.primary_listing} · {copy.dataAsOfPrefix} {data.as_of} ·{" "}
            {copy.profilePrefix} {data.profile_id}
          </p>
        </div>
        <div className="detail-heading-status">
          <StatusBadge value={view.decision.state} />
        </div>
      </header>

      <section className="identity-band" aria-label={copy.companyNameLabel}>
        <FieldList rows={identityRows} />
      </section>

      <DecisionAndValuation surface={data} />

      <Section title={copy.metricsSection} className="metrics-section">
        <p className="section-description">{copy.metricsNote}</p>
        <div className="metric-grid">
          {metricGroups(locale).map((group) => (
            <MetricGroup
              key={group.key}
              metric={view.metrics[group.key] as MetricRecord}
              rows={group.rows}
              title={group.title}
            />          ))}
        </div>
      </Section>

      <Section title={copy.gatesSection} className="gates-section">
        <p className="section-description">{copy.gatesNote}</p>
        <div className="gate-grid">
          {gates.map(({ key, label }) => (
            <GateCard gate={view.gates[key as keyof SurfaceGates] as SurfaceGate} key={key} label={label} />
          ))}
        </div>
      </Section>

      <Section title={copy.dataQualitySection}>
        <div className="status-line">
          <span>{copy.confidenceLabel}</span>
          <StatusBadge value={view.data_quality.confidence} />
        </div>
        <FieldList
          rows={[
            { label: copy.evidenceCoverage, value: view.data_quality.evidence_coverage },
            { label: copy.notesLabel, value: view.data_quality.notes },
          ]}
        />
        <h3>{copy.criticalMissing}</h3>
        <StringList items={view.data_quality.critical_missing_fields} />
        <PillList items={view.flags} />
      </Section>

      <BusinessQuality surface={data} />
      <HistoricalStatus surface={data} />
      <TechnicalAuditDetails surface={data} />
    </div>
  );
}
