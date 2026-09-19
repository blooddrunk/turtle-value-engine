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
});

describe("surface overview", () => {
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

  it("shows the explicit empty state", async () => {
    mockOverviewAPI({ surfaces: [] });
    renderDashboard();

    expect(await screen.findByText("No frozen surfaces match")).toBeInTheDocument();
    expect(screen.getByText(/Remove a filter/)).toBeInTheDocument();
  });

  it("shows an API error state with a retry action", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = new URL(String(input), "http://dashboard.test").pathname;
        if (path === "/api/healthz") return jsonResponse({ status: "ok", loaded_snapshot_count: 1 });
        return jsonResponse({ error: { code: "UPSTREAM_UNREACHABLE", message: "surface API is unreachable" } }, 502);
      }),
    );
    renderDashboard();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("surface API is unreachable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry GET request" })).toBeInTheDocument();
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
    await user.type(screen.getByLabelText("Listing"), "HK00700");
    await user.click(screen.getByRole("button", { name: "Apply filters" }));

    await waitFor(() => expect(router.state.location.search).toEqual({ listing: "HK00700" }));
    expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/v1/surfaces?primary_listing=HK00700", expect.anything());
  });
});

describe("surface detail", () => {
  it("renders deterministic values and preserves blocked/partial/unavailable states", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(testSnapshot)),
    );
    renderDashboard(`/surfaces/${testSurfaceId}`);

    expect(await screen.findByRole("heading", { name: "Fixture Holdings" })).toBeInTheDocument();
    expect(screen.getAllByText("SPECIAL_REVIEW").length).toBeGreaterThan(0);
    expect(screen.getAllByText("PARTIAL").length).toBeGreaterThan(0);
    expect(screen.getAllByText("BLOCKED").length).toBeGreaterThan(0);
    expect(screen.getAllByText("NOT_AVAILABLE").length).toBeGreaterThan(0);
    expect(screen.getAllByText("NOT_EVALUATED").length).toBeGreaterThan(0);
    expect(screen.getByText("12.5")).toBeInTheDocument();
    expect(screen.getByText("Restricted cash classification unresolved")).toBeInTheDocument();
    expect(screen.getByText(testContentHash)).toBeInTheDocument();
  });

  it("has no mutation controls", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(testSnapshot)));
    renderDashboard(`/surfaces/${testSurfaceId}`);

    await screen.findByRole("heading", { name: "Fixture Holdings" });
    expect(screen.queryByRole("button", { name: /save|approve|delete|trade|order|run/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/POST|PUT|PATCH|DELETE/)).not.toBeInTheDocument();
  });
});
