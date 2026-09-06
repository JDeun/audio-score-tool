import { useEffect, useState } from "react";
import "./engine-settings.css";

const API = "http://127.0.0.1:8080";

type EngineInfo = {
  key: string;
  name: string;
  ready: boolean;
  commercial_status: string;
};

type EngineState = {
  selected: string;
  native_checkpoint?: string | null;
  native_engine_cmd?: string | null;
  engines: EngineInfo[];
  preflight: { ok: boolean; missing: string[] };
};

export default function EngineSettingsDock() {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<EngineState | null>(null);
  const [engine, setEngine] = useState("muscriptor");
  const [checkpoint, setCheckpoint] = useState("");
  const [command, setCommand] = useState("audio-score-native");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  const refresh = async () => {
    try {
      const response = await fetch(`${API}/api/engines`);
      if (!response.ok) return;
      const body: EngineState = await response.json();
      setState(body);
      setEngine(body.selected);
      setCheckpoint(body.native_checkpoint ?? "");
      setCommand(body.native_engine_cmd ?? "audio-score-native");
    } catch {
      // Main application communicates backend connectivity separately.
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const save = async () => {
    setSaving(true);
    setMessage("");
    try {
      const response = await fetch(`${API}/api/engines`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          transcription_engine: engine,
          native_engine_cmd: command || null,
          native_checkpoint: checkpoint || null,
        }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail ?? "엔진 설정을 저장하지 못했습니다.");
      setState(body);
      setMessage("채보 엔진 설정을 저장했습니다.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  };

  const selected = state?.engines.find((item) => item.key === (state?.selected ?? engine));

  return (
    <div className="engine-dock">
      <button className="engine-dock-trigger" onClick={() => { setOpen((value) => !value); if (!open) void refresh(); }}>
        <span className={`engine-dot ${selected?.ready ? "ready" : "warning"}`} />
        채보 엔진 · {selected?.name ?? (engine === "native" ? "AudioScore Native" : "MuScriptor")}
      </button>
      {open && (
        <section className="engine-popover" role="dialog" aria-label="채보 엔진 설정">
          <div className="engine-popover-head">
            <div><span>TRANSCRIPTION ENGINE</span><h3>채보 엔진</h3></div>
            <button onClick={() => setOpen(false)} aria-label="닫기">×</button>
          </div>

          <div className="engine-choice-grid">
            {(state?.engines ?? [
              { key: "muscriptor", name: "MuScriptor", ready: false, commercial_status: "noncommercial_weights" },
              { key: "native", name: "AudioScore Native", ready: false, commercial_status: "project_owned" },
            ]).map((item) => (
              <button key={item.key} className={engine === item.key ? "selected" : ""} onClick={() => setEngine(item.key)}>
                <strong>{item.name}</strong>
                <small>{item.key === "native" ? "프로젝트 소유 체크포인트" : "외부 CC BY-NC 가중치"}</small>
                <em className={item.ready ? "ready" : "warning"}>{item.ready ? "준비됨" : "설정 필요"}</em>
              </button>
            ))}
          </div>

          {engine === "native" && (
            <div className="engine-native-fields">
              <label><span>Native 실행 명령</span><input value={command} onChange={(event) => setCommand(event.target.value)} placeholder="audio-score-native" /></label>
              <label><span>프로젝트 소유 체크포인트</span><input value={checkpoint} onChange={(event) => setCheckpoint(event.target.value)} placeholder="/path/to/audio-score-native.pt" /></label>
              <p>Native 엔진은 AudioScoreTool이 직접 학습한 체크포인트만 사용하도록 설계되어 있습니다.</p>
            </div>
          )}

          {engine === "muscriptor" && (
            <div className="engine-license-note">MuScriptor 공개 모델 가중치는 비상업 라이선스이므로 상용 배포용 기본 엔진으로 사용하지 않습니다.</div>
          )}

          {message && <p className="engine-message">{message}</p>}
          <button className="engine-save" disabled={saving} onClick={() => void save()}>{saving ? "저장 중…" : "엔진 설정 저장"}</button>
        </section>
      )}
    </div>
  );
}
