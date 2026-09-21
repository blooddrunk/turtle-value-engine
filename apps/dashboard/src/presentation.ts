import { createContext, useContext } from "react";

import { SurfaceAPIError } from "./api/client";

/**
 * M6-C3 centralized presentation/copy layer.
 *
 * This module is the single owner of user-facing labels, semantic-state
 * explanations, API-error copy and conservative value formatters. Views must
 * not scatter their own translated strings. It never recomputes or rewrites
 * payload semantics: missing stays missing, raw codes stay visible for audit,
 * and unknown enum strings fail safe as an explicit unknown state.
 */

export type Locale = "zh-CN" | "en";

export const DEFAULT_LOCALE: Locale = "zh-CN";

export const LOCALE_STORAGE_KEY = "tve-dashboard-locale";

export function resolveLocale(value: string | null | undefined): Locale {
  return value === "zh-CN" || value === "en" ? value : DEFAULT_LOCALE;
}

export const LocaleContext = createContext<Locale>(DEFAULT_LOCALE);

export function useLocale(): Locale {
  return useContext(LocaleContext) ?? DEFAULT_LOCALE;
}

export type StatusTone = "positive" | "caution" | "negative" | "neutral";

export interface StatePresentation {
  /** Exact raw code as provided by the payload (audit-visible). */
  readonly raw: string;
  /** Friendly primary label in the active locale. */
  readonly label: string;
  /** Plain-language explanation that never alters the deterministic meaning. */
  readonly explanation: string;
  /** Visual tone; never positive for unknown/missing states. */
  readonly tone: StatusTone;
  /** False when the raw code is not in the known semantic table. */
  readonly known: boolean;
}

interface StateEntry {
  readonly tone: StatusTone;
  readonly zh: readonly [label: string, explanation: string];
  readonly en: readonly [label: string, explanation: string];
}

/**
 * Known semantic states across gates, decisions, valuation, data quality,
 * business quality, historical status, health and the read-only UI itself.
 * Keys are the canonical uppercase codes; lookup tolerates raw casing.
 */
const STATE_TABLE: Record<string, StateEntry> = {
  PASS: {
    tone: "positive",
    zh: ["通过", "该确定性检查已通过。"],
    en: ["Pass", "The deterministic check passed."],
  },
  WATCH: {
    tone: "caution",
    zh: ["关注", "存在需要留意的信号，未满足自动通过的条件。"],
    en: ["Watch", "Signals need attention; automatic pass criteria were not met."],
  },
  FAIL: {
    tone: "negative",
    zh: ["未通过", "未达到该硬性门槛的要求。"],
    en: ["Fail", "The hard-gate requirement was not met."],
  },
  SPECIAL_REVIEW: {
    tone: "negative",
    zh: ["需人工复核", "结果无法自动判定，需要人工复核后才能形成结论；这不是通过。"],
    en: ["Manual review", "The result cannot be decided automatically and needs human review; it is not a pass."],
  },
  NOT_EVALUATED: {
    tone: "caution",
    zh: ["未评估", "该维度尚未评估；未评估不代表通过。"],
    en: ["Not evaluated", "This dimension has not been evaluated yet; not evaluated is not a pass."],
  },
  PARTIAL: {
    tone: "caution",
    zh: ["部分数据", "数据或覆盖不完整，相关结论只覆盖已有部分。"],
    en: ["Partial", "Data or coverage is incomplete; conclusions cover only the available part."],
  },
  BLOCKED: {
    tone: "negative",
    zh: ["受阻", "存在明确阻塞，无法完成相应的主张或结论。"],
    en: ["Blocked", "An explicit blocker prevents completing the related claim or conclusion."],
  },
  NOT_AVAILABLE: {
    tone: "neutral",
    zh: ["无可用值", "当前冻结载荷中没有可用值；不是 0，也不代表通过。"],
    en: ["No value", "The frozen payload has no usable value here; it is not zero and not a pass."],
  },
  UNAVAILABLE: {
    tone: "negative",
    zh: ["不可用", "该能力或数据当前不可用。"],
    en: ["Unavailable", "This capability or data is currently unavailable."],
  },
  UNKNOWN: {
    tone: "caution",
    zh: ["未知", "状态未知，无法据此形成结论。"],
    en: ["Unknown", "The state is unknown and cannot support a conclusion."],
  },
  READY: {
    tone: "positive",
    zh: ["就绪", "已满足相应的就绪条件。"],
    en: ["Ready", "The readiness criteria are met."],
  },
  AVAILABLE: {
    tone: "positive",
    zh: ["可用", "数据或能力当前可用。"],
    en: ["Available", "The data or capability is available."],
  },
  ACCEPTED: {
    tone: "positive",
    zh: ["已通过", "已通过相应验收。"],
    en: ["Accepted", "The corresponding acceptance passed."],
  },
  OK: {
    tone: "positive",
    zh: ["正常", "服务状态正常。"],
    en: ["OK", "The service is healthy."],
  },
  VALIDATED: {
    tone: "positive",
    zh: ["已验证", "已通过确定性校验。"],
    en: ["Validated", "Passed deterministic validation."],
  },
  PRODUCTION_ELIGIBLE: {
    tone: "positive",
    zh: ["生产可用", "已满足生产级主张的资格条件。"],
    en: ["Production eligible", "Eligibility criteria for production claims are met."],
  },
  HIGH: {
    tone: "neutral",
    zh: ["高（置信度）", "置信度等级：高。"],
    en: ["High (confidence)", "Confidence level: high."],
  },
  MEDIUM: {
    tone: "neutral",
    zh: ["中（置信度）", "置信度等级：中。"],
    en: ["Medium (confidence)", "Confidence level: medium."],
  },
  LOW: {
    tone: "neutral",
    zh: ["低（置信度）", "置信度等级：低。"],
    en: ["Low (confidence)", "Confidence level: low."],
  },
  ACCEPTABLE: {
    tone: "positive",
    zh: ["可接受", "落在可接受档位。"],
    en: ["Acceptable", "Falls in the acceptable tier."],
  },
  TURTLE_ENTRY: {
    tone: "positive",
    zh: ["龟式入场", "落在龟式入场档位。"],
    en: ["Turtle entry", "Falls in the turtle-entry tier."],
  },
  EXTREME_SAFETY: {
    tone: "positive",
    zh: ["极端安全", "落在极端安全档位。"],
    en: ["Extreme safety", "Falls in the extreme-safety tier."],
  },
  TOO_EXPENSIVE_FOR_STRICT_MODEL: {
    tone: "caution",
    zh: ["超出严格模型价格上限", "按严格模型估值，当前价格过高。"],
    en: ["Too expensive for strict model", "The current price is too high for the strict model."],
  },
  NO_NORMAL_VALUATION: {
    tone: "caution",
    zh: ["无常规估值", "当前输入不足以形成常规估值。"],
    en: ["No normal valuation", "Current inputs are insufficient for a normal valuation."],
  },
  READ_ONLY: {
    tone: "neutral",
    zh: ["只读", "本界面只读取冻结数据，不提供任何写入操作。"],
    en: ["Read-only", "This surface reads frozen data only; no writes are possible."],
  },
  NO_MATCHES: {
    tone: "neutral",
    zh: ["无匹配", "当前筛选条件下没有匹配结果。"],
    en: ["No matches", "Nothing matches the current filters."],
  },
  ERROR: {
    tone: "negative",
    zh: ["错误", "发生错误，请查看说明或重试。"],
    en: ["Error", "An error occurred; see the explanation or retry."],
  },
};

const UNKNOWN_STATE: Record<Locale, readonly [label: string, explanation: string]> = {
  "zh-CN": ["未知状态", "原始状态码不在展示层已知枚举中，按未知处理，不视为通过。"],
  en: ["Unknown state", "The raw code is not in the known semantic table; treated as unknown, never as a pass."],
};

export function statePresentation(
  value: string | null | undefined,
  locale: Locale = DEFAULT_LOCALE,
): StatePresentation {
  const raw = typeof value === "string" && value.length > 0 ? value : "NOT_AVAILABLE";
  const normalized = raw.trim().toUpperCase();
  const entry = STATE_TABLE[normalized];
  if (!entry) {
    const [label, explanation] = UNKNOWN_STATE[locale];
    return { raw, label, explanation, tone: "caution", known: false };
  }
  const [label, explanation] = locale === "en" ? entry.en : entry.zh;
  return { raw, label, explanation, tone: entry.tone, known: true };
}

export interface APIErrorPresentation {
  readonly title: string;
  readonly message: string;
  /** Exact raw diagnostics for the technical-details affordance. */
  readonly raw: { readonly status: string; readonly code: string; readonly message: string };
}

const API_ERROR_TABLE: Record<string, { zh: [string, string]; en: [string, string] }> = {
  SURFACE_NOT_FOUND: {
    zh: ["未找到该研究面", "当前服务中没有此标识对应的已验证快照。请返回列表重新选择，或确认快照已加载。"],
    en: ["Surface not found", "No validated snapshot is registered for this identifier. Go back to the list or confirm the snapshot is loaded."],
  },
  API_ROUTE_NOT_FOUND: {
    zh: ["接口路径不存在", "请求的只读接口路径不存在。"],
    en: ["API route not found", "The requested read-only API route does not exist."],
  },
  INVALID_QUERY_PARAMETER: {
    zh: ["筛选参数无效", "存在 API 不支持的筛选参数或格式，请调整后重试。"],
    en: ["Invalid filter parameter", "A filter parameter or format is not supported by the API; adjust and retry."],
  },
  READ_ONLY_METHOD_NOT_ALLOWED: {
    zh: ["只读接口不允许该操作", "该接口仅支持只读的 GET/HEAD 请求。"],
    en: ["Read-only method not allowed", "This API only supports read-only GET/HEAD requests."],
  },
  UPSTREAM_UNREACHABLE: {
    zh: ["上游服务不可达", "代理无法连接只读研究面服务，请稍后重试或检查服务状态。"],
    en: ["Upstream unreachable", "The proxy cannot reach the read-only surface service; retry later or check the service."],
  },
  UPSTREAM_NOT_CONFIGURED: {
    zh: ["服务配置错误", "只读代理的上游配置缺失，需要运维检查。"],
    en: ["Service misconfigured", "The read-only proxy upstream is not configured; an operator must check it."],
  },
  UPSTREAM_CONFIGURATION_INVALID: {
    zh: ["服务配置错误", "只读代理的上游配置无效，需要运维检查。"],
    en: ["Service misconfigured", "The read-only proxy upstream configuration is invalid; an operator must check it."],
  },
  NO_SNAPSHOTS_CONFIGURED: {
    zh: ["服务端未配置快照", "只读服务启动时没有任何已验证快照。"],
    en: ["No snapshots configured", "The read-only service started without any validated snapshot."],
  },
  SNAPSHOT_VALIDATION_FAILED: {
    zh: ["快照校验失败", "服务端加载的快照未通过校验。"],
    en: ["Snapshot validation failed", "A server-side snapshot failed validation."],
  },
  DUPLICATE_SURFACE_ID: {
    zh: ["快照注册冲突", "服务端注册了重复的研究面标识。"],
    en: ["Duplicate surface registration", "The server registered a duplicate surface identifier."],
  },
  REQUEST_FAILED: {
    zh: ["只读 API 当前不可用", "请求未成功返回，请重试。"],
    en: ["Read-only API unavailable", "The request did not complete successfully; please retry."],
  },
};

const API_ERROR_FALLBACK: Record<Locale, [string, string]> = {
  "zh-CN": ["读取研究面数据时出错", "接口返回了未识别的错误；原始状态码与消息见技术详情。"],
  en: ["Failed to read surface data", "The API returned an unrecognized error; see technical details for raw diagnostics."],
};

const API_ERROR_NETWORK: Record<Locale, [string, string]> = {
  "zh-CN": ["无法连接只读 API", "网络请求失败，服务可能未启动或不可达。"],
  en: ["Cannot reach the read-only API", "The network request failed; the service may be down or unreachable."],
};

export function apiErrorPresentation(
  error: unknown,
  locale: Locale = DEFAULT_LOCALE,
): APIErrorPresentation {
  const fallback = API_ERROR_FALLBACK[locale];
  if (error instanceof SurfaceAPIError) {
    const entry = API_ERROR_TABLE[error.code];
    const [title, message] = entry ? (locale === "en" ? entry.en : entry.zh) : fallback;
    return {
      title,
      message,
      raw: { status: String(error.status), code: error.code, message: error.message },
    };
  }
  if (error instanceof Error) {
    // A transport-level failure (for example a fetch TypeError) is still an
    // unavailable read-only API, not a deterministic result.
    if (error.name === "TypeError") {
      const [title, message] = API_ERROR_NETWORK[locale];
      return { title, message, raw: { status: "—", code: error.name, message: error.message } };
    }
    return {
      title: fallback[0],
      message: fallback[1],
      raw: { status: "—", code: error.name, message: error.message },
    };
  }
  return {
    title: fallback[0],
    message: fallback[1],
    raw: { status: "—", code: "UNKNOWN_ERROR", message: String(error) },
  };
}

export function formatBoolean(value: boolean, locale: Locale = DEFAULT_LOCALE): string {
  return locale === "en" ? (value ? "Yes" : "No") : value ? "是" : "否";
}

/**
 * Conservative scalar formatter: missing values stay explicitly missing and
 * are never rendered as zero; numbers keep their exact string form (no unit,
 * currency, scale or percent is ever inferred).
 */
export function formatScalar(value: unknown, locale: Locale = DEFAULT_LOCALE): string {
  if (value === null || value === undefined) return statePresentation("NOT_AVAILABLE", locale).label;
  if (typeof value === "boolean") return formatBoolean(value, locale);
  if (typeof value === "number") {
    return Number.isFinite(value) ? String(value) : statePresentation("NOT_AVAILABLE", locale).label;
  }
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

const TIER_LABELS: Record<Locale, Record<string, string>> = {
  "zh-CN": {
    observation: "观察位",
    acceptable: "可接受位",
    turtle_entry: "龟式入场位",
    extreme_safety: "极端安全位",
  },
  en: {
    observation: "Observation",
    acceptable: "Acceptable",
    turtle_entry: "Turtle entry",
    extreme_safety: "Extreme safety",
  },
};

export function tierPresentation(key: string, locale: Locale = DEFAULT_LOCALE): { label: string; raw: string } {
  return { label: TIER_LABELS[locale][key] ?? key, raw: key };
}

export interface GateLabel {
  readonly key: string;
  readonly label: string;
}

export function gateLabels(locale: Locale = DEFAULT_LOCALE): readonly GateLabel[] {
  const labels: Record<Locale, Record<string, string>> = {
    "zh-CN": {
      universe: "标的准入",
      balance_sheet: "资产负债表",
      cdc: "CDC 现金流创造",
      through_return: "穿透回报",
      business_quality: "商业质量",
      governance_data_quality: "治理与数据质量",
    },
    en: {
      universe: "Universe",
      balance_sheet: "Balance sheet",
      cdc: "CDC",
      through_return: "Through Return",
      business_quality: "Business Quality",
      governance_data_quality: "Governance / data quality",
    },
  };
  const map = labels[locale];
  return Object.keys(map).map((key) => ({ key, label: map[key] }));
}

const BUSINESS_DIMENSION_LABELS: Record<Locale, Record<string, string>> = {
  "zh-CN": {
    demand_durability: "需求持续性",
    cyclicality: "周期性",
    pricing_power: "定价权",
    moat: "竞争壁垒",
    capital_efficiency: "资本效率",
    dependency: "客户/渠道/供应商依赖",
    regulatory_risk: "监管与外部依赖",
    predictability: "可预测性与业务简洁度",
  },
  en: {
    demand_durability: "Demand durability",
    cyclicality: "Cyclicality",
    pricing_power: "Pricing power",
    moat: "Competitive moat",
    capital_efficiency: "Capital efficiency",
    dependency: "Customer / channel / supplier dependency",
    regulatory_risk: "Regulation / external dependency",
    predictability: "Predictability / simplicity",
  },
};

export function businessDimensionLabel(key: string, locale: Locale = DEFAULT_LOCALE): string {
  return BUSINESS_DIMENSION_LABELS[locale][key] ?? key;
}

export interface MetricRowSpec {
  readonly key: string;
  readonly label: string;
}

export type MetricGroupKey = "cdc" | "net_cash" | "through_return";

export interface MetricGroupSpec {
  readonly key: MetricGroupKey;
  readonly title: string;
  readonly rows: readonly MetricRowSpec[];
}

export function metricGroups(locale: Locale = DEFAULT_LOCALE): readonly MetricGroupSpec[] {
  if (locale === "en") {
    return [
      {
        key: "cdc",
        title: "CDC",
        rows: [
          { key: "reported_cfo", label: "Reported CFO" },
          { key: "adjusted_cfo", label: "Adjusted CFO" },
          { key: "core_cdc", label: "Core CDC" },
          { key: "normalized_parent_core_cdc", label: "Normalized parent core CDC" },
          { key: "cdc_yield", label: "CDC yield" },
          { key: "positive_years_5y", label: "Positive years (5Y)" },
          { key: "cumulative_core_cdc_5y", label: "Cumulative core CDC (5Y)" },
          { key: "confidence", label: "Metric confidence" },
        ],
      },
      {
        key: "net_cash",
        title: "Net Cash",
        rows: [
          { key: "book_cash", label: "Book cash" },
          { key: "strict_cash", label: "Strict cash" },
          { key: "owner_accessible_cash", label: "Owner accessible cash" },
          { key: "financial_debt", label: "Financial debt" },
          { key: "owner_realizable_net_cash", label: "Owner realizable net cash" },
          { key: "owner_net_cash_ratio", label: "Owner net cash ratio" },
          { key: "liquidity_coverage", label: "Liquidity coverage" },
          { key: "stress_coverage", label: "Stress coverage" },
          { key: "confidence", label: "Metric confidence" },
        ],
      },
      {
        key: "through_return",
        title: "Through Return",
        rows: [
          { key: "distributable_base", label: "Distributable base" },
          { key: "dividend_through_return", label: "Dividend Through Return" },
          { key: "normalized_net_share_reduction", label: "Normalized net share reduction" },
          { key: "through_return", label: "Through Return" },
          { key: "verified_recurring_buyback_cash", label: "Verified recurring buyback cash" },
          { key: "buyback_credit_eligible", label: "Buyback credit eligible" },
          { key: "buyback_history_years", label: "Buyback history years" },
          { key: "confidence", label: "Metric confidence" },
        ],
      },
    ];
  }
  return [
    {
      key: "cdc",
      title: "CDC 现金流创造",
      rows: [
        { key: "reported_cfo", label: "报告 CFO" },
        { key: "adjusted_cfo", label: "调整后 CFO" },
        { key: "core_cdc", label: "核心 CDC" },
        { key: "normalized_parent_core_cdc", label: "归一化母公司核心 CDC" },
        { key: "cdc_yield", label: "CDC 收益率" },
        { key: "positive_years_5y", label: "正现金年份（近 5 年）" },
        { key: "cumulative_core_cdc_5y", label: "累计核心 CDC（近 5 年）" },
        { key: "confidence", label: "指标置信度" },
      ],
    },
    {
      key: "net_cash",
      title: "净现金",
      rows: [
        { key: "book_cash", label: "账面现金" },
        { key: "strict_cash", label: "严格口径现金" },
        { key: "owner_accessible_cash", label: "股东可动用现金" },
        { key: "financial_debt", label: "有息负债" },
        { key: "owner_realizable_net_cash", label: "股东可实现净现金" },
        { key: "owner_net_cash_ratio", label: "股东净现金比率" },
        { key: "liquidity_coverage", label: "流动性覆盖" },
        { key: "stress_coverage", label: "压力覆盖" },
        { key: "confidence", label: "指标置信度" },
      ],
    },
    {
      key: "through_return",
      title: "穿透回报",
      rows: [
        { key: "distributable_base", label: "可分配基数" },
        { key: "dividend_through_return", label: "股息穿透回报" },
        { key: "normalized_net_share_reduction", label: "归一化净股本缩减" },
        { key: "through_return", label: "穿透回报" },
        { key: "verified_recurring_buyback_cash", label: "已验证经常性回购现金" },
        { key: "buyback_credit_eligible", label: "回购计入资格" },
        { key: "buyback_history_years", label: "回购历史年数" },
        { key: "confidence", label: "指标置信度" },
      ],
    },
  ];
}

export interface Copy {
  readonly brandCaption: string;
  readonly navAriaLabel: string;
  readonly navOverview: string;
  readonly readOnlyMark: string;
  readonly skipToContent: string;
  readonly localeToggleAria: string;
  readonly footerNote: string;
  readonly footerContractsSummary: string;
  readonly footerApiContractLabel: string;
  readonly footerSnapshotContractLabel: string;

  readonly overviewTitle: string;
  readonly overviewLede: string;
  readonly healthLabel: string;
  readonly healthChecking: string;
  readonly healthLoadedCount: (count: number) => string;
  readonly refreshData: string;
  readonly filterHeading: string;
  readonly filterListing: string;
  readonly filterListingPlaceholder: string;
  readonly filterProfile: string;
  readonly filterProfilePlaceholder: string;
  readonly filterAsOf: string;
  readonly applyFilters: string;
  readonly clearFilters: string;
  readonly filterNotePrefix: string;
  readonly countLabel: (count: number) => string;
  readonly awaitingIndex: string;
  readonly loadedSurfacesHeading: string;
  readonly loadedSurfacesDescription: string;
  readonly tableListing: string;
  readonly tableAsOf: string;
  readonly tableProfile: string;
  readonly tableTechnical: string;
  readonly emptyNoMatchesTitle: string;
  readonly emptyNoMatchesBody: string;
  readonly emptyNoSnapshotsTitle: string;
  readonly emptyNoSnapshotsBody: string;
  readonly loadingOverview: string;
  readonly loadingDetail: string;
  readonly loadingStateLabel: string;
  readonly errorRetry: string;
  readonly errorTechnicalSummary: string;
  readonly errorHttpStatus: string;
  readonly errorCodeLabel: string;
  readonly errorMessageLabel: string;

  readonly backToList: string;
  readonly listingLabel: string;
  readonly sectorLabel: string;
  readonly reportingCurrencyLabel: string;
  readonly otherListingsLabel: string;
  readonly asOfLabel: string;
  readonly profileLabel: string;
  readonly companyNameLabel: string;
  readonly dataAsOfPrefix: string;
  readonly profilePrefix: string;

  readonly decisionSection: string;
  readonly deterministicDecision: string;
  readonly autoDecisionAllowed: string;
  readonly decisionConfidence: string;
  readonly blockingReasonsCount: string;
  readonly valuationState: string;
  readonly valuationCurrency: string;
  readonly currentPrice: string;
  readonly normalizedParentCoreCdc: string;
  readonly recurringShareholderCash: string;
  readonly valuationNetCash: string;
  readonly tiersCaption: string;
  readonly tierColumn: string;
  readonly cdcHurdle: string;
  readonly returnHurdle: string;
  readonly priceColumn: string;
  readonly marketCapColumn: string;

  readonly metricsSection: string;
  readonly metricsNote: string;
  readonly notAvailableLabel: string;

  readonly gatesSection: string;
  readonly gatesNote: string;
  readonly gateBlockingReasons: string;
  readonly gateRulesSummary: (count: number) => string;
  readonly confidenceLabel: string;

  readonly dataQualitySection: string;
  readonly evidenceCoverage: string;
  readonly notesLabel: string;
  readonly criticalMissing: string;

  readonly bqSection: string;
  readonly bqValidationState: string;
  readonly bqNotEvaluatedBody: string;
  readonly bqScore: string;
  readonly bqGrade: string;
  readonly bqConfidence: string;
  readonly bqEvidenceCoverage: string;
  readonly supportingEvidence: string;
  readonly counterEvidence: string;
  readonly criticalWeaknesses: string;
  readonly unresolvedQuestions: string;

  readonly historicalSection: string;
  readonly availability: string;
  readonly claimState: string;
  readonly acceptance: string;
  readonly readiness: string;
  readonly validation: string;
  readonly productionEligible: string;
  readonly blockers: string;
  readonly warnings: string;
  readonly limitations: string;
  readonly targetScope: string;
  readonly scopeTarget: string;
  readonly scopeUniverse: string;
  readonly scopeMarkets: string;
  readonly scopePeriod: string;
  readonly membershipClaim: string;
  readonly coverageClaim: string;

  readonly technicalSectionSummary: string;
  readonly technicalIntro: string;
  readonly snapshotContractLabel: string;
  readonly schemaVersionLabel: string;
  readonly endpointLabel: string;
  readonly analysisIdLabel: string;
  readonly surfaceIdLabel: string;
  readonly contentHashLabel: string;
  readonly sourceArtifactsLabel: string;
  readonly historicalIdentitiesLabel: string;
  readonly datasetIdLabel: string;
  readonly datasetVersionLabel: string;
  readonly manifestHashLabel: string;
  readonly acceptanceHashLabel: string;
  readonly readinessHashLabel: string;
  readonly validationHashLabel: string;

  readonly stringListEmpty: string;
}

const ZH_CN: Copy = {
  brandCaption: "冻结研究面 · 只读",
  navAriaLabel: "主导航",
  navOverview: "研究面",
  readOnlyMark: "只读",
  skipToContent: "跳到主要内容",
  localeToggleAria: "切换界面语言",
  footerNote: "只读投影 · 不写入数据 · 不重算投资语义",
  footerContractsSummary: "契约与技术标识",
  footerApiContractLabel: "API 契约",
  footerSnapshotContractLabel: "快照契约",

  overviewTitle: "研究面总览",
  overviewLede:
    "这里是冻结公司分析的只读台账。所有数值都来自经过校验的只读 API；本界面绝不重算投资语义，也不提供任何写入操作。",
  healthLabel: "API 本地健康",
  healthChecking: "正在检查本地服务…",
  healthLoadedCount: (count) => `已加载 ${count} 个快照`,
  refreshData: "刷新数据",
  filterHeading: "筛选",
  filterListing: "上市代码",
  filterListingPlaceholder: "如 SH600000",
  filterProfile: "规则档案",
  filterProfilePlaceholder: "如 strict-v1",
  filterAsOf: "截至日期",
  applyFilters: "应用筛选",
  clearFilters: "清空",
  filterNotePrefix: "仅支持以下直通 API 的筛选参数：",
  countLabel: (count) => `${count} 个研究面`,
  awaitingIndex: "等待研究面索引…",
  loadedSurfacesHeading: "已加载的研究面",
  loadedSurfacesDescription: "以下为列表接口返回的确定性元数据。",
  tableListing: "上市代码",
  tableAsOf: "截至日期",
  tableProfile: "规则档案",
  tableTechnical: "技术详情",
  emptyNoMatchesTitle: "没有符合筛选条件的研究面",
  emptyNoMatchesBody: "当前筛选条件下没有匹配结果。可以清除或放宽筛选条件后重试。",
  emptyNoSnapshotsTitle: "当前没有已加载的研究面快照",
  emptyNoSnapshotsBody:
    "该只读服务需要显式加载经过校验的冻结快照；当前没有任何快照可供展示，这不代表任何投资结论。",
  loadingOverview: "正在读取研究面索引…",
  loadingDetail: "正在读取研究面详情…",
  loadingStateLabel: "正在读取冻结研究面数据…",
  errorRetry: "重试读取",
  errorTechnicalSummary: "技术详情（原始错误信息）",
  errorHttpStatus: "HTTP 状态",
  errorCodeLabel: "错误码",
  errorMessageLabel: "后端消息",

  backToList: "← 返回研究面列表",
  listingLabel: "上市代码",
  sectorLabel: "行业",
  reportingCurrencyLabel: "报告货币",
  otherListingsLabel: "其他上市代码",
  asOfLabel: "截至日期",
  profileLabel: "规则档案",
  companyNameLabel: "公司名称",
  dataAsOfPrefix: "数据截至",
  profilePrefix: "规则档案",

  decisionSection: "决策与估值",
  deterministicDecision: "确定性决策",
  autoDecisionAllowed: "允许自动决策",
  decisionConfidence: "决策置信度",
  blockingReasonsCount: "阻塞原因数量",
  valuationState: "估值状态",
  valuationCurrency: "估值货币",
  currentPrice: "当前价格",
  normalizedParentCoreCdc: "归一化母公司核心 CDC",
  recurringShareholderCash: "经常性股东现金",
  valuationNetCash: "估值用净现金",
  tiersCaption: "引擎返回的冻结估值档位",
  tierColumn: "档位",
  cdcHurdle: "CDC 门槛",
  returnHurdle: "回报门槛",
  priceColumn: "价格",
  marketCapColumn: "市值",

  metricsSection: "确定性指标",
  metricsNote:
    "数值按冻结载荷原样展示，不推断单位、币种或百分比；无可用值表示载荷为空或缺失，绝不会被替换为 0 或“通过”。",
  notAvailableLabel: "无可用值",

  gatesSection: "硬性门槛",
  gatesNote: "六道门槛的结果全部展示，包括阻碍推进的阻塞原因。",
  gateBlockingReasons: "阻塞原因",
  gateRulesSummary: (count) => `${count} 条确定性规则`,
  confidenceLabel: "置信度",

  dataQualitySection: "数据质量",
  evidenceCoverage: "证据覆盖度",
  notesLabel: "备注",
  criticalMissing: "关键缺失字段",

  bqSection: "商业质量",
  bqValidationState: "校验状态",
  bqNotEvaluatedBody: "该冻结研究面中没有已验证的商业质量评估结果；未评估不代表通过。",
  bqScore: "评分",
  bqGrade: "评级",
  bqConfidence: "置信度",
  bqEvidenceCoverage: "证据覆盖度",
  supportingEvidence: "支持证据",
  counterEvidence: "反向证据",
  criticalWeaknesses: "重大缺陷",
  unresolvedQuestions: "未解决的问题",

  historicalSection: "历史数据与可用性",
  availability: "可用性",
  claimState: "数据主张状态",
  acceptance: "A6 验收",
  readiness: "就绪度",
  validation: "校验",
  productionEligible: "生产可用资格",
  blockers: "阻塞项",
  warnings: "警告",
  limitations: "限制说明",
  targetScope: "目标范围",
  scopeTarget: "目标",
  scopeUniverse: "标的池",
  scopeMarkets: "市场",
  scopePeriod: "时间区间",
  membershipClaim: "成员主张",
  coverageClaim: "覆盖主张",

  technicalSectionSummary: "技术 / 审计详情（原始标识、哈希与契约）",
  technicalIntro:
    "以下为原始机器标识，仅用于审计与排障；界面主文案不依赖这些值，任何条目都未被删除或改写。",
  snapshotContractLabel: "快照契约",
  schemaVersionLabel: "契约版本",
  endpointLabel: "请求路径",
  analysisIdLabel: "分析 ID",
  surfaceIdLabel: "研究面 ID",
  contentHashLabel: "内容 SHA-256",
  sourceArtifactsLabel: "来源工件标识",
  historicalIdentitiesLabel: "历史数据集标识",
  datasetIdLabel: "数据集 ID",
  datasetVersionLabel: "数据集版本",
  manifestHashLabel: "清单哈希",
  acceptanceHashLabel: "验收报告哈希",
  readinessHashLabel: "就绪报告哈希",
  validationHashLabel: "校验内容哈希",

  stringListEmpty: "无记录",
};

const EN: Copy = {
  brandCaption: "Frozen research surface · read-only",
  navAriaLabel: "Primary navigation",
  navOverview: "Surfaces",
  readOnlyMark: "Read-only",
  skipToContent: "Skip to content",
  localeToggleAria: "Switch interface language",
  footerNote: "Read-only projection · no writes · no recalculation",
  footerContractsSummary: "Contracts & technical identifiers",
  footerApiContractLabel: "API contract",
  footerSnapshotContractLabel: "Snapshot contract",

  overviewTitle: "Research surfaces",
  overviewLede:
    "A quiet read model for frozen company analysis. Every value comes from the validated read-only API; this surface never recalculates investment semantics and offers no writes.",
  healthLabel: "API-local health",
  healthChecking: "Checking the local adapter…",
  healthLoadedCount: (count) => `${count} loaded ${count === 1 ? "snapshot" : "snapshots"}`,
  refreshData: "Refresh data",
  filterHeading: "Filters",
  filterListing: "Listing",
  filterListingPlaceholder: "e.g. SH600000",
  filterProfile: "Profile",
  filterProfilePlaceholder: "e.g. strict-v1",
  filterAsOf: "As-of date",
  applyFilters: "Apply filters",
  clearFilters: "Clear",
  filterNotePrefix: "Supported API filters only:",
  countLabel: (count) => `${count} ${count === 1 ? "surface" : "surfaces"}`,
  awaitingIndex: "Awaiting surface index…",
  loadedSurfacesHeading: "Loaded surfaces",
  loadedSurfacesDescription: "Deterministic metadata from the list endpoint.",
  tableListing: "Listing",
  tableAsOf: "As of",
  tableProfile: "Profile",
  tableTechnical: "Technical details",
  emptyNoMatchesTitle: "No surfaces match the current filters",
  emptyNoMatchesBody: "Nothing matches the current filters. Clear or relax a filter and retry.",
  emptyNoSnapshotsTitle: "No frozen surface snapshots are loaded",
  emptyNoSnapshotsBody:
    "This read-only service serves explicitly validated frozen snapshots only; none are loaded right now. This is not an investment conclusion.",
  loadingOverview: "Reading the frozen surface index…",
  loadingDetail: "Reading the frozen surface detail…",
  loadingStateLabel: "Loading frozen surface data…",
  errorRetry: "Retry read",
  errorTechnicalSummary: "Technical details (raw error)",
  errorHttpStatus: "HTTP status",
  errorCodeLabel: "Error code",
  errorMessageLabel: "Backend message",

  backToList: "← Back to surfaces",
  listingLabel: "Listing",
  sectorLabel: "Sector",
  reportingCurrencyLabel: "Reporting currency",
  otherListingsLabel: "Other listings",
  asOfLabel: "As-of date",
  profileLabel: "Profile",
  companyNameLabel: "Company name",
  dataAsOfPrefix: "data as of",
  profilePrefix: "profile",

  decisionSection: "Decision and valuation",
  deterministicDecision: "Deterministic decision",
  autoDecisionAllowed: "Auto decision allowed",
  decisionConfidence: "Decision confidence",
  blockingReasonsCount: "Blocking reasons",
  valuationState: "Valuation state",
  valuationCurrency: "Valuation currency",
  currentPrice: "Current price",
  normalizedParentCoreCdc: "Normalized parent core CDC",
  recurringShareholderCash: "Recurring shareholder cash",
  valuationNetCash: "Valuation net cash",
  tiersCaption: "Frozen valuation tiers returned by the engine",
  tierColumn: "Tier",
  cdcHurdle: "CDC hurdle",
  returnHurdle: "Return hurdle",
  priceColumn: "Price",
  marketCapColumn: "Market cap",

  metricsSection: "Deterministic metrics",
  metricsNote:
    "Values are displayed exactly as returned; units, currency and percentages are never inferred. “No value” means the frozen payload is null or omits the field; it is never replaced with zero or a pass.",
  notAvailableLabel: "No value",

  gatesSection: "Hard gates",
  gatesNote: "All six gate results remain visible, including reasons that block progress.",
  gateBlockingReasons: "Blocking reasons",
  gateRulesSummary: (count) => `${count} deterministic ${count === 1 ? "rule" : "rules"}`,
  confidenceLabel: "Confidence",

  dataQualitySection: "Data quality",
  evidenceCoverage: "Evidence coverage",
  notesLabel: "Notes",
  criticalMissing: "Critical missing fields",

  bqSection: "Business Quality",
  bqValidationState: "Validation state",
  bqNotEvaluatedBody: "No validated Business Quality assessment is present in this frozen surface.",
  bqScore: "Score",
  bqGrade: "Grade",
  bqConfidence: "Confidence",
  bqEvidenceCoverage: "Evidence coverage",
  supportingEvidence: "Supporting evidence",
  counterEvidence: "Counter-evidence",
  criticalWeaknesses: "Critical weaknesses",
  unresolvedQuestions: "Unresolved questions",

  historicalSection: "Historical data and availability",
  availability: "Availability",
  claimState: "Claim state",
  acceptance: "A6 acceptance",
  readiness: "Readiness",
  validation: "Validation",
  productionEligible: "Production eligible",
  blockers: "Blockers",
  warnings: "Warnings",
  limitations: "Limitations",
  targetScope: "Target scope",
  scopeTarget: "Target",
  scopeUniverse: "Universe",
  scopeMarkets: "Markets",
  scopePeriod: "Period",
  membershipClaim: "Membership claim",
  coverageClaim: "Coverage claim",

  technicalSectionSummary: "Technical / audit details (raw identifiers, hashes, contracts)",
  technicalIntro:
    "Raw machine identifiers for audit and debugging only; the primary copy never depends on them and nothing here is deleted or rewritten.",
  snapshotContractLabel: "Snapshot contract",
  schemaVersionLabel: "Schema version",
  endpointLabel: "Request path",
  analysisIdLabel: "Analysis ID",
  surfaceIdLabel: "Surface ID",
  contentHashLabel: "Content SHA-256",
  sourceArtifactsLabel: "Source artifact identities",
  historicalIdentitiesLabel: "Historical dataset identities",
  datasetIdLabel: "Dataset ID",
  datasetVersionLabel: "Dataset version",
  manifestHashLabel: "Manifest hash",
  acceptanceHashLabel: "Acceptance report hash",
  readinessHashLabel: "Readiness report hash",
  validationHashLabel: "Validation content hash",

  stringListEmpty: "None recorded",
};

export const COPY: Record<Locale, Copy> = {
  "zh-CN": ZH_CN,
  en: EN,
};

export function getCopy(locale: Locale = DEFAULT_LOCALE): Copy {
  return COPY[locale] ?? COPY[DEFAULT_LOCALE];
}

export function useCopy(): Copy {
  return getCopy(useLocale());
}
