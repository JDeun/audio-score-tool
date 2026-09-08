import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { invoke } from "@tauri-apps/api/core";
import AppErrorBoundary from "./AppErrorBoundary";
import EngineSettingsDock from "./EngineSettingsDock";
import EnrichmentController from "./EnrichmentController";
import ExportController from "./ExportController";
import ModelManager from "./ModelManager";
import NotationSettingsController from "./NotationSettingsController";
import OMRImportController from "./OMRImportController";
import ProductRoot from "./ProductRoot";
import SetupCenter from "./SetupCenter";
import SourceIdentificationController from "./SourceIdentificationController";
import ValidationController from "./ValidationController";
import "./styles.css";
import "./error-boundary.css";
import "./ui-polish.css";

const API_PREFIX = "http://127.0.0.1:8080/api/";
const PREFLIGHT_METHODS = new Set(["OPTIONS"]);

async function installApiAuth() {
  if (!("__TAURI_INTERNALS__" in window)) return;
  try {
    const token = await invoke<string>("backend_api_token");
    if (!token) return;
    const nativeFetch = window.fetch.bind(window);
    window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl = input instanceof Request ? input.url : String(input);
      const method = (init?.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
      if (!rawUrl.startsWith(API_PREFIX) || PREFLIGHT_METHODS.has(method)) {
        return nativeFetch(input, init);
      }
      const headers = new Headers(input instanceof Request ? input.headers : undefined);
      if (init?.headers) {
        new Headers(init.headers).forEach((value, key) => headers.set(key, value));
      }
      headers.set("X-AudioScore-Token", token);
      return nativeFetch(input, { ...init, headers });
    };
  } catch {
    // Browser-only development or an unavailable Rust IPC command keeps the existing
    // no-token development behavior. Packaged builds provide the command and sidecar env.
  }
}

function render() {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <AppErrorBoundary>
        <ProductRoot />
        <EngineSettingsDock />
        <ExportController />
        <ValidationController />
        <EnrichmentController />
        <SourceIdentificationController />
        <OMRImportController />
        <NotationSettingsController />
        <SetupCenter />
        <ModelManager />
      </AppErrorBoundary>
    </StrictMode>,
  );
}

void installApiAuth().finally(render);
