import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { DashboardApp } from "./app";
import { createDashboardRouter } from "./router";
import "./styles.css";

const router = createDashboardRouter();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <DashboardApp router={router} />
  </StrictMode>,
);
