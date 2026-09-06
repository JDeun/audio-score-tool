import { useEffect, useMemo, useState } from "react";
import "./youtube.css";

const API = "http://127.0.0.1:8080";

type Metadata = {
  title: string;
  uploader?: string | null;
  duration?: number | null;
  webpage_url: string;
};

type ToolStatus = {
  ready: boolean;
  command: string;
  fallback_note: string;
};

type Job = {
  job_id: string;
  status: "queued" | "running" | "cancelling" | "cancelled" | "interrupted" | "done" | "failed";
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
  queued: "처리 대기 중",
  starting: "YouTube 오디오 가져오는 중",
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

function formatDuration(seconds?: number | null) {
  if (seconds == null || !Number.isFinite(seconds)) return "길이 정보 없음";
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`
    : `${minutes}:${String(secs).padStart(2, "0")}`;
}

export default function YoutubeImport() {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [metadata, setMetadata] = useState<Metadata | null>(null);
  const [tool, setTool] = useState<ToolStatus | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const [authorized, setAuthorized] = useState(false);
  const [language, setLanguage] = useState("ko");
  const [lyrics, setLyrics] = useState(true);
  const [preset, setPreset] = useState("auto");
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");

  const active = !!job && ["queued", "running", "cancelling"].includes(job.status);
  const canSubmit = !!metadata && authorized && !active && tool?.ready !== false;

  useEffect(() => {
    if (!open) return;
    fetch(`${API}/api/sources/youtube/status`)
      .then((response) => response.ok ? response.json() : null)
      .then((body) => body && setTool(body))
      .catch(() => setTool(null));
  }, [open]);

  useEffect(() => {
    if (!job || !["queued", "running", "cancelling"].includes(job.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`${API}/api/jobs/${job.job_id}`);
        if (response.ok) setJob(await response.json());
      } catch {
        // Keep the latest job state while the local sidecar reconnects.
      }
    }, 800);
    return () => window.clearInterval(timer);
  }, [job?.job_id, job?.status]);

  const progressLabel = useMemo(() => {
    if (!job) return "";
    return stageLabel[job.stage ?? job.status] ?? job.stage ?? job.status;
  }, [job]);

  const inspect = async () => {
    setError("");
    setMetadata(null);
    setInspecting(true);
    try {
      const response = await fetch(`${API}/api/sources/youtube/inspect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? "YouTube 링크를 확인할 수 없습니다.");
      }
      setMetadata(await response.json());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setInspecting(false);
    }
  };

  const start = async () => {
    if (!canSubmit) return;
    setError("");
    try {
      const response = await fetch(`${API}/api/jobs/youtube`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url,
          authorized,
          language,
          skip_lyrics: !lyrics,
          preset,
        }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? "YouTube 작업을 시작할 수 없습니다.");
      }
      const created = await response.json();
      setJob({ job_id: created.job_id, status: "queued", stage: "queued", progress: 0, filename: metadata?.title });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  };

  const cancel = async () => {
    if (!job) return;
    await fetch(`${API}/api/jobs/${job.job_id}/cancel`, { method: "POST" });
  };

  const reset = () => {
    if (active) return;
    setUrl("");
    setMetadata(null);
    setAuthorized(false);
    setJob(null);
    setError("");
  };

  const artifact = (kind: string) => job ? `${API}/api/jobs/${job.job_id}/files/${kind}` : "#";

  return (
    <>
      <button className="youtube-fab" onClick={() => setOpen(true)} aria-label="Import from YouTube">
        <span className="youtube-fab-icon">▶</span>
        <span>
          <small>QUICK SOURCE</small>
          <strong>YouTube Import</strong>
        </span>
      </button>

      {open && (
        <div className="youtube-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setOpen(false)}>
          <section className="youtube-modal" role="dialog" aria-modal="true" aria-label="YouTube import">
            <header className="youtube-head">
              <div>
                <span className="youtube-eyebrow">URL → AUDIO → SCORE</span>
                <h2>YouTube에서 바로 채보</h2>
                <p>영상 전체가 아니라 최적의 오디오 스트림만 가져와 기존 로컬 채보 파이프라인으로 연결합니다.</p>
              </div>
              <button className="youtube-close" onClick={() => setOpen(false)} aria-label="Close">×</button>
            </header>

            <div className="youtube-url-row">
              <input
                type="url"
                value={url}
                placeholder="https://www.youtube.com/watch?v=…"
                onChange={(event) => {
                  setUrl(event.target.value);
                  setMetadata(null);
                  setError("");
                }}
                onKeyDown={(event) => event.key === "Enter" && url.trim() && void inspect()}
                disabled={active}
              />
              <button onClick={inspect} disabled={!url.trim() || inspecting || active}>
                {inspecting ? "확인 중…" : "링크 확인"}
              </button>
            </div>

            {tool && !tool.ready && (
              <div className="youtube-alert bad">
                <strong>yt-dlp를 실행할 수 없습니다.</strong>
                <span>uv/uvx를 설치하거나 yt-dlp를 PATH에 추가해야 YouTube 입력을 사용할 수 있습니다.</span>
              </div>
            )}

            {metadata && (
              <div className="youtube-preview">
                <div className="youtube-preview-icon">♪</div>
                <div>
                  <span className="youtube-eyebrow">SOURCE READY</span>
                  <strong>{metadata.title}</strong>
                  <p>{metadata.uploader ?? "YouTube"} · {formatDuration(metadata.duration)}</p>
                </div>
              </div>
            )}

            <div className="youtube-options">
              <label>
                <span>품질</span>
                <select value={preset} onChange={(event) => setPreset(event.target.value)} disabled={active}>
                  <option value="auto">Auto</option>
                  <option value="fast">Fast</option>
                  <option value="balanced">Balanced</option>
                  <option value="quality">Quality</option>
                </select>
              </label>
              <label>
                <span>가사 언어</span>
                <select value={language} onChange={(event) => setLanguage(event.target.value)} disabled={!lyrics || active}>
                  <option value="ko">한국어</option>
                  <option value="en">English</option>
                  <option value="">자동 감지</option>
                </select>
              </label>
              <label className="youtube-check option-check">
                <input type="checkbox" checked={lyrics} onChange={(event) => setLyrics(event.target.checked)} disabled={active} />
                <span>가사 인식·정렬 포함</span>
              </label>
            </div>

            <label className="youtube-check authorization">
              <input type="checkbox" checked={authorized} onChange={(event) => setAuthorized(event.target.checked)} disabled={active} />
              <span>이 콘텐츠를 다운로드·처리할 권한이 있거나 YouTube/권리자가 허용한 콘텐츠임을 확인합니다.</span>
            </label>

            {error && <div className="youtube-alert bad">{error}</div>}

            {job && (
              <div className={`youtube-job ${job.status}`}>
                <div className="youtube-job-head">
                  <div>
                    <span className="youtube-eyebrow">CURRENT JOB</span>
                    <strong>{job.filename ?? metadata?.title ?? "YouTube import"}</strong>
                    <p>{progressLabel}</p>
                  </div>
                  <b>{job.progress ?? 0}%</b>
                </div>
                <div className="youtube-progress"><span style={{ width: `${job.progress ?? 0}%` }} /></div>
                {job.error && <pre>{job.error}</pre>}
                {job.result?.warnings?.map((warning) => <p className="youtube-warning" key={warning}>{warning}</p>)}
                {job.status === "done" && (
                  <div className="youtube-artifacts">
                    <a href={artifact("pdf")} target="_blank">PDF</a>
                    <a href={artifact("musicxml")} target="_blank">MusicXML</a>
                    <a href={artifact("midi")} target="_blank">MIDI</a>
                    {job.result?.transcript_json && <a href={artifact("transcript")} target="_blank">Lyrics JSON</a>}
                  </div>
                )}
              </div>
            )}

            <footer className="youtube-footer">
              <button className="youtube-secondary" onClick={reset} disabled={active}>새 링크</button>
              <div>
                {active && job?.status !== "cancelling" && <button className="youtube-cancel" onClick={cancel}>취소</button>}
                <button className="youtube-primary" onClick={start} disabled={!canSubmit}>
                  {active ? "처리 중…" : "이 음원으로 채보 시작"}
                </button>
              </div>
            </footer>
          </section>
        </div>
      )}
    </>
  );
}
