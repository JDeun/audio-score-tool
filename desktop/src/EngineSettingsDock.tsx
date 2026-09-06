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
  yourmt3_cmd?: string | null;
  native_checkpoint?: string | null;
  native_engine_cmd?: string | null;
  engines: EngineInfo[];
  preflight: { ok: boolean; missing: string[] };
};

const fallbackEngines: EngineInfo[] = [
  { key: "yourmt3", name: "YourMT3+", ready: false, commercial_status: "permissive_checkpoint" },
  { key: "native", name: "AudioScore Native", ready: false, commercial_status: "project_owned" },
  { key: "muscriptor", name: "MuScriptor", ready: false, commercial_status: "noncommercial_weights" },
];

const engineDescription = (key: string) => {
  if (key === "yourmt3") return "권장 · 다중 악기 · permissive checkpoint";
  if (key === "native") return "장기 R&D · 프로젝트 소유 체크포인트";
  return "호환용 · 공개 weights는 비상업";
};

export default function EngineSettingsDock() {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<EngineState | null>(null);
  const [engine, setEngine] = useState("yourmt3");
  const [yourmt3Command, setYourmt3Command] = useState("mt3-infer");
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
      setYourmt3Command(body.yourmt3_cmd ?? "mt3-infer");
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
          yourmt3_cmd: yourmt3Command || null,
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
  const selectedName = selected?.name ?? fallbackEngines.find((item) => item.key === engine)?.name ?? engine;

  return (
    <div className="engine-dock">
      <button
        className="engine-dock-trigger"
        onClick={() => {
          setOpen((value) => !value);
          if (!open) void refresh();
        }}
      >
        <span className={`engine-dot ${selected?.ready ? "ready" : "warning"}`} />
        채보 엔진 · {selectedName}
      </button>
      {open && (
        <section className="engine-popover" role="dialog" aria-label="채보 엔진 설정">
          <div className="engine-popover-head">
            <div><span>TRANSCRIPTION ENGINE</span><h3>채보 엔진</h3></div>
            <button onClick={() => setOpen(false)} aria-label="닫기">×</button>
          </div>

          <div className="engine-choice-grid">
            {(state?.engines ?? fallbackEngines).map((item) => (
              <button
                key={item.key}
                className={engine === item.key ? "selected" : ""}
                onClick={() => setEngine(item.key)}
              >
                <strong>{item.name}</strong>
                <small>{engineDescription(item.key)}</small>
                <em className={item.ready ? "ready" : "warning"}>
                  {item.ready ? "준비됨" : "첫 실행 준비 필요"}
                </em>
              </button>
            ))}
          </div>

          {engine === "yourmt3" && (
            <div className="engine-native-fields">
              <label>
                <span>MT3-Infer 실행 명령</span>
                <input
                  value={yourmt3Command}
                  onChange={(event) => setYourmt3Command(event.target.value)}
                  placeholder="mt3-infer"
                />
              </label>
              <p>
                기본 권장 엔진입니다. 설치된 mt3-infer가 없으면 uvx를 통해 실행할 수 있고,
                YourMT3+ checkpoint는 첫 사용 시 로컬 캐시에 자동으로 내려받습니다.
              </p>
              <div className="engine-license-note">
                mt3-infer는 MIT, 사용되는 YourMT3+ checkpoint 저장소는 Apache-2.0으로 명시되어 있습니다.
                상용 릴리스 전에는 THIRD_PARTY_NOTICES와 upstream 조건을 다시 확인하세요.
              </div>
            </div>
          )}

          {engine === "native" && (
            <div className="engine-native-fields">
              <label><span>Native 실행 명령</span><input value={command} onChange={(event) => setCommand(event.target.value)} placeholder="audio-score-native" /></label>
              <label><span>프로젝트 소유 체크포인트</span><input value={checkpoint} onChange={(event) => setCheckpoint(event.target.value)} placeholder="/path/to/audio-score-native.pt" /></label>
              <p>직접 소유하는 모델이 필요할 때를 위한 장기 R&D 경로입니다. 기본 사용에는 학습이 필요하지 않습니다.</p>
            </div>
          )}

          {engine === "muscriptor" && (
            <div className="engine-license-note">
              MuScriptor 공개 모델 가중치는 CC BY-NC 계열의 비상업 조건이므로 상용 배포용 기본 엔진으로 사용하지 않습니다.
            </div>
          )}

          {message && <p className="engine-message">{message}</p>}
          <button className="engine-save" disabled={saving} onClick={() => void save()}>
            {saving ? "저장 중…" : "엔진 설정 저장"}
          </button>
        </section>
      )}
    </div>
  );
}
