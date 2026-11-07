import { expect, test, type Page } from "@playwright/test";

async function exerciseCancelledImport(
  page: Page,
  { filename, endpoint }: { filename: string; endpoint: string },
) {
  let status: "queued" | "cancelling" | "cancelled" = "queued";
  let cancelCalls = 0;
  const submissions: string[] = [];

  await page.route("**/api/health", route => route.fulfill({
    json: {
      status: "ok", packaged_runtime: false,
      device_plan: { muscriptor_device: "cpu" },
      preflight: { ok: true, missing: [], tools: {} },
      presets: { recommended: "quality", presets: [] },
      data_dir: "/tmp/ast", system: { hf_authenticated: false, jobs_bytes: 0, disk_free_bytes: 1024 },
    },
  }));
  await page.route("**/api/setup", route => route.fulfill({
    json: { preflight: { ok: true, missing: [], tools: {} }, tool_paths: {},
      instructions: { hf_note: "" } },
  }));
  await page.route("**/api/jobs?limit=100", route => route.fulfill({ json: { jobs: [] } }));
  await page.route(`**${endpoint}`, route => {
    submissions.push(route.request().method());
    return route.fulfill({ status: 202, json: { job_id: "job-cancel", status: "queued" } });
  });
  await page.route("**/api/jobs/job-cancel/cancel", route => {
    cancelCalls++;
    status = "cancelling";
    return route.fulfill({ status: 202, json: {
      job_id: "job-cancel", status: "cancelling", cancelled: true,
    } });
  });
  await page.route("**/api/jobs/job-cancel", route => {
    if (status === "cancelling") status = "cancelled";
    return route.fulfill({ json: { job_id: "job-cancel", status, progress: 25 } });
  });
  await page.addInitScript(() => {
    localStorage.setItem("ast-onboarding-v1", "done");
    localStorage.setItem("ast-section", "new");
    localStorage.setItem("ast-setup-center-v2", "dismissed");
  });
  await page.goto("/");
  await page.getByRole("tab", { name: "기존 악보 / MusicXML / MIDI" }).click();
  const modal = page.getByRole("dialog", { name: "기존 악보 가져오기" });
  await modal.locator('input[type="file"]').setInputFiles({
    name: filename, mimeType: "application/octet-stream",
    buffer: Buffer.from(filename.endsWith(".pdf") ? "%PDF-1.4" : "<score-partwise/>"),
  });
  await modal.getByRole("button", { name: "악보 가져오기", exact: true }).click();
  await expect.poll(() => submissions).toEqual(["POST"]);
  await expect(modal.getByRole("button", { name: "가져오기 취소" })).toBeVisible();
  await expect(modal.getByRole("button", { name: "닫기" })).toBeDisabled();
  await modal.getByRole("button", { name: "가져오기 취소" }).click();
  await expect.poll(() => cancelCalls).toBe(1);
  await expect(modal.getByText(/취소되었습니다/)).toBeVisible();
  await expect(modal.getByRole("button", { name: "다시 가져오기" })).toBeEnabled();
  await expect(modal.getByRole("button", { name: "곡 라이브러리에서 검토" })).toHaveCount(0);
  await modal.getByRole("button", { name: "닫기" }).click();
  await expect(modal).toHaveCount(0);
}

test("direct MusicXML import can be cancelled without opening a nonexistent Song", async ({ page }) => {
  await exerciseCancelledImport(page, {
    filename: "score.musicxml", endpoint: "/api/import/notation",
  });
});

test("OMR PDF import exposes the same cancellation and terminal controls", async ({ page }) => {
  await exerciseCancelledImport(page, {
    filename: "score.pdf", endpoint: "/api/import/score",
  });
});
