import { QueryClient } from "@tanstack/react-query";
import { createMemoryHistory } from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DashboardApp } from "./app";
import { buildSurfacesUrl } from "./api/client";
import { createDashboardRouter } from "./router";
import {
  testContentHash,
  testListResponse,
  testMonitoringActivationId,
  testMonitoringCycleId,
  testMonitoringDeliveryId,
  testMonitoringEmptyProjection,
  testMonitoringOrphanProjection,
  testMonitoringProjection,
  testSnapshot,
  testSurfaceId,
} from "./test/fixtures";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

function renderDashboard(initialPath = "/") {
  const history = createMemoryHistory({ initialEntries: [initialPath] });
  const router = createDashboardRouter({ history });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const rendered = render(<DashboardApp queryClient={queryClient} router={router} />);
  return { router, queryClient, unmount: rendered.unmount };
}

function mockOverviewAPI(list = testListResponse): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://dashboard.test").pathname;
      if (path === "/api/healthz") {
        return jsonResponse({
          status: "ok",
          contract: "research_surface_api_v1",
          version: "1.0.0",
          loaded_snapshot_count: list.surfaces.length,
        });
      }
      return jsonResponse(list);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  document.documentElement.lang = "zh-CN";
});

describe("surface overview", () => {
  it("defaults to the Chinese-first interface", async () => {
    mockOverviewAPI();
    renderDashboard();

    expect(await screen.findByRole("heading", { level: 1, name: "研究面总览" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "主导航" })).toHaveTextContent("研究面");
    expect(screen.getByText("跳到主要内容")).toBeInTheDocument();
    expect(screen.getAllByText("只读").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "应用筛选" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "清空" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "刷新数据" })).toBeInTheDocument();
    expect(await screen.findByText("已加载 1 个快照")).toBeInTheDocument();
  });

  it("shows a loading state while the list request is pending", async () => {
    let releaseList!: (response: Response) => void;
    const pendingList = new Promise<Response>((resolve) => {
      releaseList = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = new URL(String(input), "http://dashboard.test").pathname;
        if (path === "/api/healthz") return jsonResponse({ status: "ok", loaded_snapshot_count: 1 });
        return pendingList;
      }),
    );

    renderDashboard();

    expect(await screen.findByTestId("loading-state")).toBeInTheDocument();
    releaseList(jsonResponse(testListResponse));
    expect(await screen.findByText("SH600000")).toBeInTheDocument();
  });

  it("distinguishes no-snapshot empty state from no-filter-match empty state", async () => {
    mockOverviewAPI({ surfaces: [] });
    renderDashboard();

    expect(await screen.findByText("当前没有已加载的研究面快照")).toBeInTheDocument();
    expect(screen.getByText(/该只读服务需要显式加载经过校验的冻结快照/)).toBeInTheDocument();
    expect(screen.queryByText("没有符合筛选条件的研究面")).not.toBeInTheDocument();
  });

  it("shows the filter no-match empty state only when filters are active", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = new URL(String(input), "http://dashboard.test");
        if (url.pathname === "/api/healthz") {
          return jsonResponse({ status: "ok", loaded_snapshot_count: 1 });
        }
        return jsonResponse({ surfaces: [] });
      }),
    );
    renderDashboard("/?listing=HK99999");

    expect(await screen.findByText("没有符合筛选条件的研究面")).toBeInTheDocument();
    expect(screen.getByText(/可以清除或放宽筛选条件后重试/)).toBeInTheDocument();
    expect(screen.queryByText("当前没有已加载的研究面快照")).not.toBeInTheDocument();
  });

  it("shows a friendly API error state with raw diagnostics only in technical details", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = new URL(String(input), "http://dashboard.test").pathname;
        if (path === "/api/healthz") return jsonResponse({ status: "ok", loaded_snapshot_count: 1 });
        return jsonResponse(
          { error: { code: "UPSTREAM_UNREACHABLE", message: "surface API is unreachable" } },
          502,
        );
      }),
    );
    renderDashboard();

    const alert = await screen.findByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(screen.getByText("上游服务不可达")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试读取" })).toBeInTheDocument();
    const rawCode = screen.getByText("UPSTREAM_UNREACHABLE");
    expect(rawCode.closest("details")).not.toBeNull();
    expect(screen.getByText("502").closest("details")).not.toBeNull();
    expect(
      screen.getByText("surface API is unreachable").closest("details"),
    ).not.toBeNull();
    expect(alert.querySelector("h2")).toHaveTextContent("上游服务不可达");
    expect(alert.querySelector("h2")).not.toHaveTextContent("UPSTREAM_UNREACHABLE");
  });

  it("encodes only the supported API filters", () => {
    expect(
      buildSurfacesUrl({ listing: "SH600000", profile: "strict-v1", asOf: "2026-09-19" }),
    ).toBe(
      "/api/v1/surfaces?primary_listing=SH600000&profile_id=strict-v1&as_of=2026-09-19",
    );
    expect(buildSurfacesUrl({ listing: "SH600000" })).not.toContain("upstream");
  });

  it("applies filter form values through the router search", async () => {
    const user = userEvent.setup();
    mockOverviewAPI();
    const { router } = renderDashboard();

    await screen.findByText("SH600000");
    await user.type(screen.getByLabelText("上市代码"), "HK00700");
    await user.click(screen.getByRole("button", { name: "应用筛选" }));

    await waitFor(() => expect(router.state.location.search).toEqual({ listing: "HK00700" }));
    expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/v1/surfaces?primary_listing=HK00700", expect.anything());
  });

  it("switches the interface language through a client-only toggle", async () => {
    const user = userEvent.setup();
    mockOverviewAPI();
    renderDashboard();

    expect(await screen.findByRole("heading", { level: 1, name: "研究面总览" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /切换界面语言/ }));

    expect(await screen.findByRole("heading", { level: 1, name: "Research surfaces" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply filters" })).toBeInTheDocument();
    expect(window.localStorage.getItem("tve-dashboard-locale")).toBe("en");
    expect(document.documentElement.lang).toBe("en");
  });
});

describe("surface detail", () => {
  it("renders deterministic values with friendly Chinese states and raw codes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(testSnapshot)),
    );
    renderDashboard(`/surfaces/${testSurfaceId}`);

    expect(await screen.findByRole("heading", { name: "Fixture Holdings" })).toBeInTheDocument();
    for (const heading of ["决策与估值", "确定性指标", "硬性门槛", "数据质量", "商业质量", "历史数据与可用性"]) {
      expect(screen.getByRole("heading", { level: 2, name: heading })).toBeInTheDocument();
    }
    expect(screen.getAllByText("需人工复核").length).toBeGreaterThan(0);
    expect(screen.getAllByText("SPECIAL_REVIEW").length).toBeGreaterThan(0);
    expect(screen.getAllByText("部分数据").length).toBeGreaterThan(0);
    expect(screen.getAllByText("受阻").length).toBeGreaterThan(0);
    expect(screen.getAllByText("未评估").length).toBeGreaterThan(0);
    expect(screen.getAllByText("无可用值").length).toBeGreaterThan(0);
    expect(screen.getByText("12.5")).toBeInTheDocument();
    expect(screen.getByText("Restricted cash classification unresolved")).toBeInTheDocument();
    expect(screen.getAllByText("否").length).toBeGreaterThan(0);
  });

  it("keeps exact IDs and hashes available inside the technical details affordance", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(testSnapshot)));
    renderDashboard(`/surfaces/${testSurfaceId}`);

    await screen.findByRole("heading", { name: "Fixture Holdings" });
    const summary = screen.getByText("技术 / 审计详情（原始标识、哈希与契约）");
    const details = summary.closest("details");
    expect(details).not.toBeNull();
    expect(details?.textContent).toContain(testContentHash);
    expect(details?.textContent).toContain(testSurfaceId);
    expect(details?.textContent).toContain("analysis-fixture");
    expect(details?.textContent).toContain("GET /api/v1/surfaces/");
    expect(details?.textContent).toContain("research_surface_snapshot_v1");
    expect(details?.textContent).toContain("COMPANY_ANALYSIS");
  });

  it("does not surface raw hashes as primary overview content", async () => {
    mockOverviewAPI();
    renderDashboard();

    expect(await screen.findByText("SH600000")).toBeInTheDocument();
    const hashElement = screen.getByText(testContentHash);
    const hashDetails = hashElement.closest("details");
    expect(hashDetails).not.toBeNull();
    expect(hashDetails?.querySelector("summary")).toHaveTextContent("技术详情");
  });

  it("maps a 404 detail fetch to a friendly not-found message with raw diagnostics", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({ error: { code: "SURFACE_NOT_FOUND", message: "surface not found" } }, 404),
      ),
    );
    renderDashboard(`/surfaces/${testSurfaceId}`);

    const alert = await screen.findByRole("alert");
    expect(alert.querySelector("h2")).toHaveTextContent("未找到该研究面");
    expect(screen.getByText("SURFACE_NOT_FOUND").closest("details")).not.toBeNull();
  });

  it("has no mutation controls", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(testSnapshot)));
    renderDashboard(`/surfaces/${testSurfaceId}`);

    await screen.findByRole("heading", { name: "Fixture Holdings" });
    expect(
      screen.queryByRole("button", { name: /save|approve|delete|trade|order|run/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /保存|审批|删除|下单|交易/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/POST|PUT|PATCH|DELETE/)).not.toBeInTheDocument();
  });
});

function mockMonitoringAPI(body: unknown = testMonitoringProjection, status = 200): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://dashboard.test").pathname;
      if (path === "/api/v1/monitoring/operations") {
        return jsonResponse(body, status);
      }
      if (path === "/api/healthz") {
        return jsonResponse({
          status: "ok",
          contract: "research_surface_api_v1",
          version: "1.0.0",
          loaded_snapshot_count: testListResponse.surfaces.length,
        });
      }
      return jsonResponse(testListResponse);
    }),
  );
}

describe("monitoring operations", () => {
  it("shows the Chinese-first monitoring page through the main navigation", async () => {
    const user = userEvent.setup();
    mockMonitoringAPI();
    renderDashboard("/");

    await screen.findByRole("heading", { level: 1, name: "研究面总览" });
    await user.click(screen.getByRole("link", { name: "监控运行" }));

    expect(await screen.findByRole("heading", { level: 2, name: "运行概览" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "监控运行状态" })).toBeInTheDocument();
    for (const heading of ["运行概览", "重分析任务", "通知投递", "审计详情（原始标识与哈希）"]) {
      expect(screen.getByRole("heading", { level: 2, name: heading })).toBeInTheDocument();
    }
    expect(screen.getAllByText("只读").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "刷新数据" })).toBeInTheDocument();
    expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/v1/monitoring/operations", expect.anything());
  });

  it("gives every important operational state intentional Chinese copy with raw codes", async () => {
    mockMonitoringAPI();
    renderDashboard("/monitoring");

    expect((await screen.findAllByText("可用")).length).toBeGreaterThan(0);
    for (const label of [
      "租约已过期",
      "最近终结",
      "已发出提醒",
      "完整重分析",
      "已完成",
      "已解决",
      "已送达",
      "指针一致",
      "重分析完成",
    ]) {
      expect(screen.getAllByText(label).length, label).toBeGreaterThan(0);
    }
    for (const raw of ["AVAILABLE", "ABANDONED", "LATEST_TERMINAL", "ALERTS_EMITTED", "DELIVERED", "CURRENT"]) {
      expect(screen.getAllByText(raw).length, raw).toBeGreaterThan(0);
    }
    expect(screen.queryByText("未知状态")).not.toBeInTheDocument();
  });

  it("distinguishes empty and not-configured states from error states", async () => {
    mockMonitoringAPI(testMonitoringEmptyProjection);
    const { unmount } = renderDashboard("/monitoring");

    expect(await screen.findByText("尚无激活记录")).toBeInTheDocument();
    expect(screen.getByText("未配置投递账本")).toBeInTheDocument();
    expect(screen.getByText("本次周期没有重分析任务")).toBeInTheDocument();
    expect(screen.getAllByText("无可用值").length).toBeGreaterThan(0);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    unmount();

    mockMonitoringAPI(
      { error: { code: "MONITORING_OPERATIONS_CONFLICT", message: "store evidence failed" } },
      409,
    );
    renderDashboard("/monitoring");

    const alert = await screen.findByRole("alert");
    expect(alert.querySelector("h2")).toHaveTextContent("监控证据不一致");
    expect(screen.getByText("MONITORING_OPERATIONS_CONFLICT").closest("details")).not.toBeNull();
    expect(screen.queryByText("尚无激活记录")).not.toBeInTheDocument();
    expect(screen.queryByText("未配置投递账本")).not.toBeInTheDocument();
  });

  it("keeps persisted-outcome count and consumed-slot count as distinct labels and values", async () => {
    mockMonitoringAPI(testMonitoringOrphanProjection);
    renderDashboard("/monitoring");

    const outcomeRow = (await screen.findByText("已持久化投递结果数")).closest(".field-row");
    expect(outcomeRow).toHaveTextContent("0");
    const slotRow = screen.getByText("已消耗外发槽位数").closest(".field-row");
    expect(slotRow).toHaveTextContent("1");
    expect(screen.getByText(/两个计数语义不同/)).toBeInTheDocument();
    expect(screen.getByText(/绝不把结果数当作总发送次数/)).toBeInTheDocument();
  });

  it("keeps unresolved slot numbers and the orphaned dispatch visible", async () => {
    mockMonitoringAPI(testMonitoringOrphanProjection);
    renderDashboard("/monitoring");

    const unresolvedRow = (await screen.findByText("未决槽位编号")).closest(".field-row");
    expect(unresolvedRow).toHaveTextContent("1");
    expect(screen.getAllByText("结果不确定").length).toBeGreaterThan(0);
    expect(screen.getAllByText("外发结果丢失").length).toBeGreaterThan(0);
    expect(screen.getAllByText("ORPHANED_DISPATCH").length).toBeGreaterThan(0);
  });

  it("keeps the delivery pointer status visible", async () => {
    mockMonitoringAPI(testMonitoringOrphanProjection);
    renderDashboard("/monitoring");

    const pointerRow = (await screen.findByText("状态指针")).closest(".field-row");
    expect(pointerRow).toHaveTextContent("指针过期");
    expect(pointerRow).toHaveTextContent("STALE_REPAIRABLE");
  });

  it("keeps ids and hashes available inside the audit details section", async () => {
    mockMonitoringAPI();
    renderDashboard("/monitoring");

    const audit = (await screen.findByRole("heading", { level: 2, name: "审计详情（原始标识与哈希）" })).closest(
      "section",
    );
    expect(audit).not.toBeNull();
    expect(audit?.textContent).toContain(testMonitoringActivationId);
    expect(audit?.textContent).toContain(testMonitoringCycleId);
    expect(audit?.textContent).toContain(testMonitoringDeliveryId);
    expect(audit?.textContent).toContain("monitoring_operations_projection_v1");
    const attemptsSummary = screen.getByText("投递尝试明细");
    expect(attemptsSummary.closest("details")).not.toBeNull();
  });

  it("has no mutation controls", async () => {
    mockMonitoringAPI();
    renderDashboard("/monitoring");

    await screen.findByRole("heading", { level: 2, name: "运行概览" });
    expect(
      screen.queryByRole("button", { name: /save|approve|delete|trade|order|run|retry|resend|repair|acknowledge|dismiss/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /保存|审批|删除|下单|交易|重发|重试|修复|确认|立即运行/ }),
    ).not.toBeInTheDocument();
    const allowed = new Set(["刷新数据", "切换界面语言"]);
    for (const button of screen.getAllByRole("button")) {
      const name = button.getAttribute("aria-label") ?? button.textContent ?? "";
      expect(allowed.has(name), `unexpected control: ${name}`).toBe(true);
    }
  });

  it("keeps a mobile-safe semantic structure with keyboard-focusable controls", async () => {
    mockMonitoringAPI();
    renderDashboard("/monitoring");

    await screen.findByRole("heading", { level: 2, name: "运行概览" });
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("navigation", { name: "主导航" })).toBeInTheDocument();
    const refresh = screen.getByRole("button", { name: "刷新数据" });
    expect(refresh).toHaveAttribute("type", "button");
    refresh.focus();
    expect(refresh).toHaveFocus();
    const table = document.querySelector(".table-frame table");
    expect(table).not.toBeNull();
    expect(table?.querySelectorAll("th[scope='col']").length).toBeGreaterThan(0);
  });
});
