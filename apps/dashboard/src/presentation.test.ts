import { describe, expect, it } from "vitest";

import { SurfaceAPIError } from "./api/client";
import {
  DEFAULT_LOCALE,
  apiErrorPresentation,
  businessDimensionLabel,
  formatBoolean,
  formatScalar,
  gateLabels,
  getCopy,
  metricGroups,
  resolveLocale,
  statePresentation,
  tierPresentation,
} from "./presentation";

const KNOWN_STATES = [
  "PASS",
  "WATCH",
  "FAIL",
  "SPECIAL_REVIEW",
  "NOT_EVALUATED",
  "PARTIAL",
  "BLOCKED",
  "NOT_AVAILABLE",
  "UNAVAILABLE",
  "UNKNOWN",
  "READY",
  "AVAILABLE",
  "ACCEPTED",
  "OK",
  "VALIDATED",
  "PRODUCTION_ELIGIBLE",
  "HIGH",
  "MEDIUM",
  "LOW",
  "ACCEPTABLE",
  "TURTLE_ENTRY",
  "EXTREME_SAFETY",
  "TOO_EXPENSIVE_FOR_STRICT_MODEL",
  "NO_NORMAL_VALUATION",
  "READ_ONLY",
  "NO_MATCHES",
  "ERROR",
] as const;

describe("locale defaults", () => {
  it("defaults the user-facing locale to zh-CN", () => {
    expect(DEFAULT_LOCALE).toBe("zh-CN");
    expect(getCopy().overviewTitle).toBe("研究面总览");
    expect(getCopy(DEFAULT_LOCALE).notAvailableLabel).toBe("无可用值");
  });

  it("resolves only supported stored locales and falls back to zh-CN", () => {
    expect(resolveLocale("en")).toBe("en");
    expect(resolveLocale("zh-CN")).toBe("zh-CN");
    expect(resolveLocale(null)).toBe("zh-CN");
    expect(resolveLocale(undefined)).toBe("zh-CN");
    expect(resolveLocale("fr")).toBe("zh-CN");
    expect(resolveLocale("ZH_CN")).toBe("zh-CN");
  });

  it("keeps both locale dictionaries structurally complete", () => {
    expect(Object.keys(getCopy("zh-CN")).sort()).toEqual(Object.keys(getCopy("en")).sort());
    expect(getCopy("en").overviewTitle).toBe("Research surfaces");
  });
});

describe("semantic state presentation", () => {
  it("gives every known semantic state a friendly label and an explanation", () => {
    for (const raw of KNOWN_STATES) {
      const presentation = statePresentation(raw);
      expect(presentation.known, raw).toBe(true);
      expect(presentation.label.length, raw).toBeGreaterThan(0);
      expect(presentation.explanation.length, raw).toBeGreaterThan(0);
      expect(presentation.label, raw).not.toBe(raw);
      expect(presentation.raw, raw).toBe(raw);
    }
  });

  it("keeps the required negative/missing states distinguishable", () => {
    const labels = [
      statePresentation("SPECIAL_REVIEW").label,
      statePresentation("BLOCKED").label,
      statePresentation("PARTIAL").label,
      statePresentation("NOT_EVALUATED").label,
      statePresentation("NOT_AVAILABLE").label,
    ];
    expect(new Set(labels).size).toBe(labels.length);
    expect(labels).toEqual(["需人工复核", "受阻", "部分数据", "未评估", "无可用值"]);
  });

  it("maps core gate/decision states to exact Chinese labels and tones", () => {
    expect(statePresentation("PASS").label).toBe("通过");
    expect(statePresentation("PASS").tone).toBe("positive");
    expect(statePresentation("WATCH").label).toBe("关注");
    expect(statePresentation("FAIL").label).toBe("未通过");
    expect(statePresentation("SPECIAL_REVIEW").label).toBe("需人工复核");
    expect(statePresentation("SPECIAL_REVIEW").tone).toBe("negative");
    expect(statePresentation("BLOCKED").tone).toBe("negative");
    expect(statePresentation("NOT_AVAILABLE").tone).toBe("neutral");
    expect(statePresentation("NOT_EVALUATED").tone).toBe("caution");
  });

  it("fails safe on unknown enum strings and never treats them as a pass", () => {
    for (const raw of ["SOME_FUTURE_STATE", "DEFINITELY_PASSISH", "pass_like"]) {
      const presentation = statePresentation(raw);
      expect(presentation.known, raw).toBe(false);
      expect(presentation.raw, raw).toBe(raw);
      expect(presentation.label, raw).toBe("未知状态");
      expect(presentation.tone, raw).not.toBe("positive");
      expect(presentation.explanation, raw).toContain("不视为通过");
    }
  });

  it("treats null, undefined and empty as the explicit no-value state", () => {
    for (const value of [null, undefined, ""]) {
      const presentation = statePresentation(value);
      expect(presentation.known).toBe(true);
      expect(presentation.raw).toBe("NOT_AVAILABLE");
      expect(presentation.label).toBe("无可用值");
      expect(presentation.tone).not.toBe("positive");
    }
  });

  it("tolerates raw casing while preserving the exact raw code", () => {
    const presentation = statePresentation("ok");
    expect(presentation.known).toBe(true);
    expect(presentation.label).toBe("正常");
    expect(presentation.raw).toBe("ok");
  });

  it("translates known states in the optional English locale", () => {
    expect(statePresentation("PASS", "en").label).toBe("Pass");
    expect(statePresentation("SPECIAL_REVIEW", "en").label).toBe("Manual review");
    expect(statePresentation("NOT_AVAILABLE", "en").label).toBe("No value");
  });
});

describe("conservative value formatting", () => {
  it("never turns missing or non-finite values into zero", () => {
    for (const value of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY]) {
      expect(formatScalar(value)).toBe("无可用值");
      expect(formatScalar(value)).not.toBe("0");
    }
  });

  it("preserves real numeric and string payload values exactly", () => {
    expect(formatScalar(0)).toBe("0");
    expect(formatScalar(12.5)).toBe("12.5");
    expect(formatScalar(-3.2)).toBe("-3.2");
    expect(formatScalar("CNY")).toBe("CNY");
    expect(formatScalar("2026-09-19")).toBe("2026-09-19");
  });

  it("renders booleans as explicit yes/no labels", () => {
    expect(formatBoolean(true)).toBe("是");
    expect(formatBoolean(false)).toBe("否");
    expect(formatScalar(false)).toBe("否");
    expect(formatBoolean(true, "en")).toBe("Yes");
    expect(formatScalar(false, "en")).toBe("No");
  });

  it("uses the English missing-value label in the English locale", () => {
    expect(formatScalar(null, "en")).toBe("No value");
  });
});

describe("API error presentation", () => {
  it("maps known stable error codes to friendly Chinese copy with raw diagnostics", () => {
    const error = new SurfaceAPIError(404, "SURFACE_NOT_FOUND", "surface not found");
    const presentation = apiErrorPresentation(error);
    expect(presentation.title).toBe("未找到该研究面");
    expect(presentation.message).toContain("已验证快照");
    expect(presentation.raw).toEqual({ status: "404", code: "SURFACE_NOT_FOUND", message: "surface not found" });
  });

  it("maps proxy, validation and mutation codes", () => {
    expect(apiErrorPresentation(new SurfaceAPIError(502, "UPSTREAM_UNREACHABLE", "x")).title).toBe(
      "上游服务不可达",
    );
    expect(
      apiErrorPresentation(new SurfaceAPIError(400, "INVALID_QUERY_PARAMETER", "x")).title,
    ).toBe("筛选参数无效");
    expect(
      apiErrorPresentation(new SurfaceAPIError(405, "READ_ONLY_METHOD_NOT_ALLOWED", "x")).title,
    ).toBe("只读接口不允许该操作");
  });

  it("keeps unknown API codes fail-safe with raw diagnostics intact", () => {
    const error = new SurfaceAPIError(418, "BRAND_NEW_CODE", "teapot");
    const presentation = apiErrorPresentation(error);
    expect(presentation.title).toBe("读取研究面数据时出错");
    expect(presentation.raw.code).toBe("BRAND_NEW_CODE");
    expect(presentation.raw.status).toBe("418");
    expect(presentation.raw.message).toBe("teapot");
  });

  it("treats transport failures as an unavailable read-only API", () => {
    const failure = apiErrorPresentation(new TypeError("fetch failed"));
    expect(failure.title).toBe("无法连接只读 API");
    expect(failure.raw.code).toBe("TypeError");
  });

  it("maps known errors in the English locale", () => {
    const error = new SurfaceAPIError(404, "SURFACE_NOT_FOUND", "surface not found");
    expect(apiErrorPresentation(error, "en").title).toBe("Surface not found");
  });
});

describe("structural labels", () => {
  it("labels all six gates in Chinese by default and English on switch", () => {
    const zh = gateLabels();
    expect(zh.map((gate) => gate.key)).toEqual([
      "universe",
      "balance_sheet",
      "cdc",
      "through_return",
      "business_quality",
      "governance_data_quality",
    ]);
    expect(zh[0].label).toBe("标的准入");
    expect(gateLabels("en")[0].label).toBe("Universe");
  });

  it("labels the three deterministic metric groups in Chinese by default", () => {
    const groups = metricGroups();
    expect(groups.map((group) => group.key)).toEqual(["cdc", "net_cash", "through_return"]);
    expect(groups[0].title).toBe("CDC 现金流创造");
    expect(groups[1].title).toBe("净现金");
    expect(groups[2].title).toBe("穿透回报");
    for (const group of groups) {
      for (const row of group.rows) {
        expect(row.label.length).toBeGreaterThan(0);
      }
    }
    expect(metricGroups("en")[1].title).toBe("Net Cash");
  });

  it("labels business-quality dimensions with a raw fallback", () => {
    expect(businessDimensionLabel("moat")).toBe("竞争壁垒");
    expect(businessDimensionLabel("moat", "en")).toBe("Competitive moat");
    expect(businessDimensionLabel("some_new_dimension")).toBe("some_new_dimension");
  });

  it("labels valuation tiers with a raw fallback", () => {
    expect(tierPresentation("observation").label).toBe("观察位");
    expect(tierPresentation("turtle_entry").label).toBe("龟式入场位");
    expect(tierPresentation("unknown_tier")).toEqual({ label: "unknown_tier", raw: "unknown_tier" });
  });
});
