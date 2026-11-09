import { useEffect, useMemo, useRef, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import "./export-controller.css";
import { useSelectedSong } from "./SelectedSongContext";

const API = "http://127.0.0.1:8080";

type ExportKind = "musicxml" | "pdf" | "midi" | "parts";

type ExportTarget = {
  songId: string;
  title: string;
};

type ScorePart = { part_id: string; name: string; index: number };
type ExportReceipt = { export_id: string; scope: "full" | "selection"; revision: number };
type SavedExport = { destination: string; receipt?: ExportReceipt; pdf: boolean };

async function responseError(response: Response) {
  const text = await response.text();
  try {
    const body = JSON.parse(text);
    return typeof body.detail === "string" ? body.detail : text;
  } catch {
    return text;
  }
}

const labels: Record<ExportKind, string> = {
  musicxml: "MusicXML",
  pdf: "Full Score PDF",
  midi: "MIDI",
  parts: "파트별 MusicXML + PDF",
};

export default function ExportController() {
  const { target: selectedSong, notifySongChanged } = useSelectedSong();
  const [target, setTarget] = useState<ExportTarget | null>(null);
  const [destination, setDestination] = useState("");
  const [selected, setSelected] = useState<Record<ExportKind, boolean>>({
    musicxml: true,
    pdf: true,
    midi: true,
    parts: true,
  });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [parts, setParts] = useState<ScorePart[]>([]);
  const [partIds, setPartIds] = useState<string[]>([]);
  const [scope, setScope] = useState<"full" | "selection">("full");
  const [revision, setRevision] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [reload, setReload] = useState(0);
  const [saved, setSaved] = useState<SavedExport | null>(null);
  const [openingPdf, setOpeningPdf] = useState(false);
  const operationEpoch = useRef(0);
  const loadedSongId = useRef<string | null>(null);

  const formats = useMemo(
    () => (Object.entries(selected) as [ExportKind, boolean][])
      .filter(([, enabled]) => enabled)
      .map(([kind]) => kind),
    [selected],
  );

  useEffect(() => {
    const intercept = (event: MouseEvent) => {
      const element = event.target instanceof Element ? event.target : null;
      const button = element?.closest("button.export-button");
      if (!button || !button.closest(".score-workbench") || !selectedSong) return;

      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      setTarget({ songId: selectedSong.songId, title: selectedSong.title });
      setDestination("");
      setMessage("");
    };

    document.addEventListener("click", intercept, true);
    return () => document.removeEventListener("click", intercept, true);
  }, [selectedSong]);

  useEffect(() => {
    // Never leave a modal targeting the previously selected score.
    setTarget(null);
  }, [selectedSong?.songId]);

  useEffect(() => {
    const epoch = ++operationEpoch.current;
    if (!target) {
      loadedSongId.current = null;
      return;
    }
    const preserveSelection = loadedSongId.current === target.songId;
    setLoading(true);
    setBusy(false);
    setOpeningPdf(false);
    setRevision(null);
    setParts([]);
    if (!preserveSelection) {
      setPartIds([]);
      setScope("full");
    }
    setSaved(null);
    setMessage("");
    void (async () => {
      try {
        const response = await fetch(`${API}/api/songs/${target.songId}`);
        if (!response.ok) throw new Error(await responseError(response));
        const body = await response.json();
        if (operationEpoch.current !== epoch) return;
        const nextParts: ScorePart[] = body.parts ?? [];
        setParts(nextParts);
        const nextIds = nextParts.map((part) => part.part_id);
        setPartIds((current) => preserveSelection
          ? current.filter((id) => nextIds.includes(id)) : nextIds);
        setRevision(body.revision);
        loadedSongId.current = target.songId;
        if (typeof body.title === "string") {
          setTarget((current) => current?.songId === target.songId
            ? { ...current, title: body.title } : current);
        }
      } catch (error) {
        if (operationEpoch.current === epoch) setMessage(`출력 정보를 읽지 못했습니다: ${String(error)}`);
      } finally {
        if (operationEpoch.current === epoch) setLoading(false);
      }
    })();
    return () => { operationEpoch.current += 1; };
  }, [target?.songId, reload]);

  const chooseDirectory = async () => {
    const epoch = operationEpoch.current;
    setMessage("");
    try {
      const selectedDirectory = await openDialog({
        directory: true,
        multiple: false,
        title: "최종 악보 저장 폴더",
      });
      if (typeof selectedDirectory === "string" && operationEpoch.current === epoch) {
        setDestination(selectedDirectory);
        setSaved(null);
      }
    } catch (error) {
      if (operationEpoch.current === epoch) setMessage(`저장 폴더를 열지 못했습니다: ${String(error)}`);
    }
  };

  const runExport = async () => {
    if (!target || busy || loading || revision === null) return;
    if (formats.length === 0) {
      setMessage("최소 한 개의 출력 포맷을 선택하세요.");
      return;
    }
    if (!destination) {
      setMessage("최종 파일을 저장할 폴더를 선택하세요.");
      return;
    }
    if (scope === "selection" && partIds.length === 0) {
      setMessage("출력할 파트를 한 개 이상 선택하세요.");
      return;
    }

    const epoch = operationEpoch.current;
    setBusy(true);
    setSaved(null);
    setMessage("");
    try {
      const response = await fetch(`${API}/api/songs/${target.songId}/export-to`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          formats,
          destination_dir: destination,
          expected_revision: revision,
          ...(scope === "selection" ? { part_ids: partIds } : {}),
        }),
      });
      if (!response.ok) {
        if (response.status === 409 && operationEpoch.current === epoch) setRevision(null);
        throw new Error(await responseError(response));
      }
      const body = await response.json();
      if (operationEpoch.current !== epoch) return;
      setMessage(`저장 완료: ${body.destination}`);
      setSaved({ destination: body.destination, receipt: body.export, pdf: formats.includes("pdf") });
      notifySongChanged(target.songId);
    } catch (error) {
      if (operationEpoch.current === epoch) setMessage(`최종 파일 생성 실패: ${String(error)}`);
    } finally {
      if (operationEpoch.current === epoch) setBusy(false);
    }
  };

  const openPdf = async () => {
    if (!target || !saved?.receipt || openingPdf) return;
    const epoch = operationEpoch.current;
    setOpeningPdf(true);
    try {
      const response = await fetch(`${API}/api/songs/${target.songId}/export/open-pdf`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scope: saved.receipt.scope,
          export_id: saved.receipt.export_id,
          expected_revision: saved.receipt.revision,
        }),
      });
      if (!response.ok) throw new Error(await responseError(response));
      if (operationEpoch.current === epoch) setMessage(`PDF 뷰어를 열었습니다. 뷰어의 인쇄 메뉴를 이용하세요. 저장 위치: ${saved.destination}`);
    } catch (error) {
      if (operationEpoch.current === epoch) setMessage(`PDF 열기 실패: ${String(error)}`);
    } finally {
      if (operationEpoch.current === epoch) setOpeningPdf(false);
    }
  };

  if (!target) return null;

  return (
    <div className="export-modal-backdrop" role="presentation">
      <section className="export-modal" role="dialog" aria-modal="true" aria-label="최종 파일 생성">
        <header>
          <div>
            <span className="export-modal-eyebrow">FINAL EXPORT</span>
            <h2>최종 파일 생성</h2>
            <p>‘{target.title}’{revision !== null ? ` · Revision ${revision}` : ""}을 선택한 위치에 출력합니다.</p>
          </div>
          <button
            className="export-modal-close"
            type="button"
            disabled={busy || openingPdf}
            onClick={() => setTarget(null)}
            aria-label="닫기"
          >
            ×
          </button>
        </header>

        <fieldset className="export-part-scope" disabled={busy || openingPdf || loading}>
          <legend>출력할 파트</legend>
          <label><input type="radio" name="export-scope" checked={scope === "full"}
            onChange={() => { setScope("full"); setSaved(null); }} />전체 악보</label>
          <label><input type="radio" name="export-scope" checked={scope === "selection"}
            disabled={parts.length === 0}
            onChange={() => { setScope("selection"); setSaved(null); }} />선택 파트 합본</label>
          {loading && <p role="status">악보의 파트를 불러오는 중…</p>}
          {scope === "selection" && <>
            <div className="export-part-list">
              {parts.map((part) => <label key={part.part_id}>
                <input type="checkbox" checked={partIds.includes(part.part_id)}
                  onChange={(event) => {
                    setSaved(null);
                    setPartIds((current) => event.target.checked
                      ? [...current, part.part_id] : current.filter((id) => id !== part.part_id));
                  }} />
                <span>{part.index}. {part.name}</span>
              </label>)}
            </div>
            <small>선택한 파트를 원래 악보 순서로 묶습니다. 원본 악보와 전체 악보 출력은 보존됩니다.</small>
          </>}
        </fieldset>

        <div className="export-format-grid">
          {(Object.keys(labels) as ExportKind[]).map((kind) => (
            <label key={kind} className={selected[kind] ? "selected" : ""}>
              <input
                type="checkbox"
                checked={selected[kind]}
                disabled={busy || openingPdf}
                onChange={(event) => {
                  setSaved(null);
                  setSelected((current) => ({ ...current, [kind]: event.target.checked }));
                }}
              />
              <span>{scope === "selection" && kind === "pdf" ? "선택 파트 합본 PDF" : labels[kind]}</span>
            </label>
          ))}
        </div>

        <div className="export-destination">
          <span>저장 위치</span>
          <div>
            <input
              readOnly
              value={destination}
              placeholder="폴더를 선택하세요"
              title={destination}
            />
            <button type="button" disabled={busy || openingPdf} onClick={() => void chooseDirectory()}>
              폴더 선택
            </button>
          </div>
          <small>같은 이름의 폴더가 있으면 자동으로 (2), (3)… 번호를 붙입니다.</small>
        </div>

        {message && <div className="export-modal-message" role="status">{message}</div>}
        {!loading && revision === null && <button type="button" className="export-cancel"
          onClick={() => setReload((current) => current + 1)}>현재 악보 다시 불러오기</button>}
        {saved?.pdf && saved.receipt && <div className="export-pdf-actions">
          <button type="button" className="export-confirm" disabled={busy || openingPdf}
            onClick={() => void openPdf()}>{openingPdf ? "PDF 여는 중…" : "생성한 PDF 열기 · 인쇄"}</button>
          <small>기본 PDF 뷰어에서 인쇄할 페이지와 프린터를 선택할 수 있습니다.</small>
        </div>}

        <footer>
          <button type="button" className="export-cancel" disabled={busy || openingPdf} onClick={() => setTarget(null)}>
            {saved ? "닫기" : "취소"}
          </button>
          <button type="button" className="export-confirm" disabled={busy || openingPdf || loading || revision === null || (scope === "selection" && partIds.length === 0)} onClick={() => void runExport()}>
            {busy ? "생성 중…" : "생성 및 저장"}
          </button>
        </footer>
      </section>
    </div>
  );
}
