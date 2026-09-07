import { useEffect, useMemo, useState } from "react";
import "./validation-controller.css";

const API = "http://127.0.0.1:8080";

type ValidationTarget = { songId: string; title: string };
type Issue = {
  severity: "error" | "warning" | "info";
  category: string;
  message: string;
  part?: string | null;
  measure?: string | null;
  confidence?: number;
  suggested_action?: string | null;
  source?: string;
};
type ValidationReport = {
  song_id: string;
  revision: number;
  ok: boolean;
  issues: Issue[];
  llm?: { summary: string; model: string; advisory: boolean } | null;
  policy: { llm_is_advisory: boolean; auto_edit: boolean };
};
type ValidationSettings = {
  enabled: boolean;
  base_url: string;
  model: string;
  api_key_env?: string | null;
};

function currentTarget(): ValidationTarget | null {
  const workbench = document.querySelector(".score-workbench");
  const scoreLink = workbench?.querySelector<HTMLAnchorElement>('a[href*="/api/songs/"][href*="/files/"]');
  if (!scoreLink) return null;
  const pathname = new URL(scoreLink.href, window.location.href).pathname;
  const match = pathname.match(/\/api\/songs\/([^/]+)\/files\//);
  if (!match) return null;
  const title = workbench?.querySelector(".score-toolbar h2")?.textContent?.trim() || "악보";
  return { songId: decodeURIComponent(match[1]), title };
}

export default function ValidationController() {
  const [target, setTarget] = useState<ValidationTarget | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [message, setMessage] = useState("");
  const [settings, setSettings] = useState<ValidationSettings>({
    enabled: false,
    base_url: "http://127.0.0.1:11434/v1",
    model: "qwen3.5:9b",
    api_key_env: "",
  });
  const [useLlm, setUseLlm] = useState(false);

  useEffect(() => {
    const refreshTarget = () => setTarget(currentTarget());
    refreshTarget();
    const observer = new MutationObserver(refreshTarget);
    observer.observe(document.body, { subtree: true, childList: true });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!open) return;
    void fetch(`${API}/api/validation/settings`)
      .then((response) => response.ok ? response.json() : null)
      .then((body) => {
        if (!body) return;
        setSettings(body);
        setUseLlm(Boolean(body.enabled));
      })
      .catch(() => undefined);
  }, [open]);

  const counts = useMemo(() => {
    const result = { error: 0, warning: 0, info: 0 };
    report?.issues.forEach((issue) => { result[issue.severity] += 1; });
    return result;
  }, [report]);

  const saveSettings = async () => {
    const response = await fetch(`${API}/api/validation/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...settings, enabled: useLlm }),
    });
    if (!response.ok) throw new Error(await response.text());
  };

  const validate = async () => {
    if (!target || busy) return;
    setBusy(true);
    setMessage("");
    setReport(null);
    try {
      await saveSettings();
      const response = await fetch(`${API}/api/songs/${target.songId}/validate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ use_llm: useLlm }),
      });
      if (!response.ok) throw new Error(await response.text());
      const body: ValidationReport = await response.json();
      setReport(body);
    } catch (error) {
      setMessage(`검증 실패: ${String(error)}`);
    } finally {
      setBusy(false);
    }
  };

  if (!target) return null;

  return (
    <>
      <button className="validation-dock-trigger" type="button" onClick={() => setOpen(true)}>
        악보 검증
      </button>
      {open && (
        <div className="validation-backdrop" role="presentation">
          <section className="validation-modal" role="dialog" aria-modal="true" aria-label="악보 검증">
            <header>
              <div><span>TRANSCRIPTION QA</span><h2>악보 검증</h2><p>‘{target.title}’의 현재 Revision을 검사합니다.</p></div>
              <button type="button" onClick={() => setOpen(false)} aria-label="닫기">×</button>
            </header>

            <div className="validation-policy">
              <strong>검증 정책</strong>
              <p>규칙 기반 검사는 항상 실행합니다. LLM은 음악적 이상치와 검토 후보를 찾는 critic이며 자동 수정이나 원음 일치 판정을 하지 않습니다.</p>
            </div>

            <label className="validation-toggle">
              <input type="checkbox" checked={useLlm} onChange={(event) => setUseLlm(event.target.checked)} />
              <span>LLM critic 함께 사용</span>
            </label>

            {useLlm && (
              <div className="validation-settings-grid">
                <label><span>OpenAI-compatible endpoint</span><input value={settings.base_url} onChange={(event) => setSettings((current) => ({ ...current, base_url: event.target.value }))} /></label>
                <label><span>모델</span><input value={settings.model} onChange={(event) => setSettings((current) => ({ ...current, model: event.target.value }))} /></label>
                <label><span>API key 환경변수명</span><input value={settings.api_key_env ?? ""} placeholder="예: OPENAI_API_KEY" onChange={(event) => setSettings((current) => ({ ...current, api_key_env: event.target.value }))} /></label>
              </div>
            )}

            <button className="validation-run" type="button" disabled={busy} onClick={() => void validate()}>
              {busy ? "검증 중…" : "현재 악보 검증"}
            </button>

            {message && <div className="validation-message">{message}</div>}
            {report && (
              <div className="validation-results">
                <div className="validation-summary">
                  <strong>{report.ok ? "구조적 치명 오류 없음" : "수정이 필요한 오류 감지"}</strong>
                  <span>오류 {counts.error} · 경고 {counts.warning} · 정보 {counts.info}</span>
                  {report.llm && <small>LLM critic: {report.llm.model} · {report.llm.summary}</small>}
                </div>
                <div className="validation-issues">
                  {report.issues.length === 0 && <p>현재 규칙에서 발견된 이상 항목이 없습니다.</p>}
                  {report.issues.map((issue, index) => (
                    <article key={`${issue.source}-${index}`} className={`validation-issue ${issue.severity}`}>
                      <div><strong>{issue.category}</strong><span>{issue.source === "llm" ? "LLM 가설" : "규칙 검사"}</span></div>
                      <p>{issue.message}</p>
                      {(issue.part || issue.measure) && <small>{issue.part || ""}{issue.measure ? ` · M${issue.measure}` : ""}</small>}
                      {issue.suggested_action && <em>{issue.suggested_action}</em>}
                    </article>
                  ))}
                </div>
              </div>
            )}
          </section>
        </div>
      )}
    </>
  );
}
