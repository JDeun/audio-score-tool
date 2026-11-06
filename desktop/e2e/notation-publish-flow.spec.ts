import { expect, test } from "@playwright/test";

const SCORE_XML = \`<?xml version="1.0" encoding="utf-8"?>
<score-partwise version="4.0">
  <work><work-title>Owned fixture</work-title></work>
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1"><measure number="1">
    <attributes><divisions>480</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
    <note><pitch><step>C</step><octave>4</octave></pitch>
      <duration>1920</duration><type>whole</type></note>
  </measure></part>
</score-partwise>\`;

test("import MusicXML → library → lyric edit → Undo → final export uses one song", async ({ page }) => {
  let imported = false;
  let lyric = "";
  let revision = 1;
  const uploadCalls: string[] = [];
  const exported: Record<string, unknown>[] = [];
  const song = () => ({
    song_id: "owned-fixture-job",
    job_id: "owned-fixture-job",
    title: "Owned fixture",
    artist: "",
    source_kind: "notation",
    revision,
    exports: { pdf: false, midi: false, musicxml: false },
    parts: [],
  });

  await page.route("**/api/health", route => route.fulfill({
    json: {
      status: "ok", packaged_runtime: false,
      device_plan: { muscriptor_device: "cpu" },
      preflight: { ok: true, missing: [], tools: { whisperx: false } },
      presets: { recommended: "quality", presets: [] },
      data_dir: "/tmp/ast",
      system: { hf_authenticated: false, jobs_bytes: 0, disk_free_bytes: 1000 },
    },
  }));
  await page.route("**/api/setup", route => route.fulfill({
    json: { tool_paths: {}, instructions: { hf_note: "" },
      preflight: { ok: true, missing: [], tools: {} } },
  }));
  await page.route("**/api/jobs?limit=100", route => route.fulfill({ json: { jobs: [] } }));
  await page.route("**/api/import/notation", route => {
    uploadCalls.push(route.request().method());
    imported = true;
    return route.fulfill({
      status: 202, json: {
        job_id: "owned-fixture-job", kind: "notation-import", status: "queued",
      },
    });
  });
  await page.route("**/api/jobs/owned-fixture-job", route => route.fulfill({
    json: { job_id: "owned-fixture-job", kind: "notation-import",
      status: imported ? "done" : "queued", progress: 100 },
  }));
  await page.route("**/api/songs", route => route.fulfill({
    json: { songs: imported ? [song()] : [] },
  }));
  await page.route("**/api/songs/owned-fixture-job", route => route.fulfill({
    json: song(),
  }));
  await page.route("**/api/songs/owned-fixture-job/notes", route => route.fulfill({
    json: {
      song: song(),
      parts: [{ part_id: "P1", name: "Piano", notes: 1, measures: 1 }],
      notes: [{
        note_id: "p0-m0-n0", part_id: "P1", part_name: "Piano",
        measure: "1", measure_index: 0, rest: false, step: "C",
        alter: 0, octave: 4, type: "whole", dots: 0, lyric,
        ties: [], slurs: [], articulations: [], beam: "",
      }],
      chords: [],
    },
  }));
  await page.route("**/api/songs/owned-fixture-job/structure", route => route.fulfill({
    json: { measures: [] },
  }));
  await page.route("**/api/songs/owned-fixture-job/score", route => route.fulfill({
    contentType: "application/xml",
    body: SCORE_XML.replace(
      "</note>",
      \`\${lyric ? \`<lyric><text>\${lyric}</text></lyric>\` : ""}</note>\`,
    ),
  }));
  await page.route("**/api/songs/owned-fixture-job/publication", route => route.fulfill({
    json: { settings: {} },
  }));
  await page.route("**/api/songs/owned-fixture-job/notes/p0-m0-n0/structure", route => {
    lyric = String((route.request().postDataJSON() as { lyric?: string }).lyric ?? "");
    revision += 1;
    return route.fulfill({ json: { song: song(), result: { note_id: "p0-m0-n0" } } });
  });
  await page.route("**/api/songs/owned-fixture-job/undo", route => {
    lyric = "";
    revision = 1;
    return route.fulfill({ json: song() });
  });
  await page.route("**/api/songs/owned-fixture-job/export-to", route => {
    exported.push(route.request().postDataJSON() as Record<string, unknown>);
    return route.fulfill({
      json: { song: song(), parts: [], destination: "/tmp/audio-score-e2e" },
    });
  });
  await page.addInitScript(() => {
    localStorage.setItem("ast-onboarding-v1", "done");
    localStorage.setItem("ast-setup-center-v2", "dismissed");
    localStorage.setItem("ast-section", "new");
  });

  await page.goto("/");
  await page.getByRole("tab", { name: "기존 악보 / MusicXML / MIDI" }).click();
  const importer = page.getByRole("dialog", { name: "기존 악보 가져오기" });
  await expect(importer).toBeVisible();
  await importer.locator('input[type="file"]').setInputFiles({
    name: "owned.musicxml", mimeType: "application/vnd.recordare.musicxml+xml",
    buffer: Buffer.from(SCORE_XML),
  });
  await importer.getByRole("button", { name: "악보 가져오기", exact: true }).click();
  await expect.poll(() => uploadCalls).toEqual(["POST"]);
  await importer.getByRole("button", { name: "곡 라이브러리에서 검토" }).click();

  const scoreTitle = page.locator(".score-toolbar h2");
  await expect(scoreTitle).toHaveText("Owned fixture");
  await expect(page.locator(".revision-pill")).toHaveText("Revision 1");
  await page.locator(".note-list button").first().click();
  const editor = page.locator(".advanced-note-editor");
  await expect(editor).toBeVisible();
  await editor.locator(".lyric-field input").fill("Edited lyric");
  await editor.getByRole("button", { name: "노트 전체 저장" }).click();
  await expect(page.locator(".revision-pill")).toHaveText("Revision 2");
  await expect(editor.locator(".lyric-field input")).toHaveValue("Edited lyric");

  await page.getByRole("button", { name: "실행 취소" }).click();
  await expect(page.locator(".revision-pill")).toHaveText("Revision 1");
  await expect(editor.locator(".lyric-field input")).toHaveValue("");

  await page.getByRole("button", { name: "최종 파일 생성" }).click();
  const exportDialog = page.getByRole("dialog", { name: "최종 파일 생성" });
  await expect(exportDialog).toContainText("Owned fixture");

  // Tauri's dialog adapter is only stubbed at the call boundary; the React
  // export controls still perform the real frontend request serialization.
  await page.evaluate(() => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", {
      configurable: true,
      value: { invoke: (command: string) =>
        Promise.resolve(command === "plugin:dialog|open" ? "/tmp/e2e-output" : null) },
    });
  });
  await exportDialog.getByRole("button", { name: "폴더 선택" }).click();
  await expect(exportDialog.locator(".export-destination input")).toHaveValue("/tmp/e2e-output");
  await exportDialog.getByRole("button", { name: "생성 및 저장" }).click();
  await expect.poll(() => exported.length).toBe(1);
  expect(exported[0]).toEqual({
    formats: ["musicxml", "pdf", "midi", "parts"],
    destination_dir: "/tmp/e2e-output",
  });
});
