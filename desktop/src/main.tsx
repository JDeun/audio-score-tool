import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import AppErrorBoundary from "./AppErrorBoundary";
import EngineSettingsDock from "./EngineSettingsDock";
import ExportController from "./ExportController";
import ModelManager from "./ModelManager";
import NotationSettingsController from "./NotationSettingsController";
import OMRImportController from "./OMRImportController";
import ProductRoot from "./ProductRoot";
import SetupCenter from "./SetupCenter";
import ValidationController from "./ValidationController";
import "./styles.css";
import "./error-boundary.css";
import "./ui-polish.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppErrorBoundary>
      <ProductRoot />
      <EngineSettingsDock />
      <ExportController />
      <ValidationController />
      <OMRImportController />
      <NotationSettingsController />
      <SetupCenter />
      <ModelManager />
    </AppErrorBoundary>
  </StrictMode>,
);
