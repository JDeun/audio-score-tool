import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => {
    localStorage.removeItem("ast-onboarding-v1");
    localStorage.removeItem("ast-section");
    localStorage.removeItem("ast-studio-library");
    localStorage.removeItem("ast-studio-inspector");
    localStorage.removeItem("ast-studio-focus");
    localStorage.removeItem("ast-studio-view");
  });
  await page.reload();
});

test("onboarding traps keyboard focus, blocks global shortcuts, and closes with Escape", async ({ page }) => {
  const dialog = page.getByRole("dialog", { name: /입력 소스를 출판 가능한 악보 프로젝트로/ });
  await expect(dialog).toBeVisible();

  const skip = dialog.getByRole("button", { name: "건너뛰기" });
  const next = dialog.getByRole("button", { name: "다음" });
  await expect(skip).toBeFocused();

  await page.keyboard.press("Shift+Tab");
  await expect(next).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(skip).toBeFocused();

  await page.keyboard.press("s");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("새 악보");

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("새 악보");
});

test("generic modal restores opener focus and Escape activates its safe dismiss control", async ({ page }) => {
  await page.getByRole("button", { name: "건너뛰기" }).click();

  await page.evaluate(() => {
    const opener = document.createElement("button");
    opener.id = "e2e-modal-opener";
    opener.textContent = "Open test modal";
    document.body.appendChild(opener);
    opener.focus();

    const dialog = document.createElement("section");
    dialog.id = "e2e-modal";
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-label", "Test modal");

    const dismiss = document.createElement("button");
    dismiss.dataset.dialogDismiss = "true";
    dismiss.textContent = "Cancel";
    dismiss.addEventListener("click", () => dialog.remove());

    const destructive = document.createElement("button");
    destructive.textContent = "Delete";

    dialog.append(dismiss, destructive);
    document.body.appendChild(dialog);
  });

  const dialog = page.getByRole("dialog", { name: "Test modal" });
  const cancel = dialog.getByRole("button", { name: "Cancel" });
  const destructive = dialog.getByRole("button", { name: "Delete" });
  await expect(cancel).toBeFocused();

  await page.keyboard.press("Shift+Tab");
  await expect(destructive).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(cancel).toBeFocused();

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(page.locator("#e2e-modal-opener")).toBeFocused();
});

test("studio view controls expose persistent panel, page, and focus states", async ({ page }) => {
  await page.getByRole("button", { name: "건너뛰기" }).click();

  await page.evaluate(() => {
    const layout = document.createElement("section");
    layout.className = "song-layout";
    document.getElementById("root")?.appendChild(layout);
  });

  const toolbar = page.getByRole("toolbar", { name: "Studio 보기 설정" });
  await expect(toolbar).toBeVisible();

  const library = toolbar.getByRole("button", { name: "Library" });
  const inspector = toolbar.getByRole("button", { name: "Inspector" });
  const pageMode = toolbar.getByRole("button", { name: "Page" });
  const continuous = toolbar.getByRole("button", { name: "Continuous" });
  const focus = toolbar.getByRole("button", { name: "Focus" });

  await expect(library).toHaveAttribute("aria-pressed", "true");
  await expect(inspector).toHaveAttribute("aria-pressed", "true");
  await expect(pageMode).toHaveAttribute("aria-pressed", "true");

  await library.click();
  await expect(page.locator("html")).toHaveClass(/ast-library-hidden/);
  await expect(library).toHaveAttribute("aria-pressed", "false");

  await inspector.click();
  await expect(page.locator("html")).toHaveClass(/ast-inspector-hidden/);
  await expect(inspector).toHaveAttribute("aria-pressed", "false");

  await continuous.click();
  await expect(page.locator("html")).toHaveClass(/ast-score-continuous/);
  await expect(continuous).toHaveAttribute("aria-pressed", "true");
  await expect(pageMode).toHaveAttribute("aria-pressed", "false");

  await focus.click();
  await expect(page.locator("html")).toHaveClass(/ast-studio-focus/);
  await expect(focus).toHaveAttribute("aria-pressed", "true");
});
