import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import "./notation-settings.css";

const API = "http://127.0.0.1:8080";

type Settings = {
  paths: {
    audiveris_cmd?: string | null;
  };
  backends: {
    music21?: boolean;
    verovio?: boolean;
    fpdf2?: boolean;
  };
  omr: { ready: boolean };
  policy: {
    musescore_required: boolean;
    lilypond_required: boolean;
    external_pdf_renderer_required: boolean;
    pdf_renderer: string;
  };
};

export default function NotationSettingsController() {
  const [host, setHost] = useState<Element | null>(null);
  const [data, setData] = useState<Settings | null>(null);
  const [audiverisPath, setAudiverisPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    const findHost = () => setHost(document.querySelector(".settings-page .settings-columns"));
    findHost();
    const observer = new MutationObserver(findHost);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!host) return;
    void (async () => {
      try {
        const response = await fetch(`${API}/api/notation`);
        if (!response.ok) return;
        const next: Settings = await response.json();
        setData(next);
        setAudiverisPath(next.paths.audiveris_cmd ?? "");
      } catch {
        // Main settings page already exposes sidecar connectivity state.
      }
    })();
  }, [host]);

  const save = async () => {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${API}/api/notation`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ audiveris_cmd: audiverisPath || null }),
      });
      if (!response.ok) throw new Error(await response.text());
      const next: Settings = await response.json();
      setData(next);
      setAudiverisPath(next.paths.audiveris_cmd ?? "");
      setMessage("OMR backend 설정을 저장했습니다.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  if (!host || !data) return null;

  const embeddedPdfReady = Boolean(data.backends.verovio && data.backends.fpdf2);

  return createPortal(
    <section className="work-card notation-settings-card">
      <div className="section-title-row">
        <div>
          <span className="card-kicker">악보 입출력 엔진</span>
          <h2>외부 PDF renderer 없이 작동합니다</h2>
          <p>MusicXML/MIDI는 music21, PDF는 내장 Verovio + fpdf2를 사용합니다. PDF·이미지 OMR만 Audiveris component가 필요합니다.</p>
        </div>
      </div>

      <div className="notation-backend-grid">
        <div><span className={data.omr.ready ? "ready" : "missing"}>{data.omr.ready ? "✓" : "!"}</span><strong>Audiveris</strong><small>PDF/이미지 → MusicXML</small></div>
        <div><span className={data.backends.music21 ? "ready" : "missing"}>{data.backends.music21 ? "✓" : "!"}</span><strong>music21</strong><small>MIDI ↔ MusicXML</small></div>
        <div><span className={embeddedPdfReady ? "ready" : "missing"}>{embeddedPdfReady ? "✓" : "!"}</span><strong>Verovio + fpdf2</strong><small>MusicXML → PDF · 앱 내장</small></div>
      </div>

      <div className="notation-paths">
        <label>
          <span>Audiveris</span>
          <input
            value={audiverisPath}
            placeholder="개발 환경에서만 경로 override"
            onChange={(event) => setAudiverisPath(event.target.value)}
          />
        </label>
      </div>
      <p className="notation-settings-message">PDF renderer는 앱 내장 구성요소이며 별도 경로 설정이 없습니다.</p>
      {message && <p className="notation-settings-message">{message}</p>}
      <button className="primary-button" disabled={busy} onClick={() => void save()}>{busy ? "저장 중…" : "OMR backend 경로 저장"}</button>
    </section>,
    host,
  );
}
