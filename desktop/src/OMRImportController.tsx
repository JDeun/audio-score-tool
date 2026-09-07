import { ChangeEvent, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./omr-import.css";

const API = "http://127.0.0.1:8080";

type OMRJob = {
  job_id: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled" | "interrupted";
  stage?: string;
  progress?: number;
  error?: string;
};

export default function OMRImportController() {
  const [host, setHost] = useState<Element | null>(null);
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<OMRJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const findHost = () => setHost(document.querySelector(".new-score-page .segmented-control"));
    findHost();
    const observer = new MutationObserver(findHost);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`${API}/api/jobs/${job.job_id}`);
        if (!response.ok) return;
        const fresh = await response.json();
        setJob(fresh);
        if (fresh.status === "done") {
          setMessage("악보 인식이 완료되었습니다. 곡 라이브러리에서 검증·수정할 수 있습니다.");
        } else if (fresh.status === "failed") {
          setMessage(fresh.error || "악보 인식에 실패했습니다.");
        }
      } catch {
        // Keep the modal state while the local sidecar reconnects.
      }
    }, 900);
    return () => window.clearInterval(timer);
  }, [job?.job_id, job?.status]);

  const reset = () => {
    if (busy || (job && ["queued", "running"].includes(job.status))) return;
    setOpen(false);
    setFile(null);
    setJob(null);
    setMessage("");
  };

  const chooseFile = (event: ChangeEvent<HTMLInputElement>) => {
    const next = event.target.files?.[0] ?? null;
    setFile(next);
    setJob(null);
    setMessage("");
  };

  const startImport = async () => {
    if (!file || busy) return;
    setBusy(true);
    setMessage("");
    try {
      const body = new FormData();
      body.append("file", file);
      const response = await fetch(`${API}/api/import/score`, { method: "POST", body });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(payload?.detail ?? "악보 가져오기를 시작하지 못했습니다.");
      setJob({ job_id: payload.job_id, status: "queued", stage: "queued", progress: 0 });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  const openLibrary = () => {
    window.localStorage.setItem("ast-section", "songs");
    window.location.reload();
  };

  const launcher = host
    ? createPortal(
        <button
          role="tab"
          aria-selected="false"
          className="omr-import-tab"
          onClick={() => {
            setOpen(true);
            setMessage("");
          }}
        >
          PDF / 이미지 악보
        </button>,
        host,
      )
    : null;

  return (
    <>
      {launcher}
      {open && (
        <div className="omr-modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && reset()}>
          <section className="omr-modal" role="dialog" aria-modal="true" aria-labelledby="omr-title">
            <header>
              <div>
                <span className="omr-eyebrow">OPTICAL MUSIC RECOGNITION</span>
                <h2 id="omr-title">기존 악보 가져오기</h2>
                <p>PDF 또는 스캔 이미지를 MusicXML로 인식한 뒤 기존 편집·검증 파이프라인에 넣습니다.</p>
              </div>
              <button className="omr-close" type="button" onClick={reset} aria-label="닫기">×</button>
            </header>

            <input
              ref={inputRef}
              type="file"
              hidden
              accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,application/pdf,image/png,image/jpeg,image/tiff,image/bmp"
              onChange={chooseFile}
            />
            <button
              type="button"
              className={`omr-file-card ${file ? "selected" : ""}`}
              disabled={!!job && ["queued", "running"].includes(job.status)}
              onClick={() => inputRef.current?.click()}
            >
              <span>{file ? "선택한 악보" : "악보 파일 선택"}</span>
              <strong>{file?.name ?? "PDF · PNG · JPG · TIFF · BMP"}</strong>
              <small>스캔 해상도와 대비가 높을수록 인식 품질이 좋아집니다.</small>
            </button>

            <div className="omr-flow">
              <span>원본 악보</span><i>→</i><span>Audiveris OMR</span><i>→</i><span>MusicXML</span><i>→</i><span>검증·편집</span>
            </div>

            {job && (
              <div className="omr-progress-card">
                <div><strong>{job.status === "done" ? "인식 완료" : "악보 인식 중"}</strong><span>{job.progress ?? 0}%</span></div>
                <div className="omr-progress"><span style={{ width: `${job.progress ?? 0}%` }} /></div>
              </div>
            )}
            {message && <div className={`omr-message ${job?.status === "failed" ? "error" : ""}`}>{message}</div>}

            <footer>
              <button type="button" className="secondary-button" onClick={reset}>닫기</button>
              {job?.status === "done" ? (
                <button type="button" className="primary-button" onClick={openLibrary}>곡 라이브러리에서 검토</button>
              ) : (
                <button
                  type="button"
                  className="primary-button"
                  disabled={!file || busy || !!job && ["queued", "running"].includes(job.status)}
                  onClick={() => void startImport()}
                >
                  {job && ["queued", "running"].includes(job.status) ? "인식 중…" : "악보 가져오기"}
                </button>
              )}
            </footer>
          </section>
        </div>
      )}
    </>
  );
}
