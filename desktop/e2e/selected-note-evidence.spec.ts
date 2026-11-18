import { createHash } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";

const sha = "a".repeat(64);
const xml = `<?xml version="1.0"?><score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Voice</part-name></score-part></part-list><part id="P1"><measure number="1"><attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes><note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><type>half</type></note><note><pitch><step>D</step><octave>4</octave></pitch><duration>2</duration><type>half</type></note></measure></part></score-partwise>`;
function wav() {
  const length = 8000 * 4 * 2, data = Buffer.alloc(44 + length);
  data.write("RIFF", 0); data.writeUInt32LE(36 + length, 4); data.write("WAVEfmt ", 8);
  data.writeUInt32LE(16, 16); data.writeUInt16LE(1, 20); data.writeUInt16LE(1, 22);
  data.writeUInt32LE(8000, 24); data.writeUInt32LE(16000, 28); data.writeUInt16LE(2, 32);
  data.writeUInt16LE(16, 34); data.write("data", 36); data.writeUInt32LE(length, 40);
  return data;
}
async function setup(page: Page, legacy = false) {
  let scoreHash = sha, generation = 0, scoreXml = xml;
  let status: "linked" | "ambiguous" | "unavailable" | "conflict" = "linked";
  let seek: number | null = 1;
  let delay = false, release = () => {};
  let gate = Promise.resolve();
  let settle = () => {};
  let settled = Promise.resolve();
  const queries: string[] = [];
  const song = { song_id: "song-1", title: "Owned score", source_kind: "notation", revision: 1, exports: { pdf: false, midi: false, musicxml: false }, parts: [] };
  const notes = ["C", "D"].map((step, index) => ({ note_id: `p0-m0-n${index}`, part_id: "P1", part_name: "Voice", measure: "1", measure_index: 0, rest: false, step, alter: 0, octave: 4, type: "half", dots: 0, lyric: "", ties: [], slurs: [], articulations: [], beam: "" }));
  await page.route("**/api/health", r => r.fulfill({ json: { status: "ok", device_plan: {}, preflight: { ok: true, missing: [], tools: {} }, presets: { recommended: "quality", presets: [] }, system: {} } }));
  await page.route("**/api/engines", r => r.fulfill({ json: { usage_mode: "personal", engines: [], recommendation: null } }));
  await page.route("**/api/songs", r => r.fulfill({ json: { songs: [song] } }));
  await page.route("**/api/songs/song-1", r => r.fulfill({ json: song }));
  await page.route("**/api/songs/song-1/notes", r => r.fulfill({ json: { song, score_sha256: scoreHash, evidence_generation: legacy ? null : generation, parts: [{ part_id: "P1", name: "Voice", measures: 1, notes: 2 }], notes, chords: [] } }));
  await page.route("**/api/songs/song-1/structure", r => r.fulfill({ json: { measures: [] } }));
  await page.route("**/api/songs/song-1/score", r => r.fulfill({ contentType: "application/xml", body: scoreXml }));
  await page.route("**/api/songs/song-1/publication", r => r.fulfill({ json: { settings: {} } }));
  await page.route("**/api/songs/song-1/source-audio?*", r => r.fulfill({ contentType: "audio/wav", body: wav() }));
  await page.route("**/api/songs/song-1/notes/*/evidence?*", async r => {
    const url = new URL(r.request().url());
    const noteId = url.pathname.split("/").at(-2)!;
    queries.push(url.search);
    if (delay) { delay = false; await gate; }
    if (status === "conflict") { await r.fulfill({ status: 409 }); return; }
    await r.fulfill({ json: { revision: song.revision, score_sha256: scoreHash, note_id: noteId, status, patch: null,
      evidence: status === "linked" ? { performed_seconds: { start: .95, end: 1.9 }, grid_seconds: { start: 1, end: 2 }, source_audio_seek_seconds: seek, source_audio_seek_basis: seek === null ? null : "interpreted_grid" } : null } }).catch(() => undefined);
    settle();
  });
  await page.addInitScript(() => { localStorage.setItem("ast-onboarding-v1", "done"); localStorage.setItem("ast-setup-center-v2", "dismissed"); localStorage.setItem("ast-section", "songs"); });
  await page.goto("/");
  await expect(page.locator(".note-list button")).toHaveCount(2);
  return { queries, advance: () => {
    song.revision = 2;
    generation = 1;
    scoreXml = xml.replace("</score-partwise>", "<!-- revision 2 --></score-partwise>");
    scoreHash = createHash("sha256").update(scoreXml).digest("hex");
    return scoreHash;
  }, setStatus: (value: typeof status) => { status = value; }, setSeek: (value: number | null) => { seek = value; }, hold: () => { delay = true; gate = new Promise<void>(resolve => { release = resolve; }); settled = new Promise<void>(resolve => { settle = resolve; }); }, release: () => release(), settled: () => settled };
}

test("explicit evidence query connects verified grid to owned audio", async ({ page }, testInfo) => {
  const api = await setup(page);
  await page.locator(".note-list button").first().click();
  expect(api.queries).toHaveLength(0);
  await page.getByRole("button", { name: "모델 근거 확인" }).click();
  await expect(page.locator(".note-evidence")).toContainText("모델 연주 시각 0.95–1.90초");
  expect(new URLSearchParams(api.queries[0])).toEqual(new URLSearchParams({ expected_revision: "1", expected_score_sha256: sha, expected_generation: "0" }));
  await expect(page.locator(".note-evidence")).not.toContainText("수정했습니다");
  const review = page.locator(".score-workbench").getByLabel("원음 검수");
  await expect(review).not.toContainText("원음을 불러오면 구간을 재생할 수 있습니다");
  await page.locator(".note-evidence").getByRole("button", { name: "원음 구간 확인" }).click();
  await expect(review).toContainText("원음을 불러오면 구간을 재생할 수 있습니다");
  await review.getByRole("button", { name: "원음 불러오기" }).click();
  await expect(review).toContainText("확인 구간 0.70–2.30초");
  await expect(review.getByLabel("원음 재생")).toHaveJSProperty("paused", true);
  for (const [name, width, height] of [["desktop", 1240, 900], ["minimum", 920, 680]] as const) {
    await page.setViewportSize({ width, height });
    await page.locator(".note-evidence").scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath(`source-audio-selected-note-${name}.png`) });
  }
});

test("unavailable, unverified seek and stale response do not offer a clip", async ({ page }) => {
  const api = await setup(page);
  await page.locator(".note-list button").first().click();
  api.setStatus("ambiguous");
  await page.getByRole("button", { name: "모델 근거 확인" }).click();
  await expect(page.locator(".note-evidence")).toContainText("보류합니다");
  api.setStatus("unavailable");
  await page.getByRole("button", { name: "모델 근거 확인" }).click();
  await expect(page.locator(".note-evidence")).toContainText("보류합니다");
  api.setStatus("linked"); api.setSeek(null);
  await page.getByRole("button", { name: "모델 근거 확인" }).click();
  await expect(page.locator(".note-evidence")).toContainText("재생 연결을 보류합니다");
  api.setStatus("conflict");
  await page.getByRole("button", { name: "모델 근거 확인" }).click();
  await expect(page.locator(".note-evidence")).toContainText("새로고침");
  api.setStatus("linked"); api.setSeek(1); api.hold();
  await page.getByRole("button", { name: "모델 근거 확인" }).click();
  await expect.poll(() => api.queries.length).toBe(5);
  await page.locator(".note-list button").nth(1).click();
  await page.locator(".note-list button").first().click();
  api.release();
  await api.settled();
  await expect(page.locator(".note-evidence")).not.toContainText("모델 연주 시각");
  await expect(page.locator(".score-workbench").getByLabel("원음 검수")).not.toContainText("확인 구간");
});


test("legacy score with no evidence generation explicitly defers lookup", async ({ page }) => {
  const api = await setup(page, true);
  await page.locator(".note-list button").first().click();
  await expect(page.getByRole("button", { name: "모델 근거 확인" })).toBeDisabled();
  await expect(page.locator(".note-evidence")).toContainText("보류합니다");
  expect(api.queries).toHaveLength(0);
});

test("completed evidence does not return after selecting another note and back", async ({ page }) => {
  const api = await setup(page);
  const notes = page.locator(".note-list button");
  await notes.first().click();
  await page.getByRole("button", { name: "모델 근거 확인" }).click();
  await expect(page.locator(".note-evidence")).toContainText("모델 연주 시각");
  const review = page.locator(".score-workbench").getByLabel("원음 검수");
  await expect(review).not.toContainText("원음을 불러오면 구간을 재생할 수 있습니다");
  await page.locator(".note-evidence").getByRole("button", { name: "원음 구간 확인" }).click();
  await expect(review).toContainText("원음을 불러오면 구간을 재생할 수 있습니다");
  await notes.nth(1).click();
  await notes.first().click();
  await expect(page.locator(".note-evidence")).not.toContainText("모델 연주 시각");
  await expect(review).not.toContainText("원음을 불러오면 구간을 재생할 수 있습니다");
  expect(api.queries).toHaveLength(1);
});


test("refresh after conflict reloads selected score and sends new evidence stamps", async ({ page }) => {
  const api = await setup(page);
  await page.locator(".note-list button").first().click();
  await page.getByRole("button", { name: "모델 근거 확인" }).click();
  await expect(page.locator(".note-evidence")).toContainText("모델 연주 시각");
  await page.locator(".note-evidence").getByRole("button", { name: "원음 구간 확인" }).click();
  await expect(page.locator(".score-workbench").getByLabel("원음 검수")).toContainText("구간을 재생할 수 있습니다");
  api.setStatus("conflict");
  await page.getByRole("button", { name: "모델 근거 확인" }).click();
  await expect(page.locator(".note-evidence")).toContainText("새로고침");
  const nextHash = api.advance();
  api.setStatus("linked");
  await page.locator(".score-toolbar").getByRole("button", { name: "악보 새로고침", exact: true }).click();
  await expect(page.locator(".score-toolbar")).toContainText("Revision 2");
  await expect(page.locator(".score-workbench").getByLabel("원음 검수")).not.toContainText("구간을 재생할 수 있습니다");
  await page.getByRole("button", { name: "모델 근거 확인" }).click();
  await expect(page.locator(".note-evidence")).toContainText("모델 연주 시각");
  expect(new URLSearchParams(api.queries.at(-1))).toEqual(new URLSearchParams({ expected_revision: "2", expected_score_sha256: nextHash, expected_generation: "1" }));
});


test("delayed evidence does not steal focus until the user requests the audio segment", async ({ page }) => {
  const api = await setup(page);
  await page.locator(".note-list button").first().click();
  api.hold();
  await page.getByRole("button", { name: "모델 근거 확인" }).click();
  await expect.poll(() => api.queries.length).toBe(1);
  const lyric = page.locator(".lyric-field input");
  await lyric.focus();
  api.release();
  await api.settled();
  await expect(page.locator(".note-evidence")).toContainText("모델 연주 시각");
  await expect(lyric).toBeFocused();
  const review = page.locator(".score-workbench").getByLabel("원음 검수");
  await expect(review).not.toContainText("구간을 재생할 수 있습니다");
  await page.locator(".note-evidence").getByRole("button", { name: "원음 구간 확인" }).click();
  await expect(review).toBeFocused();
});
