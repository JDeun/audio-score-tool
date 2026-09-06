import { ChangeEvent, DragEvent, useEffect, useMemo, useRef, useState } from "react";

const API = "http://127.0.0.1:8080";

type DevicePlan = {
  torch_device: string;
  muscriptor_device: string;
  demucs_device: string;
  whisperx_device: string;
  whisperx_compute_type: string;
};

type Health = {
  status: string;
  device_plan: DevicePlan;
  preflight: {
    ok: boolean;
    missing: string[];
    tools: Record<string, boolean>;
  };
};

type Job = {
  job_id: string;
  status: "queued" | "running" | "done" | "failed";
  stage?: string;
  progress?: number;
  filename?: string;
  error?: string;
  result?: {
    midi?: string;
    musicxml?: string;
    lyric_musicxml?: string;
    pdf?: string;
    transcript_json?: string;
    warnings?: string[];
  };
};

const stageLabel: Record<string, string> = {
  queued: "대기 중",
  transcription: "악보 채보",
  vocal_separation: "보컬 분리",
  lyrics_asr: "가사 인식",
  lyric_alignment: "가사·노트 정렬",
  rendering: "악보 렌더링",
  complete: "완료",
};

function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [backendError, setBackendError] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [language, setLanguage] = useState("ko");
  const [lyrics, setLyrics] = useState(true);
  const [muscriptorModel, setMuscriptorModel] = useState("medium");
  const [whisperxModel, setWhisperxModel] = useState("small");
  const [job, setJob] = useState<Job | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const refreshHealth = async () => {
    try {
      const res = await fetch(`${API}/api/health`);
      if (!res.ok) throw new Error("backend unavailable");
      setHealth(await res.json());
      setBackendError(false);
    } catch {
      setBackendError(true);
    }
  };

  useEffect(() => {
    void refreshHealth();
    const timer = window.setInterval(refreshHealth, 5000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!job || job.status === "done" || job.status === "failed") return;
    const timer = window.setInterval(async () => {
      try {
        const res = await fetch(`${API}/api/jobs/${job.job_id}`);
        if (res.ok) setJob(await res.json());
      } catch {
        // Preserve the current job card while the backend reconnects.
      }
    }, 900);
    return () => window.clearInterval(timer);
  }, [job?.job_id, job?.status]);

  const accelerator = useMemo(() => {
    if (!health) return "Checking";
    const d = health.device_plan.muscriptor_device;
    if (d.startsWith("cuda")) return "NVIDIA CUDA";
    if (d === "mps") return "Apple Metal";
    return "CPU";
  }, [health]);

  const chooseFile = (candidate?: File) => {
    if (candidate) {
      setFile(candidate);
      setJob(null);
    }
  };

  const onFileInput = (event: ChangeEvent<HTMLInputElement>) =>
    chooseFile(event.target.files?.[0]);

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    chooseFile(event.dataTransfer.files?.[0]);
  };

  const submit = async () => {
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    body.append("language", language);
    body.append("skip_lyrics", String(!lyrics));
    body.append("muscriptor_model", muscriptorModel);
    body.append("whisperx_model", whisperxModel);

    const res = await fetch(`${API}/api/jobs`, { method: "POST", body });
    if (!res.ok) throw new Error(await res.text());
    setJob(await res.json());
  };

  const artifactUrl = (kind: string) =>
    job ? `${API}/api/jobs/${job.job_id}/files/${kind}` : "#";

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">LOCAL MUSIC INTELLIGENCE</div>
          <h1>AudioScoreTool</h1>
        </div>
        <div className={`backend-pill ${backendError ? "bad" : "good"}`}>
          <span className="status-dot" />
          {backendError ? "Backend offline" : accelerator}
        </div>
      </header>

      <section className="layout">
        <div className="primary">
          <section
            className={`dropzone ${dragging ? "dragging" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            onClick={() => inputRef.current?.click()}
          >
            <input ref={inputRef} type="file" accept="audio/*" hidden onChange={onFileInput} />
            <div className="music-icon">♪</div>
            {file ? (
              <>
                <h2>{file.name}</h2>
                <p>{(file.size / 1024 / 1024).toFixed(1)} MB · 클릭하여 다른 파일 선택</p>
              </>
            ) : (
              <>
                <h2>오디오 파일을 놓아주세요</h2>
                <p>WAV, MP3, FLAC, M4A · 또는 클릭하여 선택</p>
              </>
            )}
          </section>

          <section className="controls card">
            <div className="field">
              <label>MuScriptor</label>
              <select value={muscriptorModel} onChange={(e) => setMuscriptorModel(e.target.value)}>
                <option value="small">Small · CPU friendly</option>
                <option value="medium">Medium · Balanced</option>
                <option value="large">Large · Best quality</option>
              </select>
            </div>
            <div className="field">
              <label>WhisperX</label>
              <select value={whisperxModel} disabled={!lyrics} onChange={(e) => setWhisperxModel(e.target.value)}>
                <option value="small">Small</option>
                <option value="medium">Medium</option>
                <option value="large-v3">Large v3</option>
              </select>
            </div>
            <div className="field">
              <label>가사 언어</label>
              <select value={language} disabled={!lyrics} onChange={(e) => setLanguage(e.target.value)}>
                <option value="ko">한국어</option>
                <option value="en">English</option>
                <option value="">자동 감지</option>
              </select>
            </div>
            <div className="field">
              <label>가사 정렬</label>
              <button
                className={`toggle ${lyrics ? "on" : ""}`}
                onClick={() => setLyrics((v) => !v)}
                aria-pressed={lyrics}
              >
                <span />
                {lyrics ? "포함" : "악보만"}
              </button>
            </div>
            <button className="run-button" disabled={!file || backendError || !!(job && job.status === "running")} onClick={submit}>
              Transcribe
            </button>
          </section>

          {job && (
            <section className="card progress-card">
              <div className="progress-title">
                <div>
                  <span className="eyebrow">PROCESS</span>
                  <h3>{job.status === "failed" ? "처리 실패" : stageLabel[job.stage ?? "queued"] ?? job.stage}</h3>
                </div>
                <strong>{job.progress ?? 0}%</strong>
              </div>
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${job.progress ?? 0}%` }} />
              </div>
              {job.error && <pre className="error">{job.error}</pre>}
              {job.status === "done" && (
                <div className="artifacts">
                  <a href={artifactUrl("pdf")} target="_blank">PDF Score</a>
                  <a href={artifactUrl("musicxml")} target="_blank">MusicXML</a>
                  <a href={artifactUrl("midi")} target="_blank">MIDI</a>
                  {lyrics && <a href={artifactUrl("transcript")} target="_blank">Lyrics JSON</a>}
                </div>
              )}
            </section>
          )}
        </div>

        <aside>
          <section className="card environment">
            <div className="section-head">
              <span className="eyebrow">ENVIRONMENT</span>
              <button className="icon-button" onClick={refreshHealth}>↻</button>
            </div>
            <h3>{accelerator}</h3>
            {health && (
              <dl>
                <div><dt>MuScriptor</dt><dd>{health.device_plan.muscriptor_device}</dd></div>
                <div><dt>Demucs</dt><dd>{health.device_plan.demucs_device}</dd></div>
                <div><dt>WhisperX</dt><dd>{health.device_plan.whisperx_device}</dd></div>
              </dl>
            )}
          </section>

          <section className="card tools">
            <span className="eyebrow">LOCAL TOOLS</span>
            {backendError ? (
              <p className="muted">Python backend에 연결할 수 없습니다.</p>
            ) : health ? (
              Object.entries(health.preflight.tools).map(([name, ok]) => (
                <div className="tool-row" key={name}>
                  <span>{name.replace("_override_or_path", "")}</span>
                  <span className={ok ? "ok" : "missing"}>{ok ? "Ready" : "Missing"}</span>
                </div>
              ))
            ) : <p className="muted">Checking…</p>}
          </section>

          <section className="card note">
            <span className="eyebrow">PIPELINE</span>
            <p>MuScriptor가 전체 악보를 생성하고, Demucs + WhisperX가 가사를 추출한 뒤 MusicXML 노트에 정렬합니다.</p>
          </section>
        </aside>
      </section>
    </main>
  );
}

export default App;
