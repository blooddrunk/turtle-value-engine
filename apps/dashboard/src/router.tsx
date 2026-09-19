import {
  Link,
  Outlet,
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router";
import { QueryClient } from "@tanstack/react-query";
import type { ReactElement } from "react";

import { OverviewPage } from "./views/overview";
import { SurfaceDetailPage } from "./views/surface-detail";

export interface OverviewSearch {
  listing?: string;
  profile?: string;
  asOf?: string;
}

function normalizeSearch(value: Record<string, unknown>): OverviewSearch {
  const text = (candidate: unknown): string | undefined =>
    typeof candidate === "string" && candidate.length > 0 ? candidate : undefined;
  return {
    listing: text(value.listing),
    profile: text(value.profile),
    asOf: text(value.asOf),
  };
}

function RootLayout(): ReactElement {
  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="site-header">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">
            TV
          </span>
          <div>
            <Link className="brand-name" to="/">
              Turtle Value Engine
            </Link>
            <p className="brand-caption">Frozen research surface</p>
          </div>
        </div>
        <nav aria-label="Primary navigation" className="site-nav">
          <Link activeProps={{ className: "is-active" }} to="/">
            Surfaces
          </Link>
          <span className="read-only-mark">Read-only</span>
        </nav>
      </header>
      <main className="app-shell" id="main-content">
        <Outlet />
      </main>
      <footer className="site-footer">
        <span>Local projection · no writes · no recalculation</span>
        <span>API contract: research_surface_api_v1</span>
      </footer>
    </>
  );
}

export const rootRoute = createRootRoute({ component: RootLayout });

export const overviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  validateSearch: normalizeSearch,
  component: OverviewPage,
});

export const surfaceDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/surfaces/$surfaceId",
  component: SurfaceDetailPage,
});

export const routeTree = rootRoute.addChildren([overviewRoute, surfaceDetailRoute]);

type RouterOptions = Parameters<typeof createRouter>[0];

export function createDashboardRouter(options?: Pick<RouterOptions, "history">) {
  return createRouter({ routeTree, ...options });
}

export const dashboardQueryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      staleTime: 30_000,
    },
  },
});

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createDashboardRouter>;
  }
}
