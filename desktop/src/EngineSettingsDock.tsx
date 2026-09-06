import { useEffect, useState } from "react";
import "./engine-settings.css";

const API = "http://127.0.0.1:8080";

type EngineInfo = {
  key: string;
  name: string;
  ready: boolean;
  commercial_status: string;
  model?: string;
  model_commercial_status?: string;
};

type EngineState = {
  selected: string;
  mt3_infer_cmd?: string | null;
  mt3_model?: string | null;
  native_checkpoint?: string | null;
  native_engine_cmd?: string | null;
  engines: EngineInfo[];
  preflight: { ok: boolean; missing: string[] };
};

const fallbackEngines: EngineInfo[] = [
  { key: "mt3_infer", name: "MT3-Infer", ready: false, commercial_status: "permissive_default" },
  { key: "native", name: "AudioScore Native", ready: false, commercial_status: "project_owned" },
  { key: "muscriptor", name: "MuScriptor", ready: false, commercial_status: "noncommercial_weights" },
];

const engineDescription = (key: string) => {
  if (key === "mt3_infer") return "권장 · 다중 악기 · 공개 pretrained 모델";
  if (key === "native") return "장기 R&D · 프로젝트 소유 체크포인트";
  return "호환용 · 공개 weights는 비상업";
};

export default function EngineSettingsDock() {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<EngineState | null>(null);
  const [engine, setEngine] = useState("mt3_infer");
  const [mt3Command, setMt3Command] = useState("mt3-infer");
  const [mt3Model, setMt3Model] = useState("mr_mt3");
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
      setEngine(body.selected === "yourmt3" ? "mt3_infer" : body.selected);
      setMt3Command(body.mt3_infer_cmd ?? "mt3-infer");
      setMt3Model(body.mt3_model ?? "mr_mt3");
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
          mt3_infer_cmd: mt3Command || null,
          mt3_model: mt3Model,
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

  const selectedKey = state?.selected === "yourmt3" ? "mt3_infer" : state?.selected;
  const selected = state?.engines.find((item) => item.key === (selectedKey ?? engine));
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

          {engine === "mt3_infer" && (
            <div className="engine-native-fields">
              <label>
                <span>모델</span>
                <select value={mt3Model} onChange={(event) => setMt3Model(event.target.value)}>
                  <option value="mr_mt3">MR-MT3 · 기본 권장</option>
                  <option value="yourmt3">YourMT3+ · 고품질 실험</option>
                </select>
              </label>
              <label>
                <span>MT3-Infer 실행 명령</span>
                <input
                  value={mt3Command}
                  onChange={(event) => setMt3Command(event.target.value)}
                  placeholder="mt3-infer"
                />
              </label>
              {mt3Model === "mr_mt3" ? (
                <div className="engine-license-note safe">
                  MR-MT3 원 저장소와 공개 checkpoint는 MIT로 표시되어 있어 현재 상업 기본 후보로 사용합니다.
                  최종 배포 시에는 THIRD_PARTY_NOTICES와 고정된 checkpoint provenance를 함께 남기세요.
                </div>
              ) : (
                <div className="engine-license-note">
                  YourMT3+는 다중 파트 품질이 더 매력적이지만 upstream GitHub와 일부 배포본의 라이선스 표기가 서로 다릅니다.
                  품질 비교에는 사용할 수 있지만 상용 기본값으로 고정하기 전 별도 라이선스 검토를 권장합니다.
                </div>
              )}
              <p>
                MT3-Infer는 첫 사용 시 선택한 pretrained checkpoint를 로컬 캐시에 내려받습니다.
                처음부터 자체 모델을 학습할 필요가 없습니다.
              </p>
            </div>
          )}

          {engine === "native" && (
            <div className="engine-native-fields">
              <label><span>Native 실행 명령</span><input value={command} onChange={(event) => setCommand(event.target.value)} placeholder="audio-score-native" /></label>
              <label><span>프로젝트 소유 체크포인트</span><input value={checkpoint} onChange={(event) => setCheckpoint(event.target.value)} placeholder="/path/to/audio-score-native.pt" /></label>
              <p>향후 모델을 완전히 소유해야 할 때를 위한 R&D 경로입니다. 현재 기본 사용에는 학습이 필요하지 않습니다.</p>
            </div>
          )}

          {engine === "muscriptor" && (
            <div className="engine-license-note">
              MuScriptor 공개 모델 가중치는 비상업 조건이므로 상용 배포용 기본 엔진으로 사용하지 않습니다.
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
