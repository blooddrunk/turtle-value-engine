import { QueryClient } from "@tanstack/react-query";
import { createMemoryHistory } from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DashboardApp } from "./app";
import { buildSurfacesUrl } from "./api/client";
import { createDashboardRouter } from "./router";
import { testContentHash, testListResponse, testSnapshot, testSurfaceId } from "./test/fixtures";

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
  render(<DashboardApp queryClient={queryClient} router={router} />);
  return { router, queryClient };
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
