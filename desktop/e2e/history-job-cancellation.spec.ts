import { expect, test } from "@playwright/test";

test("History can cancel an active imported Job even when no current Job card exists", async ({ page }) => {
  let jobStatus = "running";
  const cancelled: string[] = [];
  const job = () => ({
    job_id: "omr-background",
    kind: "omr",
    status: jobStatus,
    filename: "scan.pdf",
    stage: jobStatus === "running" ? "omr:recognizing" : "cancelling",
    progress: 40,
  });

  await page.route("**/api/health", route => route.fulfill({
    json: {
      status: "ok", packaged_runtime: false,
      device_plan: { muscriptor_device: "cpu" },
      preflight: { ok: true, missing: [], tools: {} },
      presets: { recommended: "quality", presets: [] },
      data_dir: "/tmp/ast",
      system: { hf_authenticated: false, jobs_bytes: 0, disk_free_bytes: 1000 },
    },
  }));
  await page.route("**/api/setup", route => route.fulfill({
    json: { preflight: { ok: true, missing: [], tools: {} },
      tool_paths: {}, instructions: { hf_note: "" } },
  }));
  await page.route("**/api/jobs?limit=100", route =>
    route.fulfill({ json: { jobs: [job()] } }));
  await page.route("**/api/jobs/omr-background/cancel", route => {
    cancelled.push(route.request().method());
    jobStatus = "cancelling";
    return route.fulfill({ status: 202, json: {
      job_id: "omr-background", status: "cancelling", cancelled: true,
    } });
  });
  await page.addInitScript(() => {
    localStorage.setItem("ast-onboarding-v1", "done");
    localStorage.setItem("ast-section", "history");
    localStorage.setItem("ast-setup-center-v2", "dismissed");
  });

  await page.goto("/");
  const row = page.locator(".premium-job-row").filter({ hasText: "scan.pdf" });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "작업 취소" }).click();
  await expect.poll(() => cancelled).toEqual(["POST"]);
  await expect(row).toContainText("취소 중");
  await expect(row.getByRole("button", { name: "작업 취소" })).toHaveCount(0);
  await expect(row.getByRole("button", { name: "삭제" })).toHaveCount(0);
});
