import type {
  MonitoringOperationsProjection,
  SurfaceListResponse,
  SurfaceSnapshot,
} from "../api/client";

export const testSurfaceId = "a".repeat(64);
export const testContentHash = "b".repeat(64);

const gate = (status: string, blocking_reasons: string[] = []) => ({
  status,
  rules: [],
  blocking_reasons,
  confidence: "MEDIUM",
});

export const testSnapshot = {
  contract: "research_surface_snapshot_v1",
  schema_version: "1.0.0",
  surface_id: testSurfaceId,
  content_sha256: testContentHash,
  analysis_id: "analysis-fixture",
  as_of: "2026-09-19",
  profile_id: "strict-v1",
  company: {
    name: "Fixture Holdings",
    primary_listing: "SH600000",
    other_listings: [],
    sector: "Industrials",
    reporting_currency: "CNY",
  },
  analysis: {
    analysis_id: "analysis-fixture",
    as_of: "2026-09-19",
    profile_id: "strict-v1",
    company: {
      name: "Fixture Holdings",
      primary_listing: "SH600000",
      other_listings: [],
      sector: "Industrials",
      reporting_currency: "CNY",
    },
    data_quality: {
      confidence: "MEDIUM",
      critical_missing_fields: ["historical_membership"],
      evidence_coverage: 0.72,
      notes: "Fixture data is intentionally incomplete.",
    },
    metrics: {
      cdc: { normalized_parent_core_cdc: 12.5, cdc_yield: null, flags: ["PARTIAL"] },
      net_cash: { owner_net_cash_ratio: null, strict_net_cash: 8.2, flags: ["BLOCKED"] },
      through_return: {
        through_return: null,
        verified_recurring_buyback_cash: 0,
        buyback_credit_eligible: false,
        flags: ["NOT_AVAILABLE"],
      },
    },
    gates: {
      universe: gate("PASS"),
      balance_sheet: gate("PARTIAL", ["Restricted cash classification unresolved"]),
      cdc: gate("BLOCKED", ["CDC continuity evidence is incomplete"]),
      through_return: gate("NOT_AVAILABLE", ["Payout history is not available"]),
      business_quality: gate("NOT_EVALUATED"),
      governance_data_quality: gate("WATCH", ["One critical field is missing"]),
    },
    valuation: {
      as_of: "2026-09-19",
      listing: "SH600000",
      valuation_currency: "CNY",
      current_valuation_state: "NO_NORMAL_VALUATION",
      confidence: "LOW",
      normalized_parent_core_cdc: null,
      distributable_base: null,
      recurring_shareholder_cash: null,
      verified_recurring_buyback_cash: 0,
      tiers: {
        observation: { cdc_hurdle: 0.06, return_hurdle: 0.04, price: null, market_cap: null },
        acceptable: { cdc_hurdle: 0.08, return_hurdle: 0.05, price: null, market_cap: null },
        turtle_entry: { cdc_hurdle: 0.1, return_hurdle: 0.05, price: null, market_cap: null },
        extreme_safety: { cdc_hurdle: 0.12, return_hurdle: 0.06, price: null, market_cap: null },
      },
    },
    decision: {
      state: "SPECIAL_REVIEW",
      summary: "Frozen fixture requires review.",
      auto_decision_allowed: false,
      blocking_reasons: ["Business Quality is NOT_EVALUATED"],
      confidence: "LOW",
    },
    business_quality_status: "NOT_EVALUATED",
    business_quality: null,
    flags: ["PARTIAL"],
    evidence_ids: [],
  },
  source_artifacts: [
    {
      artifact_type: "COMPANY_ANALYSIS",
      artifact_id: "analysis-fixture",
      content_sha256: "c".repeat(64),
      as_of: "2026-09-19",
    },
  ],
  historical_status: {
    availability: "AVAILABLE",
    claim_state: "PARTIAL",
    dataset_id: "dataset-fixture",
    dataset_version: "1",
    manifest_sha256: "d".repeat(64),
    production_eligible: false,
    blockers: ["H-share coverage is not proven"],
    warnings: ["Terminal economics remain unresolved"],
    limitations: ["Fixture covers one listing only"],
    acceptance: {
      status: "BLOCKED",
      blockers: ["A6 acceptance is blocked"],
      report_sha256: "e".repeat(64),
    },
    readiness: { status: "NOT_AVAILABLE" },
    validation: { status: "NOT_AVAILABLE" },
  },
} as unknown as SurfaceSnapshot;

export const testListResponse: SurfaceListResponse = {
  surfaces: [
    {
      surface_id: testSurfaceId,
      content_sha256: testContentHash,
      analysis_id: "analysis-fixture",
      primary_listing: "SH600000",
      profile_id: "strict-v1",
      as_of: "2026-09-19",
    },
  ],
};

export const testMonitoringActivationId = "f".repeat(64);
export const testMonitoringCycleId = "1".repeat(64);
export const testMonitoringDeliveryId = "2".repeat(64);

const monitoringDeliveryState = (overrides: Record<string, unknown>) => ({
  contract: "monitoring_delivery_state_v1",
  schema_version: "1.0.0",
  delivery_id: testMonitoringDeliveryId,
  status: "DELIVERED",
  terminal: true,
  attempt_count: 1,
  terminal_attempt_number: 1,
  terminal_attempt_content_sha256: "b2".repeat(32),
  last_http_status: 200,
  last_error_code: null,
  next_attempt_not_before: null,
  intent_content_sha256: "b3".repeat(32),
  updated_at: "2026-09-08T00:10:05Z",
  content_sha256: "b4".repeat(32),
  ...overrides,
});

const monitoringDelivery = (overrides: Record<string, unknown> = {}) => ({
  delivery_id: testMonitoringDeliveryId,
  runner_id: "turtle-test",
  activation_id: testMonitoringActivationId,
  cycle_id: testMonitoringCycleId,
  alert_batch_id: "8".repeat(64),
  destination_id: "owner-primary",
  transport: "http_webhook",
  payload_contract: "monitoring_webhook_payload_v1",
  payload_sha256: "b1".repeat(32),
  empty_outbox: false,
  created_at: "2026-09-08T00:10:00Z",
  state: monitoringDeliveryState({}),
  pointer_published: true,
  pointer_status: "CURRENT",
  dispatch_claim_count: 1,
  unresolved_claim_numbers: [],
  unresolved_dispatch_claim: null,
  attempts: [
    {
      attempt_number: 1,
      started_at: "2026-09-08T00:10:00Z",
      finished_at: "2026-09-08T00:10:05Z",
      classification: "DELIVERED",
      http_status: 200,
      response_body_sha256: "b5".repeat(32),
      error_code: null,
      retry_not_before: null,
    },
  ],
  ...overrides,
});

const monitoringBase = {
  contract: "monitoring_operations_projection_v1",
  schema_version: "1.0.0",
  runner_id: "turtle-test",
  watchlist: {
    contract: "monitoring_status_v1",
    schema_version: "1.0.0",
    watchlist_id: "phase6d2a-test",
    availability: "AVAILABLE",
    state_id: "3".repeat(64),
    last_committed_run_id: "4".repeat(64),
    entries: [],
  },
  runner: {
    runner_id: "turtle-test",
    lease_state: "ABANDONED",
    lease_corrupt: false,
    lease_record: {
      contract: "monitoring_runner_lease_v1",
      schema_version: "1.0.0",
      runner_id: "turtle-test",
      activation_id: testMonitoringActivationId,
      acquired_at: "2026-09-08T00:00:00Z",
      heartbeat_at: "2026-09-08T00:05:00Z",
      lease_ttl_seconds: 900,
    },
    unfinished_activation_ids: [],
    latest_terminal_activation_id: testMonitoringActivationId,
  },
  activation: {
    kind: "LATEST_TERMINAL",
    activation_id: testMonitoringActivationId,
    runner_id: "turtle-test",
    cycle_id: testMonitoringCycleId,
    as_of: "2026-09-08T00:00:00Z",
    created_at: "2026-09-08T00:00:00Z",
    request_fingerprint: "5".repeat(64),
    intent_content_sha256: "6".repeat(64),
    receipt: {
      classification: "CYCLE_TERMINAL",
      d1_status: "ALERTS_EMITTED",
      d1_failure_code: null,
      result_content_sha256: "7".repeat(64),
      alert_batch_id: "8".repeat(64),
      alert_batch_content_sha256: "9".repeat(64),
      completed_at: "2026-09-08T00:10:00Z",
      content_sha256: "aa".repeat(32),
    },
  },
  cycle: {
    cycle_id: testMonitoringCycleId,
    status: "ALERTS_EMITTED",
    failure_code: null,
    message: null,
    as_of: "2026-09-08T00:00:00Z",
    watchlist_id: "phase6d2a-test",
    monitoring_run_id: "4".repeat(64),
    event_batch_id: "ab".repeat(32),
    next_state_id: "3".repeat(64),
    alert_batch_id: "8".repeat(64),
    alert_batch_content_sha256: "9".repeat(64),
    result_content_sha256: "7".repeat(64),
    pointer_published: true,
    alert_count: 1,
    alerts: [
      {
        alert_id: "ac".repeat(32),
        kind: "REANALYSIS_SUCCEEDED",
        message: "重分析已按确定性边界完成。",
        reason_code: "REANALYSIS_SUCCEEDED",
      },
    ],
  },
  jobs: [
    {
      request_id: "ad".repeat(32),
      listing_id: "SH600001",
      impact: "FULL_REANALYSIS",
      job_id: "ae".repeat(32),
      job_content_sha256: "af".repeat(32),
      disposition_status: "SUCCEEDED",
      disposition_failure_code: null,
      resolution: "RESOLVED",
      job: {
        status: "SUCCEEDED",
        failure_code: null,
        message: null,
        attempt_number: 1,
        evidence_codes: ["FACT_ANCHORED"],
        analysis_id: "analysis-fixture",
        analysis_sha256: null,
        surface_id: "b0".repeat(32),
        surface_sha256: null,
      },
    },
  ],
  deliveries_configured: true,
  deliveries: [monitoringDelivery()],
};

export const testMonitoringProjection =
  monitoringBase as unknown as MonitoringOperationsProjection;

export const testMonitoringOrphanProjection = {
  ...monitoringBase,
  deliveries: [
    monitoringDelivery({
      state: monitoringDeliveryState({
        status: "AMBIGUOUS",
        attempt_count: 0,
        terminal_attempt_number: null,
        terminal_attempt_content_sha256: null,
        last_http_status: null,
        last_error_code: "ORPHANED_DISPATCH",
      }),
      pointer_status: "STALE_REPAIRABLE",
      dispatch_claim_count: 1,
      unresolved_claim_numbers: [1],
      unresolved_dispatch_claim: {
        attempt_number: 1,
        idempotency_key: testMonitoringDeliveryId,
        content_sha256: "b6".repeat(32),
      },
      attempts: [],
    }),
  ],
} as unknown as MonitoringOperationsProjection;

export const testMonitoringEmptyProjection = {
  ...monitoringBase,
  watchlist: {
    contract: "monitoring_status_v1",
    schema_version: "1.0.0",
    watchlist_id: "phase6d2a-test",
    availability: "NOT_AVAILABLE",
    state_id: null,
    last_committed_run_id: null,
    entries: [],
  },
  runner: {
    runner_id: "turtle-test",
    lease_state: "FREE",
    lease_corrupt: false,
    lease_record: null,
    unfinished_activation_ids: [],
    latest_terminal_activation_id: null,
  },
  activation: null,
  cycle: null,
  jobs: [],
  deliveries_configured: false,
  deliveries: [],
} as unknown as MonitoringOperationsProjection;

export const testMonitoringUnknownLeaseProjection = {
  ...testMonitoringEmptyProjection,
  runner: {
    ...testMonitoringEmptyProjection.runner,
    lease_state: "UNKNOWN",
  },
} as unknown as MonitoringOperationsProjection;
