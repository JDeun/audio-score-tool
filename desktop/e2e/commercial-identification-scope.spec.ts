import { expect, test } from "@playwright/test";

const song = {
  song_id: "song-1",
  title: "Local tagged song",
  artist: "",
  source_kind: "transcription",
  revision: 1,
  exports: { pdf: false, midi: false, musicxml: false },
  parts: [],
};

test("commercial mode permits local source identification without unrelated provider grants", async ({ page }) => {
  const requests: Array<Record<string, unknown>> = [];
  await page.route("**/api/health", route => route.fulfill({
    json: {
      status: "ok",
      device_plan: { muscriptor_device: "cpu" },
      preflight: { ok: true, missing: [], tools: {} },
      presets: { recommended: "quality", presets: [] },
      system: { hf_authenticated: false, jobs_bytes: 0, disk_free_bytes: 1000 },
    },
  }));
  await page.route("**/api/songs", route => route.fulfill({
    json: { songs: [song] },
  }));
  await page.route("**/api/engines", route => route.fulfill({
    json: { usage_mode: "commercial", engines: [], recommendation: null },
  }));
  await page.route("**/api/songs/song-1", route => route.fulfill({
    json: song,
  }));
  await page.route("**/api/songs/song-1/notes", route => route.fulfill({
    json: { song, parts: [], notes: [], chords: [] },
  }));
  await page.route("**/api/songs/song-1/structure", route => route.fulfill({
    json: { measures: [] },
  }));
  await page.route("**/api/songs/song-1/score", route => route.fulfill({
    contentType: "application/xml",
    body: '<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list><part id="P1"><measure number="1"><note><rest/><duration>1</duration><type>quarter</type></note></measure></part></score-partwise>',
  }));
  await page.route("**/api/songs/song-1/publication", route => route.fulfill({
    json: { settings: {} },
  }));
  await page.route("**/api/songs/song-1/identify-source", route => {
    requests.push(route.request().postDataJSON() as Record<string, unknown>);
    return route.fulfill({
      json: {
        status: "identified",
        selected: { title: "Local tagged song", artist: "Local artist" },
        selected_confidence: 1.0,
        applied: false,
      },
    });
  });
  await page.addInitScript(() => {
    localStorage.setItem("ast-onboarding-v1", "done");
    localStorage.setItem("ast-setup-center-v2", "dismissed");
    localStorage.setItem("ast-section", "songs");
  });
  await page.goto("/");
  await expect(page.locator(".score-toolbar h2")).toHaveText("Local tagged song");

  await page.getByRole("button", { name: "곡 정보", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "곡 정보 보강" });
  await expect(dialog).toBeVisible();
  const trigger = dialog.getByRole("button", { name: "원본 음원 자동 식별" });
  const checks = dialog.locator(".enrichment-commercial-check input");
  await expect(checks).toHaveCount(2);
  await expect(checks.nth(0)).not.toBeChecked();
  await expect(checks.nth(1)).not.toBeChecked();
  await expect(trigger).toBeEnabled();
  await expect(dialog.getByText(/로컬 음원 태그 식별은 외부 서비스 권한 없이/)).toBeVisible();
  await expect(dialog.getByRole("button", { name: "제목·아티스트로 외부 데이터 확인" })).toBeDisabled();
  expect(requests).toHaveLength(0);

  await trigger.click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toMatchObject({
    refresh: true,
    apply_high_confidence_metadata: true,
    musicbrainz_commercial_entitlement: false,
    acoustid_commercial_entitlement: false,
  });
  await expect(trigger).toBeEnabled();

  await checks.nth(0).check();
  await trigger.click();
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1]).toMatchObject({
    musicbrainz_commercial_entitlement: true,
    acoustid_commercial_entitlement: false,
  });

  await checks.nth(0).uncheck();
  await checks.nth(1).check();
  await trigger.click();
  await expect.poll(() => requests.length).toBe(3);
  expect(requests[2]).toMatchObject({
    musicbrainz_commercial_entitlement: false,
    acoustid_commercial_entitlement: true,
  });

  await checks.nth(0).check();
  await trigger.click();
  await expect.poll(() => requests.length).toBe(4);
  expect(requests[3]).toMatchObject({
    musicbrainz_commercial_entitlement: true,
    acoustid_commercial_entitlement: true,
  });
});
