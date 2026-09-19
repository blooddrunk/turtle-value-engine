import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import type { ReactElement } from "react";

import { fetchSurface, type SurfaceSnapshot } from "../api/client";
import {
  displayValue,
  ErrorState,
  FieldList,
  HashValue,
  LoadingState,
  PillList,
  Section,
  StatusBadge,
  StringList,
} from "../components";
import type { components } from "../generated/surface-api";

type SurfaceGate = components["schemas"]["SurfaceGate"];
type SurfaceGates = components["schemas"]["SurfaceGates"];
type MetricRecord = Record<string, unknown>;

const gateLabels: readonly { key: keyof SurfaceGates; label: string }[] = [
  { key: "universe", label: "Universe" },
  { key: "balance_sheet", label: "Balance sheet" },
  { key: "cdc", label: "CDC" },
  { key: "through_return", label: "Through Return" },
  { key: "business_quality", label: "Business Quality" },
  { key: "governance_data_quality", label: "Governance / data quality" },
];

const metricGroups = [
  {
    title: "CDC",
    key: "cdc",
    rows: [
      ["Reported CFO", "reported_cfo"],
      ["Adjusted CFO", "adjusted_cfo"],
      ["Core CDC", "core_cdc"],
      ["Normalized parent core CDC", "normalized_parent_core_cdc"],
      ["CDC yield", "cdc_yield"],
      ["Positive years (5Y)", "positive_years_5y"],
      ["Cumulative core CDC (5Y)", "cumulative_core_cdc_5y"],
      ["Metric confidence", "confidence"],
    ],
  },
  {
    title: "Net Cash",
    key: "net_cash",
    rows: [
      ["Book cash", "book_cash"],
      ["Strict cash", "strict_cash"],
      ["Owner accessible cash", "owner_accessible_cash"],
      ["Financial debt", "financial_debt"],
      ["Owner realizable net cash", "owner_realizable_net_cash"],
      ["Owner net cash ratio", "owner_net_cash_ratio"],
      ["Liquidity coverage", "liquidity_coverage"],
      ["Stress coverage", "stress_coverage"],
      ["Metric confidence", "confidence"],
    ],
  },
  {
    title: "Through Return",
    key: "through_return",
    rows: [
      ["Distributable base", "distributable_base"],
      ["Dividend Through Return", "dividend_through_return"],
      ["Normalized net share reduction", "normalized_net_share_reduction"],
      ["Through Return", "through_return"],
      ["Verified recurring buyback cash", "verified_recurring_buyback_cash"],
      ["Buyback credit eligible", "buyback_credit_eligible"],
      ["Buyback history years", "buyback_history_years"],
      ["Metric confidence", "confidence"],
    ],
  },
] as const;

const businessDimensionLabels: Record<string, string> = {
  demand_durability: "Demand durability",
  cyclicality: "Cyclicality",
  pricing_power: "Pricing power",
  moat: "Competitive moat",
  capital_efficiency: "Capital efficiency",
  dependency: "Customer / channel / supplier dependency",
  regulatory_risk: "Regulation / external dependency",
  predictability: "Predictability / simplicity",
};

function MetricGroup({
  metric,
  title,
  rows,
}: {
  metric: MetricRecord;
  title: string;
  rows: readonly (readonly [string, string])[];
}): ReactElement {
  return (
    <article className="metric-group">
      <h3>{title}</h3>
      <dl className="metric-list">
        {rows.map(([label, key]) => (
          <div className="metric-row" key={key}>
            <dt>{label}</dt>
            <dd>{displayValue(metric[key])}</dd>
          </div>
        ))}
      </dl>
      <PillList items={Array.isArray(metric.flags) ? metric.flags.filter((item): item is string => typeof item === "string") : undefined} />
    </article>
  );
}

function GateCard({ label, gate }: { label: string; gate: SurfaceGate }): ReactElement {
  return (
    <article className="gate-card">
      <div className="gate-heading">
        <h3>{label}</h3>
        <StatusBadge value={gate.status} />
      </div>
      {gate.confidence ? <p className="compact-meta">Confidence: {gate.confidence}</p> : null}
      <div className="gate-blockers">
        <h4>Blocking reasons</h4>
        <StringList items={gate.blocking_reasons} />
      </div>
      {gate.rules?.length ? (
        <details className="gate-rules">
          <summary>{gate.rules.length} deterministic rules</summary>
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
  const { decision, valuation } = surface.analysis;
  return (
    <Section title="Decision and valuation" className="decision-section">
      <div className="decision-grid">
        <div className="decision-callout">
          <span className="small-label">Deterministic decision</span>
          <StatusBadge value={decision.state} />
          <p>{decision.summary}</p>
          <FieldList
            rows={[
              { label: "Auto decision allowed", value: decision.auto_decision_allowed },
              { label: "Decision confidence", value: decision.confidence },
              { label: "Blocking reasons", value: decision.blocking_reasons.length },
            ]}
          />
        </div>
        <div className="valuation-block">
          <div className="subsection-heading">
            <h3>Valuation state</h3>
            <StatusBadge value={valuation.current_valuation_state} />
          </div>
          <FieldList
            rows={[
              { label: "Listing", value: valuation.listing },
              { label: "As of", value: valuation.as_of },
              { label: "Valuation currency", value: valuation.valuation_currency },
              { label: "Current price", value: valuation.current_price },
              { label: "Normalized parent core CDC", value: valuation.normalized_parent_core_cdc },
              { label: "Recurring shareholder cash", value: valuation.recurring_shareholder_cash },
              { label: "Valuation net cash", value: valuation.valuation_net_cash },
            ]}
          />
        </div>
      </div>
      <div className="tier-table-frame">
        <table className="tier-table">
          <caption>Frozen valuation tiers returned by the engine</caption>
          <thead>
            <tr>
              <th scope="col">Tier</th>
              <th scope="col">CDC hurdle</th>
              <th scope="col">Return hurdle</th>
              <th scope="col">Price</th>
              <th scope="col">Market cap</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(valuation.tiers).map(([tier, values]) => (
              <tr key={tier}>
                <th scope="row">{tier}</th>
                <td>{displayValue(values.cdc_hurdle)}</td>
                <td>{displayValue(values.return_hurdle)}</td>
                <td>{displayValue(values.price)}</td>
                <td>{displayValue(values.market_cap)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <PillList items={valuation.flags} />
    </Section>
  );
}

function BusinessQuality({ surface }: { surface: SurfaceSnapshot }): ReactElement {
  const view = surface.analysis;
  return (
    <Section title="Business Quality">
      <div className="status-line">
        <span>Validation state</span>
        <StatusBadge value={view.business_quality_status} />
      </div>
      {view.business_quality_status === "NOT_EVALUATED" || !view.business_quality ? (
        <div className="not-evaluated-note">
          <strong>NOT_EVALUATED</strong>
          <p>No validated Business Quality assessment is present in this frozen surface.</p>
        </div>
      ) : (
        <>
          <div className="quality-summary">
            <FieldList
              rows={[
                { label: "Score", value: view.business_quality.score },
                { label: "Grade", value: view.business_quality.grade },
                { label: "Confidence", value: view.business_quality.confidence },
                { label: "Evidence coverage", value: view.business_quality.evidence_coverage },
              ]}
            />
          </div>
          <div className="dimension-grid">
            {view.business_quality.dimension_results?.map((dimension) => (
              <article className="dimension-card" key={dimension.dimension}>
                <div className="dimension-heading">
                  <h3>{businessDimensionLabels[dimension.dimension] ?? dimension.dimension}</h3>
                  <strong>{dimension.score}/5</strong>
                </div>
                <p className="compact-meta">Confidence: {dimension.confidence}</p>
                <p>{dimension.reasoning_summary ?? "NOT_AVAILABLE"}</p>
                <div className="evidence-columns">
                  <div>
                    <h4>Supporting evidence</h4>
                    <StringList items={dimension.supporting_evidence_ids} />
                  </div>
                  <div>
                    <h4>Counter-evidence</h4>
                    <StringList items={dimension.counter_evidence_ids} />
                  </div>
                </div>
              </article>
            ))}
          </div>
          <div className="two-column-notes">
            <div>
              <h3>Critical weaknesses</h3>
              <StringList items={view.business_quality.critical_weaknesses} />
            </div>
            <div>
              <h3>Unresolved questions</h3>
              <StringList items={view.business_quality.unresolved_questions} />
            </div>
          </div>
        </>
      )}
    </Section>
  );
}

function HistoricalStatus({ surface }: { surface: SurfaceSnapshot }): ReactElement {
  const historical = surface.historical_status;
  return (
    <Section title="Historical availability and readiness">
      <div className="status-grid">
        <div className="status-cell">
          <span>Availability</span>
          <StatusBadge value={historical.availability} />
        </div>
        <div className="status-cell">
          <span>Claim state</span>
          <StatusBadge value={historical.claim_state} />
        </div>
        <div className="status-cell">
          <span>Acceptance</span>
          <StatusBadge value={historical.acceptance.status} />
        </div>
        <div className="status-cell">
          <span>Readiness</span>
          <StatusBadge value={historical.readiness.status} />
        </div>
        <div className="status-cell">
          <span>Validation</span>
          <StatusBadge value={historical.validation.status} />
        </div>
        <div className="status-cell">
          <span>Production eligible</span>
          <span className="value-text">{displayValue(historical.production_eligible)}</span>
        </div>
      </div>
      <FieldList
        className="historical-identities"
        rows={[
          { label: "Dataset ID", value: historical.dataset_id, mono: true },
          { label: "Dataset version", value: historical.dataset_version, mono: true },
          { label: "Manifest hash", value: historical.manifest_sha256, mono: true },
          { label: "Acceptance report hash", value: historical.acceptance.report_sha256, mono: true },
          { label: "Readiness report hash", value: historical.readiness.report_sha256, mono: true },
          { label: "Validation content hash", value: historical.validation.content_sha256, mono: true },
        ]}
      />
      <div className="status-notes-grid">
        <div>
          <h3>Blockers</h3>
          <StringList items={historical.blockers} />
          <StringList items={historical.acceptance.blockers} />
          <StringList items={historical.readiness.blockers} />
          <StringList items={historical.validation.production_blockers} />
        </div>
        <div>
          <h3>Warnings</h3>
          <StringList items={historical.warnings} />
          <StringList items={historical.readiness.warnings} />
          <StringList items={historical.validation.warnings} />
        </div>
        <div>
          <h3>Limitations</h3>
          <StringList items={historical.limitations} />
        </div>
      </div>
      {historical.target_scope ? (
        <div className="scope-box">
          <h3>Target scope</h3>
          <FieldList
            rows={[
              { label: "Target", value: historical.target_scope.target_name },
              { label: "Universe", value: historical.target_scope.universe_id },
              { label: "Markets", value: historical.target_scope.markets.join(", ") },
              { label: "Period", value: `${historical.target_scope.start_date} → ${historical.target_scope.end_date}` },
              { label: "Membership claim", value: historical.target_scope.membership_claim },
              { label: "Coverage claim", value: historical.target_scope.coverage_claim },
            ]}
          />
        </div>
      ) : null}
    </Section>
  );
}

function SourceArtifacts({ surface }: { surface: SurfaceSnapshot }): ReactElement {
  const references = [
    ...surface.source_artifacts,
    ...(surface.decision_trace_reference ? [surface.decision_trace_reference] : []),
    ...(surface.research_report_reference ? [surface.research_report_reference] : []),
  ];
  const unique = references.filter(
    (reference, index) => references.findIndex((item) => item.artifact_id === reference.artifact_id) === index,
  );
  return (
    <Section title="Source artifact identities">
      <p className="section-description">
        Identity-only references are retained for audit. Local paths, credentials and raw provider
        payloads are intentionally absent.
      </p>
      <div className="artifact-list">
        {unique.map((reference) => (
          <div className="artifact-row" key={reference.artifact_id}>
            <div>
              <strong>{reference.artifact_type}</strong>
              <span>{reference.artifact_id}</span>
            </div>
            <HashValue value={reference.content_sha256} />
          </div>
        ))}
      </div>
    </Section>
  );
}

export function SurfaceDetailPage(): ReactElement {
  const { surfaceId } = useParams({ from: "/surfaces/$surfaceId" });
  const surface = useQuery({
    queryKey: ["surface", surfaceId],
    queryFn: () => fetchSurface(surfaceId),
  });

  if (surface.isPending) return <LoadingState label="Reading the frozen surface detail" />;
  if (surface.isError || !surface.data) {
    return (
      <div className="page page-detail">
        <Link className="back-link" to="/">
          ← Back to surfaces
        </Link>
        <ErrorState
          message={surface.error instanceof Error ? surface.error.message : undefined}
          onRetry={() => void surface.refetch()}
          title="This surface could not be opened"
        />
      </div>
    );
  }

  const data = surface.data;
  const view = data.analysis;
  return (
    <div className="page page-detail">
      <Link className="back-link" to="/">
        ← Back to surfaces
      </Link>
      <header className="detail-heading">
        <div>
          <h1>{data.company.name}</h1>
          <p className="lede">
            {data.company.primary_listing} · snapshot as of {data.as_of} · {data.profile_id}
          </p>
        </div>
        <div className="detail-heading-status">
          <StatusBadge value={view.decision.state} />
          <span className="contract-note">GET /api/v1/surfaces/{data.surface_id.slice(0, 12)}…</span>
        </div>
      </header>

      <section className="identity-band" aria-label="Surface identity">
        <FieldList
          rows={[
            { label: "Listing", value: data.company.primary_listing },
            { label: "As of", value: data.as_of },
            { label: "Profile", value: data.profile_id },
            { label: "Analysis ID", value: data.analysis_id, mono: true },
            { label: "Surface ID", value: data.surface_id, mono: true },
            { label: "Content SHA-256", value: data.content_sha256, mono: true },
          ]}
        />
      </section>

      <DecisionAndValuation surface={data} />

      <Section title="Deterministic metrics" className="metrics-section">
        <p className="section-description">
          Values are displayed as returned. <strong>NOT_AVAILABLE</strong> means the frozen payload
          contains null or omits the field; it is never replaced with zero.
        </p>
        <div className="metric-grid">
          {metricGroups.map((group) => (
            <MetricGroup
              key={group.key}
              metric={view.metrics[group.key] as MetricRecord}
              rows={group.rows}
              title={group.title}
            />
          ))}
        </div>
      </Section>

      <Section title="Hard gates" className="gates-section">
        <p className="section-description">All six gate results remain visible, including reasons that block progress.</p>
        <div className="gate-grid">
          {gateLabels.map(({ key, label }) => (
            <GateCard gate={view.gates[key]} key={key} label={label} />
          ))}
        </div>
      </Section>

      <Section title="Data quality">
        <div className="status-line">
          <span>Confidence</span>
          <StatusBadge value={view.data_quality.confidence} />
        </div>
        <FieldList
          rows={[
            { label: "Evidence coverage", value: view.data_quality.evidence_coverage },
            { label: "Notes", value: view.data_quality.notes },
          ]}
        />
        <h3>Critical missing fields</h3>
        <StringList items={view.data_quality.critical_missing_fields} />
        <PillList items={view.flags} />
      </Section>

      <BusinessQuality surface={data} />
      <HistoricalStatus surface={data} />
      <SourceArtifacts surface={data} />
    </div>
  );
}
