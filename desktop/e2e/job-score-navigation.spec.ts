import { expect, test, type Page, type Route } from "@playwright/test";

type FixtureJob = {
  job_id: string;
  filename: string;
  status: string;
  kind?: string;
  progress?: number;
  score_mode?: string;
};

const SCORE_XML = `<?xml version="1.0" encoding="utf-8"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1"><measure number="1">
    <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
    <note><rest/><duration>4</duration><type>whole</type></note>
  </measure></part>
</score-partwise>`;

const SONGS = [
  { song_id: "song-a", job_id: "job-a", title: "First unrelated score" },
  { song_id: "song-b", job_id: "job-b", title: "Requested score" },
].map((song) => ({
  ...song, artist: "", source_kind: "transcription", revision: 1,
  exports: { pdf: false, midi: false, musicxml: false }, parts: [],
}));

async function prepare(page: Page, options: {
  section?: string; jobs?: () => FixtureJob[]; demucs?: boolean;
} = {}) {
  // Only connector/API boundaries are stubbed; navigation and request
  // serialization run through the production React components.
  await page.route("**/api/**", (route) => route.fulfill({ status: 404, json: {} }));
  const health = {
    status: "ok", packaged_runtime: false, usage_mode: "personal",
    device_plan: { muscriptor_device: "cpu" },
    preflight: { ok: true, missing: [], tools: { whisperx: false, demucs: options.demucs ?? true } },
    youtube: { ready: true }, presets: { recommended: "balanced", presets: [] },
    data_dir: "/tmp/ast", system: { hf_authenticated: false, jobs_bytes: 0, disk_free_bytes: 1000 },
  };
  await page.route("**/api/health", (route) => route.fulfill({ json: health }));
  await page.route("**/api/setup", (route) => route.fulfill({
    json: { preflight: health.preflight, tool_paths: {}, instructions: { hf_note: "" } },
  }));
  await page.route("**/api/jobs?limit=100", (route) => route.fulfill({
    json: { jobs: options.jobs?.() ?? [] },
  }));
  await page.route("**/api/jobs/*", (route) => {
    const jobId = new URL(route.request().url()).pathname.split("/").pop();
    const job = options.jobs?.().find((item) => item.job_id === jobId);
    return route.fulfill({ status: job ? 200 : 404, json: job ?? {} });
  });
  await page.route("**/api/songs", (route) => route.fulfill({ json: { songs: SONGS } }));
  await page.route("**/api/songs/**", (route) => {
    const [, , , songId, kind] = new URL(route.request().url()).pathname.split("/");
    const song = SONGS.find((item) => item.song_id === songId);
    if (!song) return route.fulfill({ status: 404, json: {} });
    if (kind === "score") return route.fulfill({ contentType: "application/xml", body: SCORE_XML });
    if (kind === "notes") return route.fulfill({ json: { song, parts: [], notes: [], chords: [] } });
    if (kind === "structure") return route.fulfill({ json: { measures: [] } });
    if (kind === "publication") return route.fulfill({ json: { settings: {} } });
    return route.fulfill({ json: song });
  });
  await page.addInitScript((section) => {
    localStorage.setItem("ast-onboarding-v1", "done");
    localStorage.setItem("ast-setup-center-v2", "dismissed");
    if (!localStorage.getItem("ast-section")) localStorage.setItem("ast-section", section);
  }, options.section ?? "new");
}

function completed(jobId = "job-b"): FixtureJob {
  return { job_id: jobId, filename: `${jobId}.wav`, status: "done", kind: "transcription", progress: 100 };
}

const menu = (page: Page, name: string) => page.getByRole("navigation", { name: "주요 메뉴" })
  .getByRole("button", { name: new RegExp(name) });

test("history opens its own completed score, retaining that selection after reload", async ({ page }) => {
  await prepare(page, { section: "history", jobs: () => [completed()] });
  await page.goto("/");
  await page.locator(".premium-job-row").getByRole("button", { name: "악보 편집", exact: true }).click();
  await expect(page.locator(".score-toolbar h2")).toHaveText("Requested score");
  await expect(page.locator(".song-item.active")).toContainText("Requested score");
  await page.locator(".song-item.active").click();
  await expect(page.locator(".score-toolbar h2")).toHaveText("Requested score");
  await page.reload();
  await expect(page.locator(".score-toolbar h2")).toHaveText("Requested score");
  await menu(page, "새 악보").click();
  await menu(page, "곡 라이브러리").click();
  await expect(page.locator(".score-toolbar h2")).toHaveText("Requested score");
});

test("a deleted job result never falls back to an unrelated score", async ({ page }) => {
  await prepare(page, { section: "history", jobs: () => [completed("deleted-job")] });
  await page.goto("/");
  await page.getByRole("button", { name: "악보 편집", exact: true }).click();
  await expect(page.locator(".workspace-message")).toContainText("이 작업의 악보를 찾을 수 없습니다");
  await expect(page.locator(".score-toolbar h2")).toHaveCount(0);
  await expect(page.locator(".song-item.active")).toHaveCount(0);
  await page.locator(".song-item").filter({ hasText: "Requested score" }).click();
  await expect(page.locator(".score-toolbar h2")).toHaveText("Requested score");
});

test("running job tracking survives library visits and reload, then opens its own result", async ({ page }) => {
  const job = { ...completed(), status: "running", progress: 41 };
  await prepare(page, { jobs: () => [job] });
  await page.goto("/");
  await expect(page.locator(".current-job")).toContainText("job-b.wav");
  await expect(page.locator(".current-job [role=progressbar]")).toHaveAttribute("aria-valuenow", "41");
  await menu(page, "곡 라이브러리").click();
  await expect(page.locator(".score-toolbar h2")).toHaveText("First unrelated score");
  job.progress = 67;
  await menu(page, "새 악보").click();
  await expect(page.locator(".current-job [role=progressbar]")).toHaveAttribute("aria-valuenow", "67");
  await page.reload();
  await expect(page.locator(".current-job [role=progressbar]")).toHaveAttribute("aria-valuenow", "67");
  job.status = "done";
  job.progress = 100;
  await page.getByRole("button", { name: "곡 라이브러리에서 편집" }).click();
  await expect(page.locator(".score-toolbar h2")).toHaveText("Requested score");
});

test("notation import opens the matching score without reloading the application", async ({ page }) => {
  let imported = false;
  await prepare(page, { jobs: () => imported ? [{ ...completed(), kind: "notation-import" }] : [] });
  await page.route("**/api/import/notation", (route) => {
    imported = true;
    return route.fulfill({ status: 202, json: { job_id: "job-b", status: "queued" } });
  });
  await page.goto("/");
  let navigations = 0;
  page.on("framenavigated", (frame) => { if (frame === page.mainFrame()) navigations += 1; });
  await page.getByRole("tab", { name: "기존 악보 / MusicXML / MIDI" }).click();
  const importer = page.getByRole("dialog", { name: "기존 악보 가져오기" });
  await importer.locator('input[type="file"]').setInputFiles({
    name: "owned.musicxml", mimeType: "application/vnd.recordare.musicxml+xml", buffer: Buffer.from(SCORE_XML),
  });
  await importer.getByRole("button", { name: "악보 가져오기", exact: true }).click();
  await importer.getByRole("button", { name: "곡 라이브러리에서 검토" }).click();
  await expect(importer).toHaveCount(0);
  await expect(page.locator(".score-toolbar h2")).toHaveText("Requested score");
  expect(navigations).toBe(0);
});

test("late library responses cannot replace a newer job navigation", async ({ page }) => {
  await prepare(page, { section: "history", jobs: () => [completed("job-a"), completed()] });
  let hold = true;
  const held: Route[] = [];
  await page.route("**/api/songs", (route) => {
    if (hold) { held.push(route); return; }
    return route.fulfill({ json: { songs: SONGS } });
  });
  await page.goto("/");
  await page.locator(".premium-job-row").filter({ hasText: "job-a.wav" })
    .getByRole("button", { name: "악보 편집", exact: true }).click();
  await expect.poll(() => held.length).toBeGreaterThan(0);
  await menu(page, "작업 내역").click();
  hold = false;
  await page.locator(".premium-job-row").filter({ hasText: "job-b.wav" })
    .getByRole("button", { name: "악보 편집", exact: true }).click();
  await expect(page.locator(".score-toolbar h2")).toHaveText("Requested score");
  await Promise.all(held.map((route) => route.fulfill({ json: { songs: SONGS } })));
  await expect(page.locator(".score-toolbar h2")).toHaveText("Requested score");
  await expect(page.locator(".song-item.active")).toContainText("Requested score");
});

const MODES = [
  ["full", "전체 악보"],
  ["lead_sheet", "보컬 멜로디 + 코드"],
  ["guitar_vocal", "기타 + 보컬"],
] as const;

for (const source of ["file", "youtube"] as const) {
  for (const [mode, label] of MODES) {
    test(`${source} ${mode} serializes its mode and retries the saved job`, async ({ page }) => {
      const jobs: FixtureJob[] = [];
      const requests: string[] = [];
      const retries: string[] = [];
      await prepare(page, { jobs: () => jobs });
      await page.route("**/api/sources/youtube/inspect", (route) => route.fulfill({
        json: { title: "Mode fixture", webpage_url: "https://www.youtube.com/watch?v=abcdef12345" },
      }));
      await page.route(source === "file" ? "**/api/jobs" : "**/api/jobs/youtube", (route) => {
        const data = route.request().postData() ?? "";
        requests.push(data);
        const receivedMode = source === "youtube"
          ? String(route.request().postDataJSON().score_mode)
          : data.match(/name="score_mode"\r\n\r\n([^\r]+)/)?.[1];
        jobs.push({ job_id: "mode-job", filename: "mode.wav", status: "failed", score_mode: receivedMode });
        return route.fulfill({ status: 202, json: { job_id: "mode-job", status: "queued" } });
      });
      await page.route("**/api/jobs/mode-job/retry", (route) => {
        retries.push(route.request().method());
        jobs.unshift({ ...jobs[0], job_id: "retry-job", status: "running", progress: 29 });
        return route.fulfill({ status: 202, json: { job_id: "retry-job" } });
      });
      await page.goto("/");
      if (source === "file") {
        await page.locator('.premium-dropzone input[type="file"]').setInputFiles({
          name: "mode.wav", mimeType: "audio/wav", buffer: Buffer.from("fixture"),
        });
      } else {
        await page.getByRole("tab", { name: "YouTube 링크" }).click();
        await page.locator(".youtube-inline-row input").fill("https://www.youtube.com/watch?v=abcdef12345");
        await page.getByRole("button", { name: "링크 확인" }).click();
        await expect(page.locator(".source-preview-row")).toContainText("Mode fixture");
      }
      await page.locator(".score-mode-option").filter({ hasText: label }).getByRole("radio").check();
      await page.getByRole("button", { name: "자동 채보 시작" }).click();
      await expect.poll(() => requests.length).toBe(1);
      await expect.poll(() => jobs[0]?.score_mode).toBe(mode);
      await expect(page.locator(".current-job")).toHaveClass(/status-failed/);
      // Changing the new-job controls must not replace the original retry.
      await page.locator(".score-mode-option").filter({ hasText: "전체 악보" }).getByRole("radio").check();
      await menu(page, "작업 내역").click();
      await page.locator(".premium-job-row").getByRole("button", { name: "다시 실행" }).click();
      await expect.poll(() => retries).toEqual(["POST"]);
      const retried = page.locator(".premium-job-row").filter({ hasText: "진행 중" });
      await expect(retried).toContainText(mode === "full" ? "전체 악보" : mode === "lead_sheet" ? "보컬+코드" : "기타+보컬");
      await menu(page, "새 악보").click();
      await expect(page.locator(".current-job [role=progressbar]")).toHaveAttribute("aria-valuenow", "29");
      expect(requests).toHaveLength(1);
      expect(jobs[0].score_mode).toBe(mode);
    });
  }
}

test("stem score controls block submission without Demucs while full score remains available", async ({ page }) => {
  await prepare(page, { demucs: false });
  await page.goto("/");
  await page.locator('.premium-dropzone input[type="file"]').setInputFiles({
    name: "mode.wav", mimeType: "audio/wav", buffer: Buffer.from("fixture"),
  });
  for (const [, label] of MODES.slice(1)) {
    await page.locator(".score-mode-option").filter({ hasText: label }).getByRole("radio").check();
    await expect(page.getByRole("button", { name: "자동 채보 시작" })).toBeDisabled();
    await expect(page.locator(".score-mode-choices")).toContainText("Demucs가 미설치");
  }
  await page.locator(".score-mode-option").filter({ hasText: "전체 악보" }).getByRole("radio").check();
  await expect(page.getByRole("button", { name: "자동 채보 시작" })).toBeEnabled();
});
