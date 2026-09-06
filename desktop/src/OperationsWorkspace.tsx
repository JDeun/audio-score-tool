import { ChangeEvent, DragEvent, useEffect, useMemo, useRef, useState } from "react";

const API = "http://127.0.0.1:8080";

type Section = "new" | "history" | "benchmark" | "settings";
type SourceMode = "file" | "youtube";

type DevicePlan = {
  muscriptor_device: string;
  demucs_device: string;
  whisperx_device: string;
  whisperx_compute_type: string;
};

type Health = {
  status: string;
  device_plan: DevicePlan;
  preflight: { ok: boolean; missing: string[]; tools: Record<string, boolean> };
  presets: { recommended: string; presets: { key: string; label: string; description: string }[] };
  data_dir: string;
  system: {
    data_dir: string;
    jobs_bytes: number;
    disk_total_bytes: number;
    disk_used_bytes: number;
    disk_free_bytes: number;
    hf_authenticated: boolean;
  };
};

type SetupInfo = {
  preflight: Health["preflight"];
  tool_paths: Record<string, string>;
  instructions: {
    python_tools: { name: string; command: string }[];
    musescore: string;
    hf_login_command?: string;
    hf_note: string;
    runtime?: { recommended: string; note: string };
  };
};

type Job = {
  job_id: string;
  kind?: "transcription" | "benchmark";
  status: "queued" | "running" | "cancelling" | "cancelled" | "interrupted" | "done" | "failed";
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

type YoutubeMetadata = {
  title: string;
  uploader?: string | null;
  duration?: number | null;
  webpage_url: string;
};

type ConfirmState = {
  title: string;
  body: string;
  confirmLabel: string;
  danger?: boolean;
  action: () => Promise<void>;
} | null;

const stageLabel: Record<string, string> = {
  queued: "대기 중",
  starting: "준비 중",
  transcription: "악보 채보 중",
  vocal_separation: "보컬 분리 중",
  lyrics_asr: "가사 인식 중",
  lyric_alignment: "가사·노트 정렬 중",
  rendering: "악보 렌더링 중",
  cancelling: "취소 중",
  cancelled: "취소됨",
  interrupted: "중단됨",
  failed: "실패",
  complete: "완료",
};

const presetLabel: Record<string, string> = {
  auto: "자동",
  fast: "빠르게",
  balanced: "균형",
  quality: "고품질",
  custom: "직접 선택",
};

function formatBytes(bytes?: number) {
  if (bytes == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index < 2 ? 0 : 1)} ${units[index]}`;
}

function formatDuration(seconds?: number | null) {
  if (seconds == null || !Number.isFinite(seconds)) return "길이 정보 없음";
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`
    : `${minutes}:${String(secs).padStart(2, "0")}`;
}

function statusText(job: Job) {
  return stageLabel[job.stage ?? job.status] ?? job.stage ?? job.status;
}

function StatusPill({ status }: { status: Job["status"] }) {
  const label: Record<Job["status"], string> = {
    queued: "대기",
    running: "진행 중",
    cancelling: "취소 중",
    cancelled: "취소됨",
    interrupted: "중단됨",
    done: "완료",
    failed: "실패",
  };
  return <span className={`ui-status status-${status}`}><i />{label[status]}</span>;
}

function Toast({ message, kind = "success", onClose }: { message: string; kind?: "success" | "error"; onClose: () => void }) {
  useEffect(() => {
    const timer = window.setTimeout(onClose, 3200);
    return () => window.clearTimeout(timer);
  }, [message, onClose]);
  return (
    <div className={`product-toast ${kind}`} role="status" aria-live="polite">
      <span>{kind === "success" ? "✓" : "!"}</span>
      <p>{message}</p>
      <button onClick={onClose} aria-label="알림 닫기">×</button>
    </div>
  );
}

export default function OperationsWorkspace({ section, onOpenSongs }: { section: Section; onOpenSongs: () => void }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [setup, setSetup] = useState<SetupInfo | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [offline, setOffline] = useState(false);
  const [sourceMode, setSourceMode] = useState<SourceMode>("file");
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [youtubeMetadata, setYoutubeMetadata] = useState<YoutubeMetadata | null>(null);
  const [youtubeInspecting, setYoutubeInspecting] = useState(false);
  const [youtubeAuthorized, setYoutubeAuthorized] = useState(false);
  const [preset, setPreset] = useState("auto");
  const [language, setLanguage] = useState("ko");
  const [lyrics, setLyrics] = useState(true);
  const [muscriptorModel, setMuscriptorModel] = useState("medium");
  const [whisperxModel, setWhisperxModel] = useState("small");
  const [benchmarkFile, setBenchmarkFile] = useState<File | null>(null);
  const [referenceMidi, setReferenceMidi] = useState<File | null>(null);
  const [benchmarkProfile, setBenchmarkProfile] = useState("all");
  const [toolPaths, setToolPaths] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<{ message: string; kind: "success" | "error" } | null>(null);
  const [confirm, setConfirm] = useState<ConfirmState>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const benchmarkRef = useRef<HTMLInputElement>(null);
  const midiRef = useRef<HTMLInputElement>(null);

  const showToast = (message: string, kind: "success" | "error" = "success") => setToast({ message, kind });

  const refreshHealth = async () => {
    try {
      const response = await fetch(`${API}/api/health`);
      if (!response.ok) throw new Error("백엔드 연결 실패");
      setHealth(await response.json());
      setOffline(false);
    } catch {
      setOffline(true);
    }
  };

  const refreshSetup = async () => {
    try {
      const response = await fetch(`${API}/api/setup`);
      if (!response.ok) return;
      const body = await response.json();
      setSetup(body);
      setToolPaths(body.tool_paths ?? {});
    } catch {
      // Health state communicates connection errors.
    }
  };

  const refreshJobs = async () => {
    try {
      const response = await fetch(`${API}/api/jobs?limit=100`);
      if (!response.ok) return;
      const body = await response.json();
      setJobs(body.jobs ?? []);
    } catch {
      // Keep cached history while the sidecar reconnects.
    }
  };

  useEffect(() => {
    void refreshHealth();
    void refreshSetup();
    void refreshJobs();
    const timer = window.setInterval(() => {
      void refreshHealth();
      void refreshJobs();
    }, 4500);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!job || !["queued", "running", "cancelling"].includes(job.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`${API}/api/jobs/${job.job_id}`);
        if (response.ok) {
          const fresh = await response.json();
          setJob(fresh);
          void refreshJobs();
        }
      } catch {
        // Preserve state while reconnecting.
      }
    }, 800);
    return () => window.clearInterval(timer);
  }, [job?.job_id, job?.status]);

  const active = !!job && ["queued", "running", "cancelling"].includes(job.status);
  const recommended = health?.presets.recommended ?? "balanced";
  const accelerator = useMemo(() => {
    const device = health?.device_plan.muscriptor_device;
    if (!device) return "확인 중";
    if (device.startsWith("cuda")) return "NVIDIA CUDA";
    if (device === "mps") return "Apple Metal";
    return "CPU";
  }, [health]);

  const artifactUrl = (target: Job, kind: string) => `${API}/api/jobs/${target.job_id}/files/${kind}`;

  const chooseFile = (candidate?: File) => {
    if (!candidate) return;
    setFile(candidate);
    setJob(null);
  };

  const dropFile = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    chooseFile(event.dataTransfer.files?.[0]);
  };

  const inspectYoutube = async () => {
    if (!youtubeUrl.trim()) return;
    setYoutubeInspecting(true);
    setYoutubeMetadata(null);
    try {
      const response = await fetch(`${API}/api/sources/youtube/inspect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: youtubeUrl }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail ?? "YouTube 링크를 확인할 수 없습니다.");
      setYoutubeMetadata(body);
      showToast("YouTube 음원을 확인했습니다.");
    } catch (error) {
      showToast(error instanceof Error ? error.message : String(error), "error");
    } finally {
      setYoutubeInspecting(false);
    }
  };

  const startTranscription = async () => {
    setBusy(true);
    try {
      let response: Response;
      if (sourceMode === "file") {
        if (!file) throw new Error("먼저 음원 파일을 선택하세요.");
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
        response = await fetch(`${API}/api/jobs`, { method: "POST", body });
      } else {
        if (!youtubeMetadata) throw new Error("YouTube 링크를 먼저 확인하세요.");
        if (!youtubeAuthorized) throw new Error("콘텐츠 처리 권한을 확인해야 합니다.");
        response = await fetch(`${API}/api/jobs/youtube`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            url: youtubeUrl,
            authorized: true,
            language,
            skip_lyrics: !lyrics,
            preset: preset === "custom" ? "balanced" : preset,
          }),
        });
      }
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail ?? "채보 작업을 시작하지 못했습니다.");
      setJob({
        job_id: body.job_id,
        status: "queued",
        stage: "queued",
        progress: 0,
        filename: sourceMode === "file" ? file?.name : youtubeMetadata?.title,
      });
      showToast("채보 작업을 시작했습니다.");
    } catch (error) {
      showToast(error instanceof Error ? error.message : String(error), "error");
    } finally {
      setBusy(false);
    }
  };

  const cancelJob = async () => {
    if (!job) return;
    await fetch(`${API}/api/jobs/${job.job_id}/cancel`, { method: "POST" });
  };

  const retryJob = async (target: Job) => {
    try {
      const response = await fetch(`${API}/api/jobs/${target.job_id}/retry`, { method: "POST" });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail ?? "작업을 다시 시작하지 못했습니다.");
      const fresh = await fetch(`${API}/api/jobs/${body.job_id}`);
      if (fresh.ok) setJob(await fresh.json());
      await refreshJobs();
      showToast("작업을 다시 시작했습니다.");
    } catch (error) {
      showToast(error instanceof Error ? error.message : String(error), "error");
    }
  };

  const deleteJob = (target: Job) => {
    setConfirm({
      title: "작업 내역을 삭제할까요?",
      body: `‘${target.filename ?? "이 작업"}’의 로컬 작업 파일과 기록을 삭제합니다. 곡 라이브러리에 별도로 저장된 곡은 유지됩니다.`,
      confirmLabel: "작업 삭제",
      danger: true,
      action: async () => {
        const response = await fetch(`${API}/api/jobs/${target.job_id}`, { method: "DELETE" });
        if (!response.ok) throw new Error(await response.text());
        if (job?.job_id === target.job_id) setJob(null);
        await refreshJobs();
        showToast("작업 내역을 삭제했습니다.");
      },
    });
  };

  const revealJob = async (target: Job) => {
    const response = await fetch(`${API}/api/jobs/${target.job_id}/reveal`, { method: "POST" });
    if (!response.ok) showToast("출력 폴더를 열지 못했습니다.", "error");
  };

  const startBenchmark = async () => {
    if (!benchmarkFile) return;
    setBusy(true);
    try {
      const body = new FormData();
      body.append("file", benchmarkFile);
      if (referenceMidi) body.append("reference_midi", referenceMidi);
      body.append("language", language);
      body.append("profile", benchmarkProfile);
      const response = await fetch(`${API}/api/benchmarks`, { method: "POST", body });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(payload?.detail ?? "성능 비교를 시작하지 못했습니다.");
      setJob({ job_id: payload.job_id, status: "queued", stage: "queued", progress: 0, filename: benchmarkFile.name, kind: "benchmark" });
      showToast("성능 비교를 시작했습니다.");
    } catch (error) {
      showToast(error instanceof Error ? error.message : String(error), "error");
    } finally {
      setBusy(false);
    }
  };

  const savePaths = async () => {
    setBusy(true);
    try {
      const response = await fetch(`${API}/api/settings/tool-paths`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          muscriptor_cmd: toolPaths.muscriptor_cmd || null,
          demucs_cmd: toolPaths.demucs_cmd || null,
          whisperx_cmd: toolPaths.whisperx_cmd || null,
          musescore_cmd: toolPaths.musescore_cmd || null,
        }),
      });
      if (!response.ok) throw new Error(await response.text());
      await Promise.all([refreshHealth(), refreshSetup()]);
      showToast("실행 파일 경로를 저장했습니다.");
    } catch (error) {
      showToast(error instanceof Error ? error.message : String(error), "error");
    } finally {
      setBusy(false);
    }
  };

  const cleanupStorage = () => {
    setConfirm({
      title: "오래된 작업 데이터를 정리할까요?",
      body: "최근 30개 작업은 유지하고 그보다 오래된 완료·실패 작업 파일을 삭제합니다. 곡 라이브러리는 삭제하지 않습니다.",
      confirmLabel: "저장공간 정리",
      action: async () => {
        const response = await fetch(`${API}/api/storage/cleanup?keep=30`, { method: "POST" });
        const body = await response.json().catch(() => null);
        if (!response.ok) throw new Error(body?.detail ?? "저장공간을 정리하지 못했습니다.");
        await Promise.all([refreshHealth(), refreshJobs()]);
        showToast(`${body.deleted_jobs ?? 0}개의 오래된 작업을 정리했습니다.`);
      },
    });
  };

  const renderArtifacts = (target: Job) => {
    if (target.status !== "done") return null;
    if (target.kind === "benchmark") {
      return (
        <div className="artifact-buttons compact">
          <a href={artifactUrl(target, "benchmark_json")} target="_blank">JSON 결과</a>
          <a href={artifactUrl(target, "benchmark_csv")} target="_blank">CSV 결과</a>
          <button onClick={() => void revealJob(target)}>폴더 열기</button>
        </div>
      );
    }
    return (
      <div className="artifact-buttons compact">
        <a href={artifactUrl(target, "pdf")} target="_blank">PDF</a>
        <a href={artifactUrl(target, "musicxml")} target="_blank">MusicXML</a>
        <a href={artifactUrl(target, "midi")} target="_blank">MIDI</a>
        <button onClick={() => void revealJob(target)}>폴더 열기</button>
      </div>
    );
  };

  const currentJobCard = job ? (
    <section className={`work-card current-job status-${job.status}`}>
      <div className="job-card-top">
        <div>
          <span className="card-kicker">현재 작업</span>
          <h3>{job.filename ?? (job.kind === "benchmark" ? "성능 비교" : "새 악보")}</h3>
          <p>{statusText(job)}</p>
        </div>
        <div className="job-percentage">{job.progress ?? 0}<small>%</small></div>
      </div>
      <div className="product-progress" role="progressbar" aria-valuenow={job.progress ?? 0} aria-valuemin={0} aria-valuemax={100}>
        <span style={{ width: `${job.progress ?? 0}%` }} />
      </div>
      {job.error && <div className="inline-error"><strong>작업을 완료하지 못했습니다.</strong><p>{job.error}</p></div>}
      {job.result?.warnings?.map((warning) => <div className="inline-warning" key={warning}>{warning}</div>)}
      <div className="job-card-actions">
        {active && job.status !== "cancelling" && <button className="secondary-button danger-text" onClick={() => void cancelJob()}>작업 취소</button>}
        {job.status === "done" && job.kind !== "benchmark" && <button className="primary-button" onClick={onOpenSongs}>곡 라이브러리에서 편집</button>}
        {renderArtifacts(job)}
      </div>
    </section>
  ) : null;

  let content;

  if (section === "new") {
    content = (
      <div className="operations-page new-score-page">
        <section className="source-card work-card">
          <div className="segmented-control" role="tablist" aria-label="입력 방식">
            <button role="tab" aria-selected={sourceMode === "file"} className={sourceMode === "file" ? "active" : ""} onClick={() => setSourceMode("file")}>내 파일</button>
            <button role="tab" aria-selected={sourceMode === "youtube"} className={sourceMode === "youtube" ? "active" : ""} onClick={() => setSourceMode("youtube")}>YouTube 링크</button>
          </div>
          {sourceMode === "file" ? (
            <div className={`premium-dropzone ${dragging ? "dragging" : ""} ${file ? "has-file" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={dropFile} onClick={() => fileRef.current?.click()}>
              <input ref={fileRef} type="file" accept="audio/*" hidden onChange={(event: ChangeEvent<HTMLInputElement>) => chooseFile(event.target.files?.[0])} />
              <div className="dropzone-symbol">♫</div>
              {file ? <><span className="card-kicker">선택한 음원</span><h2>{file.name}</h2><p>{(file.size / 1024 / 1024).toFixed(1)} MB · 클릭하면 다른 파일을 선택할 수 있습니다.</p></> : <><h2>음원을 여기에 놓으세요</h2><p>WAV, MP3, FLAC, M4A, AAC, OGG, OPUS · 또는 클릭하여 파일 선택</p><span className="drop-hint">파일은 외부 서버로 업로드되지 않습니다.</span></>}
            </div>
          ) : (
            <div className="youtube-inline-source">
              <div className="youtube-inline-icon">▶</div>
              <div className="youtube-inline-copy"><span className="card-kicker">YouTube → 오디오 → 악보</span><h2>YouTube 링크에서 바로 채보</h2><p>링크를 확인한 뒤 최적의 오디오 스트림만 로컬로 가져와 동일한 채보 파이프라인을 실행합니다.</p></div>
              <div className="youtube-inline-row"><input type="url" value={youtubeUrl} placeholder="https://www.youtube.com/watch?v=…" disabled={active} onChange={(event) => { setYoutubeUrl(event.target.value); setYoutubeMetadata(null); }} onKeyDown={(event) => event.key === "Enter" && void inspectYoutube()} /><button className="secondary-button" disabled={!youtubeUrl.trim() || youtubeInspecting || active} onClick={() => void inspectYoutube()}>{youtubeInspecting ? "확인 중…" : "링크 확인"}</button></div>
              {youtubeMetadata && <div className="source-preview-row"><div className="source-preview-note">♪</div><div><strong>{youtubeMetadata.title}</strong><span>{youtubeMetadata.uploader ?? "YouTube"} · {formatDuration(youtubeMetadata.duration)}</span></div><span className="source-ready">준비됨</span></div>}
              <label className="rights-check"><input type="checkbox" checked={youtubeAuthorized} disabled={active} onChange={(event) => setYoutubeAuthorized(event.target.checked)} /><span>이 콘텐츠를 다운로드·처리할 권한이 있거나 YouTube/권리자가 허용한 콘텐츠임을 확인합니다.</span></label>
            </div>
          )}
        </section>
        <section className="transcription-options work-card">
          <div className="section-title-row"><div><span className="card-kicker">채보 설정</span><h3>결과 품질과 가사 인식을 선택하세요</h3></div><span className="hardware-badge">{accelerator}</span></div>
          <div className="premium-form-grid">
            <label><span>품질</span><select value={preset} onChange={(event) => setPreset(event.target.value)}><option value="auto">자동 · {presetLabel[recommended] ?? recommended}</option><option value="fast">빠르게</option><option value="balanced">균형</option><option value="quality">고품질</option><option value="custom">직접 선택</option></select><small>현재 컴퓨터에서는 ‘{presetLabel[recommended] ?? recommended}’을 권장합니다.</small></label>
            <label><span>가사 언어</span><select value={language} disabled={!lyrics} onChange={(event) => setLanguage(event.target.value)}><option value="ko">한국어</option><option value="en">영어</option><option value="">자동 감지</option></select><small>가사 정렬 정확도를 높이려면 언어를 직접 지정하세요.</small></label>
            <label className="switch-field"><span>가사 인식·정렬</span><button className={`product-switch ${lyrics ? "on" : ""}`} onClick={() => setLyrics((value) => !value)} aria-pressed={lyrics}><i />{lyrics ? "포함" : "악보만"}</button><small>보컬 파트에 인식한 가사를 자동 배치합니다.</small></label>
          </div>
          {preset === "custom" && <div className="custom-model-row"><label><span>MuScriptor</span><select value={muscriptorModel} onChange={(event) => setMuscriptorModel(event.target.value)}><option value="small">Small</option><option value="medium">Medium</option><option value="large">Large</option></select></label><label><span>WhisperX</span><select value={whisperxModel} disabled={!lyrics} onChange={(event) => setWhisperxModel(event.target.value)}><option value="small">Small</option><option value="medium">Medium</option><option value="large-v3">Large v3</option></select></label></div>}
          <div className="primary-action-row">{!health?.preflight.ok && <span className="setup-needed">일부 실행 환경을 확인해야 합니다. 설정 메뉴에서 상태를 확인하세요.</span>}<button className="primary-button large" disabled={busy || active || offline || (sourceMode === "file" ? !file : !youtubeMetadata || !youtubeAuthorized)} onClick={() => void startTranscription()}>{active ? "작업 진행 중" : "자동 채보 시작"}</button></div>
        </section>
        {currentJobCard}
        <section className="workflow-strip" aria-label="자동 채보 과정"><div><b>1</b><span>음원 분석</span></div><i /><div><b>2</b><span>파트별 채보</span></div><i /><div><b>3</b><span>코드·가사</span></div><i /><div><b>4</b><span>악보 편집</span></div><i /><div><b>5</b><span>PDF 내보내기</span></div></section>
      </div>
    );
  } else if (section === "history") {
    content = (
      <div className="operations-page">
        <section className="work-card history-panel">
          <div className="section-title-row"><div><span className="card-kicker">로컬 작업 기록</span><h2>최근 작업</h2><p>채보와 성능 비교 작업은 이 컴퓨터에만 저장됩니다.</p></div><button className="secondary-button" onClick={() => void refreshJobs()}>새로고침</button></div>
          {jobs.length === 0 ? <div className="premium-empty"><div>⌁</div><h3>아직 작업 내역이 없습니다</h3><p>새 악보에서 첫 번째 음원을 채보해 보세요.</p></div> : <div className="premium-job-list">{jobs.map((item) => <article key={item.job_id} className="premium-job-row"><div className="job-type-icon">{item.kind === "benchmark" ? "⌁" : "♫"}</div><div className="job-row-main"><strong>{item.filename ?? (item.kind === "benchmark" ? "성능 비교" : "이름 없는 음원")}</strong><span>{item.kind === "benchmark" ? `성능 비교 · ${item.preset ?? "전체"}` : `${item.muscriptor_model ?? "자동"} · ${item.whisperx_model ?? "자동"} · ${item.language || "언어 자동"}`}</span><small>{item.created_at ? new Date(item.created_at).toLocaleString() : ""}</small></div><StatusPill status={item.status} /><div className="job-row-actions">{item.status === "done" && renderArtifacts(item)}{!["queued", "running", "cancelling"].includes(item.status) && <button className="text-action" onClick={() => void retryJob(item)}>다시 실행</button>}{!["queued", "running", "cancelling"].includes(item.status) && <button className="text-action danger" onClick={() => deleteJob(item)}>삭제</button>}</div></article>)}</div>}
        </section>
      </div>
    );
  } else if (section === "benchmark") {
    content = (
      <div className="operations-page benchmark-page">
        <section className="work-card">
          <div className="section-title-row"><div><span className="card-kicker">내 컴퓨터에서 직접 측정</span><h2>모델 성능 비교</h2><p>같은 음원을 여러 모델 조합에 넣어 품질과 처리 시간을 비교합니다.</p></div><span className="hardware-badge">{accelerator}</span></div>
          <div className="benchmark-file-grid"><input ref={benchmarkRef} type="file" accept="audio/*" hidden onChange={(event) => setBenchmarkFile(event.target.files?.[0] ?? null)} /><button className="file-selection-card" onClick={() => benchmarkRef.current?.click()}><span>테스트 음원</span><strong>{benchmarkFile?.name ?? "음원 파일 선택"}</strong><small>필수</small></button><input ref={midiRef} type="file" accept=".mid,.midi,audio/midi" hidden onChange={(event) => setReferenceMidi(event.target.files?.[0] ?? null)} /><button className="file-selection-card optional" onClick={() => midiRef.current?.click()}><span>정답 MIDI</span><strong>{referenceMidi?.name ?? "Reference MIDI 선택"}</strong><small>선택 · 정확도 지표 계산에 사용</small></button></div>
          <div className="premium-form-grid benchmark-controls"><label><span>비교 범위</span><select value={benchmarkProfile} onChange={(event) => setBenchmarkProfile(event.target.value)}><option value="score">악보 모델 · MuScriptor S/M/L</option><option value="lyrics">가사 모델 조합</option><option value="all">전체 조합</option></select></label><label><span>가사 언어</span><select value={language} onChange={(event) => setLanguage(event.target.value)}><option value="ko">한국어</option><option value="en">영어</option><option value="">자동 감지</option></select></label></div>
          <div className="benchmark-explain"><div><strong>정답 MIDI 없음</strong><span>처리 시간·성공 여부·가사 정렬률 비교</span></div><div><strong>정답 MIDI 있음</strong><span>Note Precision / Recall / F1, Onset MAE까지 계산</span></div></div>
          <div className="primary-action-row"><button className="primary-button large" disabled={!benchmarkFile || busy || active || offline} onClick={() => void startBenchmark()}>성능 비교 시작</button></div>
        </section>
        {job?.kind === "benchmark" && currentJobCard}
      </div>
    );
  } else {
    content = (
      <div className="operations-page settings-page">
        <section className="settings-summary-grid"><div className="work-card metric-card"><span>실행 장치</span><strong>{accelerator}</strong><small>MuScriptor 기준</small></div><div className="work-card metric-card"><span>Hugging Face</span><strong className={health?.system.hf_authenticated ? "positive" : "attention"}>{health?.system.hf_authenticated ? "인증됨" : "인증 필요"}</strong><small>MuScriptor 모델 접근</small></div><div className="work-card metric-card"><span>작업 데이터</span><strong>{formatBytes(health?.system.jobs_bytes)}</strong><small>{health?.data_dir ?? "로컬 저장소"}</small></div><div className="work-card metric-card"><span>남은 디스크</span><strong>{formatBytes(health?.system.disk_free_bytes)}</strong><small>현재 데이터 드라이브</small></div></section>
        <section className="settings-columns"><div className="work-card settings-card"><div className="section-title-row"><div><span className="card-kicker">환경 진단</span><h2>필수 도구</h2><p>모든 모델과 렌더러는 이 컴퓨터에서 실행됩니다.</p></div></div><div className="tool-readiness-list">{health ? Object.entries(health.preflight.tools).map(([name, ready]) => <div key={name}><span className={`tool-check ${ready ? "ready" : "missing"}`}>{ready ? "✓" : "!"}</span><div><strong>{name.replace("_override_or_path", "")}</strong><small>{ready ? "사용 가능" : "확인 필요"}</small></div></div>) : <div className="settings-skeleton">환경 정보를 확인하고 있습니다…</div>}</div>{!health?.system.hf_authenticated && <div className="settings-callout"><strong>MuScriptor 모델 인증이 필요합니다</strong><p>{setup?.instructions.hf_note}</p>{setup?.instructions.hf_login_command && <code>{setup.instructions.hf_login_command}</code>}</div>}</div><div className="work-card settings-card"><div className="section-title-row"><div><span className="card-kicker">실행 파일</span><h2>도구 경로</h2><p>앱이 도구를 자동으로 찾지 못하는 경우에만 지정하세요.</p></div></div><div className="path-input-list">{[["muscriptor_cmd", "MuScriptor"], ["demucs_cmd", "Demucs"], ["whisperx_cmd", "WhisperX"], ["musescore_cmd", "MuseScore"]].map(([key, label]) => <label key={key}><span>{label}</span><input value={toolPaths[key] ?? ""} placeholder="자동 검색" onChange={(event) => setToolPaths((current) => ({ ...current, [key]: event.target.value }))} /></label>)}</div><button className="primary-button" disabled={busy} onClick={() => void savePaths()}>경로 저장</button></div></section>
        <section className="work-card storage-card"><div><span className="card-kicker">저장공간 관리</span><h3>오래된 작업 데이터 정리</h3><p>곡 라이브러리는 유지하고, 최근 30개를 제외한 오래된 작업 임시파일만 정리합니다.</p></div><button className="secondary-button" onClick={cleanupStorage}>저장공간 정리</button></section>
        {offline && <div className="offline-banner"><strong>로컬 백엔드에 연결할 수 없습니다.</strong><span>AudioScoreTool 백엔드가 실행 중인지 확인하세요.</span></div>}
      </div>
    );
  }

  return (
    <>
      {content}
      {toast && <Toast message={toast.message} kind={toast.kind} onClose={() => setToast(null)} />}
      {confirm && (
        <div className="confirm-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setConfirm(null)}>
          <section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
            <div className={`confirm-icon ${confirm.danger ? "danger" : ""}`}>{confirm.danger ? "!" : "?"}</div>
            <h2 id="confirm-title">{confirm.title}</h2>
            <p>{confirm.body}</p>
            <div className="confirm-actions">
              <button className="secondary-button" onClick={() => setConfirm(null)}>취소</button>
              <button className={confirm.danger ? "danger-button" : "primary-button"} onClick={() => void (async () => {
                try {
                  setBusy(true);
                  await confirm.action();
                  setConfirm(null);
                } catch (error) {
                  showToast(error instanceof Error ? error.message : String(error), "error");
                } finally {
                  setBusy(false);
                }
              })()}>{confirm.confirmLabel}</button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
