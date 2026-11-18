import { expect, test, type Page } from "@playwright/test";

function wav() {
  const rate = 8000, size = rate * 4 * 2;
  const data = Buffer.alloc(44 + size);
  data.write("RIFF", 0); data.writeUInt32LE(36 + size, 4); data.write("WAVEfmt ", 8);
  data.writeUInt32LE(16, 16); data.writeUInt16LE(1, 20); data.writeUInt16LE(1, 22);
  data.writeUInt32LE(rate, 24); data.writeUInt32LE(rate * 2, 28); data.writeUInt16LE(2, 32);
  data.writeUInt16LE(16, 34); data.write("data", 36); data.writeUInt32LE(size, 40);
  return data;
}
async function setup(page: Page) {
  let audioStatus = 200;
  let holdValidate = false;
  let releaseValidation = () => {};
  let gate = Promise.resolve();
  let audioRequests = 0;
  let validationRequests = 0;
  let holdAudio = false;
  let releaseAudio = () => {};
  let audioGate = Promise.resolve();
  await page.route("**/api/health", r => r.fulfill({ json: { status: "ok", device_plan: {}, preflight: { ok: true, missing: [], tools: {} }, presets: { recommended: "quality", presets: [] }, system: {} } }));
  await page.route("**/api/engines", r => r.fulfill({ json: { usage_mode: "personal", engines: [], recommendation: null } }));
  const song = (id: string) => ({ song_id: id, title: id, source_kind: "notation", revision: 1, exports: { pdf: false, midi: false, musicxml: false }, parts: [] });
  await page.route("**/api/songs", r => r.fulfill({ json: { songs: [song("song-a"), song("song-b")] } }));
  await page.route("**/api/validation/settings", r => r.fulfill({ json: { enabled: false, base_url: "http://127.0.0.1:11434/v1", model: "stub", visual_enabled: false, visual_model: "stub", visual_max_pages: 2, audio_enabled: false, audio_threshold: .42 } }));
  await page.route(/\/api\/songs\/(song-a|song-b)(?:\/(notes|structure|score|publication|validate|source-audio))?(?:\?.*)?$/, async r => {
    const match = new URL(r.request().url()).pathname.match(/\/api\/songs\/(song-a|song-b)(?:\/(.*))?$/)!;
    const id = match[1], kind = match[2] ?? "detail";
    if (kind === "source-audio") { audioRequests++; if (holdAudio) { holdAudio = false; await audioGate; } await r.fulfill(audioStatus === 200 ? { status: 200, contentType: "audio/wav", body: wav() } : { status: audioStatus }).catch(() => undefined); }
    else if (kind === "validate") { const order = ++validationRequests; if (holdValidate) { holdValidate = false; await gate; } await r.fulfill({ json: { song_id: id, revision: 1, ok: true, issues: [{ severity: "warning", source: "vocal_acoustic", category: "음역", message: `검토 ${order}`, start_seconds: 1, end_seconds: 2 }], policy: { llm_is_advisory: true, auto_edit: false } } }); }
    else if (kind === "notes") await r.fulfill({ json: { song: song(id), parts: [], notes: [], chords: [] } });
    else if (kind === "structure") await r.fulfill({ json: { measures: [] } });
    else if (kind === "score") await r.fulfill({ contentType: "application/xml", body: '<score-partwise><part-list><score-part id="P1"><part-name>Voice</part-name></score-part></part-list><part id="P1"><measure number="1"><attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes><note><rest/><duration>4</duration><type>whole</type></note></measure></part></score-partwise>' });
    else if (kind === "publication") await r.fulfill({ json: { settings: {} } });
    else await r.fulfill({ json: song(id) });
  });
  await page.addInitScript(() => { localStorage.setItem("ast-onboarding-v1", "done"); localStorage.setItem("ast-setup-center-v2", "dismissed"); localStorage.setItem("ast-section", "songs"); });
  await page.goto("/");
  await expect(page.locator(".score-toolbar h2")).toHaveText("song-a");
  return { setStatus: (v: number) => { audioStatus = v; }, requests: () => audioRequests, validations: () => validationRequests, holdAudio: () => { holdAudio = true; audioGate = new Promise<void>(resolve => { releaseAudio = resolve; }); }, releaseAudio: () => releaseAudio(), hold: () => { holdValidate = true; gate = new Promise<void>(resolve => { releaseValidation = resolve; }); }, release: () => releaseValidation() };
}

test("on-demand audio and acoustic clip repeat", async ({ page }) => {
  const api = await setup(page);
  expect(api.requests()).toBe(0);
  await page.getByRole("button", { name: "악보 검증" }).click();
  const modal = page.getByRole("dialog", { name: "악보 검증" });
  await modal.getByRole("button", { name: "현재 악보 검증" }).click();
  await modal.getByRole("button", { name: "원음 구간 확인" }).click();
  await modal.getByRole("button", { name: "원음 불러오기" }).click();
  await expect(modal.getByLabel("원음 재생")).toBeVisible();
  await expect(modal).toContainText("확인 구간 0.70–2.30초");
  await modal.getByLabel("반복").check();
  await modal.getByRole("button", { name: "구간 재생" }).click();
  const player = modal.getByLabel("원음 재생");
  await expect.poll(() => player.evaluate((e: HTMLAudioElement) => e.currentTime)).toBeGreaterThanOrEqual(.7);
  await expect.poll(() => player.evaluate((e: HTMLAudioElement) => e.paused)).toBe(false);
  await expect.poll(() => player.evaluate((e: HTMLAudioElement) => e.currentTime)).toBeGreaterThan(.75);
  await player.evaluate((e: HTMLAudioElement) => { e.currentTime = 2.31; });
  await expect.poll(() => player.evaluate((e: HTMLAudioElement) => e.currentTime), { timeout: 3000 }).toBeLessThan(1.5);
  expect(api.requests()).toBe(1);
});

test("errors and late validation do not follow another song", async ({ page }) => {
  const api = await setup(page);
  api.setStatus(404);
  await page.getByLabel("원음 검수").getByRole("button", { name: "원음 불러오기" }).click();
  await expect(page.getByLabel("원음 검수")).toContainText("보존된 원음이 없습니다");
  api.setStatus(409);
  await page.getByLabel("원음 검수").getByRole("button", { name: "원음 불러오기" }).click();
  await expect(page.getByLabel("원음 검수")).toContainText("악보가 변경되었습니다");
  api.hold();
  await page.getByRole("button", { name: "악보 검증" }).click();
  await page.getByRole("dialog", { name: "악보 검증" }).getByRole("button", { name: "현재 악보 검증" }).click();
  await page.locator(".validation-modal header button").click();
  await page.locator(".song-item").filter({ hasText: "song-b" }).click();
  await expect(page.locator(".score-toolbar h2")).toHaveText("song-b");
  api.release();
  await page.getByRole("button", { name: "악보 검증" }).click();
  await expect(page.getByRole("dialog", { name: "악보 검증" }).locator(".validation-issue")).toHaveCount(0);
});


test("old A validation cannot replace a newer A report after A-B-A", async ({ page }) => {
  const api = await setup(page);
  api.hold();
  await page.getByRole("button", { name: "악보 검증" }).click();
  await page.getByRole("dialog", { name: "악보 검증" }).getByRole("button", { name: "현재 악보 검증" }).click();
  await expect.poll(api.validations).toBe(1);
  await page.locator(".validation-modal header button").click();
  await page.locator(".song-item").filter({ hasText: "song-b" }).click();
  await expect(page.locator(".score-toolbar h2")).toHaveText("song-b");
  await page.locator(".song-item").filter({ hasText: "song-a" }).click();
  await expect(page.locator(".score-toolbar h2")).toHaveText("song-a");
  await page.getByRole("button", { name: "악보 검증" }).click();
  const modal = page.getByRole("dialog", { name: "악보 검증" });
  await modal.getByRole("button", { name: "현재 악보 검증" }).click();
  await expect(modal.locator(".validation-issue")).toHaveCount(1);
  await expect(modal.locator(".validation-issue p")).toHaveText("검토 2");
  await modal.getByRole("button", { name: "원음 구간 확인" }).click();
  const oldResponse = page.waitForResponse(/\/api\/songs\/song-a\/validate$/);
  api.release();
  await (await oldResponse).finished();
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => resolve())));
  await expect(modal.locator(".validation-issue p")).toHaveText("검토 2");
  await expect(modal).toContainText("악보 시간표로 찾은 구간");
});

test("switching songs pauses the detached player and revokes its blob", async ({ page }) => {
  await page.addInitScript(() => {
    const original = URL.revokeObjectURL.bind(URL);
    (window as any).__revoked = [];
    URL.revokeObjectURL = (value) => { (window as any).__revoked.push(value); original(value); };
  });
  await setup(page);
  const review = page.getByLabel("원음 검수");
  await review.getByRole("button", { name: "원음 불러오기" }).click();
  const player = review.getByLabel("원음 재생");
  await expect(player).toBeVisible();
  const blob = await player.evaluate((e: HTMLAudioElement) => { (window as any).__oldAudio = e; return e.src; });
  await player.evaluate((e: HTMLAudioElement) => e.play());
  await expect.poll(() => player.evaluate((e: HTMLAudioElement) => e.paused)).toBe(false);
  await page.locator(".song-item").filter({ hasText: "song-b" }).click();
  await expect(page.locator(".score-toolbar h2")).toHaveText("song-b");
  await expect.poll(() => page.evaluate(() => (window as any).__oldAudio.paused)).toBe(true);
  await expect.poll(() => page.evaluate((value) => (window as any).__revoked.includes(value), blob)).toBe(true);
});

test("owned fixture screenshots", async ({ page }, testInfo) => {
  const api = await setup(page);
  for (const [label, width, height] of [["desktop", 1240, 900], ["small", 390, 844]] as const) {
    await page.setViewportSize({ width, height });
    await page.reload();
    await expect(page.locator(".score-toolbar h2")).toHaveText("song-a");
    const review = page.getByLabel("원음 검수");
    await review.scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath(`source-audio-${label}-empty.png`) });
    api.setStatus(404);
    await review.getByRole("button", { name: "원음 불러오기" }).click();
    await expect(review).toContainText("보존된 원음이 없습니다");
    await page.screenshot({ path: testInfo.outputPath(`source-audio-${label}-error.png`) });
    api.setStatus(200);
    await page.getByRole("button", { name: "악보 검증" }).click();
    const modal = page.getByRole("dialog", { name: "악보 검증" });
    await modal.getByRole("button", { name: "현재 악보 검증" }).click();
    await modal.getByRole("button", { name: "원음 구간 확인" }).click();
    await modal.getByRole("button", { name: "원음 불러오기" }).click();
    await expect(modal.getByLabel("원음 재생")).toBeVisible();
    await expect(modal).toContainText("확인 구간 0.70–2.30초");
    await modal.getByLabel("원음 검수").scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath(`source-audio-${label}-success.png`) });
    await modal.getByRole("button", { name: "닫기" }).click();
  }
});


test("late blob is ignored after song switch", async ({ page }) => {
  const api = await setup(page);
  api.holdAudio();
  await page.getByLabel("원음 검수").getByRole("button", { name: "원음 불러오기" }).click();
  await expect.poll(api.requests).toBe(1);
  await page.locator(".song-item").filter({ hasText: "song-b" }).click();
  await expect(page.locator(".score-toolbar h2")).toHaveText("song-b");
  api.releaseAudio();
  await page.waitForTimeout(200);
  await expect(page.getByLabel("원음 검수").getByLabel("원음 재생")).toHaveCount(0);
});
