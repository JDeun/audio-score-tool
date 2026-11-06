import { expect, test } from "@playwright/test";

test("local-only auto identification is off by default and explicit opt-in persists", async ({ page }) => {
  let enabled = false;
  let saves = 0;
  await page.route("**/api/health", route => route.fulfill({
    json: {
      status: "ok",
      packaged_runtime: false,
      device_plan: { muscriptor_device: "cpu" },
      preflight: { ok: true, missing: [], tools: {} },
      presets: { recommended: "quality", presets: [] },
      system: { hf_authenticated: true, jobs_bytes: 0, disk_free_bytes: 1024 },
    },
  }));
  await page.route("**/api/setup", route => route.fulfill({
    json: { preflight: { ok: true, missing: [], tools: {} }, tool_paths: {}, instructions: { hf_note: "" } },
  }));
  await page.route("**/api/jobs?limit=100", route => route.fulfill({ json: { jobs: [] } }));
  await page.route("**/api/settings/local-identification", async route => {
    if (route.request().method() === "PUT") {
      enabled = Boolean((route.request().postDataJSON() as { enabled?: boolean }).enabled);
      saves += 1;
    }
    await route.fulfill({ json: {
      enabled, scope: "local_embedded_tags_only", external_requests: false,
    } });
  });
  await page.addInitScript(() => {
    localStorage.setItem("ast-onboarding-v1", "done");
    localStorage.setItem("ast-setup-center-v2", "dismissed");
    localStorage.setItem("ast-section", "settings");
  });
  await page.goto("/");

  const section = page.locator(".local-identification-card");
  await expect(section.getByRole("heading", { name: "새 음원 태그 자동 식별" })).toBeVisible();
  await expect(section.getByText(/외부 MusicBrainz·AcoustID 요청은 자동으로 보내지 않습니다/)).toBeVisible();
  const checkbox = section.getByRole("checkbox");
  await expect(checkbox).toBeEnabled();
  await expect(checkbox).not.toBeChecked();
  expect(saves).toBe(0);

  await checkbox.check();
  await expect.poll(() => saves).toBe(1);
  await expect(checkbox).toBeChecked();
  await page.reload();
  await expect(checkbox).toBeChecked();

  await checkbox.uncheck();
  await expect.poll(() => saves).toBe(2);
  await expect(checkbox).not.toBeChecked();
  await page.reload();
  await expect(checkbox).not.toBeChecked();
});
