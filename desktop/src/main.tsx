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

function responseFilename(response: Response, fallback: string) {
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const utf8 = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (utf8) {
    try {
      return decodeURIComponent(utf8.replace(/^"|"$/g, ""));
    } catch {
      // Fall through to the plain filename/fallback.
    }
  }
  return disposition.match(/filename="?([^";]+)"?/i)?.[1] ?? fallback;
}

function installAuthenticatedArtifactLinks() {
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const anchor = target.closest("a");
    if (!anchor || !anchor.href.startsWith(API_PREFIX)) return;

    event.preventDefault();
    void (async () => {
      const response = await fetch(anchor.href);
      if (!response.ok) throw new Error(`Artifact request failed (${response.status})`);
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const download = document.createElement("a");
      const fallback = new URL(anchor.href).pathname.split("/").pop() || "audioscore-artifact";
      download.href = objectUrl;
      download.download = responseFilename(response, fallback);
      download.style.display = "none";
      document.body.appendChild(download);
      download.click();
      download.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 30_000);
    })().catch((error) => {
      console.error("Authenticated artifact download failed", error);
    });
  });
}

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
    installAuthenticatedArtifactLinks();
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
