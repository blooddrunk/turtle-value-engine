import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, type AnyRouter } from "@tanstack/react-router";
import type { QueryClient } from "@tanstack/react-query";
import type { ReactElement } from "react";

import { LocaleProvider } from "./components";
import { createDashboardRouter, dashboardQueryClient } from "./router";

export interface DashboardAppProps {
  router?: AnyRouter;
  queryClient?: QueryClient;
}

export function DashboardApp({
  router = createDashboardRouter(),
  queryClient = dashboardQueryClient,
}: DashboardAppProps): ReactElement {
  return (
    <LocaleProvider>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </LocaleProvider>
  );
}
