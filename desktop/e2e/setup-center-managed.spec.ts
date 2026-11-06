import { expect, test, type Page } from "@playwright/test";

type Component = {
  key: string;
  label: string;
  ready: boolean;
  tier: "core" | "optional";
  delivery: "embedded" | "managed-component";
  role: string;
  required_for: string[];
  auto_install: boolean;
  managed_status?: { ready: boolean; integrity: string };
  catalog?: { published: boolean; target: string; version: string; publication_reason?: string | null };
};

function fixture(published: boolean, reason = "artifact-not-published") {
  const component: Component = {
    key: "audiveris",
    label: "OMR 엔진",
    ready: false,
    tier: "optional",
    delivery: "managed-component",
    role: "MusicXML 변환",
    required_for: ["omr"],
    auto_install: published,
    managed_status: { ready: false, integrity: "not-installed" },
    catalog: { published, target: "linux-x86_64", version: "1.0.0", publication_reason: published ? null : reason },
  };
  const status = {
    platform: "linux",
    core_ready: true,
    recommended_ready: true,
    components: [
      {
        key: "desktop_runtime",
        label: "앱 내장 런타임",
        ready: true,
        tier: "core" as const,
        delivery: "embedded" as const,
        role: "MusicXML",
        required_for: ["musicxml"],
        auto_install: false,
      },
      component,
    ],
    profiles: { core: "MusicXML 편집", optional: "OMR" },
    policy: {},
  };
  return { status, component };
}

async function openSetup(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("ast-onboarding-v1", "done");
    window.localStorage.setItem("ast-setup-center-v2", "dismissed");
  });
  await page.goto("/");
  await page.getByRole("button", { name: "구성요소 상태" }).click();
  return page.getByRole("dialog", { name: "구성요소 상태" });
}

test("published managed artifact: install, verify and remove through authenticated API", async ({ page }) => {
  const { status, component } = fixture(true);
  await page.route("**/api/setup/center", async (route) => {
    await route.fulfill({ json: status });
  });
  const requests: string[] = [];
  await page.route("**/api/setup/install", async (route) => {
    requests.push(route.request().postData() || "");
    component.ready = true;
    component.managed_status = { ready: true, integrity: "verified" };
    await route.fulfill({ json: {
      installed: { ready: true, integrity: "verified" },
      setup: status,
    } });
  });
  await page.route("**/api/setup/remove", async (route) => {
    requests.push(route.request().postData() || "");
    component.ready = false;
    component.managed_status = { ready: false, integrity: "not-installed" };
    await route.fulfill({ json: {
      removed: { component: "audiveris", removed: true, cleanup_pending: false },
      setup: status,
    } });
  });

  const dialog = await openSetup(page);
  await expect(dialog.getByRole("button", { name: "앱에서 설치" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "구성요소 삭제" })).toHaveCount(0);
  await dialog.getByRole("button", { name: "앱에서 설치" }).click();
  await expect(dialog.getByRole("status")).toContainText("설치 파일이 검증됐습니다");
  await expect(dialog.getByRole("button", { name: "구성요소 삭제" })).toBeVisible();
  await dialog.getByRole("button", { name: "구성요소 삭제" }).click();
  await expect(dialog.getByRole("status")).toContainText("삭제됐습니다");
  expect(requests.map((r) => JSON.parse(r))).toEqual([
    { component: "audiveris" },
    { component: "audiveris" },
  ]);
});

test("unpublished artifact cannot install; recovery is a separate explicit action", async ({ page }) => {
  const { status } = fixture(false);
  await page.route("**/api/setup/center", async (route) => {
    await route.fulfill({ json: status });
  });
  let recoverCalls = 0;
  await page.route("**/api/setup/recover", async (route) => {
    recoverCalls += 1;
    await route.fulfill({ json: {
      recovery: { removed_component_staging: 2 },
      setup: status,
    } });
  });

  const dialog = await openSetup(page);
  await expect(dialog.getByText("이 플랫폼용 배포 파일 미게시")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "앱에서 설치" })).toHaveCount(0);
  await dialog.getByRole("button", { name: "중단된 설치 복구" }).click();
  await expect(dialog.getByRole("status")).toContainText("2개를 정리했습니다");
  expect(recoverCalls).toBe(1);
});

test("pending redistribution approval never offers install and explains why", async ({ page }) => {
  const { status } = fixture(false, "redistribution-not-approved");
  await page.route("**/api/setup/center", route => route.fulfill({ json: status }));
  let attemptedInstalls = 0;
  await page.route("**/api/setup/install", route => {
    attemptedInstalls += 1;
    return route.fulfill({ status: 409, json: { detail: "not approved" } });
  });

  const dialog = await openSetup(page);
  await expect(dialog.getByText("재배포 승인 대기")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "앱에서 설치" })).toHaveCount(0);
  expect(attemptedInstalls).toBe(0);
});

test("incomplete tool mappings are not advertised as installable", async ({ page }) => {
  const { status } = fixture(false, "required-tools-missing:deno,ffprobe");
  await page.route("**/api/setup/center", route => route.fulfill({ json: status }));
  const dialog = await openSetup(page);
  await expect(dialog.getByText("필수 실행 도구 구성 누락")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "앱에서 설치" })).toHaveCount(0);
});
