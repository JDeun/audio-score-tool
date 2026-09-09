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
import StudioViewControls from "./StudioViewControls";
import ValidationController from "./ValidationController";
import { installModalFocusLifecycle } from "./modalFocusLifecycle";
import "./styles.css";
import "./error-boundary.css";
import "./ui-polish.css";

const DEVELOPMENT_API_ORIGIN = "http://127.0.0.1:8080";
let runtimeApiOrigin = DEVELOPMENT_API_ORIGIN;
const PREFLIGHT_METHODS = new Set(["OPTIONS"]);

function rewriteApiUrl(rawUrl: string) {
  const developmentPrefix = `${DEVELOPMENT_API_ORIGIN}/api/`;
  if (rawUrl.startsWith(developmentPrefix)) {
    return `${runtimeApiOrigin}${rawUrl.slice(DEVELOPMENT_API_ORIGIN.length)}`;
  }
  return rawUrl;
}

function isRuntimeApiUrl(rawUrl: string) {
  return rewriteApiUrl(rawUrl).startsWith(`${runtimeApiOrigin}/api/`);
}

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
    if (!anchor || !isRuntimeApiUrl(anchor.href)) return;

    event.preventDefault();
    void (async () => {
      const artifactUrl = rewriteApiUrl(anchor.href);
      const response = await fetch(artifactUrl);
      if (!response.ok) throw new Error(`Artifact request failed (${response.status})`);
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const fallback = new URL(artifactUrl).pathname.split("/").pop() || "audioscore-artifact";
      const download = document.createElement("a");
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
    const [token, baseUrl] = await Promise.all([
      invoke<string>("backend_api_token"),
      invoke<string>("backend_api_base_url"),
    ]);
    if (!token || !baseUrl.startsWith("http://127.0.0.1:")) return;
    runtimeApiOrigin = baseUrl.replace(/\/$/, "");

    const nativeFetch = window.fetch.bind(window);
    window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl = input instanceof Request ? input.url : String(input);
      const rewrittenUrl = rewriteApiUrl(rawUrl);
      const method = (init?.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
      let requestInput: RequestInfo | URL = input;
      if (rewrittenUrl !== rawUrl) {
        requestInput = input instanceof Request ? new Request(rewrittenUrl, input) : rewrittenUrl;
      }
      if (!rewrittenUrl.startsWith(`${runtimeApiOrigin}/api/`) || PREFLIGHT_METHODS.has(method)) {
        return nativeFetch(requestInput, init);
      }
      const headers = new Headers(input instanceof Request ? input.headers : undefined);
      if (init?.headers) {
        new Headers(init.headers).forEach((value, key) => headers.set(key, value));
      }
      headers.set("X-AudioScore-Token", token);
      return nativeFetch(requestInput, { ...init, headers });
    };
    installAuthenticatedArtifactLinks();
  } catch {
    // Browser-only development or an unavailable Rust IPC command keeps the existing
    // fixed-port/no-token development behavior. Packaged builds provide both commands.
  }
}

function render() {
  installModalFocusLifecycle();
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <AppErrorBoundary>
        <ProductRoot />
        <StudioViewControls />
        <EngineSettingsDock />
        <ExportController />
        <ValidationController />
        <EnrichmentController />
        <OMRImportController />
        <NotationSettingsController />
        <SetupCenter />
        <ModelManager />
      </AppErrorBoundary>
    </StrictMode>,
  );
}

void installApiAuth().finally(render);
