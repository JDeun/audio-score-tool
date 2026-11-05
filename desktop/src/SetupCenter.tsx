import { useEffect, useMemo, useState } from "react";
import "./setup-center.css";

// main.tsx rewrites this development origin to the authenticated dynamic loopback
// endpoint in packaged Tauri builds.
const API = "http://127.0.0.1:8080";

type Tier = "core" | "conditional" | "optional";
type Delivery =
  | "embedded"
  | "managed-model-runtime"
  | "managed-component"
  | "account-credential"
  | "external-service";

type Component = {
  key: string;
  label: string;
  ready: boolean;
  tier: Tier;
  delivery: Delivery;
  role: string;
  required_for: string[];
  note?: string | null;
  auto_install?: boolean;
  managed_status?: { ready?: boolean; integrity?: string; version?: string } | null;
  catalog?: { published?: boolean; target?: string; version?: string } | null;
};

type SetupStatus = {
  platform: string;
  core_ready: boolean;
  recommended_ready: boolean;
  components: Component[];
  profiles: Record<string, string>;
  policy: {
    pdf_renderer: string;
    musescore_required: boolean;
    lilypond_required: boolean;
    system_package_manager_required: boolean;
    developer_toolchain_required: boolean;
    optional_features_do_not_block_core: boolean;
    desktop_release_must_not_require_manual_runtime_install: boolean;
  };
};

const tierLabel: Record<Tier, string> = {
  core: "핵심",
  conditional: "조건부",
  optional: "선택",
};

async function apiError(response: Response): Promise<string> {
  const raw = await response.text();
  try {
    const parsed = JSON.parse(raw) as { detail?: string };
    return typeof parsed.detail === "string" ? parsed.detail : raw;
  } catch {
    return raw || `요청이 실패했습니다 (HTTP ${response.status}).`;
  }
}

const deliveryLabel: Record<Delivery, string> = {
  embedded: "앱 내장",
  "managed-model-runtime": "앱 관리 모델/런타임",
  "managed-component": "앱 관리 구성요소",
  "account-credential": "계정 인증",
  "external-service": "선택적 외부 서비스",
};

export default function SetupCenter() {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ message: string; error: boolean } | null>(null);

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
      const setupDismissed = window.localStorage.getItem("ast-setup-center-v2") === "dismissed";
      if (productOnboardingDone && !setupDismissed) {
        setOpen(true);
        window.clearInterval(timer);
      }
    }, 700);
    return () => window.clearInterval(timer);
  }, [status?.core_ready]);

  const counts = useMemo(() => {
    if (!status) return { ready: 0, total: 0 };
    const core = status.components.filter((item) => item.tier === "core");
    return { ready: core.filter((item) => item.ready).length, total: core.length };
  }, [status]);

  const install = async (component: Component) => {
    if (!component.auto_install || !component.catalog?.published || busy) return;
    setBusy(component.key);
    setFeedback(null);
    try {
      const response = await fetch(`${API}/api/setup/install`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ component: component.key }),
      });
      if (!response.ok) throw new Error(await apiError(response));
      const result = await response.json() as {
        installed: { ready?: boolean; integrity?: string };
        setup: SetupStatus;
      };
      setStatus(result.setup);
      if (!result.installed?.ready || result.installed.integrity !== "verified") {
        throw new Error("설치 요청이 완료됐지만 무결성 검증에 통과하지 못했습니다.");
      }
      setFeedback({
        message: `${component.label} 설치 파일이 검증됐습니다. 실행 준비 상태를 다시 확인하세요.`,
        error: false,
      });
    } catch (error) {
      setFeedback({ message: error instanceof Error ? error.message : "구성요소 설치 실패", error: true });
      await refresh();
    } finally {
      setBusy(null);
    }
  };

  const recover = async () => {
    if (busy) return;
    setBusy("recovery");
    setFeedback(null);
    try {
      const response = await fetch(`${API}/api/setup/recover`, { method: "POST" });
      if (!response.ok) throw new Error(await apiError(response));
      const result = await response.json() as {
        recovery: { removed_component_staging?: number };
        setup: SetupStatus;
      };
      setStatus(result.setup);
      setFeedback({
        message: `임시 설치 파일 ${result.recovery.removed_component_staging ?? 0}개를 정리했습니다.`,
        error: false,
      });
    } catch (error) {
      setFeedback({ message: error instanceof Error ? error.message : "복구 작업 실패", error: true });
      await refresh();
    } finally {
      setBusy(null);
    }
  };

  const close = () => {
    window.localStorage.setItem("ast-setup-center-v2", "dismissed");
    setOpen(false);
  };

  if (!status) return null;

  return (
    <>
      <button className={`setup-center-trigger ${status.core_ready ? "ready" : "attention"}`} type="button" onClick={() => setOpen(true)}>
        <span>{status.core_ready ? "✓" : "!"}</span>
        구성요소 상태
      </button>

      {open && (
        <div className="setup-center-backdrop" onMouseDown={(event) => event.target === event.currentTarget && close()}>
          <section className="setup-center-modal" role="dialog" aria-modal="true" aria-label="구성요소 상태">
            <header>
              <div>
                <span className="setup-eyebrow">RUNTIME STATUS</span>
                <h2>별도 프로그램 설치 없이 동작하는 데스크탑 런타임</h2>
                <p>핵심 구성요소는 설치본에 포함합니다. 큰 모델과 선택 기능은 앱이 자체 관리하며 시스템 package manager를 사용하지 않습니다.</p>
              </div>
              <button type="button" onClick={close} aria-label="닫기">×</button>
            </header>

            <div className={`setup-readiness ${status.core_ready ? "ready" : "attention"}`}>
              <div>
                <strong>{status.core_ready ? "핵심 런타임 준비됨" : "패키지 구성요소 확인이 필요합니다"}</strong>
                <span>핵심 {counts.ready}/{counts.total} 준비</span>
              </div>
              <div className="setup-readiness-actions">
                <button type="button" disabled={Boolean(busy)} onClick={() => void refresh()}>다시 검사</button>
                <button type="button" disabled={Boolean(busy)} onClick={() => void recover()}>
                  {busy === "recovery" ? "정리 중…" : "중단된 설치 복구"}
                </button>
              </div>
            </div>

            {feedback && (
              <p className={`setup-center-message${feedback.error ? " setup-center-error" : ""}`}
                role={feedback.error ? "alert" : "status"}>{feedback.message}</p>
            )}

            <div className="setup-profile-strip">
              <div><strong>핵심</strong><span>{status.profiles.core}</span></div>
              <div><strong>선택</strong><span>{status.profiles.optional}</span></div>
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
                    <small>{deliveryLabel[component.delivery]}</small>
                    {component.note && <small>{component.note}</small>}
                  </div>
                  <div className="setup-component-actions">
                    <span className="setup-installed">
                      {component.ready
                        ? "사용 가능"
                        : component.managed_status?.ready
                          ? "설치됨 · 실행 환경 점검 필요"
                          : component.catalog && !component.catalog.published
                            ? "이 플랫폼용 배포 파일 미게시"
                            : component.delivery === "embedded"
                              ? "패키지 점검 필요"
                              : "현재 비활성"}
                    </span>
                    {component.auto_install && component.catalog?.published && (
                      <button type="button" disabled={Boolean(busy)}
                        onClick={() => void install(component)}>
                        {busy === component.key ? "설치·검증 중…" :
                          component.managed_status?.ready ? "재설치 / 업데이트" : "앱에서 설치"}
                      </button>
                    )}
                  </div>
                </article>
              ))}
            </div>

            <div className="setup-policy-note">
              <strong>사용자에게 개발 도구 설치를 요구하지 않습니다.</strong>
              <span>Python, Node, Rust, MuseScore, LilyPond, Homebrew, winget, pip, uv는 일반 사용자 설치 절차가 아닙니다.</span>
            </div>

            <footer>
              <button className="setup-later" type="button" onClick={close}>닫기</button>
              <button className="setup-done" type="button" disabled={!status.core_ready || Boolean(busy)} onClick={close}>
                {status.core_ready ? "확인" : "핵심 구성요소를 확인하세요"}
              </button>
            </footer>
          </section>
        </div>
      )}
    </>
  );
}
