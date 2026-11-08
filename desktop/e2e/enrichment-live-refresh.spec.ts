import { expect, test } from "@playwright/test";

// The metadata/lyrics dialog lives outside SongWorkspace. Committing through
// its own endpoint must invalidate the canonical score editor and song list.
test("successful external enrichment refreshes the selected song without a manual reload", async ({ page }) => {
  let title = "Original song";
  let revision = 1;
  let noteReads = 0;
  const song = () => ({
    song_id: "song-live", title, artist: "Original artist", source_kind: "local",
    revision, updated_at: "2026-11-09T00:00:00Z",
    exports: { pdf: false, midi: false, musicxml: false }, parts: [],
  });

  await page.route("**/api/health", (route) => route.fulfill({
    json: {
      status: "ok", device_plan: { muscriptor_device: "cpu" },
      preflight: { ok: true, missing: [], tools: {} },
      presets: { recommended: "quality", presets: [] },
      system: { hf_authenticated: false, jobs_bytes: 0, disk_free_bytes: 1000 },
    },
  }));
  await page.route("**/api/songs", (route) => route.fulfill({ json: { songs: [song()] } }));
  await page.route("**/api/engines", (route) => route.fulfill({
    json: { usage_mode: "personal", engines: [], recommendation: null },
  }));
  await page.route("**/api/songs/song-live/identify-source", (route) => {
    title = "Identified song";
    revision += 1;
    return route.fulfill({
      json: { selected: { title, artist: "Original artist" }, applied: true, selected_confidence: 0.99 },
    });
  });
  await page.route("**/api/songs/song-live/enrich", (route) => {
    title = "Enriched song";
    revision += 1;
    return route.fulfill({
      json: {
        metadata: {
          candidates: [{ title, artist: "Original artist", score: 98 }],
          selected: { title, artist: "Original artist", score: 98 },
          applied: true, error: null,
        },
        lyric_application: { applied: true, attached_tokens: 2 },
      },
    });
  });
  await page.route(/\\/api\\/songs\\/song-live(?:\\/(?:notes|structure|score|publication))?$/, (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/notes")) {
      noteReads += 1;
      return route.fulfill({ json: { song: song(), parts: [], notes: [], chords: [] } });
    }
    if (path.endsWith("/structure")) return route.fulfill({ json: { measures: [] } });
    if (path.endsWith("/publication")) return route.fulfill({ json: { settings: {} } });
    if (path.endsWith("/score")) {
      return route.fulfill({
        contentType: "application/xml",
        body: '<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list><part id="P1"><measure number="1"><note><rest/><duration>1</duration><type>quarter</type></note></measure></part></score-partwise>',
      });
    }
    return route.fulfill({ json: song() });
  });

  await page.addInitScript(() => {
    localStorage.setItem("ast-onboarding-v1", "done");
    localStorage.setItem("ast-setup-center-v2", "dismissed");
    localStorage.setItem("ast-section", "songs");
  });
  await page.goto("/");
  await expect(page.locator(".score-toolbar h2")).toHaveText("Original song");

  await page.getByRole("button", { name: "곡 정보", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "곡 정보 보강" });
  await dialog.getByRole("button", { name: "원본 음원 자동 식별" }).click();
  await expect(page.locator(".score-toolbar h2")).toHaveText("Identified song");
  await expect(page.locator(".song-item").first()).toContainText("Identified song");

  const readsAfterIdentify = noteReads;
  await dialog.getByRole("button", { name: "제목·아티스트로 외부 데이터 확인" }).click();
  await expect(page.locator(".score-toolbar h2")).toHaveText("Enriched song");
  await expect(page.locator(".song-item").first()).toContainText("Enriched song");
  expect(noteReads).toBeGreaterThan(readsAfterIdentify);
});
