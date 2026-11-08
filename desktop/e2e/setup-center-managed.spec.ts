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
  managed_status?: {
    ready: boolean;
    integrity: string;
    version?: string;
    rollback?: { available: boolean; version?: string; integrity?: string; reason?: string };
  };
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


test("interrupted same-version install reports verified backup recovery", async ({ page }) => {
  const { status } = fixture(false);
  await page.route("**/api/setup/center", route => route.fulfill({ json: status }));
  await page.route("**/api/setup/recover", route => route.fulfill({
    json: {
      recovery: {
        removed_component_staging: 1,
        restored_component_removal: 0,
        restored_previous_install: 1,
        removed_previous_install_backup: 2,
        pending_previous_install_backup: 0,
      },
      setup: status,
    },
  }));

  const dialog = await openSetup(page);
  await dialog.getByRole("button", { name: "중단된 설치 복구" }).click();
  const feedback = dialog.getByRole("status");
  await expect(feedback).toContainText("임시 설치 파일 1개");
  await expect(feedback).toContainText("이전 정상 버전으로 복구했습니다");
  await expect(feedback).toContainText("이전 설치 백업 2개");
});

test("unverifiable managed backup is preserved and warned, not called success", async ({ page }) => {
  const { status } = fixture(false);
  await page.route("**/api/setup/center", route => route.fulfill({ json: status }));
  await page.route("**/api/setup/recover", route => route.fulfill({
    json: {
      recovery: {
        removed_component_staging: 0,
        restored_previous_install: 0,
        removed_previous_install_backup: 0,
        pending_previous_install_backup: 1,
      },
      setup: status,
    },
  }));
  const dialog = await openSetup(page);
  await dialog.getByRole("button", { name: "중단된 설치 복구" }).click();
  const warning = dialog.getByRole("alert");
  await expect(warning).toContainText("검증할 수 없는 이전 설치 백업 1개");
  await expect(warning).toContainText("자동 재설치를 중단");
});


test("verified previous version is rollbackable even when a newer catalog is unpublished", async ({ page }) => {
  const { status, component } = fixture(false);
  component.managed_status = {
    ready: false,
    integrity: "tool-digest-mismatch",
    version: "2",
    rollback: { available: true, version: "1", integrity: "verified" },
  };
  await page.route("**/api/setup/center", route => route.fulfill({ json: status }));
  const calls: string[] = [];
  await page.route("**/api/setup/rollback", route => {
    calls.push(route.request().postData() || "");
    component.ready = true;
    component.managed_status = {
      ready: true,
      integrity: "verified",
      version: "1",
      rollback: { available: false, reason: "no-previous-version" },
    };
    return route.fulfill({
      json: {
        rolled_back: { ready: true, integrity: "verified", version: "1" },
        setup: status,
      },
    });
  });

  const dialog = await openSetup(page);
  await expect(dialog.getByRole("button", { name: "앱에서 설치" })).toHaveCount(0);
  await expect(dialog.getByText("실행 파일 무결성 불일치 · 복구 필요")).toBeVisible();
  const rollbackButton = dialog.getByRole("button", { name: "이전 버전 (1)으로 복원" });
  await expect(rollbackButton).toBeVisible();
  await rollbackButton.click();
  await expect(dialog.getByRole("status")).toContainText("검증된 이전 버전 1으로 되돌렸습니다");
  await expect(dialog.getByRole("button", { name: "이전 버전 (1)으로 복원" })).toHaveCount(0);
  expect(calls.map(call => JSON.parse(call))).toEqual([{ component: "audiveris" }]);
});

test("unverified previous generation never exposes rollback, even if old bytes remain", async ({ page }) => {
  const { status, component } = fixture(true);
  component.managed_status = {
    ready: false, integrity: "tool-digest-mismatch",
    rollback: { available: false, reason: "previous-version-unverified" },
  };
  await page.route("**/api/setup/center", route => route.fulfill({ json: status }));
  let rollbackCalls = 0;
  await page.route("**/api/setup/rollback", route => {
    rollbackCalls += 1;
    return route.fulfill({ status: 409, json: { detail: "previous version corrupt" } });
  });
  const dialog = await openSetup(page);
  await expect(dialog.getByRole("button", { name: /이전 버전.*복원/ })).toHaveCount(0);
  expect(rollbackCalls).toBe(0);
});

test("rollback 409 failure remains an error, does not claim a restored runtime", async ({ page }) => {
  const { status, component } = fixture(false);
  component.managed_status = {
    ready: false, integrity: "tool-digest-mismatch",
    rollback: { available: true, version: "1", integrity: "verified" },
  };
  await page.route("**/api/setup/center", route => route.fulfill({ json: status }));
  await page.route("**/api/setup/rollback", route => route.fulfill({
    status: 409,
    json: { detail: "Previous managed runtime is missing or not verified" },
  }));
  const dialog = await openSetup(page);
  await dialog.getByRole("button", { name: "이전 버전 (1)으로 복원" }).click();
  await expect(dialog.getByRole("alert")).toContainText("not verified");
  await expect(dialog.getByRole("status")).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: "이전 버전 (1)으로 복원" })).toBeVisible();
});


test("nested Java or model resource corruption displays an integrity failure", async ({ page }) => {
  const { status, component } = fixture(false);
  component.managed_status = {
    ready: false, integrity: "payload-digest-mismatch",
    rollback: { available: false, reason: "previous-version-unverified" },
  };
  await page.route("**/api/setup/center", route => route.fulfill({ json: status }));
  const dialog = await openSetup(page);
  await expect(dialog.getByText("내장 JRE·모델·리소스 무결성 실패 · 재설치 또는 복원 필요")).toBeVisible();
  await expect(dialog.getByRole("button", { name: /이전 버전.*복원/ })).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: "앱에서 설치" })).toHaveCount(0);
});

test("legacy managed status is not marked ready without a full payload manifest", async ({ page }) => {
  const { status, component } = fixture(true);
  component.managed_status = {
    ready: false, integrity: "payload-manifest-missing",
    rollback: { available: false, reason: "no-previous-version" },
  };
  await page.route("**/api/setup/center", route => route.fulfill({ json: status }));
  const dialog = await openSetup(page);
  await expect(dialog.getByText("전체 런타임 검증 정보 없음 · 재설치 필요")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "앱에서 설치" })).toBeVisible();
});
