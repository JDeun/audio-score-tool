import { expect, test, type Page } from "@playwright/test";

const PARTS = [
  { part_id: "P1", index: 1, name: "Voice" },
  { part_id: "P2", index: 2, name: "Guitar" },
  { part_id: "P3", index: 3, name: "Bass" },
];
const SCORE = `<score-partwise version="4.0"><part-list>
  ${PARTS.map(part => `<score-part id="${part.part_id}"><part-name>${part.name}</part-name></score-part>`).join("")}
  </part-list>${PARTS.map(part => `<part id="${part.part_id}"><measure number="1">
  <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
  <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
  </measure></part>`).join("")}</score-partwise>`;

async function prepare(page: Page, rejectStale = false) {
  const exports: Record<string, unknown>[] = [];
  const opens: Record<string, unknown>[] = [];
  let revision = 5;
  const song = () => ({
    song_id: "ensemble", job_id: "ensemble", title: revision === 5 ? "Owned ensemble" : "Updated ensemble", artist: "Fixture artist",
    revision, source_kind: "notation", exports: {}, parts: PARTS,
  });
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/health") return route.fulfill({ json: {
      status: "ok", device_plan: { muscriptor_device: "cpu" },
      preflight: { ok: true, missing: [], tools: {} },
      presets: { recommended: "quality", presets: [] },
      system: { hf_authenticated: false, jobs_bytes: 0, disk_free_bytes: 1000 },
    } });
    if (path === "/api/songs") return route.fulfill({ json: { songs: [song()] } });
    if (path === "/api/songs/ensemble") return route.fulfill({ json: song() });
    if (path.endsWith("/score")) return route.fulfill({ body: SCORE, contentType: "application/xml" });
    if (path.endsWith("/notes")) return route.fulfill({ json: {
      song: song(), parts: PARTS.map(part => ({ ...part, notes: 1, measures: 1 })), notes: [], chords: [],
    } });
    if (path.endsWith("/structure")) return route.fulfill({ json: { measures: [] } });
    if (path.endsWith("/publication")) return route.fulfill({ json: { settings: {} } });
    if (path.endsWith("/export-to")) {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      exports.push(body);
      if (rejectStale && exports.length === 1) {
        revision = 6;
        return route.fulfill({ status: 409, json: { detail: "악보가 변경되었습니다. 현재 악보를 확인하세요." } });
      }
      return route.fulfill({ json: {
        song: song(), parts: PARTS, destination: "/tmp/published/Owned ensemble - 선택 파트",
        export: { export_id: "generated-ensemble", scope: body.part_ids ? "selection" : "full", revision },
      } });
    }
    if (path.endsWith("/export/open-pdf")) {
      opens.push(route.request().postDataJSON() as Record<string, unknown>);
      return route.fulfill({ json: { opened: true } });
    }
    return route.fulfill({ json: {} });
  });
  await page.addInitScript(() => {
    localStorage.setItem("ast-onboarding-v1", "done");
    localStorage.setItem("ast-setup-center-v2", "dismissed");
    localStorage.setItem("ast-section", "songs");
  });
  await page.goto("/");
  await expect(page.locator(".score-toolbar h2")).toHaveText("Owned ensemble");
  await page.getByRole("button", { name: "최종 파일 생성" }).click();
  const modal = page.getByRole("dialog", { name: "최종 파일 생성" });
  await expect(modal).toContainText("Revision 5");
  await page.evaluate(() => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", { configurable: true, value: {
      invoke: (command: string) => Promise.resolve(command === "plugin:dialog|open" ? "/tmp/published" : null),
    } });
  });
  await modal.getByRole("button", { name: "폴더 선택" }).click();
  await expect(modal.locator(".export-destination input")).toHaveValue("/tmp/published");
  return { modal, exports, opens };
}

test("selected parts reach publication API and the exact generated PDF opens without reloading", async ({ page }) => {
  const { modal, exports, opens } = await prepare(page);
  await modal.getByRole("radio", { name: "선택 파트 합본" }).check();
  await modal.getByRole("checkbox", { name: "1. Voice" }).uncheck();
  await modal.getByRole("button", { name: "생성 및 저장" }).click();
  await expect.poll(() => exports.length).toBe(1);
  expect(exports[0]).toEqual({
    formats: ["musicxml", "pdf", "midi", "parts"], destination_dir: "/tmp/published",
    expected_revision: 5, part_ids: ["P2", "P3"],
  });
  await expect(modal).toContainText("저장 완료");
  await modal.getByRole("button", { name: "생성한 PDF 열기 · 인쇄" }).click();
  await expect.poll(() => opens).toEqual([{
    scope: "selection", export_id: "generated-ensemble", expected_revision: 5,
  }]);
  await expect(modal).toContainText("PDF 뷰어를 열었습니다");
  await expect(page.locator(".score-toolbar h2")).toHaveText("Owned ensemble");
});

test("empty part selection cannot submit and switching back exports the whole score", async ({ page }) => {
  const { modal, exports } = await prepare(page);
  await modal.getByRole("radio", { name: "선택 파트 합본" }).check();
  for (const part of PARTS) await modal.getByRole("checkbox", { name: `${part.index}. ${part.name}` }).uncheck();
  await expect(modal.getByRole("button", { name: "생성 및 저장" })).toBeDisabled();
  expect(exports).toHaveLength(0);
  await modal.getByRole("radio", { name: "전체 악보", exact: true }).check();
  await modal.getByRole("button", { name: "생성 및 저장" }).click();
  await expect.poll(() => exports.length).toBe(1);
  expect(exports[0]).not.toHaveProperty("part_ids");
});

test("stale publication requires refreshing the visible revision before retry", async ({ page }) => {
  const { modal, exports } = await prepare(page, true);
  await modal.getByRole("radio", { name: "선택 파트 합본" }).check();
  await modal.getByRole("checkbox", { name: "1. Voice" }).uncheck();
  await modal.getByRole("button", { name: "생성 및 저장" }).click();
  await expect(modal).toContainText("악보가 변경되었습니다");
  await expect(modal.getByRole("button", { name: "생성 및 저장" })).toBeDisabled();
  await modal.getByRole("button", { name: "현재 악보 다시 불러오기" }).click();
  await expect(modal).toContainText("Revision 6");
  await expect(modal).toContainText("Updated ensemble");
  await expect(modal.getByRole("radio", { name: "선택 파트 합본" })).toBeChecked();
  await expect(modal.getByRole("checkbox", { name: "1. Voice" })).not.toBeChecked();
  await modal.getByRole("button", { name: "생성 및 저장" }).click();
  await expect.poll(() => exports.length).toBe(2);
  expect(exports[1].expected_revision).toBe(6);
  expect(exports[1].part_ids).toEqual(["P2", "P3"]);
});
