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
  // Phase 6-D3 monitoring operations states.
  LIVE: {
    tone: "positive",
    zh: ["租约有效", "运行器租约在心跳有效期内。"],
    en: ["Lease live", "The runner lease is within its heartbeat validity window."],
  },
  ABANDONED: {
    tone: "caution",
    zh: ["租约已过期", "运行器租约超过心跳有效期；原持有者可能已停止，不代表任务已完成。"],
    en: ["Lease abandoned", "The runner lease exceeded its heartbeat validity; the holder may have stopped. This does not mean the work finished."],
  },
  FREE: {
    tone: "neutral",
    zh: ["租约空闲", "当前没有运行器持有租约。"],
    en: ["Lease free", "No runner currently holds the lease."],
  },
  ACTIVE: {
    tone: "caution",
    zh: ["进行中", "该激活已开始但尚无终结回执；进行中不代表成功。"],
    en: ["Active", "This activation started but has no terminal receipt yet; in progress is not success."],
  },
  LATEST_TERMINAL: {
    tone: "neutral",
    zh: ["最近终结", "最近一次已终结的激活。"],
    en: ["Latest terminal", "The most recent terminal activation."],
  },
  NO_CHANGE: {
    tone: "positive",
    zh: ["无变化", "本次监控周期没有发现需要处理的变化。"],
    en: ["No change", "The monitoring cycle found nothing requiring action."],
  },
  ALERTS_EMITTED: {
    tone: "caution",
    zh: ["已发出提醒", "本次监控周期产生了事实性提醒，请查看提醒与任务。"],
    en: ["Alerts emitted", "The monitoring cycle emitted factual alerts; review alerts and jobs."],
  },
  ATTENTION_REQUIRED: {
    tone: "negative",
    zh: ["需要注意", "监控周期存在阻塞、失败或需人工复核的项，需要人工介入。"],
    en: ["Attention required", "The cycle has blocked, failed or manual-review items; human attention is needed."],
  },
  FAILED: {
    tone: "negative",
    zh: ["失败", "执行失败；失败不代表任何投资结论。"],
    en: ["Failed", "Execution failed; a failure is not an investment conclusion."],
  },
  MANUAL_REVIEW_REQUIRED: {
    tone: "negative",
    zh: ["需人工复核", "按规则必须人工复核，系统不会自动判定通过。"],
    en: ["Manual review required", "Rules require human review; the system never auto-passes this."],
  },
  SUCCEEDED: {
    tone: "positive",
    zh: ["已完成", "该执行步骤已按确定性边界完成。"],
    en: ["Succeeded", "This execution step completed within its deterministic boundary."],
  },
  NO_ACTION: {
    tone: "neutral",
    zh: ["无需处理", "按确定性规则无需进一步处理。"],
    en: ["No action", "No further action is required by the deterministic rules."],
  },
  PENDING: {
    tone: "caution",
    zh: ["待投递", "通知尚未完成投递。"],
    en: ["Pending", "The notification has not been delivered yet."],
  },
  DELIVERED: {
    tone: "positive",
    zh: ["已送达", "通知已被接收方确认（2xx）。"],
    en: ["Delivered", "The receiver acknowledged the notification (2xx)."],
  },
  RETRYABLE_FAILURE: {
    tone: "caution",
    zh: ["可重试失败", "投递失败但允许按预算重试。"],
    en: ["Retryable failure", "Delivery failed but may be retried within budget."],
  },
  AMBIGUOUS: {
    tone: "negative",
    zh: ["结果不确定", "请求可能已发出但结果未知；默认不会自动重发，需要人工判断。"],
    en: ["Ambiguous", "The request may have been sent but the outcome is unknown; it is not resent automatically by default."],
  },
  PERMANENT_FAILURE: {
    tone: "negative",
    zh: ["永久失败", "投递失败且不再重试。"],
    en: ["Permanent failure", "Delivery failed permanently; no further retries."],
  },
  NOOP: {
    tone: "neutral",
    zh: ["无需投递", "提醒箱为空，本次没有任何外发请求。"],
    en: ["No-op", "The alert outbox was empty; zero outbound requests were made."],
  },
  CURRENT: {
    tone: "positive",
    zh: ["指针一致", "已发布指针与账本内容一致。"],
    en: ["Current", "The published pointer matches the ledger content."],
  },
  MISSING: {
    tone: "caution",
    zh: ["指针缺失", "尚未发布状态指针；不代表没有历史记录。"],
    en: ["Missing", "No state pointer is published yet; this does not mean there is no history."],
  },
  STALE_REPAIRABLE: {
    tone: "caution",
    zh: ["指针过期", "已发布指针落后于账本内容；只读界面不会修复它。"],
    en: ["Stale (repairable)", "The published pointer lags the ledger; this read-only view never repairs it."],
  },
  RESOLVED: {
    tone: "positive",
    zh: ["已解决", "该处置已有确定结果。"],
    en: ["Resolved", "This disposition has a determined outcome."],
  },
  UNRESOLVED: {
    tone: "negative",
    zh: ["未解决", "该处置没有可用结果，会阻止后续推进。"],
    en: ["Unresolved", "This disposition has no usable outcome and blocks advancement."],
  },
  NO_REANALYSIS: {
    tone: "neutral",
    zh: ["无需重分析", "该事件按规则不触发重分析。"],
    en: ["No re-analysis", "The event does not trigger re-analysis."],
  },
  PARTIAL_REANALYSIS: {
    tone: "caution",
    zh: ["部分重分析", "该事件触发部分重分析。"],
    en: ["Partial re-analysis", "The event triggers a partial re-analysis."],
  },
  FULL_REANALYSIS: {
    tone: "caution",
    zh: ["完整重分析", "该事件触发完整重分析。"],
    en: ["Full re-analysis", "The event triggers a full re-analysis."],
  },
  URGENT_MANUAL_REVIEW: {
    tone: "negative",
    zh: ["紧急人工复核", "该事件要求紧急人工复核，绝不自动处理。"],
    en: ["Urgent manual review", "The event demands urgent human review; never handled automatically."],
  },
  ORPHANED_DISPATCH: {
    tone: "negative",
    zh: ["外发结果丢失", "一次外发已占用授权槽位但结果未持久化；默认不会自动重发。"],
    en: ["Orphaned dispatch", "An outbound dispatch consumed an authorized slot but its outcome never persisted; it is not resent by default."],
  },
  MATERIAL_EVENT: {
    tone: "caution",
    zh: ["重大事件", "监控发现需要关注的事实性事件；不代表任何投资结论。"],
    en: ["Material event", "A factual event worth attention was observed; it is not an investment conclusion."],
  },
  REANALYSIS_BLOCKED: {
    tone: "negative",
    zh: ["重分析受阻", "重分析执行被确定性边界阻止，需要人工介入。"],
    en: ["Re-analysis blocked", "Re-analysis was blocked by a deterministic boundary and needs human attention."],
  },
  REANALYSIS_FAILED: {
    tone: "negative",
    zh: ["重分析失败", "重分析执行失败；失败不代表任何投资结论。"],
    en: ["Re-analysis failed", "Re-analysis execution failed; failure is not an investment conclusion."],
  },
  REANALYSIS_SUCCEEDED: {
    tone: "positive",
    zh: ["重分析完成", "重分析已按确定性边界完成。"],
    en: ["Re-analysis completed", "Re-analysis completed within the deterministic boundary."],
  },
  CYCLE_FAILED: {
    tone: "negative",
    zh: ["周期失败", "监控周期执行失败；不代表任何投资结论。"],
    en: ["Cycle failed", "The monitoring cycle failed; this is not an investment conclusion."],
  },
  HTTP_RETRYABLE_STATUS: {
    tone: "caution",
    zh: ["可重试的响应状态", "接收方返回可重试状态码，允许按预算重试。"],
    en: ["Retryable HTTP status", "The receiver returned a retryable status; retries are allowed within budget."],
  },
  HTTP_PERMANENT_STATUS: {
    tone: "negative",
    zh: ["永久响应状态", "接收方返回不可重试状态码，不再重试。"],
    en: ["Permanent HTTP status", "The receiver returned a non-retryable status; no further retries."],
  },
  HTTP_REDIRECT_NOT_FOLLOWED: {
    tone: "negative",
    zh: ["重定向未跟随", "接收方返回重定向；按边界策略绝不跟随。"],
    en: ["Redirect not followed", "The receiver returned a redirect; it is never followed."],
  },
  CONNECT_FAILED_PRE_DISPATCH: {
    tone: "caution",
    zh: ["连接失败", "请求字节发出前连接失败，可安全重试。"],
    en: ["Connect failed", "The connection failed before any request byte was sent; safe to retry."],
  },
  TIMEOUT_AFTER_DISPATCH: {
    tone: "negative",
    zh: ["发出后超时", "请求可能已发出但响应等待超时；默认不会自动重发。"],
    en: ["Timeout after dispatch", "The request may have been sent before the wait timed out; not resent by default."],
  },
  CONNECTION_LOST_AFTER_DISPATCH: {
    tone: "negative",
    zh: ["发出后连接中断", "请求可能已发出但连接中断；默认不会自动重发。"],
    en: ["Connection lost after dispatch", "The request may have been sent before the connection dropped; not resent by default."],
  },
  RESPONSE_BYTES_EXCEEDED: {
    tone: "negative",
    zh: ["响应超出限制", "响应体超过允许的最大字节数。"],
    en: ["Response too large", "The response exceeded the bounded byte limit."],
  },
  RETRIES_EXHAUSTED: {
    tone: "negative",
    zh: ["重试预算耗尽", "授权外发槽位已全部消耗，不再重试。"],
    en: ["Retry budget exhausted", "All authorized dispatch slots are consumed; no further retries."],
  },
  DEADLINE_EXHAUSTED_PRE_DISPATCH: {
    tone: "caution",
    zh: ["发出前期限耗尽", "整体期限在任何请求字节发出前耗尽，可安全重试。"],
    en: ["Deadline exhausted pre-dispatch", "The overall deadline expired before any request byte was sent; safe to retry."],
  },
  ACQUISITION_FAILED: {
    tone: "negative",
    zh: ["事件采集失败", "监控事件采集失败。"],
    en: ["Acquisition failed", "Monitoring event acquisition failed."],
  },
  INVALID_ACQUISITION_RESULT: {
    tone: "negative",
    zh: ["采集结果无效", "事件采集结果未通过确定性校验。"],
    en: ["Invalid acquisition result", "The acquisition result failed deterministic validation."],
  },
  UNRESOLVED_CURRENT_RUN: {
    tone: "negative",
    zh: ["存在未解决项", "当前周期存在未解决的阻塞或失败项，阻止后续推进。"],
    en: ["Unresolved blockers", "The current run has unresolved blocked or failed jobs that block advancement."],
  },
  MISSING_EXECUTION_DISPOSITION: {
    tone: "negative",
    zh: ["缺少执行处置", "执行结果缺少对应的处置记录。"],
    en: ["Missing execution disposition", "The execution outcome has no matching disposition record."],
  },
  MISSING_EXECUTION_BINDING: {
    tone: "negative",
    zh: ["缺少执行绑定", "该标的没有配置执行绑定，无法执行重分析。"],
    en: ["Missing execution binding", "No execution binding is configured for this listing; re-analysis cannot run."],
  },
  EXECUTION_ATTENTION_REQUIRED: {
    tone: "negative",
    zh: ["执行需注意", "执行层存在需要人工注意的项。"],
    en: ["Execution attention required", "The execution layer contains items that need human attention."],
  },
  MONITORING_COMMIT_FAILED: {
    tone: "negative",
    zh: ["状态提交失败", "监控状态的原子提交失败。"],
    en: ["Monitoring commit failed", "The atomic monitoring state commit failed."],
  },
  CYCLE_STORE_FAILED: {
    tone: "negative",
    zh: ["周期存储失败", "周期工件写入失败。"],
    en: ["Cycle store failed", "Persisting the cycle artifacts failed."],
  },
  CYCLE_CONFLICT: {
    tone: "negative",
    zh: ["周期证据冲突", "周期存储证据冲突或损坏。"],
    en: ["Cycle conflict", "Cycle store evidence is conflicting or corrupt."],
  },
  LOWER_LEVEL_INELIGIBLE: {
    tone: "negative",
    zh: ["下层不具备条件", "下层边界不具备执行条件。"],
    en: ["Lower level ineligible", "A lower-level boundary is not eligible to execute."],
  },
  BLOCKED_RESEARCH_RUNTIME: {
    tone: "negative",
    zh: ["研究运行时受阻", "研究执行被确定性边界阻止（例如未授权模型）。"],
    en: ["Blocked research runtime", "Research execution was blocked by a deterministic boundary (for example a model was not allowed)."],
  },
  PREPARATION_FAILED: {
    tone: "negative",
    zh: ["数据准备失败", "重分析的数据准备步骤失败。"],
    en: ["Preparation failed", "The re-analysis preparation step failed."],
  },
  RESEARCH_FAILED: {
    tone: "negative",
    zh: ["研究失败", "重分析的研究步骤失败。"],
    en: ["Research failed", "The re-analysis research step failed."],
  },
  ANALYSIS_FAILED: {
    tone: "negative",
    zh: ["分析失败", "重分析的确定性分析步骤失败。"],
    en: ["Analysis failed", "The re-analysis deterministic analysis step failed."],
  },
  SURFACE_FAILED: {
    tone: "negative",
    zh: ["研究面生成失败", "重分析的研究面生成步骤失败。"],
    en: ["Surface failed", "The re-analysis surface build step failed."],
  },
  INVALID_PRIOR_ANALYSIS: {
    tone: "negative",
    zh: ["先前分析无效", "先前分析工件未通过校验。"],
    en: ["Invalid prior analysis", "The prior analysis artifact failed validation."],
  },
  JOB_STORE_WRITE_FAILED: {
    tone: "negative",
    zh: ["任务存储写入失败", "重分析任务工件写入失败。"],
    en: ["Job store write failed", "Persisting the re-analysis job artifacts failed."],
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
  MONITORING_OPERATIONS_NOT_FOUND: {
    zh: ["未配置监控只读视图", "当前服务没有挂载监控运行投影，或请求的路径不存在。"],
    en: ["Monitoring view not configured", "The service has no monitoring operations projection mounted, or the path does not exist."],
  },
  MONITORING_OPERATIONS_SOURCES_INVALID: {
    zh: ["监控源配置无效", "服务端显式配置的监控源无法读取或校验；请检查运行配置。"],
    en: ["Monitoring sources invalid", "The explicitly configured monitoring sources cannot be read or validated; check the runtime configuration."],
  },
  MONITORING_OPERATIONS_CONFLICT: {
    zh: ["监控证据不一致", "本地监控存储存在损坏、外来或相互矛盾的证据；只读界面不会掩盖或修复，需要人工核查存储。"],
    en: ["Monitoring evidence conflict", "Local monitoring stores contain corrupt, foreign or contradictory evidence; the read-only view never hides or repairs it. Inspect the stores manually."],
  },
  MONITORING_OPERATIONS_ERROR: {
    zh: ["监控投影读取失败", "监控运行投影读取失败；原始错误码见技术详情。"],
    en: ["Monitoring projection failed", "Reading the monitoring operations projection failed; see technical details for the raw code."],
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

  readonly navMonitoring: string;
  readonly monitoringTitle: string;
  readonly monitoringLede: string;
  readonly loadingMonitoring: string;
  readonly monitoringOverviewSection: string;
  readonly monitoringWatchlistAvailability: string;
  readonly monitoringRunnerId: string;
  readonly monitoringLeaseState: string;
  readonly monitoringLeaseCorrupt: string;
  readonly monitoringLeaseHeartbeat: string;
  readonly monitoringLeaseTtl: string;
  readonly monitoringUnfinishedActivations: (count: number) => string;
  readonly monitoringActivationKind: string;
  readonly monitoringActivationAsOf: string;
  readonly monitoringActivationCreatedAt: string;
  readonly monitoringNoActivationTitle: string;
  readonly monitoringNoActivationBody: string;
  readonly monitoringCycleStatus: string;
  readonly monitoringCycleAsOf: string;
  readonly monitoringCycleFailureCode: string;
  readonly monitoringCycleMessage: string;
  readonly monitoringAlertCount: (count: number) => string;
  readonly monitoringCyclePointerPublished: string;
  readonly monitoringNoCycleTitle: string;
  readonly monitoringNoCycleBody: string;
  readonly monitoringAlertsHeading: string;
  readonly monitoringJobsSection: string;
  readonly monitoringJobsCount: (count: number) => string;
  readonly monitoringNoJobsTitle: string;
  readonly monitoringNoJobsBody: string;
  readonly monitoringJobListing: string;
  readonly monitoringJobImpact: string;
  readonly monitoringJobDisposition: string;
  readonly monitoringJobResolution: string;
  readonly monitoringJobStatus: string;
  readonly monitoringJobFailureCode: string;
  readonly monitoringJobMessage: string;
  readonly monitoringJobEvidence: string;
  readonly monitoringDeliveriesSection: string;
  readonly monitoringDeliveriesCount: (count: number) => string;
  readonly monitoringDeliveriesNotConfiguredTitle: string;
  readonly monitoringDeliveriesNotConfiguredBody: string;
  readonly monitoringNoDeliveriesTitle: string;
  readonly monitoringNoDeliveriesBody: string;
  readonly monitoringDeliveryDestination: string;
  readonly monitoringDeliveryTransport: string;
  readonly monitoringDeliveryStatus: string;
  readonly monitoringDeliveryAttemptCount: string;
  readonly monitoringDeliveryDispatchClaimCount: string;
  readonly monitoringDeliveryCountsNote: string;
  readonly monitoringDeliveryUnresolvedSlots: string;
  readonly monitoringDeliveryLastHttpStatus: string;
  readonly monitoringDeliveryLastError: string;
  readonly monitoringDeliveryPointerStatus: string;
  readonly monitoringDeliveryEmptyOutbox: string;
  readonly monitoringDeliveryNextRetry: string;
  readonly monitoringDeliveryAttemptsSummary: string;
  readonly monitoringAuditSection: string;
  readonly monitoringAuditWatchlistId: string;
  readonly monitoringAuditStateId: string;
  readonly monitoringAuditLastRunId: string;
  readonly monitoringAuditActivationId: string;
  readonly monitoringAuditIntentHash: string;
  readonly monitoringAuditReceiptHash: string;
  readonly monitoringAuditCycleId: string;
  readonly monitoringAuditResultHash: string;
  readonly monitoringAuditAlertBatchId: string;
  readonly monitoringAuditAlertBatchHash: string;
  readonly monitoringAuditRunId: string;
  readonly monitoringAuditEventBatchId: string;
  readonly monitoringAuditNextStateId: string;
  readonly monitoringAuditJobId: string;
  readonly monitoringAuditJobHash: string;
  readonly monitoringAuditDeliveryId: string;
  readonly monitoringAuditPayloadHash: string;
  readonly monitoringAuditPayloadContract: string;
  readonly monitoringAuditIdempotencyKey: string;
  readonly monitoringAuditProjectionContract: string;

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

  navMonitoring: "监控运行",
  monitoringTitle: "监控运行状态",
  monitoringLede:
    "这里是无人值守监控链路的只读投影。所有内容都来自本地持久化工件的只读读取；本界面绝不触发采集、分析、投递或任何修复/写入操作。",
  loadingMonitoring: "正在读取监控运行投影…",
  monitoringOverviewSection: "运行概览",
  monitoringWatchlistAvailability: "监控状态可用性",
  monitoringRunnerId: "运行器标识",
  monitoringLeaseState: "租约状态",
  monitoringLeaseCorrupt: "租约记录损坏",
  monitoringLeaseHeartbeat: "最近心跳",
  monitoringLeaseTtl: "租约有效期（秒）",
  monitoringUnfinishedActivations: (count) => `${count} 个未终结激活`,
  monitoringActivationKind: "激活类型",
  monitoringActivationAsOf: "数据时点（as_of）",
  monitoringActivationCreatedAt: "激活创建时间",
  monitoringNoActivationTitle: "尚无激活记录",
  monitoringNoActivationBody:
    "该运行器尚未持久化任何激活。这不代表异常，只表示还没有运行记录。",
  monitoringCycleStatus: "周期状态",
  monitoringCycleAsOf: "周期时点（as_of）",
  monitoringCycleFailureCode: "失败分类",
  monitoringCycleMessage: "说明",
  monitoringAlertCount: (count) => `${count} 条提醒`,
  monitoringCyclePointerPublished: "周期指针已发布",
  monitoringNoCycleTitle: "该激活尚无终结周期",
  monitoringNoCycleBody:
    "当前激活还没有已提交的监控周期结果；进行中不代表成功或失败。",
  monitoringAlertsHeading: "事实提醒",
  monitoringJobsSection: "重分析任务",
  monitoringJobsCount: (count) => `${count} 个任务`,
  monitoringNoJobsTitle: "本次周期没有重分析任务",
  monitoringNoJobsBody: "该监控周期没有产生需要重分析的处置。",
  monitoringJobListing: "上市代码",
  monitoringJobImpact: "影响等级",
  monitoringJobDisposition: "处置状态",
  monitoringJobResolution: "解决状态",
  monitoringJobStatus: "执行状态",
  monitoringJobFailureCode: "失败分类",
  monitoringJobMessage: "说明",
  monitoringJobEvidence: "证据代码",
  monitoringDeliveriesSection: "通知投递",
  monitoringDeliveriesCount: (count) => `${count} 条投递`,
  monitoringDeliveriesNotConfiguredTitle: "未配置投递账本",
  monitoringDeliveriesNotConfiguredBody:
    "服务端未配置通知投递账本路径；这不代表已关闭通知，只表示本视图无法读取投递状态。",
  monitoringNoDeliveriesTitle: "该激活没有投递记录",
  monitoringNoDeliveriesBody: "绑定当前激活的通知投递账本中没有条目。",
  monitoringDeliveryDestination: "接收方标识",
  monitoringDeliveryTransport: "传输方式",
  monitoringDeliveryStatus: "投递状态",
  monitoringDeliveryAttemptCount: "已持久化投递结果数",
  monitoringDeliveryDispatchClaimCount: "已消耗外发槽位数",
  monitoringDeliveryCountsNote:
    "两个计数语义不同：前者是已持久化的投递结果数，后者是已消耗的授权外发槽位数；外发结果丢失（orphan）后二者合法不一致，未决槽位编号单独列出，绝不把结果数当作总发送次数。",
  monitoringDeliveryUnresolvedSlots: "未决槽位编号",
  monitoringDeliveryLastHttpStatus: "最近 HTTP 状态",
  monitoringDeliveryLastError: "最近错误分类",
  monitoringDeliveryPointerStatus: "状态指针",
  monitoringDeliveryEmptyOutbox: "空提醒箱",
  monitoringDeliveryNextRetry: "下次可重试时间",
  monitoringDeliveryAttemptsSummary: "投递尝试明细",
  monitoringAuditSection: "审计详情（原始标识与哈希）",
  monitoringAuditWatchlistId: "观察清单 ID",
  monitoringAuditStateId: "当前状态 ID",
  monitoringAuditLastRunId: "最近提交运行 ID",
  monitoringAuditActivationId: "激活 ID",
  monitoringAuditIntentHash: "激活意图哈希",
  monitoringAuditReceiptHash: "终结回执哈希",
  monitoringAuditCycleId: "周期 ID",
  monitoringAuditResultHash: "周期结果哈希",
  monitoringAuditAlertBatchId: "提醒批次 ID",
  monitoringAuditAlertBatchHash: "提醒批次哈希",
  monitoringAuditRunId: "监控运行 ID",
  monitoringAuditEventBatchId: "事件批次 ID",
  monitoringAuditNextStateId: "下一状态 ID",
  monitoringAuditJobId: "任务 ID",
  monitoringAuditJobHash: "任务内容哈希",
  monitoringAuditDeliveryId: "投递 ID",
  monitoringAuditPayloadHash: "载荷哈希",
  monitoringAuditPayloadContract: "载荷契约",
  monitoringAuditIdempotencyKey: "幂等键",
  monitoringAuditProjectionContract: "投影契约",

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

  navMonitoring: "Monitoring",
  monitoringTitle: "Monitoring operations",
  monitoringLede:
    "A read-only projection of the unattended monitoring chain. Everything comes from read-only access to local durable artifacts; this view never triggers acquisition, analysis, delivery or any repair/write operation.",
  loadingMonitoring: "Reading the monitoring operations projection…",
  monitoringOverviewSection: "Run overview",
  monitoringWatchlistAvailability: "Monitoring status availability",
  monitoringRunnerId: "Runner identity",
  monitoringLeaseState: "Lease state",
  monitoringLeaseCorrupt: "Lease record corrupt",
  monitoringLeaseHeartbeat: "Latest heartbeat",
  monitoringLeaseTtl: "Lease TTL (seconds)",
  monitoringUnfinishedActivations: (count) =>
    `${count} unfinished ${count === 1 ? "activation" : "activations"}`,
  monitoringActivationKind: "Activation kind",
  monitoringActivationAsOf: "Data as-of",
  monitoringActivationCreatedAt: "Activation created at",
  monitoringNoActivationTitle: "No activation recorded yet",
  monitoringNoActivationBody:
    "This runner has not persisted any activation. That is not an error; there is simply no run history yet.",
  monitoringCycleStatus: "Cycle status",
  monitoringCycleAsOf: "Cycle as-of",
  monitoringCycleFailureCode: "Failure classification",
  monitoringCycleMessage: "Message",
  monitoringAlertCount: (count) => `${count} ${count === 1 ? "alert" : "alerts"}`,
  monitoringCyclePointerPublished: "Cycle pointer published",
  monitoringNoCycleTitle: "No terminal cycle for this activation",
  monitoringNoCycleBody:
    "The current activation has no committed monitoring cycle result yet; in progress is neither success nor failure.",
  monitoringAlertsHeading: "Factual alerts",
  monitoringJobsSection: "Re-analysis jobs",
  monitoringJobsCount: (count) => `${count} ${count === 1 ? "job" : "jobs"}`,
  monitoringNoJobsTitle: "No re-analysis jobs in this cycle",
  monitoringNoJobsBody: "The monitoring cycle produced no re-analysis dispositions.",
  monitoringJobListing: "Listing",
  monitoringJobImpact: "Impact class",
  monitoringJobDisposition: "Disposition status",
  monitoringJobResolution: "Resolution",
  monitoringJobStatus: "Execution status",
  monitoringJobFailureCode: "Failure classification",
  monitoringJobMessage: "Message",
  monitoringJobEvidence: "Evidence codes",
  monitoringDeliveriesSection: "Notification deliveries",
  monitoringDeliveriesCount: (count) => `${count} ${count === 1 ? "delivery" : "deliveries"}`,
  monitoringDeliveriesNotConfiguredTitle: "Delivery ledger not configured",
  monitoringDeliveriesNotConfiguredBody:
    "The server is not configured with a delivery ledger root; this does not mean notifications are disabled, only that this view cannot read delivery state.",
  monitoringNoDeliveriesTitle: "No deliveries for this activation",
  monitoringNoDeliveriesBody: "The delivery ledger holds no entry bound to the current activation.",
  monitoringDeliveryDestination: "Destination identity",
  monitoringDeliveryTransport: "Transport",
  monitoringDeliveryStatus: "Delivery status",
  monitoringDeliveryAttemptCount: "Persisted delivery outcomes",
  monitoringDeliveryDispatchClaimCount: "Consumed dispatch slots",
  monitoringDeliveryCountsNote:
    "The two counts have different semantics: the first counts persisted delivery outcomes, the second counts consumed authorized outbound transport slots. After an orphaned dispatch they legitimately differ, and unresolved slot numbers are listed separately; the outcome count is never a total-send or total-retry count.",
  monitoringDeliveryUnresolvedSlots: "Unresolved slot numbers",
  monitoringDeliveryLastHttpStatus: "Last HTTP status",
  monitoringDeliveryLastError: "Last error classification",
  monitoringDeliveryPointerStatus: "State pointer",
  monitoringDeliveryEmptyOutbox: "Empty outbox",
  monitoringDeliveryNextRetry: "Next retry not before",
  monitoringDeliveryAttemptsSummary: "Delivery attempt details",
  monitoringAuditSection: "Audit details (raw identities and hashes)",
  monitoringAuditWatchlistId: "Watchlist ID",
  monitoringAuditStateId: "Current state ID",
  monitoringAuditLastRunId: "Last committed run ID",
  monitoringAuditActivationId: "Activation ID",
  monitoringAuditIntentHash: "Activation intent hash",
  monitoringAuditReceiptHash: "Terminal receipt hash",
  monitoringAuditCycleId: "Cycle ID",
  monitoringAuditResultHash: "Cycle result hash",
  monitoringAuditAlertBatchId: "Alert batch ID",
  monitoringAuditAlertBatchHash: "Alert batch hash",
  monitoringAuditRunId: "Monitoring run ID",
  monitoringAuditEventBatchId: "Event batch ID",
  monitoringAuditNextStateId: "Next state ID",
  monitoringAuditJobId: "Job ID",
  monitoringAuditJobHash: "Job content hash",
  monitoringAuditDeliveryId: "Delivery ID",
  monitoringAuditPayloadHash: "Payload hash",
  monitoringAuditPayloadContract: "Payload contract",
  monitoringAuditIdempotencyKey: "Idempotency key",
  monitoringAuditProjectionContract: "Projection contract",

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
