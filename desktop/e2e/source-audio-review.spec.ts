import { readFileSync } from "node:fs";
import { resolve } from "node:path";
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
async function setup(page: Page, manyIssues = false) {
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
    else if (kind === "validate") { const order = ++validationRequests; if (holdValidate) { holdValidate = false; await gate; } await r.fulfill({ json: { song_id: id, revision: 1, ok: true, issues: Array.from({ length: manyIssues ? 12 : 1 }, (_, index) => ({ severity: "warning", source: "vocal_acoustic", category: "음역", message: `검토 ${order}-${index}`, start_seconds: 1, end_seconds: 2 })), policy: { llm_is_advisory: true, auto_edit: false } } }); }
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
  const config = JSON.parse(readFileSync(resolve(process.cwd(), "src-tauri/tauri.conf.json"), "utf8"));
  const mediaPolicy = (config.app.security.csp as string).split(";").map(item => item.trim()).find(item => item.startsWith("media-src "));
  expect(mediaPolicy).toBe("media-src 'self' blob:");
  await page.evaluate((policy) => {
    const meta = document.createElement("meta");
    meta.httpEquiv = "Content-Security-Policy";
    meta.content = policy;
    document.head.append(meta);
  }, mediaPolicy!);
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
  await expect(modal.locator(".validation-issue p")).toHaveText("검토 2-0");
  await modal.getByRole("button", { name: "원음 구간 확인" }).click();
  const oldResponse = page.waitForResponse(/\/api\/songs\/song-a\/validate$/);
  api.release();
  await (await oldResponse).finished();
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => resolve())));
  await expect(modal.locator(".validation-issue p")).toHaveText("검토 2-0");
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
  for (const [label, width, height] of [["desktop", 1240, 900], ["minimum", 920, 680]] as const) {
    await page.setViewportSize({ width, height });
    await page.reload();
    await expect(page.locator(".score-toolbar h2")).toHaveText("song-a");
    const review = page.getByLabel("원음 검수");
    await review.scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath(`source-audio-${label}-empty.png`) });
    api.setStatus(404);
    await review.getByRole("button", { name: "원음 불러오기" }).click();
    await expect(review).toContainText("보존된 원음이 없습니다");
    const contrast = await review.evaluate((element) => {
      const luminance = (color: string) => {
        const rgb = color.match(/\d+/g)!.slice(0, 3).map(Number).map(value => {
          const n = value / 255;
          return n <= .04045 ? n / 12.92 : ((n + .055) / 1.055) ** 2.4;
        });
        return .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2];
      };
      const background = luminance(getComputedStyle(element.closest('.score-workbench')!).backgroundColor);
      return [element.querySelector('strong')!, element.querySelector('[role=status]')!].map(node => {
        const foreground = luminance(getComputedStyle(node).color);
        return (Math.max(foreground, background) + .05) / (Math.min(foreground, background) + .05);
      });
    });
    expect(Math.min(...contrast)).toBeGreaterThanOrEqual(4.5);
    await page.screenshot({ path: testInfo.outputPath(`source-audio-${label}-error.png`) });
    api.setStatus(200);
    await page.getByRole("button", { name: "악보 검증" }).click();
    const modal = page.getByRole("dialog", { name: "악보 검증" });
    await modal.getByRole("button", { name: "현재 악보 검증" }).click();
    await modal.getByRole("button", { name: "원음 구간 확인" }).click();
    await expect(modal.getByLabel("원음 검수")).toBeFocused();
    await expect(modal.getByLabel("원음 검수")).toBeInViewport();
    await modal.getByRole("button", { name: "원음 불러오기" }).click();
    await expect(modal.getByLabel("원음 재생")).toBeVisible();
    await expect(modal).toContainText("확인 구간 0.70–2.30초");
    await expect(modal.getByLabel("원음 검수")).toBeInViewport();
    const modalContrast = await modal.getByLabel("원음 검수").evaluate((element) => {
      const luminance = (color: string) => {
        const rgb = color.match(/\d+/g)!.slice(0, 3).map(Number).map(value => {
          const n = value / 255;
          return n <= .04045 ? n / 12.92 : ((n + .055) / 1.055) ** 2.4;
        });
        return .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2];
      };
      const background = luminance(getComputedStyle(element.closest('.validation-modal')!).backgroundColor);
      return [element.querySelector('strong')!, element.querySelector('.source-audio-clip p')!].map(node => {
        const foreground = luminance(getComputedStyle(node).color);
        return (Math.max(foreground, background) + .05) / (Math.min(foreground, background) + .05);
      });
    });
    expect(Math.min(...modalContrast)).toBeGreaterThanOrEqual(4.5);
    const modalBox = await modal.boundingBox();
    const playerBox = await modal.getByLabel("원음 재생").boundingBox();
    const reviewBox = await modal.getByLabel("원음 검수").boundingBox();
    expect(modalBox && playerBox && reviewBox && [modalBox, playerBox, reviewBox].every(box => box.x >= 0 && box.x + box.width <= width)).toBeTruthy();
    await page.screenshot({ path: testInfo.outputPath(`source-audio-${label}-success.png`) });
    const actionBox = await modal.getByRole("button", { name: "원음 구간 확인" }).boundingBox();
    if (actionBox && (actionBox.y < 0 || actionBox.y + actionBox.height > height)) {
      await modal.getByRole("button", { name: "원음 구간 확인" }).scrollIntoViewIfNeeded();
      await page.screenshot({ path: testInfo.outputPath(`source-audio-${label}-action.png`) });
    }
    await modal.getByRole("button", { name: "닫기" }).click();
  }
  // A 390px viewport is a dialog-only stress case, below the supported window minimum.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "악보 검증" }).click();
  const modal = page.getByRole("dialog", { name: "악보 검증" });
  await modal.getByRole("button", { name: "현재 악보 검증" }).click();
  await modal.getByRole("button", { name: "원음 구간 확인" }).click();
  await expect(modal.getByLabel("원음 검수")).toBeFocused();
  await modal.getByRole("button", { name: "원음 불러오기" }).click();
  await expect(modal.getByLabel("원음 재생")).toBeVisible();
  await expect(modal.getByLabel("원음 검수")).toBeInViewport();
  const box = await modal.boundingBox();
  expect(box && box.x >= 0 && box.x + box.width <= 390).toBeTruthy();
  await page.screenshot({ path: testInfo.outputPath("source-audio-stress-success.png") });
  await modal.getByRole("button", { name: "원음 구간 확인" }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath("source-audio-stress-action.png") });
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

test("failed reload clears the previous player and clip controls", async ({ page }) => {
  await page.addInitScript(() => {
    const original = URL.revokeObjectURL.bind(URL);
    (window as any).__revoked = [];
    URL.revokeObjectURL = (value) => { (window as any).__revoked.push(value); original(value); };
  });
  const api = await setup(page);
  await page.getByRole("button", { name: "악보 검증" }).click();
  const modal = page.getByRole("dialog", { name: "악보 검증" });
  await modal.getByRole("button", { name: "현재 악보 검증" }).click();
  await modal.getByRole("button", { name: "원음 구간 확인" }).click();
  await modal.getByRole("button", { name: "원음 불러오기" }).click();
  const player = modal.getByLabel("원음 재생");
  await expect(modal.getByRole("button", { name: "구간 재생" })).toBeVisible();
  const blob = await player.evaluate((element: HTMLAudioElement) => { (window as any).__oldAudio = element; return element.src; });
  await modal.getByRole("button", { name: "구간 재생" }).click();
  await expect.poll(() => player.evaluate((element: HTMLAudioElement) => element.paused)).toBe(false);
  api.setStatus(409);
  await modal.getByRole("button", { name: "원음 다시 불러오기" }).click();
  await expect(modal).toContainText("악보가 변경되었습니다");
  await expect(modal.getByLabel("원음 재생")).toHaveCount(0);
  await expect(modal.getByRole("button", { name: "구간 재생" })).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => (window as any).__oldAudio.paused)).toBe(true);
  await expect.poll(() => page.evaluate((value) => (window as any).__revoked.includes(value), blob)).toBe(true);
});


test("last warning brings its source player into view without autoplay", async ({ page }) => {
  await setup(page, true);
  await page.getByRole("button", { name: "악보 검증" }).click();
  const modal = page.getByRole("dialog", { name: "악보 검증" });
  await modal.getByRole("button", { name: "현재 악보 검증" }).click();
  const buttons = modal.getByRole("button", { name: "원음 구간 확인" });
  await expect(buttons).toHaveCount(12);
  await buttons.last().click();
  const review = modal.getByLabel("원음 검수");
  await expect(review).toBeFocused();
  await expect(review).toBeInViewport();
  await expect(review.getByLabel("원음 재생")).toHaveCount(0);
});

test("playing a clip pauses the workspace player and closing does not resume it", async ({ page }) => {
  await setup(page);
  const workspace = page.locator(".score-workbench").getByLabel("원음 검수");
  await workspace.getByRole("button", { name: "원음 불러오기" }).click();
  const original = workspace.getByLabel("원음 재생");
  await original.evaluate((element: HTMLAudioElement) => element.play());
  await expect.poll(() => original.evaluate((element: HTMLAudioElement) => element.paused)).toBe(false);
  await page.getByRole("button", { name: "악보 검증" }).click();
  const modal = page.getByRole("dialog", { name: "악보 검증" });
  await modal.getByRole("button", { name: "현재 악보 검증" }).click();
  await modal.getByRole("button", { name: "원음 구간 확인" }).click();
  await modal.getByRole("button", { name: "원음 불러오기" }).click();
  const clipped = modal.getByLabel("원음 재생");
  await clipped.evaluate((element: HTMLAudioElement) => { (window as any).__clipAudio = element; });
  await modal.getByRole("button", { name: "구간 재생" }).click();
  await expect.poll(() => clipped.evaluate((element: HTMLAudioElement) => element.paused)).toBe(false);
  await expect.poll(() => original.evaluate((element: HTMLAudioElement) => element.paused)).toBe(true);
  await modal.getByRole("button", { name: "닫기" }).click();
  await expect.poll(() => page.evaluate(() => (window as any).__clipAudio.paused)).toBe(true);
  await expect.poll(() => original.evaluate((element: HTMLAudioElement) => element.paused)).toBe(true);
});
