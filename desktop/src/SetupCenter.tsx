import { useEffect, useMemo, useState } from "react";
import "./setup-center.css";

const API = "http://127.0.0.1:8080";

type Component = {
  key: string;
  label: string;
  ready: boolean;
  tier: "core" | "recommended" | "optional";
  role: string;
  required_for: string[];
  download_url?: string | null;
  note?: string | null;
  auto_install: boolean;
  install_command?: string | null;
};

type SetupStatus = {
  platform: string;
  core_ready: boolean;
  recommended_ready: boolean;
  components: Component[];
  profiles: Record<string, string>;
  policy: {
    llm_required: boolean;
    musescore_required: boolean;
    optional_features_do_not_block_core: boolean;
  };
};

const tierLabel = {
  core: "필수",
  recommended: "권장",
  optional: "선택",
};

export default function SetupCenter() {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  const refresh = async () => {
    try {
      const response = await fetch(`${API}/api/setup/center`);
      if (!response.ok) throw new Error(await response.text());
      setStatus(await response.json());
    } catch {
      setStatus(null);
    }
  };

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(refresh, 10000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!status || status.core_ready) return;
    const timer = window.setInterval(() => {
      const productOnboardingDone = window.localStorage.getItem("ast-onboarding-v1") === "done";
      const setupDismissed = window.localStorage.getItem("ast-setup-center-v1") === "dismissed";
      if (productOnboardingDone && !setupDismissed) {
        setOpen(true);
        window.clearInterval(timer);
      }
    }, 700);
    return () => window.clearInterval(timer);
  }, [status?.core_ready]);

  const counts = useMemo(() => {
    if (!status) return { ready: 0, total: 0 };
    const relevant = status.components.filter((item) => item.tier !== "optional");
    return { ready: relevant.filter((item) => item.ready).length, total: relevant.length };
  }, [status]);

  const install = async (component: Component) => {
    setBusyKey(component.key);
    setMessage("");
    try {
      const response = await fetch(`${API}/api/setup/install`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ component: component.key }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail ?? "자동 설치에 실패했습니다.");
      setStatus(body.status);
      setMessage(`${component.label} 설치를 완료했습니다.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusyKey(null);
    }
  };

  const copyCommand = async (command: string) => {
    await navigator.clipboard.writeText(command);
    setMessage("설치 명령을 클립보드에 복사했습니다.");
  };

  const close = () => {
    window.localStorage.setItem("ast-setup-center-v1", "dismissed");
    setOpen(false);
  };

  if (!status) return null;

  return (
    <>
      <button className={`setup-center-trigger ${status.core_ready ? "ready" : "attention"}`} type="button" onClick={() => setOpen(true)}>
        <span>{status.core_ready ? "✓" : "!"}</span>
        설치 도우미
      </button>

      {open && (
        <div className="setup-center-backdrop" onMouseDown={(event) => event.target === event.currentTarget && close()}>
          <section className="setup-center-modal" role="dialog" aria-modal="true" aria-label="설치 도우미">
            <header>
              <div>
                <span className="setup-eyebrow">SETUP CENTER</span>
                <h2>첫 악보까지 필요한 것만 준비합니다</h2>
                <p>기본 채보에 필요하지 않은 OMR, Audio evidence, LLM은 설치하지 않아도 됩니다.</p>
              </div>
              <button type="button" onClick={close} aria-label="닫기">×</button>
            </header>

            <div className={`setup-readiness ${status.core_ready ? "ready" : "attention"}`}>
              <div>
                <strong>{status.core_ready ? "기본 채보 준비됨" : "기본 채보 준비가 필요합니다"}</strong>
                <span>권장 구성 {counts.ready}/{counts.total} 준비</span>
              </div>
              <button type="button" onClick={() => void refresh()}>다시 검사</button>
            </div>

            <div className="setup-profile-strip">
              <div><strong>기본</strong><span>{status.profiles.core}</span></div>
              <div><strong>권장</strong><span>{status.profiles.recommended}</span></div>
              <div><strong>전체</strong><span>{status.profiles.full}</span></div>
            </div>

            <div className="setup-component-list">
              {status.components.map((component) => (
                <article key={component.key} className={`setup-component ${component.ready ? "ready" : "missing"}`}>
                  <div className="setup-component-state">{component.ready ? "✓" : "!"}</div>
                  <div className="setup-component-copy">
                    <div>
                      <strong>{component.label}</strong>
                      <span className={`setup-tier ${component.tier}`}>{tierLabel[component.tier]}</span>
                    </div>
                    <p>{component.role}</p>
                    {component.note && <small>{component.note}</small>}
                  </div>
                  <div className="setup-component-actions">
                    {component.ready ? (
                      <span className="setup-installed">사용 가능</span>
                    ) : (
                      <>
                        {component.auto_install && (
                          <button type="button" disabled={busyKey !== null} onClick={() => void install(component)}>
                            {busyKey === component.key ? "설치 중…" : "자동 설치"}
                          </button>
                        )}
                        {component.install_command && (
                          <button className="secondary" type="button" onClick={() => void copyCommand(component.install_command!)}>명령 복사</button>
                        )}
                        {component.download_url && (
                          <a href={component.download_url} target="_blank" rel="noreferrer">공식 다운로드</a>
                        )}
                      </>
                    )}
                  </div>
                </article>
              ))}
            </div>

            <div className="setup-policy-note">
              <strong>선택 기능은 기본 사용을 막지 않습니다.</strong>
              <span>LLM/Vision은 기본 OFF이며 API 방식으로도 사용할 수 있습니다. MuseScore도 필수가 아닙니다.</span>
            </div>

            {message && <div className="setup-center-message">{message}</div>}

            <footer>
              <button className="setup-later" type="button" onClick={close}>나중에</button>
              <button className="setup-done" type="button" disabled={!status.core_ready} onClick={close}>
                {status.core_ready ? "설정 완료" : "필수 항목을 준비하세요"}
              </button>
            </footer>
          </section>
        </div>
      )}
    </>
  );
}
