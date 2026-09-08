import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import "./notation-settings.css";

const API = "http://127.0.0.1:8080";

type Settings = {
  paths: {
    audiveris_cmd?: string | null;
    lilypond_cmd?: string | null;
    musicxml2ly_cmd?: string | null;
  };
  backends: Record<string, boolean>;
  omr: { ready: boolean };
  policy: { musescore_required: boolean; pdf_renderer: string };
};

export default function NotationSettingsController() {
  const [host, setHost] = useState<Element | null>(null);
  const [data, setData] = useState<Settings | null>(null);
  const [paths, setPaths] = useState<Record<string, string>>({});
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
        setPaths(Object.fromEntries(Object.entries(next.paths).map(([key, value]) => [key, value ?? ""])));
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
        body: JSON.stringify({
          audiveris_cmd: paths.audiveris_cmd || null,
          lilypond_cmd: paths.lilypond_cmd || null,
          musicxml2ly_cmd: paths.musicxml2ly_cmd || null,
        }),
      });
      if (!response.ok) throw new Error(await response.text());
      const next: Settings = await response.json();
      setData(next);
      setMessage("악보 처리 backend 설정을 저장했습니다.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  if (!host || !data) return null;

  return createPortal(
    <section className="work-card notation-settings-card">
      <div className="section-title-row">
        <div>
          <span className="card-kicker">악보 입출력 엔진</span>
          <h2>MuseScore 없이 작동합니다</h2>
          <p>MusicXML/MIDI는 music21, PDF는 LilyPond, PDF·이미지 악보 인식은 Audiveris를 사용합니다.</p>
        </div>
      </div>

      <div className="notation-backend-grid">
        <div><span className={data.omr.ready ? "ready" : "missing"}>{data.omr.ready ? "✓" : "!"}</span><strong>Audiveris</strong><small>PDF/이미지 → MusicXML</small></div>
        <div><span className={data.backends.music21 ? "ready" : "missing"}>{data.backends.music21 ? "✓" : "!"}</span><strong>music21</strong><small>MIDI ↔ MusicXML</small></div>
        <div><span className={data.backends.lilypond && data.backends.musicxml2ly ? "ready" : "missing"}>{data.backends.lilypond && data.backends.musicxml2ly ? "✓" : "!"}</span><strong>LilyPond</strong><small>MusicXML → PDF</small></div>
      </div>

      <div className="notation-paths">
        {[
          ["audiveris_cmd", "Audiveris"],
          ["lilypond_cmd", "LilyPond"],
          ["musicxml2ly_cmd", "musicxml2ly"],
        ].map(([key, label]) => (
          <label key={key}>
            <span>{label}</span>
            <input
              value={paths[key] ?? ""}
              placeholder="자동 검색"
              onChange={(event) => setPaths((current) => ({ ...current, [key]: event.target.value }))}
            />
          </label>
        ))}
      </div>
      {message && <p className="notation-settings-message">{message}</p>}
      <button className="primary-button" disabled={busy} onClick={() => void save()}>{busy ? "저장 중…" : "악보 backend 경로 저장"}</button>
    </section>,
    host,
  );
}
