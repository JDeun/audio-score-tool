import { useEffect, useMemo, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import "./export-controller.css";

const API = "http://127.0.0.1:8080";

type ExportKind = "musicxml" | "pdf" | "midi" | "parts";

type ExportTarget = {
  songId: string;
  title: string;
};

const labels: Record<ExportKind, string> = {
  musicxml: "MusicXML",
  pdf: "Full Score PDF",
  midi: "MIDI",
  parts: "파트별 MusicXML + PDF",
};

function resolveTarget(button: Element): ExportTarget | null {
  const workbench = button.closest(".score-workbench");
  const scoreLink = workbench?.querySelector<HTMLAnchorElement>(
    'a[href*="/api/songs/"][href*="/files/"]',
  );
  if (!scoreLink) return null;

  const pathname = new URL(scoreLink.href, window.location.href).pathname;
  const match = pathname.match(/\/api\/songs\/([^/]+)\/files\//);
  if (!match) return null;

  const title = workbench?.querySelector(".score-toolbar h2")?.textContent?.trim();
  return {
    songId: decodeURIComponent(match[1]),
    title: title || "악보",
  };
}

export default function ExportController() {
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
      if (!button) return;
      const nextTarget = resolveTarget(button);
      if (!nextTarget) return;

      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      setTarget(nextTarget);
      setDestination("");
      setMessage("");
    };

    document.addEventListener("click", intercept, true);
    return () => document.removeEventListener("click", intercept, true);
  }, []);

  const chooseDirectory = async () => {
    setMessage("");
    try {
      const selectedDirectory = await openDialog({
        directory: true,
        multiple: false,
        title: "최종 악보 저장 폴더",
      });
      if (typeof selectedDirectory === "string") {
        setDestination(selectedDirectory);
      }
    } catch (error) {
      setMessage(`저장 폴더를 열지 못했습니다: ${String(error)}`);
    }
  };

  const runExport = async () => {
    if (!target || busy) return;
    if (formats.length === 0) {
      setMessage("최소 한 개의 출력 포맷을 선택하세요.");
      return;
    }
    if (!destination) {
      setMessage("최종 파일을 저장할 폴더를 선택하세요.");
      return;
    }

    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${API}/api/songs/${target.songId}/export-to`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          formats,
          destination_dir: destination,
        }),
      });
      if (!response.ok) throw new Error(await response.text());
      const body = await response.json();
      setMessage(`저장 완료: ${body.destination}`);
      window.setTimeout(() => window.location.reload(), 850);
    } catch (error) {
      setMessage(`최종 파일 생성 실패: ${String(error)}`);
      setBusy(false);
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
            <p>‘{target.title}’의 현재 Revision만 선택한 위치에 출력합니다.</p>
          </div>
          <button
            className="export-modal-close"
            type="button"
            disabled={busy}
            onClick={() => setTarget(null)}
            aria-label="닫기"
          >
            ×
          </button>
        </header>

        <div className="export-format-grid">
          {(Object.keys(labels) as ExportKind[]).map((kind) => (
            <label key={kind} className={selected[kind] ? "selected" : ""}>
              <input
                type="checkbox"
                checked={selected[kind]}
                disabled={busy}
                onChange={(event) => setSelected((current) => ({
                  ...current,
                  [kind]: event.target.checked,
                }))}
              />
              <span>{labels[kind]}</span>
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
            <button type="button" disabled={busy} onClick={() => void chooseDirectory()}>
              폴더 선택
            </button>
          </div>
          <small>같은 이름의 폴더가 있으면 자동으로 (2), (3)… 번호를 붙입니다.</small>
        </div>

        {message && <div className="export-modal-message">{message}</div>}

        <footer>
          <button type="button" className="export-cancel" disabled={busy} onClick={() => setTarget(null)}>
            취소
          </button>
          <button type="button" className="export-confirm" disabled={busy} onClick={() => void runExport()}>
            {busy ? "생성 중…" : "생성 및 저장"}
          </button>
        </footer>
      </section>
    </div>
  );
}
