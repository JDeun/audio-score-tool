import { expect, test, type Page } from "@playwright/test";

type Engine = {
  key: "mt3_infer" | "muscriptor" | "native";
  model?: string;
  name: string;
};

type FixtureJob = {
  job_id: string;
  filename: string;
  status: string;
  kind?: string;
  progress?: number;
  score_mode?: string;
  transcription_engine?: Engine["key"] | null;
  mt3_model?: string | null;
  muscriptor_model?: string | null;
};

async function prepare(page: Page, options: {
  engine: () => Engine;
  jobs: FixtureJob[];
  section?: string;
}) {
  await page.route("**/api/**", (route) => route.fulfill({ status: 404, json: {} }));
  const health = () => ({
    status: "ok", packaged_runtime: false, usage_mode: "personal",
    device_plan: { muscriptor_device: "cpu" },
    preflight: {
      ok: true, missing: [], tools: { whisperx: false, demucs: true },
      engine: options.engine(),
    },
    youtube: { ready: true }, presets: { recommended: "balanced", presets: [] },
    data_dir: "/tmp/ast", system: { hf_authenticated: false, jobs_bytes: 0, disk_free_bytes: 1000 },
  });
  await page.route("**/api/health", (route) => route.fulfill({ json: health() }));
  await page.route("**/api/setup", (route) => route.fulfill({
    json: { preflight: health().preflight, tool_paths: {}, instructions: { hf_note: "" } },
  }));
  await page.route("**/api/jobs?limit=100", (route) => route.fulfill({ json: { jobs: options.jobs } }));
  await page.route("**/api/jobs/*", (route) => {
    const id = new URL(route.request().url()).pathname.split("/").pop();
    const job = options.jobs.find((item) => item.job_id === id);
    return route.fulfill({ status: job ? 200 : 404, json: job ?? {} });
  });
  await page.addInitScript((section) => {
    localStorage.setItem("ast-onboarding-v1", "done");
    localStorage.setItem("ast-setup-center-v2", "dismissed");
    if (!localStorage.getItem("ast-section")) localStorage.setItem("ast-section", section);
  }, options.section ?? "new");
}

const menu = (page: Page, name: string) => page.getByRole("navigation", { name: "주요 메뉴" })
  .getByRole("button", { name: new RegExp(name) });

const quality = (page: Page) => page.locator(".transcription-options").getByRole("combobox").first();

async function chooseFile(page: Page) {
  await page.locator('.premium-dropzone input[type="file"]').setInputFiles({
    name: "owned.wav", mimeType: "audio/wav", buffer: Buffer.from("fixture; inference is mocked"),
  });
}

for (const source of ["file", "youtube"] as const) {
  test(`${source} keeps its admitted MT3 model visible after the default engine changes`, async ({ page }) => {
    const model = source === "file" ? "mr_mt3" : "yourmt3";
    const label = source === "file" ? "MR-MT3" : "YourMT3+";
    let engine: Engine = { key: "mt3_infer", model, name: "MT3-Infer" };
    const jobs: FixtureJob[] = [];
    const requests: string[] = [];
    await prepare(page, { engine: () => engine, jobs });
    await page.route("**/api/sources/youtube/inspect", (route) => route.fulfill({
      json: { title: "Owned YouTube fixture", webpage_url: "https://www.youtube.com/watch?v=abcdef12345" },
    }));
    await page.route(source === "file" ? "**/api/jobs" : "**/api/jobs/youtube", (route) => {
      requests.push(route.request().postData() ?? "");
      jobs.push({
        job_id: "new-job", filename: source === "file" ? "owned.wav" : "Owned YouTube fixture",
        kind: "transcription", status: "running", progress: 32, score_mode: "full",
        transcription_engine: "mt3_infer", mt3_model: model,
        // An unrelated retained MuScriptor preference must not label this job.
        muscriptor_model: "large",
      });
      return route.fulfill({ status: 202, json: { job_id: "new-job", status: "queued" } });
    });
    await page.goto("/");
    await expect(page.locator(".transcription-model")).toContainText(label);
    await quality(page).selectOption("custom");
    await expect(page.locator(".custom-model-row")).not.toContainText("MuScriptor");
    await expect(page.locator(".transcription-model")).toContainText(label);
    if (source === "file") {
      await chooseFile(page);
    } else {
      await page.getByRole("tab", { name: "YouTube 링크" }).click();
      await page.locator(".youtube-inline-row input").fill("https://www.youtube.com/watch?v=abcdef12345");
      await page.getByRole("button", { name: "링크 확인" }).click();
      await expect(page.locator(".source-preview-row")).toContainText("Owned YouTube fixture");
    }
    await page.getByRole("button", { name: "자동 채보 시작" }).click();
    await expect.poll(() => requests.length).toBe(1);
    expect(requests[0]).not.toContain("muscriptor_model");
    await expect(page.locator(".current-job .job-model")).toContainText(label);
    await expect(page.locator(".current-job .job-model")).not.toContainText("MuScriptor");

    // The server's new default differs, while the saved job remains unchanged.
    engine = { key: "muscriptor", model: "medium", name: "MuScriptor" };
    await page.reload();
    await expect(page.locator(".transcription-model")).toContainText("MuScriptor medium");
    await expect(page.locator(".current-job .job-model")).toContainText(label);
    await menu(page, "작업 내역").click();
    await expect(page.locator(".premium-job-row .job-row-main")).toContainText(label);
    await expect(page.locator(".premium-job-row .job-row-main")).not.toContainText("MuScriptor");
    await expect(page.locator(".premium-job-row .job-row-main")).not.toContainText("large");
  });
}

test("MuScriptor preview reflects the chosen preset while history keeps the saved size", async ({ page }) => {
  const jobs: FixtureJob[] = [];
  const requests: string[] = [];
  await prepare(page, {
    engine: () => ({ key: "muscriptor", model: "small", name: "MuScriptor" }), jobs,
  });
  await page.route("**/api/jobs", (route) => {
    requests.push(route.request().postData() ?? "");
    jobs.push({
      job_id: "quality-job", filename: "owned.wav", kind: "transcription", status: "running",
      progress: 24, transcription_engine: "muscriptor", muscriptor_model: "large", mt3_model: null,
    });
    return route.fulfill({ status: 202, json: { job_id: "quality-job", status: "queued" } });
  });
  await page.goto("/");
  await expect(page.locator(".transcription-model")).toContainText("MuScriptor small");
  await quality(page).selectOption("quality");
  await expect(page.locator(".transcription-model")).toContainText("MuScriptor large");
  await chooseFile(page);
  await page.getByRole("button", { name: "자동 채보 시작" }).click();
  await expect(page.locator(".current-job .job-model")).toContainText("MuScriptor large");
  expect(requests[0]).toContain('name="preset"\r\n\r\nquality');
  await quality(page).selectOption("fast");
  await expect(page.locator(".transcription-model")).toContainText("MuScriptor small");
  await expect(page.locator(".current-job .job-model")).toContainText("MuScriptor large");
  await menu(page, "작업 내역").click();
  await expect(page.locator(".premium-job-row .job-row-main")).toContainText("MuScriptor large");
});

test("legacy model identity stays unknown and imported scores do not claim an audio model", async ({ page }) => {
  const jobs: FixtureJob[] = [
    { job_id: "legacy-missing", filename: "legacy-missing.wav", status: "done", muscriptor_model: "large" },
    { job_id: "legacy-null", filename: "legacy-null.wav", status: "failed", transcription_engine: null, mt3_model: null, muscriptor_model: "medium" },
    { job_id: "native", filename: "native.wav", status: "done", transcription_engine: "native" },
    { job_id: "notation", filename: "notation.musicxml", status: "done", kind: "notation-import" },
    { job_id: "omr", filename: "scan.pdf", status: "done", kind: "omr" },
  ];
  await prepare(page, {
    engine: () => ({ key: "mt3_infer", model: "yourmt3", name: "MT3-Infer" }), jobs, section: "history",
  });
  await page.goto("/");
  for (const filename of ["legacy-missing.wav", "legacy-null.wav"]) {
    const row = page.locator(".premium-job-row").filter({ hasText: filename });
    await expect(row).toContainText("모델 정보 없음");
    await expect(row).not.toContainText(/MuScriptor|YourMT3|MR-MT3|large|medium/);
  }
  await expect(page.locator(".premium-job-row").filter({ hasText: "native.wav" })).toContainText("AudioScore Native");
  await expect(page.locator(".premium-job-row").filter({ hasText: "notation.musicxml" })).toContainText("기존 악보 가져오기");
  await expect(page.locator(".premium-job-row").filter({ hasText: "scan.pdf" })).toContainText("PDF·이미지 악보 인식");
});
