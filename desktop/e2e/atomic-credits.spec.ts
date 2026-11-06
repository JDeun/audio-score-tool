import { expect, test } from "@playwright/test";

const scoreXml = `<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <work><work-title>Original</work-title></work>
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1"><measure number="1">
    <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
    <note><rest/><duration>4</duration><type>whole</type></note>
  </measure></part>
</score-partwise>`;

test("first-page credits submit one atomic mutation, not two independent PATCH calls", async ({ page }) => {
  let revision = 1;
  let title = "Original";
  let artist = "";
  let composer = "Original composer";
  let legacyPatches = 0;
  const creditsRequests: Record<string, unknown>[] = [];

  const song = () => ({
    song_id: "song-1",
    title,
    artist,
    source_kind: "notation",
    revision,
    exports: { pdf: false, midi: false, musicxml: false },
    parts: [],
  });

  await page.route("**/api/health", route => route.fulfill({
    json: {
      status: "ok", device_plan: { muscriptor_device: "cpu" },
      preflight: { ok: true, missing: [], tools: {} },
      presets: { recommended: "quality", presets: [] },
      system: { hf_authenticated: false, jobs_bytes: 0, disk_free_bytes: 1000 },
    },
  }));
  await page.route("**/api/songs", route => route.fulfill({
    json: { songs: [song()] },
  }));
  await page.route("**/api/songs/song-1", route => {
    if (route.request().method() === "PATCH") legacyPatches += 1;
    return route.fulfill({ json: song() });
  });
  await page.route("**/api/songs/song-1/notes", route => route.fulfill({
    json: { song: song(), parts: [], notes: [], chords: [] },
  }));
  await page.route("**/api/songs/song-1/structure", route => route.fulfill({
    json: { measures: [] },
  }));
  await page.route("**/api/songs/song-1/score", route => route.fulfill({
    contentType: "application/xml",
    body: scoreXml,
  }));
  await page.route("**/api/songs/song-1/publication", route => {
    if (route.request().method() === "PATCH") legacyPatches += 1;
    return route.fulfill({ json: { settings: { composer } } });
  });
  await page.route("**/api/songs/song-1/credits", async route => {
    const data = route.request().postDataJSON() as Record<string, unknown>;
    creditsRequests.push(data);
    title = String(data.title);
    artist = String(data.artist);
    composer = String(data.composer);
    revision += 1;
    await route.fulfill({
      json: { song: song(), settings: { composer } },
    });
  });

  await page.addInitScript(() => {
    localStorage.setItem("ast-onboarding-v1", "done");
    localStorage.setItem("ast-section", "songs");
    localStorage.setItem("ast-setup-center-v2", "dismissed");
  });
  await page.goto("/");
  await expect(page.locator(".score-toolbar h2")).toHaveText("Original");
  await page.getByRole("button", { name: "제목·정보" }).click();

  const editor = page.locator(".credits-editor");
  await editor.locator("label").filter({ hasText: "곡 제목" }).locator("input").fill("Published song");
  await editor.locator("label").filter({ hasText: "작곡" }).locator("input").fill("New composer");
  await editor.getByRole("button", { name: "제목 영역 적용" }).click();

  await expect.poll(() => creditsRequests.length).toBe(1);
  expect(creditsRequests[0]).toMatchObject({
    title: "Published song",
    expected_revision: 1,
    composer: "New composer",
  });
  expect(legacyPatches).toBe(0);
  await expect(page.locator(".score-toolbar h2")).toHaveText("Published song");
});
