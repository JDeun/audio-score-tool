import { expect, test } from "@playwright/test";

test("offline settings exposes original Apache license and project NOTICE", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("ast-onboarding-v1", "done");
    localStorage.setItem("ast-section", "settings");
  });
  // Legal notices are compiled into frontend assets, not fetched from the sidecar.
  await page.route("**/api/**", route => route.abort());
  await page.goto("/");

  const region = page.getByRole("region", { name: "라이선스 및 출처 표시" });
  await expect(region).toBeVisible();
  await region.getByText("프로젝트 출처 고지 (NOTICE)").click();
  await expect(region.getByText("Copyright 2026 JDeun and AudioScoreTool contributors")).toBeVisible();
  await expect(region.getByText("Project: https://github.com/JDeun/audio-score-tool")).toBeVisible();
  await region.getByText("Apache License 2.0 전문").click();
  await expect(region.getByText("Version 2.0, January 2004")).toBeVisible();
});
