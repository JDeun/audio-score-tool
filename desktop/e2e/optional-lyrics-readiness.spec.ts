import { expect, test, type Page } from "@playwright/test";

async function openNewScore(
  page: Page,
  { coreReady, whisperxReady, youtubeReady }: {
    coreReady: boolean;
    whisperxReady: boolean;
    youtubeReady: boolean;
  },
) {
  await page.route("**/api/health", (route) => route.fulfill({
    json: {
      status: "ok",
      device_plan: { muscriptor_device: "cpu" },
      preflight: {
        ok: coreReady,
        missing: coreReady ? [] : ["transcription_engine:mt3_infer"],
        tools: { transcription_engine: coreReady, whisperx: whisperxReady },
      },
      presets: { recommended: "quality", presets: [] },
      data_dir: "/tmp/ast",
      system: { hf_authenticated: true, jobs_bytes: 0, disk_free_bytes: 1024 },
      youtube: { ready: youtubeReady },
    },
  }));
  await page.route("**/api/setup", (route) => route.fulfill({
    json: {
      preflight: { ok: coreReady, missing: [], tools: {} },
      tool_paths: {}, instructions: { hf_note: "" },
    },
  }));
  await page.route("**/api/jobs?limit=100", (route) => route.fulfill({
    json: { jobs: [] },
  }));
  await page.addInitScript(() => {
    localStorage.setItem("ast-onboarding-v1", "done");
    localStorage.setItem("ast-setup-center-v2", "dismissed");
    localStorage.setItem("ast-section", "new");
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "새 악보", exact: true })).toBeVisible();
  await page.locator(".premium-dropzone input").setInputFiles({
    name: "fixture.wav",
    mimeType: "audio/wav",
    buffer: Buffer.from("fixture"),
  });
}

test("missing optional WhisperX defaults to score-only while core upload stays available", async ({ page }) => {
  await openNewScore(page, { coreReady: true, whisperxReady: false, youtubeReady: false });
  const lyricToggle = page.getByRole("button", { name: "악보만" });
  await expect(lyricToggle).toBeDisabled();
  await expect(lyricToggle).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByText(/WhisperX 미설치/)).toBeVisible();
  await expect(page.getByRole("button", { name: "자동 채보 시작" })).toBeEnabled();
});

test("missing required AMT engine disables starting an audio Job", async ({ page }) => {
  await openNewScore(page, { coreReady: false, whisperxReady: true, youtubeReady: false });
  await expect(page.getByRole("button", { name: "자동 채보 시작" })).toBeDisabled();
  await expect(page.locator(".setup-needed")).toContainText("설정");
});

test("missing YouTube runtime blocks YouTube import even if AMT is available", async ({ page }) => {
  await openNewScore(page, { coreReady: true, whisperxReady: true, youtubeReady: false });
  await page.getByRole("tab", { name: "YouTube 링크" }).click();
  await page.route("**/api/sources/youtube/inspect", (route) => route.fulfill({
    json: { title: "Owned fixture", webpage_url: "https://www.youtube.com/watch?v=abcdef12345" },
  }));
  await page.locator(".youtube-inline-row input").fill("https://www.youtube.com/watch?v=abcdef12345");
  await page.getByRole("button", { name: "링크 확인" }).click();
  await expect(page.locator(".source-preview-row")).toContainText("Owned fixture");
  await page.locator(".rights-check input").check();
  await expect(page.getByRole("button", { name: "자동 채보 시작" })).toBeDisabled();
});
