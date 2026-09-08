import { useEffect, useState } from "react";
import "./engine-settings.css";

const API = "http://127.0.0.1:8080";

type UsageMode = "personal" | "commercial";

type EngineInfo = {
  key: string;
  name: string;
  ready: boolean;
  commercial_status: string;
  model?: string;
  model_commercial_status?: string;
  quality_rank?: number;
  quality_note?: string;
  license_note?: string;
  allowed_for_usage_mode?: boolean;
};

type EngineState = {
  usage_mode: UsageMode;
  selected: string;
  mt3_infer_cmd?: string | null;
  mt3_model?: string | null;
  muscriptor_cmd?: string | null;
  muscriptor_model?: string | null;
  native_checkpoint?: string | null;
  native_engine_cmd?: string | null;
  engines: EngineInfo[];
  recommendation?: { engine: string; model: string; reason: string };
  preflight: { ok: boolean; missing: string[] };
};

const fallbackEngines: EngineInfo[] = [
  { key: "muscriptor", name: "MuScriptor", ready: false, commercial_status: "noncommercial_weights", quality_rank: 1 },
  { key: "mt3_infer", name: "MT3-Infer", ready: false, commercial_status: "commercial_candidate", quality_rank: 2 },
  { key: "native", name: "AudioScore Native", ready: false, commercial_status: "project_owned", quality_rank: 4 },
];

const engineDescription = (key: string) => {
  if (key === "muscriptor") return "품질 최우선 · 개인/비상업 전용";
  if (key === "mt3_infer") return "YourMT3+ / MR-MT3 · 상용 후보";
  return "장기 R&D · 프로젝트 소유 체크포인트";
};

export default function EngineSettingsDock() {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<EngineState | null>(null);
  const [usageMode, setUsageMode] = useState<UsageMode>("personal");
  const [engine, setEngine] = useState("muscriptor");
  const [mt3Command, setMt3Command] = useState("mt3-infer");
  const [mt3Model, setMt3Model] = useState("yourmt3");
  const [muscriptorCommand, setMuscriptorCommand] = useState("muscriptor");
  const [muscriptorModel, setMuscriptorModel] = useState("large");
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
      setUsageMode(body.usage_mode ?? "personal");
      setEngine(body.selected === "yourmt3" ? "mt3_infer" : body.selected);
      setMt3Command(body.mt3_infer_cmd ?? "mt3-infer");
      setMt3Model(body.mt3_model ?? "yourmt3");
      setMuscriptorCommand(body.muscriptor_cmd ?? "muscriptor");
      setMuscriptorModel(body.muscriptor_model ?? "large");
      setCheckpoint(body.native_checkpoint ?? "");
      setCommand(body.native_engine_cmd ?? "audio-score-native");
    } catch {
      // Main application communicates backend connectivity separately.
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    if (usageMode === "commercial" && engine === "muscriptor") {
      setEngine("mt3_infer");
      setMt3Model("yourmt3");
      setMessage("상용 모드에서는 MuScriptor의 CC BY-NC weights를 사용할 수 없어 YourMT3+로 전환했습니다.");
    }
  }, [usageMode, engine]);

  const save = async () => {
    setSaving(true);
    setMessage("");
    try {
      const response = await fetch(`${API}/api/engines`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          usage_mode: usageMode,
          transcription_engine: engine,
          mt3_infer_cmd: mt3Command || null,
          mt3_model: mt3Model,
          muscriptor_cmd: muscriptorCommand || null,
          muscriptor_model: muscriptorModel,
          native_engine_cmd: command || null,
          native_checkpoint: checkpoint || null,
        }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail ?? "엔진 설정을 저장하지 못했습니다.");
      setState(body);
      setMessage("채보 엔진 정책을 저장했습니다.");
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
            <div><span>QUALITY-FIRST TRANSCRIPTION</span><h3>채보 엔진</h3></div>
            <button onClick={() => setOpen(false)} aria-label="닫기">×</button>
          </div>

          <div className="engine-native-fields">
            <label>
              <span>사용 목적</span>
              <select value={usageMode} onChange={(event) => setUsageMode(event.target.value as UsageMode)}>
                <option value="personal">개인 / 비상업 · 정확도 최우선</option>
                <option value="commercial">상용 · 라이선스 제약 적용</option>
              </select>
            </label>
            <p>
              개인 모드는 MuScriptor-large를 최우선으로 사용합니다. 상용 모드에서는 CC BY-NC weights를 자동 차단합니다.
            </p>
          </div>

          <div className="engine-choice-grid">
            {(state?.engines ?? fallbackEngines).map((item) => {
              const disabled = usageMode === "commercial" && item.key === "muscriptor";
              return (
                <button
                  key={item.key}
                  className={engine === item.key ? "selected" : ""}
                  disabled={disabled}
                  onClick={() => !disabled && setEngine(item.key)}
                >
                  <strong>{item.name}</strong>
                  <small>{engineDescription(item.key)}</small>
                  <em className={item.ready ? "ready" : "warning"}>
                    {disabled ? "상용 사용 불가" : item.ready ? "준비됨" : "첫 실행 준비 필요"}
                  </em>
                </button>
              );
            })}
          </div>

          {engine === "muscriptor" && (
            <div className="engine-native-fields">
              <label>
                <span>MuScriptor 모델</span>
                <select value={muscriptorModel} onChange={(event) => setMuscriptorModel(event.target.value)}>
                  <option value="large">Large · 정확도 최우선</option>
                  <option value="medium">Medium</option>
                  <option value="small">Small</option>
                </select>
              </label>
              <label>
                <span>MuScriptor 실행 명령</span>
                <input value={muscriptorCommand} onChange={(event) => setMuscriptorCommand(event.target.value)} placeholder="muscriptor" />
              </label>
              <div className="engine-license-note safe">
                개인/비상업용 최고 품질 기본 경로입니다. 코드 자체는 MIT지만 공개 model weights는 CC BY-NC 4.0이므로 상용 사용은 차단됩니다.
              </div>
              <p>첫 사용 전 Hugging Face에서 모델 라이선스를 수락하고 로그인해야 합니다.</p>
            </div>
          )}

          {engine === "mt3_infer" && (
            <div className="engine-native-fields">
              <label>
                <span>모델</span>
                <select value={mt3Model} onChange={(event) => setMt3Model(event.target.value)}>
                  <option value="yourmt3">YourMT3+ · MT3 계열 정확도 우선</option>
                  <option value="mr_mt3">MR-MT3 · 빠른 permissive fallback</option>
                </select>
              </label>
              <label>
                <span>MT3-Infer 실행 명령</span>
                <input value={mt3Command} onChange={(event) => setMt3Command(event.target.value)} placeholder="mt3-infer" />
              </label>
              {mt3Model === "yourmt3" ? (
                <div className="engine-license-note">
                  YourMT3+ checkpoint와 mt3-infer vendored implementation은 Apache-2.0으로 표기되지만 공식 GitHub 저장소는 GPL-3.0입니다. 개인 사용에는 문제가 없고, 상용 배포 전에는 고정 revision 기준 provenance 검토가 필요합니다.
                </div>
              ) : (
                <div className="engine-license-note safe">
                  MR-MT3 원 구현과 공개 checkpoint는 MIT로 표시되어 있어 라이선스가 더 단순합니다. 정확도보다 배포 단순성/속도를 우선할 때 사용합니다.
                </div>
              )}
            </div>
          )}

          {engine === "native" && (
            <div className="engine-native-fields">
              <label><span>Native 실행 명령</span><input value={command} onChange={(event) => setCommand(event.target.value)} placeholder="audio-score-native" /></label>
              <label><span>프로젝트 소유 체크포인트</span><input value={checkpoint} onChange={(event) => setCheckpoint(event.target.value)} placeholder="/path/to/audio-score-native.pt" /></label>
              <p>장기적으로 외부 weights를 제거해야 할 때를 위한 R&D 경로입니다.</p>
            </div>
          )}

          {state?.recommendation && (
            <div className="engine-license-note safe">
              권장: {state.recommendation.engine} / {state.recommendation.model} — {state.recommendation.reason}
            </div>
          )}
          {message && <p className="engine-message">{message}</p>}
          <button className="engine-save" disabled={saving} onClick={() => void save()}>
            {saving ? "저장 중…" : "엔진 정책 저장"}
          </button>
        </section>
      )}
    </div>
  );
}
