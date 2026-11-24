import { expect, test } from "@playwright/test";
import { scoreSha256, scoreSnapshot } from "./score-fixture";

const scoreXml = `<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <work><work-title>Demo</work-title></work>
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1"><measure number="1">
    <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></attributes>
    <note><pitch><step>C</step><octave>4</octave></pitch>
      <duration>1</duration><type>quarter</type></note>
  </measure></part>
</score-partwise>`;

test("note editor avoids no-op requests and sends only actual pitch/lyric changes", async ({ page }) => {
  let revision = 1;
  let generation = 1;
  let note = {
    note_id: "p0-m0-n0", part_id: "P1", part_name: "Piano",
    measure: "1", measure_index: 0, rest: false,
    step: "C", alter: 0, octave: 4, type: "quarter", dots: 0,
    lyric: "", ties: [], slurs: [], articulations: [], beam: "",
  };
  const requests: Record<string, unknown>[] = [];
  const currentXml = () => scoreXml
    .replace("<step>C</step>", `<step>${note.step}</step>`)
    .replace("</type></note>", `</type>${note.lyric ? `<lyric><text>${note.lyric}</text></lyric>` : ""}</note>`);
  const currentSha = () => scoreSha256(currentXml());
  const song = () => ({
    song_id: "song-1", title: "Demo", artist: "",
    source_kind: "notation", revision,
    exports: { pdf: false, midi: false, musicxml: false }, parts: [],
  });

  await page.route("**/api/health", route => route.fulfill({
    json: {
      status: "ok", device_plan: { muscriptor_device: "cpu" },
      preflight: { ok: true, missing: [], tools: {} },
      presets: { recommended: "quality", presets: [] },
      system: { hf_authenticated: false, jobs_bytes: 0, disk_free_bytes: 1000 },
    },
  }));
  await page.route("**/api/songs", route => route.fulfill({ json: { songs: [song()] } }));
  await page.route("**/api/songs/song-1", route => route.fulfill({ json: song() }));
  await page.route("**/api/songs/song-1/notes", route => route.fulfill({
    json: {
      song: song(),
      score_sha256: currentSha(), evidence_generation: generation,
      parts: [{ part_id: "P1", name: "Piano", notes: 1, measures: 1 }],
      notes: [note], chords: [],
    },
  }));
  await page.route("**/api/songs/song-1/structure", route => route.fulfill({
    json: { ...scoreSnapshot(song(), currentXml()), measures: [] },
  }));
  await page.route("**/api/songs/song-1/score", route => route.fulfill({
    contentType: "application/xml", body: currentXml(),
  }));
  await page.route("**/api/songs/song-1/publication", route => route.fulfill({
    json: { settings: {} },
  }));
  await page.route("**/api/songs/song-1/notes/p0-m0-n0/structure", async route => {
    const patch = route.request().postDataJSON() as Record<string, unknown>;
    const changes = requests.length === 0 ? { lyric: "hello" } : { step: "D", lyric: "world" };
    expect(patch).toEqual({ ...changes, expected_revision: revision,
      expected_score_sha256: currentSha(), expected_generation: generation });
    const { expected_revision, expected_score_sha256, expected_generation, ...noteChanges } = patch;
    expect([expected_revision, expected_score_sha256, expected_generation]).toEqual([revision, currentSha(), generation]);
    requests.push(noteChanges);
    note = { ...note, ...noteChanges } as typeof note;
    revision += 1;
    generation += 1;
    await route.fulfill({ json: { song: song(), result: { note_id: note.note_id } } });
  });

  await page.addInitScript(() => {
    localStorage.setItem("ast-onboarding-v1", "done");
    localStorage.setItem("ast-setup-center-v2", "dismissed");
    localStorage.setItem("ast-section", "songs");
  });
  await page.goto("/");
  await expect(page.locator(".note-list button")).toHaveCount(1);
  await page.locator(".note-list button").click();
  const editor = page.locator(".advanced-note-editor");
  await expect(editor).toBeVisible();

  await editor.getByRole("button", { name: "노트 전체 저장" }).click();
  await expect(page.getByText("변경된 노트 항목이 없습니다.")).toBeVisible();
  expect(requests).toHaveLength(0);

  await editor.locator(".lyric-field input").fill("hello");
  await editor.getByRole("button", { name: "노트 전체 저장" }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toEqual({ lyric: "hello" });
  // The save action reloads canonical state asynchronously. Do not edit the
  // next value until the previous save/reload has committed to the inspector.
  await expect(page.locator(".workspace-message")).toContainText("노트·리듬·표현을 저장했습니다.");
  await expect(page.locator(".note-list button.active")).toHaveCount(1);
  await expect(editor.locator(".lyric-field input")).toHaveValue("hello");

  await editor.locator(".pitch-fields select").first().selectOption("D");
  await editor.locator(".lyric-field input").fill("world");
  await editor.getByRole("button", { name: "노트 전체 저장" }).click();
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1]).toEqual({ step: "D", lyric: "world" });
  await expect(page.locator(".note-list button.active")).toContainText("D4");
});

test("chord editor can edit a rest anchor", async ({ page }) => {
  const song = { song_id: "song-1", title: "Demo", artist: "", source_kind: "notation", revision: 1, exports: {}, parts: [] };
  const rest = { note_id: "p0-m0-n0", part_id: "P1", part_name: "Piano", measure: "1", measure_index: 0, rest: true, step: null, alter: null, octave: null, type: "quarter", dots: 0, lyric: "", ties: [], slurs: [], articulations: [], beam: "" };
  let chord = "C";
  const currentXml = () => scoreXml.replace("<pitch><step>C</step><octave>4</octave></pitch>", "<rest/>")
    .replace("<note>", `<harmony><root><root-step>${chord[0]}</root-step></root><kind>${chord === "C" ? "major" : "minor-seventh"}</kind></harmony><note>`);
  const originalHash = scoreSha256(currentXml());
  let request: unknown;
  await page.route("**/api/health", route => route.fulfill({ json: { status: "ok", device_plan: { muscriptor_device: "cpu" }, preflight: { ok: true, missing: [], tools: {} }, presets: { recommended: "quality", presets: [] }, system: { hf_authenticated: false, jobs_bytes: 0, disk_free_bytes: 1000 } } }));
  await page.route("**/api/songs", route => route.fulfill({ json: { songs: [song] } }));
  await page.route("**/api/songs/song-1", route => route.fulfill({ json: song }));
  await page.route("**/api/songs/song-1/notes", route => route.fulfill({ json: { ...scoreSnapshot(song, currentXml()), evidence_generation: song.revision - 1, parts: [{ part_id: "P1", name: "Piano", notes: 1, measures: 1 }], notes: [rest], chords: [{ note_id: rest.note_id, symbol: chord }] } }));
  await page.route("**/api/songs/song-1/structure", route => route.fulfill({ json: { ...scoreSnapshot(song, currentXml()), measures: [] } }));
  await page.route("**/api/songs/song-1/score", route => route.fulfill({ contentType: "application/xml", body: currentXml() }));
  await page.route("**/api/songs/song-1/publication", route => route.fulfill({ json: { settings: {} } }));
  await page.route("**/api/songs/song-1/notes/p0-m0-n0/chord", async route => {
    request = route.request().postDataJSON();
    chord = "Am7";
    song.revision += 1;
    await route.fulfill({ json: { song } });
  });
  await page.addInitScript(() => {
    localStorage.setItem("ast-onboarding-v1", "done");
    localStorage.setItem("ast-setup-center-v2", "dismissed");
    localStorage.setItem("ast-section", "songs");
  });
  await page.goto("/");
  await page.getByRole("button", { name: "코드", exact: true }).click();
  const restButton = page.locator(".chord-note-list button");
  await expect(restButton).toContainText("쉼표");
  await restButton.click();
  const editor = page.locator(".chord-editor");
  await expect(editor).toContainText("쉼표");
  await expect(editor.locator("input")).toHaveValue("C");
  await editor.locator("input").fill("Am7");
  await editor.getByRole("button", { name: "코드 적용" }).click();
  await expect.poll(() => request).toEqual({ symbol: "Am7", expected_revision: 1, expected_score_sha256: originalHash, expected_generation: 0 });
  await expect(page.locator(".revision-pill")).toHaveText("Revision 2");
  await expect(page.locator(".chord-note-list button.active")).toContainText("Am7");
});
