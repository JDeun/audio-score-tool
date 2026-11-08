import { expect, test, type Page } from "@playwright/test";

const HEALTH = {
  status: "ok",
  device_plan: { muscriptor_device: "cpu", demucs_device: "cpu", whisperx_device: "cpu", whisperx_compute_type: "int8" },
  preflight: { ok: true, missing: [], tools: { transcription_engine: true, whisperx: true } },
  presets: { recommended: "quality", presets: [] },
  data_dir: "/tmp/audio-score-tool",
  system: { hf_authenticated: true, jobs_bytes: 0, disk_total_bytes: 1024, disk_used_bytes: 0, disk_free_bytes: 1024 },
};

async function prepareYoutubePage(page: Page, recorded: Record<string, unknown>[], mode: "personal" | "commercial" = "personal") {
  await page.route("**/api/health", async (route) => route.fulfill({ json: { ...HEALTH, usage_mode: mode } }));
  await page.route("**/api/setup", async (route) => route.fulfill({
    json: { preflight: HEALTH.preflight, tool_paths: {}, instructions: { hf_note: "" } },
  }));
  await page.route("**/api/jobs?limit=100", async (route) => route.fulfill({ json: { jobs: [] } }));
  await page.route("**/api/sources/youtube/inspect", async (route) => route.fulfill({
    json: { title: "Owned fixture", uploader: "Test", duration: 30, webpage_url: "https://www.youtube.com/watch?v=abcdef12345" },
  }));
  await page.route("**/api/jobs/youtube", async (route) => {
    recorded.push(route.request().postDataJSON() as Record<string, unknown>);
    await route.fulfill({ status: 202, json: { job_id: "fixture-job", status: "queued" } });
  });
  await page.addInitScript(() => {
    localStorage.setItem("ast-onboarding-v1", "done");
    localStorage.setItem("ast-setup-center-v2", "dismissed");
  });
  await page.goto("/");
  await page.getByRole("tab", { name: "YouTube 링크" }).click();
  await page.locator(".youtube-inline-row input").fill("https://www.youtube.com/watch?v=abcdef12345");
  await page.getByRole("button", { name: "링크 확인" }).click();
  await expect(page.locator(".source-preview-row")).toContainText("Owned fixture");
  if (mode === "commercial") {
    await page.locator(".rights-check input").check();
  } else {
    await expect(page.locator(".rights-check")).toHaveCount(0);
    await expect(page.locator(".source-usage-note")).toContainText("개인 연습");
  }
}

test("YouTube custom preset forwards both explicit model choices to the job API", async ({ page }) => {
  const recorded: Record<string, unknown>[] = [];
  await prepareYoutubePage(page, recorded);

  await page.locator(".transcription-options select").first().selectOption("custom");
  await page.locator(".custom-model-row select").first().selectOption("small");
  await page.locator(".custom-model-row select").nth(1).selectOption("large-v3");
  await page.getByRole("button", { name: "자동 채보 시작" }).click();

  await expect.poll(() => recorded.length).toBe(1);
  expect(recorded[0]).toMatchObject({
    url: "https://www.youtube.com/watch?v=abcdef12345",
    authorized: false,
    preset: "balanced",
    muscriptor_model: "small",
    whisperx_model: "large-v3",
  });
});

test("YouTube built-in presets do not leak previous custom model choices", async ({ page }) => {
  const recorded: Record<string, unknown>[] = [];
  await prepareYoutubePage(page, recorded);

  const preset = page.locator(".transcription-options select").first();
  await preset.selectOption("custom");
  await page.locator(".custom-model-row select").first().selectOption("small");
  await page.locator(".custom-model-row select").nth(1).selectOption("large-v3");
  await preset.selectOption("quality");
  await page.getByRole("button", { name: "자동 채보 시작" }).click();

  await expect.poll(() => recorded.length).toBe(1);
  expect(recorded[0]).toMatchObject({ preset: "quality" });
  expect(recorded[0]).not.toHaveProperty("muscriptor_model");
  expect(recorded[0]).not.toHaveProperty("whisperx_model");
});



test("personal YouTube link analysis starts without asserting ownership", async ({ page }) => {
  const recorded: Record<string, unknown>[] = [];
  await prepareYoutubePage(page, recorded, "personal");

  await expect(page.getByRole("button", { name: "자동 채보 시작" })).toBeEnabled();
  await page.getByRole("button", { name: "자동 채보 시작" }).click();
  await expect.poll(() => recorded.length).toBe(1);
  expect(recorded[0]).toMatchObject({
    url: "https://www.youtube.com/watch?v=abcdef12345",
    authorized: false,
  });
});

test("commercial mode keeps explicit rights confirmation", async ({ page }) => {
  const recorded: Record<string, unknown>[] = [];
  await prepareYoutubePage(page, recorded, "commercial");

  await expect(page.locator(".rights-check")).toContainText("상용 이용");
  await page.locator(".rights-check input").uncheck();
  await expect(page.getByRole("button", { name: "자동 채보 시작" })).toBeDisabled();
  await page.locator(".rights-check input").check();
  await expect(page.getByRole("button", { name: "자동 채보 시작" })).toBeEnabled();
  await page.getByRole("button", { name: "자동 채보 시작" }).click();
  await expect.poll(() => recorded.length).toBe(1);
  expect(recorded[0]).toMatchObject({ authorized: true });
});
