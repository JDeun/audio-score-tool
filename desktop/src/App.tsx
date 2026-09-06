import { ChangeEvent, DragEvent, useEffect, useMemo, useRef, useState } from "react";

const API = "http://127.0.0.1:8080";

type DevicePlan = {
  torch_device: string;
  muscriptor_device: string;
  demucs_device: string;
  whisperx_device: string;
  whisperx_compute_type: string;
};

type Preset = {
  key: string;
  label: string;
  muscriptor_model: string;
  whisperx_model: string;
  description: string;
};

type Health = {
  status: string;
  device_plan: DevicePlan;
  preflight: {
    ok: boolean;
    missing: string[];
    tools: Record<string, boolean>;
  };
  presets: {
    recommended: string;
    presets: Preset[];
  };
  data_dir: string;
};

type SetupInfo = {
  preflight: Health["preflight"];
  tool_paths: Record<string, string>;
  instructions: {
    python_tools: { name: string; command: string }[];
    musescore: string;
    hf_required: boolean;
    hf_note: string;
  };
};

type Job = {
  job_id: string;
  kind?: "transcription" | "benchmark";
  status:
    | "queued"
    | "running"
    | "cancelling"
    | "cancelled"
    | "interrupted"
    | "done"
    | "failed";
  stage?: string;
  progress?: number;
  filename?: string;
  language?: string;
  preset?: string;
  muscriptor_model?: string;
  whisperx_model?: string;
  created_at?: string;
  updated_at?: string;
  error?: string;
  result?: {
    midi?: string;
    musicxml?: string;
    lyric_musicxml?: string;
    pdf?: string;
    transcript_json?: string;
    warnings?: string[];
    benchmark_json?: string;
    benchmark_csv?: string;
    runs?: number;
    successful_runs?: number;
  };
};

const stageLabel: Record<string, string> = {
  queued: "대기 중",
  starting: "시작 중",
  transcription: "악보 채보",
  vocal_separation: "보컬 분리",
  lyrics_asr: "가사 인식",
  lyric_alignment: "가사·노트 정렬",
  rendering: "악보 렌더링",
  cancelling: "취소 중",
  cancelled: "취소됨",
  interrupted: "중단됨",
  failed: "실패",
  complete: "완료",
};

function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [setup, setSetup] = useState<SetupInfo | null>(null);
  const [toolPaths, setToolPaths] = useState<Record<string, string>>({});
  const [settingsSaved, setSettingsSaved] = useState(false);
  const [backendError, setBackendError] = useState(false);
  const [tab, setTab] = useState<"transcribe" | "benchmark" | "history" | "setup">("transcribe");
  const [file, setFile] = useState<File | null>(null);
  const [language, setLanguage] = useState("ko");
  const [lyrics, setLyrics] = useState(true);
  const [preset, setPreset] = useState("auto");
  const [muscriptorModel, setMuscriptorModel] = useState("medium");
  const [whisperxModel, setWhisperxModel] = useState("small");
  const [job, setJob] = useState<Job | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [dragging, setDragging] = useState(false);
  const [benchmarkFile, setBenchmarkFile] = useState<File | null>(null);
  const [referenceMidi, setReferenceMidi] = useState<File | null>(null);
  const [benchmarkProfile, setBenchmarkProfile] = useState("all");
  const inputRef = useRef<HTMLInputElement>(null);
  const benchmarkInputRef = useRef<HTMLInputElement>(null);
  const referenceInputRef = useRef<HTMLInputElement>(null);

  const fetchJobs = async () => {
    try {
      const res = await fetch(`${API}/api/jobs?limit=80`);
      if (res.ok) {
        const body = await res.json();
        setJobs(body.jobs ?? []);
      }
    } catch {
      // Health polling owns the offline state.
    }
  };

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

  const refreshSetup = async () => {
    try {
      const res = await fetch(`${API}/api/setup`);
      if (res.ok) {
        const body = await res.json();
        setSetup(body);
        setToolPaths(body.tool_paths ?? {});
      }
    } catch {
      // Health card already communicates connectivity.
    }
  };

  useEffect(() => {
    void refreshHealth();
    void refreshSetup();
    void fetchJobs();
    const timer = window.setInterval(() => {
      void refreshHealth();
      void fetchJobs();
    }, 4000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!job || ["done", "failed", "cancelled", "interrupted"].includes(job.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const res = await fetch(`${API}/api/jobs/${job.job_id}`);
        if (res.ok) {
          const updated = await res.json();
          setJob(updated);
          void fetchJobs();
        }
      } catch {
        // Preserve the current card while the backend reconnects.
      }
    }, 800);
    return () => window.clearInterval(timer);
  }, [job?.job_id, job?.status]);

  const accelerator = useMemo(() => {
    if (!health) return "Checking";
    const d = health.device_plan.muscriptor_device;
    if (d.startsWith("cuda")) return "NVIDIA CUDA";
    if (d === "mps") return "Apple Metal";
    return "CPU";
  }, [health]);

  const recommended = health?.presets.recommended ?? "balanced";

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

  const saveToolPaths = async () => {
    const res = await fetch(`${API}/api/settings/tool-paths`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        muscriptor_cmd: toolPaths.muscriptor_cmd || null,
        demucs_cmd: toolPaths.demucs_cmd || null,
        whisperx_cmd: toolPaths.whisperx_cmd || null,
        musescore_cmd: toolPaths.musescore_cmd || null,
      }),
    });
    if (res.ok) {
      setSettingsSaved(true);
      window.setTimeout(() => setSettingsSaved(false), 1800);
      await refreshHealth();
      await refreshSetup();
    }
  };

  const submit = async () => {
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    body.append("language", language);
    body.append("skip_lyrics", String(!lyrics));

    if (preset === "custom") {
      body.append("preset", "balanced");
      body.append("muscriptor_model", muscriptorModel);
      body.append("whisperx_model", whisperxModel);
    } else {
      body.append("preset", preset);
    }

    const res = await fetch(`${API}/api/jobs`, { method: "POST", body });
    if (!res.ok) throw new Error(await res.text());
    setJob(await res.json());
    void fetchJobs();
  };

  const submitBenchmark = async () => {
    if (!benchmarkFile) return;
    const body = new FormData();
    body.append("file", benchmarkFile);
    if (referenceMidi) body.append("reference_midi", referenceMidi);
    body.append("language", language);
    body.append("profile", benchmarkProfile);

    const res = await fetch(`${API}/api/benchmarks`, { method: "POST", body });
    if (!res.ok) throw new Error(await res.text());
    setJob(await res.json());
    void fetchJobs();
  };

  const cancelJob = async () => {
    if (!job) return;
    const res = await fetch(`${API}/api/jobs/${job.job_id}/cancel`, { method: "POST" });
    if (res.ok) {
      const fresh = await fetch(`${API}/api/jobs/${job.job_id}`);
      if (fresh.ok) setJob(await fresh.json());
    }
  };

  const deleteJob = async (target: Job) => {
    const res = await fetch(`${API}/api/jobs/${target.job_id}`, { method: "DELETE" });
    if (res.ok) {
      if (job?.job_id === target.job_id) setJob(null);
      void fetchJobs();
    }
  };

  const artifactUrl = (target: Job | null, kind: string) =>
    target ? `${API}/api/jobs/${target.job_id}/files/${kind}` : "#";

  const running = job && ["queued", "running", "cancelling"].includes(job.status);

  const renderArtifacts = (target: Job) => {
    if (target.status !== "done") return null;
    if (target.kind === "benchmark") {
      return (
        <div className="artifacts benchmark-artifacts">
          <a href={artifactUrl(target, "benchmark_json")} target="_blank">Benchmark JSON</a>
          <a href={artifactUrl(target, "benchmark_csv")} target="_blank">Benchmark CSV</a>
        </div>
      );
    }
    return (
      <div className="artifacts">
        <a href={artifactUrl(target, "pdf")} target="_blank">PDF Score</a>
        <a href={artifactUrl(target, "musicxml")} target="_blank">MusicXML</a>
        <a href={artifactUrl(target, "midi")} target="_blank">MIDI</a>
        {target.result?.transcript_json && (
          <a href={artifactUrl(target, "transcript")} target="_blank">Lyrics JSON</a>
        )}
      </div>
    );
  };

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">LOCAL MUSIC INTELLIGENCE</div>
          <h1>AudioScoreTool</h1>
        </div>
        <div className="header-actions">
          <nav className="tabs">
            <button className={tab === "transcribe" ? "active" : ""} onClick={() => setTab("transcribe")}>Transcribe</button>
            <button className={tab === "benchmark" ? "active" : ""} onClick={() => setTab("benchmark")}>Benchmark</button>
            <button className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>History</button>
            <button className={tab === "setup" ? "active" : ""} onClick={() => setTab("setup")}>Setup</button>
          </nav>
          <div className={`backend-pill ${backendError ? "bad" : "good"}`}>
            <span className="status-dot" />
            {backendError ? "Backend offline" : accelerator}
          </div>
        </div>
      </header>

      {tab === "transcribe" && (
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
                <label>품질 프리셋</label>
                <select value={preset} onChange={(e) => setPreset(e.target.value)}>
                  <option value="auto">Auto · {recommended}</option>
                  <option value="fast">Fast</option>
                  <option value="balanced">Balanced</option>
                  <option value="quality">Quality</option>
                  <option value="custom">Custom</option>
                </select>
              </div>
              {preset === "custom" && (
                <>
                  <div className="field">
                    <label>MuScriptor</label>
                    <select value={muscriptorModel} onChange={(e) => setMuscriptorModel(e.target.value)}>
                      <option value="small">Small</option>
                      <option value="medium">Medium</option>
                      <option value="large">Large</option>
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
                </>
              )}
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
              <button className="run-button" disabled={!file || backendError || !!running} onClick={submit}>
                Transcribe
              </button>
            </section>

            {job && (
              <section className="card progress-card">
                <div className="progress-title">
                  <div>
                    <span className="eyebrow">CURRENT JOB</span>
                    <h3>{job.filename ?? file?.name ?? "Transcription"}</h3>
                    <p className="muted">{stageLabel[job.stage ?? "queued"] ?? job.stage}</p>
                  </div>
                  <strong>{job.progress ?? 0}%</strong>
                </div>
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${job.progress ?? 0}%` }} />
                </div>
                {running && job.status !== "cancelling" && (
                  <button className="secondary danger" onClick={cancelJob}>Cancel job</button>
                )}
                {job.error && <pre className="error">{job.error}</pre>}
                {job.result?.warnings?.map((warning) => <p className="warning" key={warning}>{warning}</p>)}
                {renderArtifacts(job)}
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
              {health ? Object.entries(health.preflight.tools).map(([name, ok]) => (
                <div className="tool-row" key={name}>
                  <span>{name.replace("_override_or_path", "")}</span>
                  <span className={ok ? "ok" : "missing"}>{ok ? "Ready" : "Missing"}</span>
                </div>
              )) : <p className="muted">Checking…</p>}
              {health && !health.preflight.ok && (
                <button className="text-button" onClick={() => setTab("setup")}>Open setup guide →</button>
              )}
            </section>

            <section className="card note">
              <span className="eyebrow">AUTO PRESET</span>
              <p>현재 하드웨어에서는 <strong>{recommended}</strong> 프리셋을 기본 권장합니다. 실제 최적값은 로컬 benchmark 결과로 확정할 수 있습니다.</p>
            </section>
          </aside>
        </section>
      )}


      {tab === "benchmark" && (
        <section className="benchmark-grid">
          <section className="card setup-card">
            <span className="eyebrow">MODEL A/B</span>
            <h2>Local benchmark</h2>
            <p className="muted">같은 음원으로 MuScriptor / WhisperX 조합을 순차 실행합니다. Reference MIDI를 넣으면 Note Precision/Recall/F1과 onset MAE를 계산합니다.</p>

            <div className="benchmark-picker">
              <input ref={benchmarkInputRef} type="file" accept="audio/*" hidden onChange={(e) => setBenchmarkFile(e.target.files?.[0] ?? null)} />
              <button className="file-button" onClick={() => benchmarkInputRef.current?.click()}>
                <span>Audio</span>
                <strong>{benchmarkFile?.name ?? "Select test audio"}</strong>
              </button>
              <input ref={referenceInputRef} type="file" accept=".mid,.midi,audio/midi" hidden onChange={(e) => setReferenceMidi(e.target.files?.[0] ?? null)} />
              <button className="file-button optional" onClick={() => referenceInputRef.current?.click()}>
                <span>Ground Truth MIDI · optional</span>
                <strong>{referenceMidi?.name ?? "Select reference MIDI"}</strong>
              </button>
            </div>

            <div className="benchmark-options">
              <div className="field">
                <label>Benchmark profile</label>
                <select value={benchmarkProfile} onChange={(e) => setBenchmarkProfile(e.target.value)}>
                  <option value="score">Score only · MuScriptor S/M/L</option>
                  <option value="lyrics">Lyrics combinations</option>
                  <option value="all">All combinations</option>
                </select>
              </div>
              <div className="field">
                <label>가사 언어</label>
                <select value={language} onChange={(e) => setLanguage(e.target.value)}>
                  <option value="ko">한국어</option>
                  <option value="en">English</option>
                  <option value="">자동 감지</option>
                </select>
              </div>
              <button className="run-button" disabled={!benchmarkFile || backendError || !!running} onClick={submitBenchmark}>
                Run benchmark
              </button>
            </div>

            {job?.kind === "benchmark" && (
              <div className="benchmark-progress">
                <div className="progress-title">
                  <div>
                    <span className="eyebrow">BENCHMARK JOB</span>
                    <h3>{job.filename ?? benchmarkFile?.name}</h3>
                    <p className="muted">{job.stage ?? job.status}</p>
                  </div>
                  <strong>{job.progress ?? 0}%</strong>
                </div>
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${job.progress ?? 0}%` }} />
                </div>
                {running && job.status !== "cancelling" && (
                  <button className="secondary danger" onClick={cancelJob}>Cancel benchmark</button>
                )}
                {job.error && <pre className="error">{job.error}</pre>}
                {job.status === "done" && (
                  <>
                    <p className="muted">{job.result?.successful_runs ?? 0} / {job.result?.runs ?? 0} runs succeeded</p>
                    {renderArtifacts(job)}
                  </>
                )}
              </div>
            )}
          </section>

          <aside className="benchmark-aside">
            <section className="card note">
              <span className="eyebrow">WITHOUT REFERENCE</span>
              <p>실행 시간, 성공 여부, 가사 attachment ratio를 비교합니다.</p>
            </section>
            <section className="card note">
              <span className="eyebrow">WITH REFERENCE MIDI</span>
              <p>Note Precision / Recall / F1과 onset MAE(ms)를 추가로 계산합니다. 모델 선택에는 이 경로가 더 유효합니다.</p>
            </section>
          </aside>
        </section>
      )}

      {tab === "history" && (
        <section className="card history-card">
          <div className="history-head">
            <div>
              <span className="eyebrow">LOCAL HISTORY</span>
              <h2>최근 작업</h2>
            </div>
            <button className="secondary" onClick={fetchJobs}>Refresh</button>
          </div>
          {jobs.length === 0 ? (
            <p className="muted">아직 저장된 작업이 없습니다.</p>
          ) : (
            <div className="job-list">
              {jobs.map((item) => (
                <article className="job-row" key={item.job_id}>
                  <button className="job-main" onClick={() => { setJob(item); setTab(item.kind === "benchmark" ? "benchmark" : "transcribe"); }}>
                    <div>
                      <strong>{item.kind === "benchmark" ? "Benchmark · " : ""}{item.filename ?? "Untitled audio"}</strong>
                      <span>{item.kind === "benchmark" ? (item.preset ?? "all") : `${item.muscriptor_model} · ${item.whisperx_model}`} · {item.language || "auto"}</span>
                    </div>
                    <div className="job-state">
                      <span className={`state state-${item.status}`}>{stageLabel[item.status] ?? item.status}</span>
                      <small>{item.created_at ? new Date(item.created_at).toLocaleString() : ""}</small>
                    </div>
                  </button>
                  {item.status === "done" && <div className="history-artifacts">{renderArtifacts(item)}</div>}
                  {!["queued", "running", "cancelling"].includes(item.status) && (
                    <button className="delete-button" onClick={() => deleteJob(item)}>Delete</button>
                  )}
                </article>
              ))}
            </div>
          )}
        </section>
      )}

      {tab === "setup" && (
        <section className="setup-grid">
          <section className="card setup-card">
            <span className="eyebrow">FIRST RUN</span>
            <h2>Local dependencies</h2>
            <p className="muted">AudioScoreTool 자체는 모델 가중치와 상용 제한 자산을 재배포하지 않습니다.</p>
            {setup?.instructions.python_tools.map((tool) => {
              const key = tool.name.toLowerCase();
              const healthKey = key === "muscriptor" ? "muscriptor" : key;
              const ready = setup.preflight.tools[healthKey];
              return (
                <div className="setup-row" key={tool.name}>
                  <div>
                    <strong>{tool.name}</strong>
                    <code>{tool.command}</code>
                  </div>
                  <span className={ready ? "ok" : "missing"}>{ready ? "Ready" : "Required"}</span>
                </div>
              );
            })}
            <div className="setup-row">
              <div>
                <strong>MuseScore 4</strong>
                <p>{setup?.instructions.musescore}</p>
              </div>
              <span className={setup?.preflight.tools.musescore_override_or_path ? "ok" : "missing"}>
                {setup?.preflight.tools.musescore_override_or_path ? "Ready" : "Required"}
              </span>
            </div>
          </section>

          <section className="card setup-card">
            <span className="eyebrow">MODEL ACCESS</span>
            <h2>MuScriptor weights</h2>
            <p>{setup?.instructions.hf_note}</p>
            <div className="callout">
              <strong>사용자가 직접 해야 하는 부분</strong>
              <p>Hugging Face에서 MuScriptor 모델 라이선스를 수락하고 로컬 환경에서 인증해야 합니다. 토큰은 앱에 저장하지 않습니다.</p>
            </div>

            <span className="eyebrow">TOOL PATH OVERRIDES</span>
            <p>앱으로 직접 실행할 때 터미널 PATH가 전달되지 않는 경우 여기에서 실행 파일 또는 명령 경로를 지정할 수 있습니다.</p>
            <div className="path-fields">
              {[
                ["muscriptor_cmd", "MuScriptor"],
                ["demucs_cmd", "Demucs"],
                ["whisperx_cmd", "WhisperX"],
                ["musescore_cmd", "MuseScore"],
              ].map(([key, label]) => (
                <label className="path-field" key={key}>
                  <span>{label}</span>
                  <input
                    value={toolPaths[key] ?? ""}
                    placeholder="자동 검색"
                    onChange={(e) => setToolPaths((current) => ({ ...current, [key]: e.target.value }))}
                  />
                </label>
              ))}
            </div>
            <button className="secondary save-settings" onClick={saveToolPaths}>
              {settingsSaved ? "Saved" : "Save paths"}
            </button>

            <span className="eyebrow data-label">DATA LOCATION</span>
            <code className="path-code">{health?.data_dir ?? "Checking…"}</code>
          </section>
        </section>
      )}
    </main>
  );
}

export default App;
