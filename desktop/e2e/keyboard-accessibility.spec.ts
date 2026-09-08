import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => {
    localStorage.removeItem("ast-onboarding-v1");
    localStorage.removeItem("ast-section");
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
