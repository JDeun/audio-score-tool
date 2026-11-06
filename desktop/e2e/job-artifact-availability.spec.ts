import { expect, test } from "@playwright/test";

test("Job history only exposes server-confirmed artifact links for each source kind", async ({ page }) => {
  const jobs = [
    {
      job_id: "notation-only",
      filename: "score.musicxml",
      kind: "notation-import",
      status: "done",
      progress: 100,
      available_artifacts: ["musicxml"],
    },
    {
      job_id: "audio-without-pdf",
      filename: "recording.wav",
      kind: "transcription",
      status: "done",
      progress: 100,
      available_artifacts: ["musicxml", "midi"],
    },
    {
      job_id: "benchmark-partial",
      filename: "benchmark.wav",
      kind: "benchmark",
      status: "done",
      progress: 100,
      available_artifacts: ["benchmark_json"],
    },
  ];

  await page.route("**/api/health", async (route) => route.fulfill({
    json: {
      status: "ok",
      device_plan: { muscriptor_device: "cpu" },
      preflight: { ok: true, missing: [], tools: {} },
      presets: { recommended: "quality", presets: [] },
      data_dir: "/tmp/audio-score-tool",
      system: { hf_authenticated: false, jobs_bytes: 0, disk_free_bytes: 1000 },
    },
  }));
  await page.route("**/api/setup", async (route) => route.fulfill({
    json: { preflight: { ok: true, missing: [], tools: {} }, tool_paths: {}, instructions: { hf_note: "" } },
  }));
  await page.route("**/api/jobs?limit=100", async (route) => route.fulfill({ json: { jobs } }));
  await page.addInitScript(() => {
    localStorage.setItem("ast-onboarding-v1", "done");
    localStorage.setItem("ast-section", "history");
    localStorage.setItem("ast-setup-center-v2", "dismissed");
  });
  await page.goto("/");

  const notation = page.locator(".premium-job-row").filter({ hasText: "score.musicxml" });
  await expect(notation.getByRole("link", { name: "MusicXML" })).toBeVisible();
  await expect(notation.getByRole("link", { name: "PDF" })).toHaveCount(0);
  await expect(notation.getByRole("link", { name: "MIDI" })).toHaveCount(0);

  const audio = page.locator(".premium-job-row").filter({ hasText: "recording.wav" });
  await expect(audio.getByRole("link", { name: "MusicXML" })).toBeVisible();
  await expect(audio.getByRole("link", { name: "MIDI" })).toBeVisible();
  await expect(audio.getByRole("link", { name: "PDF" })).toHaveCount(0);

  const benchmark = page.locator(".premium-job-row").filter({ hasText: "benchmark.wav" });
  await expect(benchmark.getByRole("link", { name: "JSON 결과" })).toBeVisible();
  await expect(benchmark.getByRole("link", { name: "CSV 결과" })).toHaveCount(0);
});
