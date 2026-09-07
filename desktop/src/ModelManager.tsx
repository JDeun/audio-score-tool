import { useEffect, useMemo, useState } from "react";
import { openUrl } from "@tauri-apps/plugin-opener";
import "./model-manager.css";

const API = "http://127.0.0.1:8080";

type ManagedModel = {
  family: "muscriptor";
  variant: "small" | "medium" | "large";
  label: string;
  repo_id: string;
  parameters: string;
  weight_bytes: number;
  cached_bytes: number;
  ready: boolean;
  selected: boolean;
  allowed_for_usage_mode: boolean;
  license: string;
  commercial_allowed: boolean;
  description: string;
  requires_hf_auth: boolean;
};

type ModelsStatus = {
  usage_mode: "personal" | "commercial";
  selected_engine: string;
  selected_muscriptor_model: string;
  hf_authenticated: boolean;
  hf_home: string;
  hf_cli_ready: boolean;
  disk_free_bytes: number;
  models: ManagedModel[];
  policy: {
    automatic_download: boolean;
    explicit_user_action_required: boolean;
    commercial_mode_blocks_muscriptor: boolean;
    model_license_acceptance_required: boolean;
    auth_token_stored_by_app: boolean;
  };
};

type DownloadJob = {
  job_id: string;
  family: string;
  variant: string;
  status: "queued" | "running" | "done" | "failed";
  progress: number;
  cached_bytes: number;
  target_bytes: number;
  error?: string | null;
};

type AuthJob = {
  auth_id: string;
  status: "queued" | "running" | "waiting_for_user" | "done" | "failed";
  authenticated: boolean;
  verification_url?: string | null;
  user_code?: string | null;
  message?: string | null;
  error?: string | null;
};

function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes)) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index >= 3 ? 1 : 0)} ${units[index]}`;
}

export default function ModelManager() {
  const [status, setStatus] = useState<ModelsStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [job, setJob] = useState<DownloadJob | null>(null);
  const [authJob, setAuthJob] = useState<AuthJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const refresh = async () => {
    try {
      const response = await fetch(`${API}/api/models`);
      if (!response.ok) return;
      setStatus(await response.json());
    } catch {
      // Setup Center communicates backend connection errors.
    }
  };

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(refresh, 12000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`${API}/api/models/jobs/${job.job_id}`);
        if (!response.ok) return;
        const fresh: DownloadJob = await response.json();
        setJob(fresh);
        if (fresh.status === "done") {
          setMessage(`${fresh.variant.toUpperCase()} 모델 준비가 완료되었습니다.`);
          await refresh();
        }
        if (fresh.status === "failed") setMessage(fresh.error || "모델 다운로드에 실패했습니다.");
      } catch {
        // Keep visible state while the local sidecar reconnects.
      }
    }, 900);
    return () => window.clearInterval(timer);
  }, [job?.job_id, job?.status]);

  useEffect(() => {
    if (!authJob || ["done", "failed"].includes(authJob.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`${API}/api/models/hf-auth/${authJob.auth_id}`);
        if (!response.ok) return;
        const fresh: AuthJob = await response.json();
        setAuthJob(fresh);
        if (fresh.status === "done") {
          setMessage("Hugging Face 로그인이 완료되었습니다.");
          await refresh();
        }
        if (fresh.status === "failed") setMessage(fresh.error || "Hugging Face 로그인에 실패했습니다.");
      } catch {
        // Preserve the browser-auth code while reconnecting.
      }
    }, 850);
    return () => window.clearInterval(timer);
  }, [authJob?.auth_id, authJob?.status]);

  const selected = useMemo(() => status?.models.find((model) => model.selected), [status]);

  const startAuth = async () => {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${API}/api/models/hf-auth/start`, { method: "POST" });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail ?? "Hugging Face 로그인을 시작하지 못했습니다.");
      if (body.already_authenticated) {
        setMessage("이미 Hugging Face에 로그인되어 있습니다.");
        await refresh();
      } else {
        setAuthJob({ auth_id: body.auth_id, status: "queued", authenticated: false });
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  const openAuthPage = async () => {
    const url = authJob?.verification_url ?? "https://huggingface.co/oauth/device";
    await openUrl(url);
  };

  const prepare = async (model: ManagedModel) => {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${API}/api/models/download`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ family: model.family, variant: model.variant }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail ?? "모델 다운로드를 시작하지 못했습니다.");
      if (body.already_ready) {
        setMessage("이미 다운로드된 모델입니다.");
        await refresh();
      } else {
        setJob({
          job_id: body.job_id,
          family: model.family,
          variant: model.variant,
          status: body.status ?? "queued",
          progress: 0,
          cached_bytes: model.cached_bytes,
          target_bytes: model.weight_bytes,
        });
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  const useModel = async (model: ManagedModel) => {
    setBusy(true);
    setMessage("");
    try {
      const currentResponse = await fetch(`${API}/api/engines`);
      if (!currentResponse.ok) throw new Error("현재 엔진 설정을 읽을 수 없습니다.");
      const current = await currentResponse.json();
      const response = await fetch(`${API}/api/engines`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          usage_mode: current.usage_mode,
          transcription_engine: "muscriptor",
          mt3_infer_cmd: current.mt3_infer_cmd,
          mt3_model: current.mt3_model,
          muscriptor_cmd: current.muscriptor_cmd,
          muscriptor_model: model.variant,
          native_engine_cmd: current.native_engine_cmd,
          native_checkpoint: current.native_checkpoint,
        }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail ?? "모델을 선택하지 못했습니다.");
      setMessage(`${model.label}를 기본 채보 모델로 선택했습니다.`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (model: ManagedModel) => {
    if (!window.confirm(`${model.label} 모델의 로컬 캐시를 삭제할까요? 다시 사용할 때 재다운로드가 필요합니다.`)) return;
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${API}/api/models/remove`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ family: model.family, variant: model.variant }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail ?? "모델을 삭제하지 못했습니다.");
      setStatus(body.status);
      setMessage(`${model.label} 로컬 캐시를 삭제했습니다.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  if (!status) return null;

  return (
    <>
      <button className="model-manager-trigger" type="button" onClick={() => setOpen(true)}><span>AI</span>모델</button>

      {open && (
        <div className="model-manager-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setOpen(false)}>
          <section className="model-manager-modal" role="dialog" aria-modal="true" aria-label="AI 모델 관리자">
            <header>
              <div><span className="model-eyebrow">MODEL LIBRARY</span><h2>AI 모델 관리자</h2><p>필요한 모델만 명시적으로 다운로드합니다. 기본 선택은 품질 우선 Large입니다.</p></div>
              <button className="model-close" type="button" onClick={() => setOpen(false)} aria-label="닫기">×</button>
            </header>

            <div className="model-manager-summary">
              <div><span>현재 모델</span><strong>{selected ? `MuScriptor ${selected.label}` : status.selected_engine}</strong></div>
              <div><span>Hugging Face</span><strong className={status.hf_authenticated ? "positive" : "attention"}>{status.hf_authenticated ? "인증됨" : "인증 필요"}</strong></div>
              <div><span>남은 디스크</span><strong>{formatBytes(status.disk_free_bytes)}</strong></div>
            </div>

            {status.usage_mode === "commercial" && (
              <div className="model-license-warning"><strong>상용 모드에서는 MuScriptor를 사용할 수 없습니다.</strong><span>공개 weights가 CC BY-NC 4.0이므로 다운로드와 선택을 차단합니다.</span></div>
            )}

            {!status.hf_authenticated && status.usage_mode === "personal" && (
              <div className="model-auth-callout model-auth-flow">
                <div>
                  <strong>Hugging Face 로그인과 모델 라이선스 수락이 필요합니다.</strong>
                  <span>토큰은 AudioScoreTool이 저장하지 않습니다. Hugging Face 공식 CLI의 브라우저 인증을 사용합니다.</span>
                  {authJob?.user_code && <code>{authJob.user_code}</code>}
                </div>
                <div className="model-auth-actions">
                  <button type="button" onClick={() => void openUrl("https://huggingface.co/MuScriptor/muscriptor-large")}>1. 라이선스 수락</button>
                  {!authJob || authJob.status === "failed" ? (
                    <button type="button" disabled={busy || !status.hf_cli_ready} onClick={() => void startAuth()}>2. 로그인 시작</button>
                  ) : authJob.status === "done" ? (
                    <span>로그인 완료</span>
                  ) : (
                    <button type="button" onClick={() => void openAuthPage()}>{authJob.user_code ? "브라우저에서 코드 입력" : "인증 페이지 열기"}</button>
                  )}
                </div>
              </div>
            )}

            {job && ["queued", "running"].includes(job.status) && (
              <div className="model-download-banner">
                <div><strong>MuScriptor {job.variant} 다운로드 중</strong><span>{formatBytes(job.cached_bytes)} / 약 {formatBytes(job.target_bytes)}</span></div>
                <div className="model-progress"><span style={{ width: `${job.progress}%` }} /></div><b>{job.progress}%</b>
              </div>
            )}

            <div className="model-card-grid">
              {status.models.map((model) => (
                <article key={model.variant} className={`model-card ${model.selected ? "selected" : ""} ${model.ready ? "installed" : ""}`}>
                  <div className="model-card-top"><div><span className="model-size-label">{model.parameters}</span><h3>MuScriptor {model.label}</h3></div>{model.selected ? <span className="model-state selected">사용 중</span> : model.ready ? <span className="model-state ready">설치됨</span> : <span className="model-state">미설치</span>}</div>
                  <p>{model.description}</p>
                  <dl><div><dt>Weights</dt><dd>약 {formatBytes(model.weight_bytes)}</dd></div><div><dt>License</dt><dd>{model.license}</dd></div><div><dt>Cache</dt><dd>{model.ready ? formatBytes(model.cached_bytes) : "—"}</dd></div></dl>
                  <div className="model-card-actions">
                    {!model.ready && <button className="model-primary" type="button" disabled={busy || !model.allowed_for_usage_mode || !status.hf_authenticated || !status.hf_cli_ready} onClick={() => void prepare(model)}>모델 준비</button>}
                    {model.ready && !model.selected && <button className="model-primary" type="button" disabled={busy || !model.allowed_for_usage_mode} onClick={() => void useModel(model)}>이 모델 사용</button>}
                    {model.ready && !model.selected && <button className="model-secondary" type="button" disabled={busy} onClick={() => void remove(model)}>캐시 삭제</button>}
                  </div>
                </article>
              ))}
            </div>

            <div className="model-manager-footnote"><span>모델 캐시: {status.hf_home}</span><span>자동 다운로드 OFF · 사용자 동의 후에만 다운로드</span></div>
            {message && <div className="model-manager-message">{message}</div>}
          </section>
        </div>
      )}
    </>
  );
}
