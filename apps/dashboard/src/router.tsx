import {
  Link,
  Outlet,
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router";
import { QueryClient } from "@tanstack/react-query";
import type { ReactElement } from "react";

import { TechnicalDetails, useLocaleControls } from "./components";
import { useCopy } from "./presentation";
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
  const copy = useCopy();
  const { locale, toggleLocale } = useLocaleControls();
  return (
    <>
      <a className="skip-link" href="#main-content">
        {copy.skipToContent}
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
            <p className="brand-caption">{copy.brandCaption}</p>
          </div>
        </div>
        <nav aria-label={copy.navAriaLabel} className="site-nav">
          <Link activeProps={{ className: "is-active" }} to="/">
            {copy.navOverview}
          </Link>
          <span className="read-only-mark">{copy.readOnlyMark}</span>
          <button
            aria-label={copy.localeToggleAria}
            className="button button-quiet locale-toggle"
            onClick={toggleLocale}
            type="button"
          >
            {locale === "zh-CN" ? "EN" : "中文"}
          </button>
        </nav>
      </header>
      <main className="app-shell" id="main-content">
        <Outlet />
      </main>
      <footer className="site-footer">
        <span>{copy.footerNote}</span>
        <TechnicalDetails className="footer-contracts" summary={copy.footerContractsSummary}>
          <dl className="field-list">
            <div className="field-row">
              <dt>{copy.footerApiContractLabel}</dt>
              <dd className="mono-value">research_surface_api_v1</dd>
            </div>
            <div className="field-row">
              <dt>{copy.footerSnapshotContractLabel}</dt>
              <dd className="mono-value">research_surface_snapshot_v1</dd>
            </div>
          </dl>
        </TechnicalDetails>
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
