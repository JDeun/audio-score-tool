import { expect, test, type Page, type Route } from "@playwright/test";
import { scoreSha256, scoreSnapshot } from "./score-fixture";

const xml = `<?xml version="1.0"?><score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Voice</part-name></score-part></part-list><part id="P1"><measure number="1"><attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes><note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><type>half</type></note><note><pitch><step>D</step><octave>4</octave></pitch><duration>2</duration><type>half</type></note></measure></part></score-partwise>`;
const sha = scoreSha256(xml);
const sourceIds = ["selected-midi-v1:" + "a".repeat(64) + ":0", "selected-midi-v1:" + "a".repeat(64) + ":1"];
function pitchFixture(ids = [sourceIds[0]]) {
  return { schema_version: 1, status: "available", frame_clock: "stem_local", advisory: true,
    algorithm: "tiny-frame-window-v1", pitch_sha256: "a".repeat(64), stem_sha256: "b".repeat(64),
    pitch_runtime_sha256: "c".repeat(64), frame_interval_seconds: .01,
    thresholds: { periodicity: .21, loudness_db_a: -60 }, acoustic_onset: { status: "not_measured" },
    perceptual_onset: { status: "not_measured" }, sources: ids.map((source_id, n) => ({ source_id,
      start_frame: 0, end_frame_exclusive: 3, note_frame_start: 1, note_frame_end_exclusive: 2,
      frames: [{ index: 0, time_seconds: 0, raw_hz: 220 + n * 20, hz: 0, periodicity: .1, loudness_db_a: -30 },
        { index: 1, time_seconds: .01, raw_hz: 220 + n * 20, hz: 220 + n * 20, periodicity: Math.fround(.21), loudness_db_a: -30 },
        { index: 2, time_seconds: .02, raw_hz: 220 + n * 20, hz: 0, periodicity: .1, loudness_db_a: -30 }],
      gate_transitions: [{ kind: "accepted", left_frame: 0, right_frame: 1, from_seconds: 0, to_seconds: .01 },
        { kind: "rejected", left_frame: 1, right_frame: 2, from_seconds: .01, to_seconds: .02 }] })) };
}
const revisedXml = (revision: number) => xml.replace("</score-partwise>", `<!-- revision ${revision} --></score-partwise>`);
function wav() {
  const length = 8000 * 4 * 2, data = Buffer.alloc(44 + length);
  data.write("RIFF", 0); data.writeUInt32LE(36 + length, 4); data.write("WAVEfmt ", 8);
  data.writeUInt32LE(16, 16); data.writeUInt16LE(1, 20); data.writeUInt16LE(1, 22);
  data.writeUInt32LE(8000, 24); data.writeUInt32LE(16000, 28); data.writeUInt16LE(2, 32);
  data.writeUInt16LE(16, 34); data.write("data", 36); data.writeUInt32LE(length, 40);
  return data;
}
async function setup(page: Page, legacy = false, octave = 4) {
  let scoreHash = sha, generation = 0, scoreXml = xml;
  let status: "linked" | "ambiguous" | "unavailable" | "conflict" = "linked";
  let seek: number | null = 1;
  let multi = false;
  let pitch: unknown = undefined;
  let pitchGeneration: number | undefined;
  let delay = false, release = () => {};
  let gate = Promise.resolve();
  let settle = () => {};
  let settled = Promise.resolve();
  const queries: string[] = [];
  const edits: Record<string, unknown>[] = [];
  let noteReads = 0;
  let editStatus = 200;
  let editGate = Promise.resolve();
  const song = { song_id: "song-1", title: "Owned score", source_kind: "notation", revision: 1, exports: { pdf: false, midi: false, musicxml: false }, parts: [] };
  const notes = ["C", "D"].map((step, index) => ({ note_id: `p0-m0-n${index}`, part_id: "P1", part_name: "Voice", measure: "1", measure_index: 0, rest: false, step, alter: 0, octave, type: "half", dots: 0, lyric: "", ties: [], slurs: [], articulations: [], beam: "" }));
  const measures = [{ measure_index: 0, number: "1", divisions: 1, key_fifths: 0, key_mode: "major", beats: 4, beat_type: 4 }];
  await page.route("**/api/health", r => r.fulfill({ json: { status: "ok", device_plan: {}, preflight: { ok: true, missing: [], tools: {} }, presets: { recommended: "quality", presets: [] }, system: {} } }));
  await page.route("**/api/engines", r => r.fulfill({ json: { usage_mode: "personal", engines: [], recommendation: null } }));
  await page.route("**/api/songs", r => r.fulfill({ json: { songs: [song] } }));
  await page.route("**/api/songs/song-1", r => r.fulfill({ json: song }));
  await page.route("**/api/songs/song-1/notes", r => {
    noteReads++;
    return r.fulfill({ json: { song, score_sha256: scoreHash, evidence_generation: legacy ? null : generation, parts: [{ part_id: "P1", name: "Voice", measures: 1, notes: notes.length }], notes, chords: [] } });
  });
  await page.route("**/api/songs/song-1/structure", r => r.fulfill({ json: { song, score_sha256: scoreHash, measures } }));
  await page.route("**/api/songs/song-1/score", r => r.fulfill({ contentType: "application/xml", body: scoreXml }));
  await page.route("**/api/songs/song-1/publication", r => r.fulfill({ json: { settings: {} } }));
  await page.route("**/api/songs/song-1/notes/rhythm-edit", async r => {
    const payload = r.request().postDataJSON() as Record<string, unknown>;
    edits.push(payload);
    await editGate;
    if (editStatus !== 200) { await r.fulfill({ status: editStatus, json: { detail: "unsupported owned fixture" } }); return; }
    song.revision += 1; generation += 1;
    scoreXml = revisedXml(song.revision);
    scoreHash = scoreSha256(scoreXml);
    if (payload.action === "split") {
      notes[1].note_id = "p0-m0-n2";
      notes.splice(1, 0, { ...notes[0], note_id: "p0-m0-n1", type: "quarter" });
      notes[0].type = "quarter";
    }
    if (payload.action === "delete") notes[0].rest = true;
    await r.fulfill({ json: { song, result: { result_note_ids: ["p0-m0-n0"] } } });
  });
  await page.route("**/api/songs/song-1/source-audio?*", r => r.fulfill({ contentType: "audio/wav", body: wav() }));
  await page.route("**/api/songs/song-1/notes/*/evidence?*", async r => {
    const url = new URL(r.request().url());
    const noteId = url.pathname.split("/").at(-2)!;
    queries.push(url.search);
    if (delay) { delay = false; await gate; }
    if (status === "conflict") { await r.fulfill({ status: 409 }); return; }
    await r.fulfill({ json: { schema_version: multi ? 2 : 1, revision: song.revision, score_sha256: scoreHash, note_id: noteId, status, patch: null,
      ...(pitch === undefined ? {} : { pitch_observations: pitch, evidence_generation: pitchGeneration ?? generation }),
      evidence: status === "linked" ? (multi ? { performed_seconds: null, grid_seconds: null, source_audio_seek_seconds: null, source_audio_seek_basis: null, written_quarters: { start: .5, end: 2 }, sources: [
        { source_id: sourceIds[0], performed_seconds: { start: .95, end: 1.9 }, grid_seconds: { start: 1, end: 2 }, source_audio_seek_seconds: 1, source_audio_seek_basis: "interpreted_grid" },
        { source_id: sourceIds[1], performed_seconds: { start: 2.05, end: 2.9 }, grid_seconds: { start: 2, end: 3 }, source_audio_seek_seconds: 2, source_audio_seek_basis: "interpreted_grid" },
      ] } : { source_id: sourceIds[0], performed_seconds: { start: .95, end: 1.9 }, grid_seconds: { start: 1, end: 2 }, source_audio_seek_seconds: seek, source_audio_seek_basis: seek === null ? null : "interpreted_grid" }) : null } }).catch(() => undefined);
    settle();
  });
  await page.addInitScript(() => { localStorage.setItem("ast-onboarding-v1", "done"); localStorage.setItem("ast-setup-center-v2", "dismissed"); localStorage.setItem("ast-section", "songs"); });
  await page.goto("/");
  await expect(page.locator(".note-list button")).toHaveCount(2);
  return { song, queries, edits, setPitch: (value: unknown, stamp?: number) => { pitch = value; pitchGeneration = stamp; }, noteReads: () => noteReads, holdEdit: () => {
    let releaseEdit!: () => void;
    editGate = new Promise<void>(resolve => { releaseEdit = resolve; });
    return releaseEdit;
  }, setEditStatus: (value: number) => { editStatus = value; }, advance: () => {
    song.revision = 2;
    generation = 1;
    scoreXml = revisedXml(2);
    scoreHash = scoreSha256(scoreXml);
    return scoreHash;
  }, insertFirst: () => {
    song.revision += 1;
    generation += 1;
    const [first, second] = notes;
    first.note_id = "p0-m0-n1";
    first.type = "quarter";
    second.note_id = "p0-m0-n2";
    notes.unshift({ ...first, note_id: "p0-m0-n0", step: "E" });
    scoreXml = xml.replace("<duration>2</duration><type>half</type>", "<duration>1</duration><type>quarter</type>")
      .replace("<note>", "<note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note><note>");
    scoreHash = scoreSha256(scoreXml);
  }, supersede: () => { song.revision = 3; generation = 2; scoreXml = xml + "<!-- newer -->"; scoreHash = scoreSha256(scoreXml); }, setMulti: () => { multi = true; }, setStatus: (value: typeof status) => { status = value; }, setSeek: (value: number | null) => { seek = value; }, hold: () => { delay = true; gate = new Promise<void>(resolve => { release = resolve; }); settled = new Promise<void>(resolve => { settle = resolve; }); }, release: () => release(), settled: () => settled };
}

for (const [name, width, height] of [["desktop", 1240, 900], ["minimum", 920, 680]] as const) {
test(`explicit evidence query connects verified grid to owned audio at ${name}`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height });
  const api = await setup(page);
  await page.locator(".note-list button").first().click();
  expect(api.queries).toHaveLength(0);
  await page.getByRole("button", { name: "모델 근거 확인" }).click();
  await expect(page.locator(".note-evidence")).toContainText("모델 연주 시각 0.95–1.90초");
  expect(new URLSearchParams(api.queries[0])).toEqual(new URLSearchParams({ expected_revision: "1", expected_score_sha256: sha, expected_generation: "0", include_pitch_observations: "true" }));
  await expect(page.locator(".note-evidence")).not.toContainText("수정했습니다");
  const review = page.locator(".score-workbench").getByLabel("원음 검수");
  await expect(review).not.toContainText("원음을 불러오면 구간을 재생할 수 있습니다");
  await page.locator(".note-evidence").getByRole("button", { name: "원음 구간 확인" }).click();
  await expect(review).toContainText("원음을 불러오면 구간을 재생할 수 있습니다");
  await review.getByRole("button", { name: "원음 불러오기" }).click();
  await expect(review).toContainText("확인 구간 0.70–2.30초");
  await expect(review.getByLabel("원음 재생")).toHaveJSProperty("paused", true);
  const list = page.locator(".note-list");
  expect(await list.evaluate(element => element.clientHeight)).toBeGreaterThanOrEqual(
    await list.locator("button").first().evaluate(element => element.getBoundingClientRect().height) + 10);
  await page.locator(".note-evidence").scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath(`source-audio-selected-note-${name}.png`) });
  await page.locator(".note-evidence").getByRole("button", { name: "원음 구간 확인" }).click();
  await expect(review).toBeFocused();
  await page.screenshot({ path: testInfo.outputPath(`source-audio-selected-note-${name}-player.png`) });
});
}

for (const width of [920, 1240, 1301]) {
test(`pitch observation maps merged sources without overflow at ${width}`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 });
  const api = await setup(page);
  api.setMulti();
  api.setPitch(pitchFixture([sourceIds[1], sourceIds[0]]));
  await page.locator(".note-list button").first().click();
  await page.getByRole("button", { name: "모델 근거 확인" }).click();
  const sources = page.locator(".note-evidence-source");
  await expect(sources).toHaveCount(2);
  await expect(sources.first().locator(".pitch-observation svg")).toHaveCount(1);
  await expect(sources.nth(1).locator(".pitch-observation svg")).toHaveCount(1);
  await expect(sources.first().locator(".pitch-observation")).toHaveAttribute("data-source-id", sourceIds[0]);
  await expect(sources.nth(1).locator(".pitch-observation")).toHaveAttribute("data-source-id", sourceIds[1]);
  await expect(sources.first()).toContainText("통과 1개 · 제외 2개");
  await expect(sources.first()).toContainText("강조 범위는 원본 모델 음표 구간");
  await expect(sources.first()).toContainText("점선은 현재 기보 C4");
  await expect(sources.first().locator(".pitch-note-range")).toHaveCount(1);
  await expect(sources.first().locator(".pitch-accepted")).toHaveCount(1);
  await expect(sources.first().locator(".pitch-rejected")).toHaveCount(2);
  const graph = sources.first().locator(".pitch-observation");
  await graph.scrollIntoViewIfNeeded();
  expect(await page.locator(".song-layout").evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath(`pitch-observation-${width}.png`) });
});
}

test("retained rejected boundary from a separate float64 payload remains available", async ({ page }) => {
  const api = await setup(page);
  const pitch = pitchFixture();
  pitch.sources[0].frames[1].hz = 0;
  pitch.sources[0].gate_transitions = [];
  api.setPitch(pitch);
  await page.locator(".note-list button").first().click();
  await page.getByRole("button", { name: "모델 근거 확인" }).click();
  const plot = page.locator(".pitch-observation");
  await expect(plot).toContainText("통과 0개 · 제외 3개");
  await expect(plot.locator(".pitch-accepted")).toHaveCount(0);
  await expect(plot.locator(".pitch-rejected")).toHaveCount(3);
});

test("invalid written pitch does not produce invalid SVG coordinates", async ({ page }) => {
  const api = await setup(page, false, 1e308);
  api.setPitch(pitchFixture());
  await page.locator(".note-list button").first().click();
  await page.getByRole("button", { name: "모델 근거 확인" }).click();
  const plot = page.locator(".pitch-observation");
  await expect(plot.locator("svg")).toHaveCount(1);
  await expect(plot.locator(".pitch-written")).toHaveCount(0);
  await expect(plot).not.toContainText("Infinity");
});

test("optional pitch data fails closed without hiding linked evidence", async ({ page }) => {
  const api = await setup(page);
  await page.locator(".note-list button").first().click();
  for (const value of [{ schema_version: 1, status: "unavailable", reason: "no_source" },
    { ...pitchFixture(), schema_version: 2 }, { ...pitchFixture(), sources: [{ ...pitchFixture().sources[0], frames: [] }] },
    pitchFixture(["unproven"])]) {
    api.setPitch(value);
    await page.getByRole("button", { name: "모델 근거 확인" }).click();
    await expect(page.locator(".note-evidence")).toContainText("모델 연주 시각");
    await expect(page.locator(".note-evidence")).toContainText("표시하지 않");
    await expect(page.locator(".pitch-observation svg")).toHaveCount(0);
  }
  api.setPitch(pitchFixture(), 1);
  await page.getByRole("button", { name: "모델 근거 확인" }).click();
  await expect(page.locator(".note-evidence")).toContainText("형식을 확인할 수 없어");
  await expect(page.locator(".pitch-observation svg")).toHaveCount(0);
  api.setPitch(undefined);
  await page.getByRole("button", { name: "모델 근거 확인" }).click();
  await expect(page.locator(".note-evidence")).not.toContainText("표시하지 않");
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
  api.setStatus("linked"); api.setSeek(1); api.setPitch(pitchFixture()); api.hold();
  await page.getByRole("button", { name: "모델 근거 확인" }).click();
  await expect.poll(() => api.queries.length).toBe(5);
  await page.locator(".note-list button").nth(1).click();
  await page.locator(".note-list button").first().click();
  api.release();
  await api.settled();
  await expect(page.locator(".note-evidence")).not.toContainText("모델 연주 시각");
  await expect(page.locator(".pitch-observation svg")).toHaveCount(0);
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


test("refresh after conflict clears selection and a new evidence request uses fresh stamps", async ({ page }) => {
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
  await expect(page.locator(".note-list button.active")).toHaveCount(0);
  await expect(page.locator(".score-workbench").getByLabel("원음 검수")).not.toContainText("구간을 재생할 수 있습니다");
  await page.locator(".note-list button").first().click();
  await page.getByRole("button", { name: "모델 근거 확인" }).click();
  await expect(page.locator(".note-evidence")).toContainText("모델 연주 시각");
  expect(new URLSearchParams(api.queries.at(-1))).toEqual(new URLSearchParams({ expected_revision: "2", expected_score_sha256: nextHash, expected_generation: "1", include_pitch_observations: "true" }));
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


for (const [size, width, height] of [["desktop", 1240, 900], ["minimum", 920, 680], ["boundary", 1301, 900]] as const) {
test(`merged schema exposes each original source and separate explicit audio clips at ${size}`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height });
  const api = await setup(page);
  api.setMulti();
  await page.locator(".note-list button").first().click();
  await page.getByRole("button", { name: "모델 근거 확인" }).click();
  const evidence = page.locator(".note-evidence");
  await expect(evidence).toContainText("현재 기보 위치 (4분음표 기준) 0.50–2.00");
  await expect(evidence).toContainText("모델 연주 시각 0.95–1.90초");
  await expect(evidence).toContainText("모델 연주 시각 2.05–2.90초");
  await evidence.scrollIntoViewIfNeeded();
  expect(await page.locator(".song-layout").evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath(`source-audio-rhythm-${size}-sources.png`) });
  const review = page.locator(".score-workbench").getByLabel("원음 검수");
  await evidence.getByRole("button", { name: "원음 구간 확인 1" }).click();
  await review.getByRole("button", { name: "원음 불러오기" }).click();
  await expect(review).toContainText("확인 구간 0.70–2.30초");
  await evidence.getByRole("button", { name: "원음 구간 확인 2" }).click();
  await expect(review).toContainText("확인 구간 1.70–3.30초");
  await expect(review.getByLabel("원음 재생")).toHaveJSProperty("paused", true);
  const rhythm = page.locator(".note-rhythm-edit");
  await rhythm.scrollIntoViewIfNeeded();
  expect(await page.locator(".song-layout").evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath(`source-audio-rhythm-${size}-controls.png`) });
  api.setEditStatus(422);
  await rhythm.getByRole("button", { name: "음표 나누기" }).click();
  await expect(rhythm.getByRole("status")).toContainText("unsupported owned fixture");
  await rhythm.scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath(`source-audio-rhythm-${size}-error.png`) });
});
}


for (const [action, label, count] of [["split", "음표 나누기", 1], ["merge", "다음과 합치기", 2], ["boundary", "경계 옮기기", 2], ["delete", "같은 길이 쉼표로 바꾸기", 1]] as const) {
  test(`rhythm ${action} sends exact score stamps and selects only the returned locator`, async ({ page }) => {
    const api = await setup(page);
    await page.locator(".note-list button").first().click();
    const editor = page.locator(".note-rhythm-edit");
    await expect(editor).toContainText("바로 다음");
    await editor.getByRole("button", { name: label, exact: true }).click();
    await expect.poll(() => api.edits.length).toBe(1);
    expect(api.edits[0]).toEqual({ action, note_ids: ["p0-m0-n0", ...(count === 2 ? ["p0-m0-n1"] : [])],
      expected_revision: 1, expected_score_sha256: sha, expected_generation: 0,
      ...(["split", "boundary"].includes(action) ? { left_note_type: "eighth", left_dots: 0 } : {}) });
    await expect(page.locator(".score-toolbar")).toContainText("Revision 2");
    await expect(page.locator(".note-list button").first()).toHaveClass(/active/);
    await expect(editor.getByRole("status")).toHaveText("리듬 편집을 적용했습니다.");
    if (action === "split") await expect(page.locator(".note-list button")).toHaveCount(3);
  });
}

test("rhythm errors and legacy state are explained without a silent fallback", async ({ page }) => {
  const api = await setup(page);
  await page.locator(".note-list button").first().click();
  api.setEditStatus(422);
  await page.getByRole("button", { name: "음표 나누기" }).click();
  await expect(page.locator(".note-rhythm-edit").getByRole("status")).toContainText("unsupported owned fixture");
  api.setEditStatus(409);
  await page.getByRole("button", { name: "음표 나누기" }).click();
  await expect(page.locator(".note-rhythm-edit").getByRole("status")).toContainText("악보 새로고침");
  expect(api.edits).toHaveLength(2);
});

test("legacy without a generation cannot submit a rhythm edit", async ({ page }) => {
  const api = await setup(page, true);
  await page.locator(".note-list button").first().click();
  await expect(page.getByRole("button", { name: "음표 나누기" })).toBeDisabled();
  await expect(page.locator(".note-rhythm-edit")).toContainText("상태를 확인할 수 없습니다");
  expect(api.edits).toHaveLength(0);
});

test("consecutive rhythm edits use the newly reloaded stamps", async ({ page }) => {
  const api = await setup(page);
  await page.locator(".note-list button").first().click();
  await page.getByRole("button", { name: "음표 나누기" }).click();
  await expect(page.locator(".score-toolbar")).toContainText("Revision 2");
  await page.getByLabel("왼쪽 길이").selectOption("quarter");
  await page.getByLabel("왼쪽 점").selectOption("1");
  await page.getByRole("button", { name: "경계 옮기기" }).click();
  await expect.poll(() => api.edits.length).toBe(2);
  const expectedHash = scoreSha256(revisedXml(2));
  expect(api.edits[1]).toEqual({ action: "boundary", note_ids: ["p0-m0-n0", "p0-m0-n1"],
    expected_revision: 2, expected_score_sha256: expectedHash, expected_generation: 1,
    left_note_type: "quarter", left_dots: 1 });
});


test("a superseding score clears positional selection after a pending rhythm edit", async ({ page }) => {
  const api = await setup(page);
  let release!: () => void, arrived!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const requested = new Promise<void>(resolve => { arrived = resolve; });
  await page.route("**/api/songs/song-1/notes/rhythm-edit", async route => {
    arrived(); await gate;
    await route.fulfill({ json: { result: { result_note_ids: ["p0-m0-n0"] } } });
  });
  await page.locator(".note-list button").first().click();
  await page.getByRole("button", { name: "음표 나누기" }).click();
  await requested;
  await expect(page.locator(".note-list button").first()).toBeDisabled();
  await expect(page.getByRole("button", { name: "선택 음표 삭제" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "노트 전체 저장" })).toBeDisabled();
  api.supersede(); release();
  await expect(page.locator(".score-toolbar")).toContainText("Revision 3");
  await expect(page.locator(".note-list button.active")).toHaveCount(0);
  await expect(page.locator(".note-rhythm-edit")).toHaveCount(0);
});

for (const responseStatus of [200, 422]) {
  test(`a delayed rhythm response ${responseStatus} cannot invalidate another song load`, async ({ page }) => {
    await setup(page);
    const song = { song_id: "song-2", title: "Second owned score", source_kind: "notation", revision: 1, exports: { pdf: false, midi: false, musicxml: false }, parts: [] };
    let releaseEdit!: () => void, editArrived!: () => void, releaseNotes!: () => void, notesArrived!: () => void;
    const editGate = new Promise<void>(resolve => { releaseEdit = resolve; });
    const editRequested = new Promise<void>(resolve => { editArrived = resolve; });
    const notesGate = new Promise<void>(resolve => { releaseNotes = resolve; });
    const notesRequested = new Promise<void>(resolve => { notesArrived = resolve; });
    await page.route("**/api/songs", route => route.fulfill({ json: { songs: [{ ...song, song_id: "song-1", title: "Owned score" }, song] } }));
    await page.route("**/api/songs/song-2", route => route.fulfill({ json: song }));
    await page.route("**/api/songs/song-2/notes", async route => {
      notesArrived(); await notesGate;
      await route.fulfill({ json: { song, score_sha256: sha, evidence_generation: 0, parts: [], notes: [], chords: [] } });
    });
    await page.route("**/api/songs/song-2/structure", route => route.fulfill({ json: { ...scoreSnapshot(song, xml), measures: [] } }));
    await page.route("**/api/songs/song-2/score", route => route.fulfill({ contentType: "application/xml", body: xml }));
    await page.route("**/api/songs/song-2/publication", route => route.fulfill({ json: { settings: {} } }));
    await page.route("**/api/songs/song-1/notes/rhythm-edit", async route => {
      editArrived(); await editGate;
      await route.fulfill({ status: responseStatus, json: responseStatus === 200 ? { result: { result_note_ids: ["p0-m0-n0"] } } : { detail: "old error" } });
    });
    await page.getByRole("button", { name: "악보 새로고침" }).click();
    await page.locator(".note-list button").first().click();
    await page.getByRole("button", { name: "음표 나누기" }).click();
    await editRequested;
    await page.getByText("Second owned score", { exact: true }).click();
    await notesRequested;
    const editResponse = page.waitForResponse(response => response.url().includes("/notes/rhythm-edit"));
    releaseEdit();
    await editResponse;
    releaseNotes();
    await expect(page.locator(".score-toolbar")).toContainText("Second owned score");
    await expect(page.locator(".note-rhythm-edit")).toHaveCount(0);
    await expect(page.locator(".workspace-message").filter({ hasText: "old error" })).toHaveCount(0);
  });
}

test("returning to a song while its rhythm edit is pending refreshes its final snapshot", async ({ page }) => {
  const api = await setup(page);
  const song = { song_id: "song-2", title: "Second owned score", source_kind: "notation", revision: 1, exports: { pdf: false, midi: false, musicxml: false }, parts: [] };
  let release!: () => void, arrived!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const requested = new Promise<void>(resolve => { arrived = resolve; });
  await page.route("**/api/songs", route => route.fulfill({ json: { songs: [{ ...song, song_id: "song-1", title: "Owned score" }, song] } }));
  await page.route("**/api/songs/song-2", route => route.fulfill({ json: song }));
  await page.route("**/api/songs/song-2/notes", route => route.fulfill({ json: { song, score_sha256: sha, evidence_generation: 0, parts: [], notes: [], chords: [] } }));
  await page.route("**/api/songs/song-2/structure", route => route.fulfill({ json: { ...scoreSnapshot(song, xml), measures: [] } }));
  await page.route("**/api/songs/song-2/score", route => route.fulfill({ contentType: "application/xml", body: xml }));
  await page.route("**/api/songs/song-2/publication", route => route.fulfill({ json: { settings: {} } }));
  await page.route("**/api/songs/song-1/notes/rhythm-edit", async route => {
    arrived(); await gate; api.advance();
    await route.fulfill({ json: { result: { result_note_ids: ["p0-m0-n0"] } } });
  });
  await page.getByRole("button", { name: "악보 새로고침" }).click();
  await page.locator(".note-list button").first().click();
  await page.getByRole("button", { name: "음표 나누기" }).click();
  await requested;
  await page.getByText("Second owned score", { exact: true }).click();
  await expect(page.locator(".score-toolbar")).toContainText("Second owned score");
  await page.locator(".song-item").filter({ hasText: "Owned score" }).first().click();
  await expect(page.locator(".score-toolbar")).toContainText("Revision 1");
  await expect(page.locator(".note-list button").first()).toBeDisabled();
  release();
  await expect(page.locator(".score-toolbar")).toContainText("Revision 2");
  await expect(page.locator(".note-list button.active")).toHaveCount(0);
  await expect(page.locator(".note-list button").first()).toBeEnabled();
});

test("an auxiliary export reload during a pending rhythm edit still reconciles the committed score", async ({ page }) => {
  const api = await setup(page);
  const releaseRhythm = api.holdEdit();
  let releaseExport!: () => void;
  let exportRequested!: () => void;
  const exportGate = new Promise<void>(resolve => { releaseExport = resolve; });
  const exportStarted = new Promise<void>(resolve => { exportRequested = resolve; });
  await page.route("**/api/songs/song-1/export-to", async route => {
    exportRequested();
    await exportGate;
    await route.fulfill({ json: { destination: "/tmp/owned-score" } });
  });
  await page.locator(".note-list button").first().click();
  await page.getByRole("button", { name: "최종 파일 생성", exact: true }).click();
  const modal = page.getByRole("dialog", { name: "최종 파일 생성" });
  await expect(modal).toContainText("Revision 1");
  await page.evaluate(() => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", { configurable: true, value: {
      invoke: (command: string) => Promise.resolve(command === "plugin:dialog|open" ? "/tmp/owned-score" : null),
    } });
  });
  await modal.getByRole("button", { name: "폴더 선택" }).click();
  await expect(modal.locator(".export-destination input")).toHaveValue("/tmp/owned-score");
  await modal.getByRole("button", { name: "생성 및 저장" }).click();
  await exportStarted;

  // Drive the overlapping requests independently of the modal's pointer capture.
  await page.locator(".note-rhythm-actions button").first().dispatchEvent("click");
  await expect.poll(() => api.edits.length).toBe(1);
  const readsBeforeExport = api.noteReads();
  releaseExport();
  await expect(modal).toContainText("저장 완료");
  await expect.poll(api.noteReads).toBeGreaterThan(readsBeforeExport);
  await modal.locator("button.export-cancel").click();
  await expect(page.locator(".score-toolbar")).toContainText("Revision 1");
  await expect(page.getByRole("button", { name: "선택 음표 삭제" })).toBeDisabled();

  releaseRhythm();
  await expect(page.locator(".score-toolbar")).toContainText("Revision 2");
  await expect(page.locator(".note-list button")).toHaveCount(3);
  await expect(page.locator(".note-editor-head code")).toHaveText("p0-m0-n0");
  await expect(page.getByRole("button", { name: "선택 음표 삭제" })).toBeEnabled();
});

for (const refresh of ["manual", "auxiliary"] as const) {
  test(`${refresh} refresh clears note and measure selection after positional IDs shift`, async ({ page }) => {
    const api = await setup(page);
    const notes = page.locator(".note-list button");
    await notes.nth(1).click();
    await expect(notes.nth(1)).toContainText("D4");
    await expect(page.locator(".note-editor-head code")).toHaveText("p0-m0-n1");
    await page.getByRole("button", { name: "마디·조성", exact: true }).click();
    const measure = page.getByLabel("편집 마디");
    await expect(measure).toHaveValue("0");

    if (refresh === "manual") {
      api.insertFirst();
      await page.getByRole("button", { name: "악보 새로고침", exact: true }).click();
    } else {
      await page.route("**/api/songs/song-1/identify-source", route => {
        api.insertFirst();
        return route.fulfill({ json: { applied: true } });
      });
      await page.getByRole("button", { name: "곡 정보", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "곡 정보 보강" });
      await dialog.getByRole("button", { name: "원본 음원 자동 식별" }).click();
      await expect(dialog).toContainText("신뢰도가 높은 곡 정보를 반영했습니다.");
      await dialog.getByRole("button", { name: "곡 정보 보강 닫기" }).click();
    }
    await expect(page.locator(".score-toolbar")).toContainText("Revision 2");
    await expect(measure).toHaveValue("");
    await expect(page.getByRole("button", { name: "조표·박자표 적용" })).toBeDisabled();
    await page.getByRole("button", { name: "노트", exact: true }).click();
    await expect(notes.nth(1)).toContainText("C4");
    await expect(page.locator(".note-list button.active")).toHaveCount(0);
    await expect(page.locator(".note-editor-head")).toHaveCount(0);
  });
}

test("returning from History preserves the pending lock until the committed score is loaded", async ({ page }) => {
  const api = await setup(page);
  const releaseRhythm = api.holdEdit();
  await page.route("**/api/jobs?limit=100", route => route.fulfill({ json: { jobs: [] } }));
  await page.locator(".note-list button").first().click();
  await page.getByRole("button", { name: "음표 나누기" }).click();
  await expect.poll(() => api.edits.length).toBe(1);
  const menu = page.getByRole("navigation", { name: "주요 메뉴" });
  await menu.getByRole("button", { name: /작업 내역/ }).click();
  await expect(page.locator(".song-shell")).toHaveCount(0);
  await menu.getByRole("button", { name: /곡 라이브러리/ }).click();
  await expect(page.locator(".score-toolbar")).toContainText("Revision 1");
  await expect(page.locator(".note-list button").first()).toBeDisabled();
  await page.getByRole("button", { name: "코드", exact: true }).click();
  await expect(page.locator(".chord-note-list button").first()).toBeDisabled();
  await expect(page.locator(".chord-editor")).toHaveCount(0);

  releaseRhythm();
  await expect(page.locator(".score-toolbar")).toContainText("Revision 2");
  await expect(page.locator(".chord-note-list button")).toHaveCount(3);
  await expect(page.locator(".chord-note-list button.active")).toHaveCount(0);
  await expect(page.locator(".chord-note-list button").first()).toBeEnabled();
});

for (const mismatch of ["preview", "song revision", "structure"] as const) {
  test(`a mismatched ${mismatch} blocks positional edits until a coherent snapshot is loaded`, async ({ page }) => {
    const api = await setup(page);
    const originalSong = { ...api.song };
    const stalePath = mismatch === "preview" ? "/score" : mismatch === "structure" ? "/structure" : "";
    const pattern = `**/api/songs/song-1${stalePath}`;
    const stale = (route: Route) => {
      if (mismatch === "preview") return route.fulfill({
        contentType: "application/xml", body: xml, headers: { ETag: `"${scoreSha256(revisedXml(2))}"` },
      });
      if (mismatch === "structure") return route.fulfill({
        json: { ...scoreSnapshot(api.song, xml), measures: [] },
      });
      return route.fulfill({ json: originalSong });
    };
    await page.route(pattern, stale);
    await page.locator(".note-list button").first().click();
    await page.getByRole("button", { name: "음표 나누기" }).click();
    await expect(page.locator(".workspace-message")).toContainText("악보를 불러오는 중 변경되었습니다.");
    await expect(page.locator(".score-toolbar")).toContainText("Revision 1");
    await expect(page.locator(".note-list button")).toHaveCount(2);
    await expect(page.locator(".note-list button.active")).toHaveCount(0);
    await expect(page.locator(".note-list button").first()).toBeDisabled();
    await expect(page.locator(".note-rhythm-edit")).toHaveCount(0);

    await page.unroute(pattern, stale);
    await page.getByRole("button", { name: "악보 새로고침", exact: true }).click();
    await expect(page.locator(".score-toolbar")).toContainText("Revision 2");
    await expect(page.locator(".note-list button")).toHaveCount(3);
    await expect(page.locator(".note-list button").first()).toBeEnabled();
    await expect(page.locator(".note-list button.active")).toHaveCount(0);
  });
}

test("a stale positional delete sends its snapshot stamps and clears the selection on conflict", async ({ page }) => {
  const api = await setup(page);
  let query: URLSearchParams | undefined;
  await page.route("**/api/songs/song-1/notes/p0-m0-n0?*", route => {
    expect(route.request().method()).toBe("DELETE");
    query = new URL(route.request().url()).searchParams;
    api.advance();
    return route.fulfill({ status: 409, json: { detail: "Song changed. Reload and retry." } });
  });
  await page.locator(".note-list button").first().click();
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "선택 음표 삭제", exact: true }).click();
  await expect(page.locator(".workspace-message")).toContainText("음표나 마디를 다시 선택하세요.");
  expect(query).toEqual(new URLSearchParams({
    expected_revision: "1", expected_score_sha256: sha, expected_generation: "0",
  }));
  await expect(page.locator(".score-toolbar")).toContainText("Revision 2");
  await expect(page.locator(".note-list button.active")).toHaveCount(0);
  await expect(page.locator(".note-list button").first()).toBeEnabled();
});

test("a failed reload after a committed edit blocks stale positional edits until refresh", async ({ page }) => {
  await setup(page);
  await page.locator(".note-list button").first().click();
  const fail = (route: Route) => route.fulfill({ status: 500 });
  await page.route("**/api/songs/song-1/structure", fail);
  await page.getByRole("button", { name: "음표 나누기" }).click();
  await expect(page.getByRole("status").filter({ hasText: "수정 결과를 확인하려면" })).toBeVisible();
  await expect(page.locator(".note-list button").first()).toBeDisabled();
  await expect(page.getByRole("button", { name: "선택 음표 삭제" })).toHaveCount(0);
  await page.unroute("**/api/songs/song-1/structure", fail);
  await page.getByRole("button", { name: "악보 새로고침" }).click();
  await expect(page.locator(".score-toolbar")).toContainText("Revision 2");
  await expect(page.locator(".note-list button").first()).toBeEnabled();
  await expect(page.locator(".note-list button.active")).toHaveCount(0);
});
