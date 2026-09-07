import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import AppErrorBoundary from "./AppErrorBoundary";
import EngineSettingsDock from "./EngineSettingsDock";
import ExportController from "./ExportController";
import ProductRoot from "./ProductRoot";
import "./styles.css";
import "./error-boundary.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppErrorBoundary>
      <ProductRoot />
      <EngineSettingsDock />
      <ExportController />
    </AppErrorBoundary>
  </StrictMode>,
);
