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
  page?: number | null;
  start_seconds?: number | null;
  end_seconds?: number | null;
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
  visual?: { summary: string; model: string; pages_compared: number; advisory: boolean } | null;
  visual_skipped?: string | null;
  audio?: { overall_similarity: number; alignment_shift_seconds: number; provider: string } | null;
  audio_skipped?: string | null;
  policy: { llm_is_advisory: boolean; visual_is_advisory?: boolean; auto_edit: boolean };
};
type ValidationSettings = {
  enabled: boolean;
  base_url: string;
  model: string;
  api_key_env?: string | null;
  visual_enabled: boolean;
  visual_model: string;
  visual_max_pages: number;
  audio_enabled: boolean;
  audio_threshold: number;
  validation_soundfont?: string | null;
  ffmpeg_cmd?: string | null;
  fluidsynth_cmd?: string | null;
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
    visual_enabled: false,
    visual_model: "qwen2.5vl:7b",
    visual_max_pages: 4,
    audio_enabled: false,
    audio_threshold: 0.42,
    validation_soundfont: "",
    ffmpeg_cmd: "ffmpeg",
    fluidsynth_cmd: "fluidsynth",
  });
  const [useLlm, setUseLlm] = useState(false);
  const [useVisual, setUseVisual] = useState(false);
  const [useAudio, setUseAudio] = useState(false);

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
        setUseVisual(Boolean(body.visual_enabled));
        setUseAudio(Boolean(body.audio_enabled));
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
      body: JSON.stringify({ ...settings, enabled: useLlm, visual_enabled: useVisual, audio_enabled: useAudio }),
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
        body: JSON.stringify({ use_llm: useLlm, use_visual: useVisual, use_audio: useAudio }),
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
      <button className="validation-dock-trigger" type="button" onClick={() => setOpen(true)}>악보 검증</button>
      {open && (
        <div className="validation-backdrop" role="presentation">
          <section className="validation-modal" role="dialog" aria-modal="true" aria-label="악보 검증">
            <header>
              <div><span>TRANSCRIPTION QA</span><h2>악보 검증</h2><p>‘{target.title}’의 현재 Revision을 검사합니다.</p></div>
              <button type="button" onClick={() => setOpen(false)} aria-label="닫기">×</button>
            </header>

            <div className="validation-policy">
              <strong>검증 정책</strong>
              <p>규칙 검사는 항상 실행합니다. LLM/Vision은 검토 후보를 설명하고, Audio evidence는 원음과 현재 악보 재합성의 chroma/onset 차이를 실제 근거로 찾습니다. 어느 단계도 자동 수정하지 않습니다.</p>
            </div>

            <label className="validation-toggle"><input type="checkbox" checked={useLlm} onChange={(event) => setUseLlm(event.target.checked)} /><span>LLM critic 함께 사용</span></label>
            <label className="validation-toggle"><input type="checkbox" checked={useVisual} onChange={(event) => setUseVisual(event.target.checked)} /><span>OMR 원본 ↔ 재렌더링 시각 비교</span></label>
            <label className="validation-toggle"><input type="checkbox" checked={useAudio} onChange={(event) => setUseAudio(event.target.checked)} /><span>원음 ↔ 현재 악보 재합성 Audio evidence</span></label>

            {(useLlm || useVisual) && (
              <div className="validation-settings-grid">
                <label><span>OpenAI-compatible endpoint</span><input value={settings.base_url} onChange={(event) => setSettings((current) => ({ ...current, base_url: event.target.value }))} /></label>
                {useLlm && <label><span>텍스트 critic 모델</span><input value={settings.model} onChange={(event) => setSettings((current) => ({ ...current, model: event.target.value }))} /></label>}
                {useVisual && <label><span>Vision 모델</span><input value={settings.visual_model} placeholder="예: qwen2.5vl:7b" onChange={(event) => setSettings((current) => ({ ...current, visual_model: event.target.value }))} /></label>}
                {useVisual && <label><span>비교 페이지 수</span><input type="number" min={1} max={8} value={settings.visual_max_pages} onChange={(event) => setSettings((current) => ({ ...current, visual_max_pages: Number(event.target.value) || 1 }))} /></label>}
                <label><span>API key 환경변수명</span><input value={settings.api_key_env ?? ""} placeholder="예: OPENAI_API_KEY" onChange={(event) => setSettings((current) => ({ ...current, api_key_env: event.target.value }))} /></label>
              </div>
            )}

            {useAudio && (
              <div className="validation-settings-grid">
                <label><span>ffmpeg 실행 경로</span><input value={settings.ffmpeg_cmd ?? ""} placeholder="ffmpeg" onChange={(event) => setSettings((current) => ({ ...current, ffmpeg_cmd: event.target.value }))} /></label>
                <label><span>FluidSynth 실행 경로</span><input value={settings.fluidsynth_cmd ?? ""} placeholder="fluidsynth" onChange={(event) => setSettings((current) => ({ ...current, fluidsynth_cmd: event.target.value }))} /></label>
                <label><span>검증용 SoundFont 경로</span><input value={settings.validation_soundfont ?? ""} placeholder="/path/to/general-midi.sf2" onChange={(event) => setSettings((current) => ({ ...current, validation_soundfont: event.target.value }))} /></label>
                <label><span>불일치 임계값</span><input type="number" min={0.1} max={0.9} step={0.01} value={settings.audio_threshold} onChange={(event) => setSettings((current) => ({ ...current, audio_threshold: Number(event.target.value) || 0.42 }))} /></label>
                <small>SoundFont는 라이선스가 다양하므로 앱에 번들하지 않습니다. General MIDI 호환 SoundFont를 직접 지정하세요.</small>
              </div>
            )}

            <button className="validation-run" type="button" disabled={busy} onClick={() => void validate()}>{busy ? "검증 중…" : "현재 악보 검증"}</button>

            {message && <div className="validation-message">{message}</div>}
            {report && (
              <div className="validation-results">
                <div className="validation-summary">
                  <strong>{report.ok ? "구조적 치명 오류 없음" : "수정이 필요한 오류 감지"}</strong>
                  <span>오류 {counts.error} · 경고 {counts.warning} · 정보 {counts.info}</span>
                  {report.llm && <small>LLM critic: {report.llm.model} · {report.llm.summary}</small>}
                  {report.visual && <small>OMR Vision: {report.visual.model} · {report.visual.pages_compared}페이지 비교 · {report.visual.summary}</small>}
                  {report.visual_skipped && <small>OMR Vision 건너뜀: {report.visual_skipped}</small>}
                  {report.audio && <small>Audio evidence: 유사도 {Math.round(report.audio.overall_similarity * 100)}% · 정렬 shift {report.audio.alignment_shift_seconds.toFixed(2)}s</small>}
                  {report.audio_skipped && <small>Audio evidence 건너뜀: {report.audio_skipped}</small>}
                </div>
                <div className="validation-issues">
                  {report.issues.length === 0 && <p>현재 검사에서 발견된 이상 항목이 없습니다.</p>}
                  {report.issues.map((issue, index) => (
                    <article key={`${issue.source}-${index}`} className={`validation-issue ${issue.severity}`}>
                      <div><strong>{issue.category}</strong><span>{issue.source === "llm" ? "LLM 가설" : issue.source === "vision" ? "원본 비교" : issue.source === "audio_symbol" ? "Audio evidence" : "규칙 검사"}</span></div>
                      <p>{issue.message}</p>
                      {(issue.page || issue.part || issue.measure || typeof issue.start_seconds === "number") && <small>{issue.page ? `P${issue.page}` : ""}{issue.part ? `${issue.page ? " · " : ""}${issue.part}` : ""}{issue.measure ? ` · M${issue.measure}` : ""}{typeof issue.start_seconds === "number" ? ` · ${issue.start_seconds.toFixed(1)}–${(issue.end_seconds ?? issue.start_seconds).toFixed(1)}s` : ""}</small>}
                      {typeof issue.confidence === "number" && ["vision", "audio_symbol"].includes(issue.source ?? "") && <small>confidence {Math.round(issue.confidence * 100)}%</small>}
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
