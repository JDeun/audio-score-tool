import { expect, test } from "@playwright/test";

type SongId = "song-a" | "song-b";

function song(id: SongId) {
  return {
    song_id: id,
    title: id === "song-a" ? "Song A" : "Song B",
    artist: "",
    source_kind: "notation",
    revision: 1,
    updated_at: "2026-11-06T00:00:00Z",
    exports: { pdf: false, midi: false, musicxml: false },
    parts: [],
  };
}

function scoreXml(title: string) {
  return `<?xml version="1.0" encoding="UTF-8"?>
    <score-partwise version="4.0">
      <work><work-title>${title}</work-title></work>
      <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
      <part id="P1"><measure number="1">
        <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
        <note><rest/><duration>4</duration><type>whole</type></note>
      </measure></part>
    </score-partwise>`;
}

test("rapid A→B selection ignores late A responses and targets the right song in auxiliary controllers", async ({ page }) => {
  const pathsHeldForA: string[] = [];
  const validationTargets: string[] = [];
  let bDetailReads = 0;
  let releaseA!: () => void;
  const holdA = new Promise<void>((resolve) => { releaseA = resolve; });

  await page.route("**/api/health", (route) => route.fulfill({
    json: {
      status: "ok", device_plan: { muscriptor_device: "cpu" },
      preflight: { ok: true, missing: [], tools: {} },
      presets: { recommended: "quality", presets: [] },
      system: { hf_authenticated: false, jobs_bytes: 0, disk_free_bytes: 1000 },
    },
  }));
  await page.route("**/api/songs", (route) => route.fulfill({
    json: { songs: [song("song-a"), song("song-b")] },
  }));
  await page.route("**/api/engines", (route) => route.fulfill({
    json: { usage_mode: "personal", engines: [], recommendation: null },
  }));
  await page.route("**/api/validation/settings", (route) => route.fulfill({
    json: {
      enabled: false, base_url: "http://127.0.0.1:11434/v1", model: "stub",
      visual_enabled: false, visual_model: "stub", visual_max_pages: 2,
      audio_enabled: false, audio_threshold: 0.42,
    },
  }));
  await page.route(/\/api\/songs\/(song-a|song-b)(?:\/(?:notes|structure|score|publication|validate))?$/, async (route) => {
    const path = new URL(route.request().url()).pathname;
    const match = path.match(/^\/api\/songs\/(song-a|song-b)(?:\/(notes|structure|score|publication|validate))?$/);
    if (!match) throw new Error(`Unexpected song route: ${path}`);
    const id = match[1] as SongId;
    const kind = match[2] ?? "detail";
    if (id === "song-a") {
      pathsHeldForA.push(path);
      await holdA;
    }
    if (id === "song-b" && kind === "detail") bDetailReads += 1;
    if (kind === "validate") {
      validationTargets.push(id);
      expect(route.request().postDataJSON().use_audio).toBe(true);
      await route.fulfill({
        json: {
          song_id: id, revision: 1, ok: true,
          issues: [{ severity: "warning", source: "vocal_acoustic", category: "octave discrepancy", message: "보컬 음역 재검토", start_seconds: 12, end_seconds: 13 }],
          acoustic: { melody: { predicted_notes: 100, compared_notes: 10, octave_suspects: 2 }, chords: { compared_intervals: 20, spectral_warnings: 3 } },
          policy: { llm_is_advisory: true, auto_edit: false },
        },
      });
    } else if (kind === "notes") {
      await route.fulfill({ json: { song: song(id), parts: [], notes: [], chords: [] } });
    } else if (kind === "structure") {
      await route.fulfill({ json: { measures: [] } });
    } else if (kind === "score") {
      await route.fulfill({ contentType: "application/xml", body: scoreXml(song(id).title) });
    } else if (kind === "publication") {
      await route.fulfill({ json: { settings: {} } });
    } else {
      await route.fulfill({ json: song(id) });
    }
  });

  await page.addInitScript(() => {
    localStorage.setItem("ast-onboarding-v1", "done");
    localStorage.setItem("ast-setup-center-v2", "dismissed");
    localStorage.setItem("ast-section", "songs");
  });
  await page.goto("/");
  await expect(page.locator(".song-item")).toHaveCount(2);
  await expect.poll(() => pathsHeldForA.length).toBeGreaterThan(0);
  await page.locator(".song-item").filter({ hasText: "Song B" }).click();
  await expect(page.locator(".score-toolbar h2")).toHaveText("Song B");

  releaseA();
  await page.waitForTimeout(100);
  await expect(page.locator(".score-toolbar h2")).toHaveText("Song B");

  await page.getByRole("button", { name: "악보 검증" }).click();
  const validation = page.getByRole("dialog", { name: "악보 검증" });
  await expect(validation).toContainText("Song B");
  await validation.getByRole("checkbox", { name: "원음 ↔ 현재 악보 · 보컬 음역·코드·재합성 대조" }).check();
  await validation.getByRole("button", { name: "현재 악보 검증" }).click();
  await expect.poll(() => validationTargets).toEqual(["song-b"]);
  await expect(validation).toContainText("보컬 대조 10/100음");
  await expect(validation).toContainText("전곡 정확도가 아닙니다");
  await expect(validation.locator(".validation-issue")).toContainText("Audio evidence");
  await validation.getByRole("button", { name: "닫기" }).click();

  const previousReads = bDetailReads;
  await page.getByRole("button", { name: "곡 정보", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "곡 정보 보강" })).toBeVisible();
  await expect.poll(() => bDetailReads).toBeGreaterThan(previousReads);
  await page.getByRole("dialog", { name: "곡 정보 보강" }).getByRole("button", { name: "곡 정보 보강 닫기" }).click();

  await page.getByRole("button", { name: "최종 파일 생성" }).click();
  const exportDialog = page.getByRole("dialog", { name: "최종 파일 생성" });
  await expect(exportDialog).toContainText("Song B");
});
