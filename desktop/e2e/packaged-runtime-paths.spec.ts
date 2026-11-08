import { expect, test, type Page } from "@playwright/test";

async function openSettings(page: Page, packaged: boolean, engineRequests: Record<string, unknown>[], managedModel: "mr_mt3" | null = null) {
  const engine = {
    packaged_runtime: packaged,
    managed_mt3_model: managedModel,
    usage_mode: "personal",
    selected: "muscriptor",
    mt3_model: managedModel ?? "yourmt3",
    mt3_infer_cmd: "/managed/mt3-infer",
    muscriptor_cmd: "/managed/muscriptor",
    muscriptor_model: "small",
    native_engine_cmd: "/managed/native",
    engines: [
      { key: "muscriptor", name: "MuScriptor", ready: true, commercial_status: "noncommercial_weights" },
      { key: "mt3_infer", name: "MT3-Infer", ready: true, commercial_status: "commercial_candidate" },
      { key: "native", name: "AudioScore Native", ready: false, commercial_status: "project_owned" },
    ],
    preflight: { ok: true, missing: [] },
  };
  await page.route("**/api/engines", async route => {
    if (route.request().method() === "PUT") engineRequests.push(
      route.request().postDataJSON() as Record<string, unknown>,
    );
    await route.fulfill({ json: engine });
  });
  await page.route("**/api/health", route => route.fulfill({
    json: {
      status: "ok", packaged_runtime: packaged,
      device_plan: { muscriptor_device: "cpu", demucs_device: "cpu" },
      preflight: { ok: true, missing: [], tools: { muscriptor: true } },
      presets: { recommended: "quality", presets: [] },
      data_dir: "/tmp/ast",
      system: { hf_authenticated: true, jobs_bytes: 0, disk_free_bytes: 1024 },
    },
  }));
  await page.route("**/api/setup", route => route.fulfill({
    json: {
      packaged_runtime: packaged,
      preflight: { ok: true, missing: [], tools: {} },
      tool_paths: { muscriptor_cmd: "/ignored/legacy", whisperx_cmd: "/ignored/asr" },
      instructions: { hf_note: "" },
    },
  }));
  await page.route("**/api/jobs?limit=100", route => route.fulfill({ json: { jobs: [] } }));
  await page.addInitScript(() => {
    localStorage.setItem("ast-onboarding-v1", "done");
    localStorage.setItem("ast-setup-center-v2", "dismissed");
    localStorage.setItem("ast-section", "settings");
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "도구 경로" }).or(
    page.getByRole("heading", { name: "앱 관리형 구성요소" }),
  )).toBeVisible();
}

test("packaged desktop hides ignored command overrides and engine save excludes them", async ({ page }) => {
  const requests: Record<string, unknown>[] = [];
  await openSettings(page, true, requests);

  await expect(page.getByRole("heading", { name: "앱 관리형 구성요소" })).toBeVisible();
  await expect(page.locator(".path-input-list input")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "경로 저장" })).toHaveCount(0);
  await page.locator(".engine-dock-trigger").click();
  const dialog = page.getByRole("dialog", { name: "채보 엔진 설정" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("MuScriptor 실행 명령")).toHaveCount(0);
  await expect(dialog.getByText("배포 앱에서는 사용자 지정 실행 명령")).toBeVisible();
  await expect(dialog.getByRole("button", { name: /AudioScore Native/ })).toBeDisabled();

  await dialog.getByRole("button", { name: /MT3-Infer/ }).click();
  await expect(dialog.getByText("MT3-Infer 실행 명령")).toHaveCount(0);
  await dialog.getByRole("button", { name: "엔진 정책 저장" }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toMatchObject({ transcription_engine: "mt3_infer" });
  for (const key of ["mt3_infer_cmd", "muscriptor_cmd", "native_engine_cmd", "native_checkpoint"]) {
    expect(requests[0]).not.toHaveProperty(key);
  }
});

test("developer desktop still offers explicit command override controls", async ({ page }) => {
  await openSettings(page, false, []);
  await expect(page.getByRole("heading", { name: "도구 경로" })).toBeVisible();
  await expect(page.locator(".path-input-list input")).toHaveCount(3);
  await expect(page.getByRole("button", { name: "경로 저장" })).toBeVisible();
  await page.locator(".engine-dock-trigger").click();
  const dialog = page.getByRole("dialog", { name: "채보 엔진 설정" });
  await expect(dialog.getByText("MuScriptor 실행 명령")).toBeVisible();
});



test("published packaged MR-MT3 is selected instead of unavailable YourMT3", async ({ page }) => {
  const requests: Record<string, unknown>[] = [];
  await openSettings(page, true, requests, "mr_mt3");
  await page.locator(".engine-dock-trigger").click();
  const dialog = page.getByRole("dialog", { name: "채보 엔진 설정" });
  const usage = dialog.getByRole("combobox", { name: "사용 목적" });
  await usage.selectOption("commercial");
  const model = dialog.getByRole("combobox", { name: "모델" });
  await expect(model).toHaveValue("mr_mt3");
  await expect(model.locator('option[value="yourmt3"]')).toBeDisabled();
  await dialog.getByRole("button", { name: "엔진 정책 저장" }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toMatchObject({
    usage_mode: "commercial",
    transcription_engine: "mt3_infer",
    mt3_model: "mr_mt3",
  });
});
