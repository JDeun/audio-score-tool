import { ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./omr-import.css";

const API = "http://127.0.0.1:8080";
const DIRECT_EXTENSIONS = new Set(["musicxml", "xml", "mxl", "mid", "midi"]);

type ImportJob = {
  job_id: string;
  status: "queued" | "running" | "cancelling" | "done" | "failed" | "cancelled" | "interrupted";
  stage?: string;
  progress?: number;
  error?: string;
};

function extensionOf(file: File | null) {
  if (!file) return "";
  return file.name.split(".").pop()?.toLowerCase() ?? "";
}

export default function OMRImportController() {
  const [host, setHost] = useState<Element | null>(null);
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<ImportJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const directImport = useMemo(() => DIRECT_EXTENSIONS.has(extensionOf(file)), [file]);
  const activeJob = !!job && ["queued", "running", "cancelling"].includes(job.status);

  useEffect(() => {
    const findHost = () => setHost(document.querySelector(".new-score-page .segmented-control"));
    findHost();
    const observer = new MutationObserver(findHost);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!job || !["queued", "running", "cancelling"].includes(job.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`${API}/api/jobs/${job.job_id}`);
        if (!response.ok) return;
        const fresh = await response.json();
        setJob(fresh);
        if (fresh.status === "done") {
          setMessage(
            directImport
              ? "악보 파일을 가져왔습니다. 곡 라이브러리에서 검증·수정할 수 있습니다."
              : "악보 인식이 완료되었습니다. 곡 라이브러리에서 검증·수정할 수 있습니다.",
          );
        } else if (fresh.status === "failed") {
          setMessage(fresh.error || "악보 가져오기에 실패했습니다.");
        } else if (fresh.status === "cancelled") {
          setMessage("악보 가져오기가 취소되었습니다. 원본 파일을 다시 선택하거나 재시도할 수 있습니다.");
        } else if (fresh.status === "interrupted") {
          setMessage("중단된 가져오기입니다. 원본 파일로 재시도할 수 있습니다.");
        }
      } catch {
        // Keep the modal state while the local sidecar reconnects.
      }
    }, 900);
    return () => window.clearInterval(timer);
  }, [job?.job_id, job?.status, directImport]);

  const reset = () => {
    if (busy || activeJob) return;
    setOpen(false);
    setFile(null);
    setJob(null);
    setMessage("");
  };

  const chooseFile = (event: ChangeEvent<HTMLInputElement>) => {
    const next = event.target.files?.[0] ?? null;
    if (activeJob) return;
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
      const endpoint = directImport ? "/api/import/notation" : "/api/import/score";
      const response = await fetch(`${API}${endpoint}`, { method: "POST", body });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(payload?.detail ?? "악보 가져오기를 시작하지 못했습니다.");
      setJob({ job_id: payload.job_id, status: "queued", stage: "queued", progress: 0 });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  const cancelImport = async () => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    try {
      const response = await fetch(`${API}/api/jobs/${job.job_id}/cancel`, { method: "POST" });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(payload?.detail ?? "가져오기 취소 요청에 실패했습니다.");
      const updatedStatus = String(payload?.status ?? "cancelling") as ImportJob["status"];
      setJob((current) => current?.job_id === job.job_id ? { ...current, status: updatedStatus } : current);
      setMessage(updatedStatus === "cancelling" ? "가져오기 취소 중…" : "작업 상태가 변경됐습니다.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "가져오기 취소에 실패했습니다.");
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
          기존 악보 / MusicXML / MIDI
        </button>,
        host,
      )
    : null;

  const flow = directImport
    ? ["기존 파일", "→", extensionOf(file).startsWith("mid") ? "music21" : "구조 검증", "→", "MusicXML", "→", "검증·편집"]
    : ["원본 악보", "→", "Audiveris OMR", "→", "MusicXML", "→", "검증·편집"];

  return (
    <>
      {launcher}
      {open && (
        <div className="omr-modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && reset()}>
          <section className="omr-modal" role="dialog" aria-modal="true" aria-labelledby="omr-title">
            <header>
              <div>
                <span className="omr-eyebrow">SCORE IMPORT</span>
                <h2 id="omr-title">기존 악보 가져오기</h2>
                <p>PDF/스캔 이미지는 OMR로 인식하고, MusicXML/MXL/MIDI는 직접 가져와 동일한 편집·검증 파이프라인에 넣습니다.</p>
              </div>
              <button className="omr-close" type="button" onClick={reset} aria-label="닫기">×</button>
            </header>

            <input
              ref={inputRef}
              type="file"
              hidden
              accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.musicxml,.xml,.mxl,.mid,.midi,application/pdf,image/png,image/jpeg,image/tiff,image/bmp,application/vnd.recordare.musicxml+xml,application/vnd.recordare.musicxml,audio/midi"
              onChange={chooseFile}
            />
            <button
              type="button"
              className={`omr-file-card ${file ? "selected" : ""}`}
              disabled={activeJob}
              onClick={() => inputRef.current?.click()}
            >
              <span>{file ? "선택한 악보" : "악보 파일 선택"}</span>
              <strong>{file?.name ?? "PDF · 이미지 · MusicXML/MXL · MIDI"}</strong>
              <small>
                {directImport
                  ? "MusicXML/MXL은 구조를 검증하고, MIDI는 music21로 MusicXML로 변환합니다."
                  : "PDF/이미지는 스캔 해상도와 대비가 높을수록 OMR 품질이 좋아집니다."}
              </small>
            </button>

            <div className="omr-flow">
              {flow.map((item, index) => item === "→" ? <i key={`${item}-${index}`}>→</i> : <span key={`${item}-${index}`}>{item}</span>)}
            </div>

            {job && (
              <div className="omr-progress-card">
                <div><strong>{
                  job.status === "done" ? "가져오기 완료"
                    : job.status === "cancelling" ? "가져오기 취소 중"
                    : job.status === "cancelled" ? "가져오기 취소됨"
                    : job.status === "failed" ? "가져오기 실패"
                    : directImport ? "악보 가져오는 중" : "악보 인식 중"
                }</strong><span>{job.progress ?? 0}%</span></div>
                <div className="omr-progress"><span style={{ width: `${job.progress ?? 0}%` }} /></div>
              </div>
            )}
            {message && <div className={`omr-message ${job?.status === "failed" ? "error" : ""}`} role="status">{message}</div>}

            <footer>
              <button type="button" className="secondary-button" onClick={reset} disabled={activeJob}>닫기</button>
              {job && ["queued", "running"].includes(job.status) && (
                <button type="button" className="secondary-button" onClick={() => void cancelImport()}>
                  가져오기 취소
                </button>
              )}
              {job?.status === "done" ? (
                <button type="button" className="primary-button" onClick={openLibrary}>곡 라이브러리에서 검토</button>
              ) : (
                <button
                  type="button"
                  className="primary-button"
                  disabled={!file || busy || activeJob}
                  onClick={() => void startImport()}
                >
                  {activeJob ? (job?.status === "cancelling" ? "취소 중…" : "가져오는 중…") : job?.status === "cancelled" ? "다시 가져오기" : "악보 가져오기"}
                </button>
              )}
            </footer>
          </section>
        </div>
      )}
    </>
  );
}
