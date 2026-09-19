import type { SurfaceListResponse, SurfaceSnapshot } from "../api/client";

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
