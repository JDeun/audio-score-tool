import { expect, test } from "@playwright/test";

async function dismissOnboarding(page: import("@playwright/test").Page) {
  const skip = page.getByRole("button", { name: "건너뛰기" });
  if (await skip.isVisible().catch(() => false)) await skip.click();
}

function durationToMilliseconds(value: string) {
  const normalized = value.trim().toLowerCase();
  if (normalized.endsWith("ms")) return Number.parseFloat(normalized.slice(0, -2));
  if (normalized.endsWith("s")) return Number.parseFloat(normalized.slice(0, -1)) * 1000;
  return Number.NaN;
}

test("management shell does not overflow supported desktop viewports", async ({ page }) => {
  for (const viewport of [
    { width: 1366, height: 768 },
    { width: 1440, height: 900 },
    { width: 1920, height: 1080 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto("/");
    await dismissOnboarding(page);
    const dimensions = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      bodyFont: Number.parseFloat(getComputedStyle(document.body).fontSize),
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth + 1);
    expect(dimensions.bodyFont).toBeGreaterThanOrEqual(13);
  }
});

test("studio aesthetic keeps print paper invariant in dark mode", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/");
  await dismissOnboarding(page);
  await page.evaluate(() => {
    const stage = document.createElement("section");
    stage.className = "product-stage";
    stage.innerHTML = `
      <div class="song-shell">
        <div class="song-layout">
          <aside class="song-library"></aside>
          <main class="score-workbench">
            <div class="score-toolbar"></div>
            <div class="score-canvas"><svg width="200" height="300"></svg></div>
          </main>
          <aside class="score-inspector"></aside>
        </div>
      </div>`;
    document.body.appendChild(stage);
  });

  const styles = await page.locator(".score-canvas svg").evaluate((element) => {
    const computed = getComputedStyle(element);
    return { background: computed.backgroundColor, boxShadow: computed.boxShadow };
  });
  expect(styles.background).toBe("rgb(255, 254, 249)");
  expect(styles.boxShadow).not.toBe("none");
});

test("pressed micro-controls use restrained tactile depth rather than global neumorphism", async ({ page }) => {
  await page.goto("/");
  await dismissOnboarding(page);
  await page.evaluate(() => {
    const control = document.createElement("div");
    control.className = "studio-view-controls";
    control.innerHTML = '<button class="active" type="button">Page</button>';
    document.body.appendChild(control);
  });
  const button = page.locator(".studio-view-controls button.active");
  await expect(button).toBeVisible();
  const shadow = await button.evaluate((element) => getComputedStyle(element).boxShadow);
  expect(shadow).toContain("inset");
});

test("reduced-motion preference removes decorative workstation motion", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await dismissOnboarding(page);
  const duration = await page.locator("button").first().evaluate((element) => {
    const value = getComputedStyle(element).transitionDuration.split(",")[0] ?? "0s";
    return value.trim();
  });
  const milliseconds = durationToMilliseconds(duration);
  expect(Number.isFinite(milliseconds)).toBe(true);
  expect(milliseconds).toBeLessThanOrEqual(0.001);
});
