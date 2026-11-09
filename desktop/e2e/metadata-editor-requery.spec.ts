import { expect, test } from "@playwright/test";

// A user can recover an unidentified score without leaving the editor:
// Unknown -> edit verified names -> atomic save -> exact-match API lookup.
test("Unknown score metadata can be saved in the manager and re-queried without losing manual credits", async ({ page }) => {
  let title = "Unknown";
  let artist = "Unknown";
  let revision = 1;
  let credits = {
    album: "Unknown", performer: "Unknown", release_date: "Unknown",
    composer: "Unknown", lyricist: "Unknown",
    arranger: "Original arranger", rights: "Original license notes",
  };
  const saved: Array<Record<string, unknown>> = [];
  const queries: Array<Record<string, unknown>> = [];

  const song = () => ({
    song_id: "unidentified", title, artist, source_kind: "youtube",
    revision, exports: { pdf: false, midi: false, musicxml: false },
    parts: [],
  });
  const scoreXml = () =>
    '<?xml version="1.0"?><score-partwise version="4.0"><part-list>' +
    '<score-part id="P1"><part-name>Voice</part-name></score-part></part-list>' +
    '<part id="P1"><measure number="1"><attributes><divisions>1</divisions>' +
    '</attributes><note><pitch><step>C</step><octave>4</octave></pitch>' +
    '<duration>1</duration><type>quarter</type></note></measure></part></score-partwise>';

  await page.route("**/api/health", (route) => route.fulfill({
    json: {
      status: "ok", device_plan: { muscriptor_device: "cpu" },
      preflight: { ok: true, missing: [], tools: {} },
      presets: { recommended: "quality", presets: [] },
      system: { hf_authenticated: false, jobs_bytes: 0, disk_free_bytes: 1000 },
    },
  }));
  await page.route("**/api/engines", (route) => route.fulfill({
    json: { usage_mode: "personal", engines: [], recommendation: null },
  }));
  await page.route("**/api/songs", (route) => route.fulfill({
    json: { songs: [song()] },
  }));
  await page.route("**/api/songs/unidentified", (route) => route.fulfill({
    json: song(),
  }));
  await page.route("**/api/songs/unidentified/notes", (route) => route.fulfill({
    json: { song: song(), parts: [], notes: [], chords: [] },
  }));
  await page.route("**/api/songs/unidentified/structure", (route) => route.fulfill({
    json: { measures: [] },
  }));
  await page.route("**/api/songs/unidentified/score", (route) => route.fulfill({
    contentType: "application/xml", body: scoreXml(),
  }));
  await page.route("**/api/songs/unidentified/publication", (route) => route.fulfill({
    json: { settings: credits },
  }));
  await page.route("**/api/songs/unidentified/credits", (route) => {
    const data = route.request().postDataJSON() as Record<string, unknown>;
    saved.push(data);
    title = String(data.title);
    artist = String(data.artist);
    credits = { ...credits, ...(data as typeof credits) };
    revision++;
    return route.fulfill({ json: { song: song(), settings: credits } });
  });
  await page.route("**/api/songs/unidentified/enrich", (route) => {
    const data = route.request().postDataJSON() as Record<string, unknown>;
    queries.push(data);
    credits = { ...credits, performer: "Green Day", composer: "Verified composer" };
    revision++;
    return route.fulfill({
      json: {
        metadata: {
          provider: "musicbrainz", error: null, applied: true,
          candidates: [{
            title: "American Idiot", artist: "Green Day", album: "Official album",
            composer: "Verified composer", score: 99,
          }],
          selected: {
            title: "American Idiot", artist: "Green Day", album: "Official album",
            composer: "Verified composer", score: 99,
          },
        },
        lyrics_source: "whisperx", lyrics: null,
        lyric_application: null,
      },
    });
  });
  await page.addInitScript(() => {
    localStorage.setItem("ast-onboarding-v1", "done");
    localStorage.setItem("ast-setup-center-v2", "dismissed");
    localStorage.setItem("ast-section", "songs");
  });
  await page.goto("/");
  await expect(page.locator(".score-toolbar h2")).toHaveText("Unknown");
  await expect(page.getByText("곡 정보 확인이 필요합니다.")).toBeVisible();
  await page.getByRole("button", { name: "메타데이터 관리·재조회" }).click();
  const dialog = page.getByRole("dialog", { name: "곡 정보 보강" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("곡명")).toHaveValue("Unknown");
  await expect(dialog.getByLabel("아티스트")).toHaveValue("Unknown");
  await expect(dialog.getByLabel("앨범명")).toHaveValue("Unknown");

  // Unknown is not sent to MusicBrainz as an identifying song title.
  await dialog.getByRole("button", { name: "곡 정보·가사 자동 조회" }).click();
  await expect(dialog.getByText(/정확한 곡 제목과 아티스트/)).toBeVisible();
  expect(queries).toHaveLength(0);

  await dialog.getByLabel("곡명").fill("American Idiot");
  await dialog.getByLabel("아티스트").fill("Green Day");
  await dialog.getByLabel("앨범명").fill("Personal edition");
  await dialog.getByRole("button", { name: "메타데이터 저장" }).click();
  await expect.poll(() => saved.length).toBe(1);
  expect(saved[0]).toMatchObject({
    title: "American Idiot",
    artist: "Green Day",
    album: "Personal edition",
    composer: "Unknown",
    expected_revision: 1,
  });
  expect(saved[0]).not.toHaveProperty("rights");
  expect(saved[0]).not.toHaveProperty("arranger");
  await expect(page.locator(".score-toolbar h2")).toHaveText("American Idiot");

  await dialog.getByRole("button", { name: "곡 정보·가사 자동 조회" }).click();
  await expect.poll(() => queries.length).toBe(1);
  expect(queries[0]).toMatchObject({
    title: "American Idiot",
    artist: "Green Day",
    require_exact_match: true,
    metadata_threshold: 92,
  });
  // The user-supplied album wins; API may fill remaining Unknown fields.
  await expect(dialog.getByLabel("앨범명")).toHaveValue("Personal edition");
  await expect(dialog.getByLabel("작곡가")).toHaveValue("Verified composer");
  await expect(dialog.getByLabel("가수·연주자")).toHaveValue("Green Day");
  expect(credits.arranger).toBe("Original arranger");
  expect(credits.rights).toBe("Original license notes");
});


test("unsaved edits are saved before external metadata re-query", async ({ page }) => {
  let title = "Unknown";
  let artist = "Unknown";
  let revision = 1;
  const calls: string[] = [];
  await page.route("**/api/health", (route) => route.fulfill({
    json: {
      status: "ok", device_plan: { muscriptor_device: "cpu" },
      preflight: { ok: true, missing: [], tools: {} },
      presets: { recommended: "quality", presets: [] },
      system: { hf_authenticated: false, jobs_bytes: 0, disk_free_bytes: 1000 },
    },
  }));
  const song = () => ({
    song_id: "track", title, artist, revision, source_kind: "local",
    exports: { pdf: false, midi: false, musicxml: false }, parts: [],
  });
  await page.route("**/api/songs", (route) => route.fulfill({ json: { songs: [song()] } }));
  await page.route("**/api/engines", (route) => route.fulfill({ json: { usage_mode: "personal", engines: [] } }));
  await page.route("**/api/songs/track", (route) => route.fulfill({ json: song() }));
  await page.route("**/api/songs/track/notes", (route) => route.fulfill({ json: { song: song(), parts: [], notes: [], chords: [] } }));
  await page.route("**/api/songs/track/structure", (route) => route.fulfill({ json: { measures: [] } }));
  await page.route("**/api/songs/track/score", (route) => route.fulfill({
    contentType: "application/xml",
    body: '<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Voice</part-name></score-part></part-list><part id="P1"><measure number="1"><note><rest/><duration>1</duration><type>quarter</type></note></measure></part></score-partwise>',
  }));
  await page.route("**/api/songs/track/publication", (route) => route.fulfill({ json: { settings: {} } }));
  await page.route("**/api/songs/track/credits", (route) => {
    calls.push("save");
    const data = route.request().postDataJSON() as Record<string, string>;
    title = data.title;
    artist = data.artist;
    revision++;
    return route.fulfill({ json: { song: song(), settings: {} } });
  });
  await page.route("**/api/songs/track/enrich", (route) => {
    calls.push("lookup");
    const params = route.request().postDataJSON() as Record<string, unknown>;
    expect(params).toMatchObject({ title: "A Song", artist: "A Band", require_exact_match: true });
    return route.fulfill({ json: {
      metadata: { candidates: [], selected: null, applied: false, error: null },
      lyrics: null, lyrics_source: "whisperx",
    } });
  });
  await page.addInitScript(() => {
    localStorage.setItem("ast-onboarding-v1", "done");
    localStorage.setItem("ast-setup-center-v2", "dismissed");
    localStorage.setItem("ast-section", "songs");
  });
  await page.goto("/");
  await expect(page.locator(".score-toolbar h2")).toHaveText("Unknown");
  await page.getByRole("button", { name: "메타데이터 관리·재조회" }).click();
  const dialog = page.getByRole("dialog", { name: "곡 정보 보강" });
  await dialog.getByLabel("곡명").fill("A Song");
  await dialog.getByLabel("아티스트").fill("A Band");
  await dialog.getByRole("button", { name: "곡 정보·가사 자동 조회" }).click();
  await expect.poll(() => calls.length).toBe(2);
  expect(calls).toEqual(["save", "lookup"]);
});
