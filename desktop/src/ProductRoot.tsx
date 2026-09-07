import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import OperationsWorkspace from "./OperationsWorkspace";
import SongWorkspace from "./SongWorkspace";
import "./song-workspace.css";
import "./advanced-score-editor.css";
import "./product-ui.css";

const API = "http://127.0.0.1:8080";

type ProductSection = "new" | "songs" | "history" | "benchmark" | "settings";

type HealthSummary = {
  status: string;
  preflight: { ok: boolean; missing: string[] };
  device_plan: { muscriptor_device: string };
  system: { hf_authenticated: boolean };
};

const sectionMeta: Record<ProductSection, { label: string; eyebrow: string; description: string }> = {
  new: {
    label: "새 악보",
    eyebrow: "NEW SCORE",
    description: "음원·YouTube·PDF/이미지 악보에서 편집 가능한 악보 프로젝트를 만듭니다.",
  },
  songs: {
    label: "곡 라이브러리",
    eyebrow: "SCORE LIBRARY",
    description: "완성된 곡을 미리보고 수정한 뒤 출판용 악보로 내보냅니다.",
  },
  history: {
    label: "작업 내역",
    eyebrow: "JOB HISTORY",
    description: "진행 중인 작업과 이전 채보·벤치마크 결과를 관리합니다.",
  },
  benchmark: {
    label: "성능 비교",
    eyebrow: "MODEL BENCHMARK",
    description: "현재 컴퓨터에서 모델 조합별 속도와 정확도를 비교합니다.",
  },
  settings: {
    label: "설정",
    eyebrow: "LOCAL SETUP",
    description: "모델 실행 환경, 저장공간, 실행 파일 경로와 인증 상태를 확인합니다.",
  },
};

function NavIcon({ name }: { name: ProductSection }) {
  const paths: Record<ProductSection, ReactNode> = {
    new: <><path d="M12 5v14M5 12h14" /><circle cx="12" cy="12" r="9" /></>,
    songs: <><path d="M5 4h12a2 2 0 0 1 2 2v14H7a2 2 0 0 1-2-2V4Z" /><path d="M9 9h6M9 13h6" /></>,
    history: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
    benchmark: <><path d="M4 19V9M10 19V5M16 19v-7M22 19V8" /></>,
    settings: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21h-4v-.08A1.7 1.7 0 0 0 8.6 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3v-4h.08A1.7 1.7 0 0 0 4.6 8.6a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3h4v.08A1.7 1.7 0 0 0 15.4 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9c.3.35.5.7.6 1 .1.35.14.72.1 1.1H21v4h-.08A1.7 1.7 0 0 0 19.4 15Z" /></>,
  };
  return <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

export default function ProductRoot() {
  const [section, setSection] = useState<ProductSection>(() => {
    const saved = window.localStorage.getItem("ast-section");
    return (["new", "songs", "history", "benchmark", "settings"] as ProductSection[]).includes(saved as ProductSection)
      ? saved as ProductSection
      : "new";
  });
  const [health, setHealth] = useState<HealthSummary | null>(null);
  const [offline, setOffline] = useState(false);
  const [showOnboarding, setShowOnboarding] = useState(
    () => window.localStorage.getItem("ast-onboarding-v1") !== "done",
  );
  const [onboardingStep, setOnboardingStep] = useState(0);

  useEffect(() => {
    window.localStorage.setItem("ast-section", section);
  }, [section]);

  useEffect(() => {
    const refresh = async () => {
      try {
        const response = await fetch(`${API}/api/health`);
        if (!response.ok) throw new Error("offline");
        setHealth(await response.json());
        setOffline(false);
      } catch {
        setOffline(true);
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLSelectElement) return;
      const keyMap: Record<string, ProductSection> = { n: "new", l: "songs", h: "history", b: "benchmark", s: "settings" };
      const next = keyMap[event.key.toLowerCase()];
      if (next) setSection(next);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const accelerator = useMemo(() => {
    const device = health?.device_plan.muscriptor_device;
    if (!device) return "확인 중";
    if (device.startsWith("cuda")) return "NVIDIA CUDA";
    if (device === "mps") return "Apple Metal";
    return "CPU";
  }, [health]);

  const ready = !!health?.preflight.ok;
  const meta = sectionMeta[section];
  const navPrimary: ProductSection[] = ["new", "songs"];
  const navSecondary: ProductSection[] = ["history", "benchmark"];

  const finishOnboarding = (destination: ProductSection = "new") => {
    window.localStorage.setItem("ast-onboarding-v1", "done");
    setShowOnboarding(false);
    setSection(destination);
  };

  return (
    <div className="product-frame">
      <aside className="product-sidebar">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">♩</div>
          <div>
            <strong>AudioScoreTool</strong>
            <span>AI 악보 제작 스튜디오</span>
          </div>
        </div>

        <nav className="product-nav" aria-label="주요 메뉴">
          <div className="nav-group">
            {navPrimary.map((item) => (
              <button key={item} className={section === item ? "active" : ""} onClick={() => setSection(item)}>
                <NavIcon name={item} />
                <span>{sectionMeta[item].label}</span>
                <kbd>{item === "new" ? "N" : "L"}</kbd>
              </button>
            ))}
          </div>
          <div className="nav-divider" />
          <div className="nav-group">
            {navSecondary.map((item) => (
              <button key={item} className={section === item ? "active" : ""} onClick={() => setSection(item)}>
                <NavIcon name={item} />
                <span>{sectionMeta[item].label}</span>
                <kbd>{item === "history" ? "H" : "B"}</kbd>
              </button>
            ))}
          </div>
        </nav>

        <div className="sidebar-bottom">
          <button className={`sidebar-setup ${section === "settings" ? "active" : ""}`} onClick={() => setSection("settings")}>
            <NavIcon name="settings" />
            <span>설정</span>
            {!ready && <i className="attention-dot" aria-label="설정 필요" />}
          </button>
          <div className="runtime-summary">
            <span className={`runtime-dot ${offline ? "offline" : ready ? "ready" : "warning"}`} />
            <div>
              <strong>{offline ? "백엔드 연결 안 됨" : ready ? "준비됨" : "설정 확인 필요"}</strong>
              <small>{offline ? "로컬 서비스를 확인하세요" : accelerator}</small>
            </div>
          </div>
          <span className="product-version">v0.8 · 로컬 우선</span>
        </div>
      </aside>

      <main className="product-main">
        <header className="product-page-header">
          <div>
            <span className="page-eyebrow">{meta.eyebrow}</span>
            <h1>{meta.label}</h1>
            <p>{meta.description}</p>
          </div>
          <div className="header-statuses">
            <span className={`compact-status ${health?.system.hf_authenticated ? "ready" : "warning"}`}>
              <i />HF {health?.system.hf_authenticated ? "인증됨" : "인증 필요"}
            </span>
            <span className={`compact-status ${offline ? "offline" : "ready"}`}>
              <i />{offline ? "오프라인" : accelerator}</span>
          </div>
        </header>

        <section className="product-stage">
          {section === "songs" ? (
            <SongWorkspace />
          ) : (
            <OperationsWorkspace section={section} onOpenSongs={() => setSection("songs")} />
          )}
        </section>
      </main>

      {showOnboarding && (
        <div className="onboarding-backdrop" role="presentation">
          <section className="onboarding-card" role="dialog" aria-modal="true" aria-labelledby="onboarding-title">
            <div className="onboarding-progress" aria-label={`3단계 중 ${onboardingStep + 1}단계`}>
              {[0, 1, 2].map((step) => <span key={step} className={step <= onboardingStep ? "active" : ""} />)}
            </div>

            {onboardingStep === 0 && (
              <div className="onboarding-content">
                <div className="onboarding-icon">♬</div>
                <span className="page-eyebrow">WELCOME</span>
                <h2 id="onboarding-title">입력 소스를 출판 가능한 악보 프로젝트로</h2>
                <p>AudioScoreTool은 음원·YouTube를 자동 채보하고 PDF/이미지 악보를 OMR로 가져와, 앱 안에서 검증·수정·조판한 뒤 PDF/MusicXML/MIDI로 내보내는 로컬 데스크탑 앱입니다.</p>
                <div className="onboarding-features">
                  <span>다중 악기 자동 채보</span><span>OMR·코드·가사</span><span>출판용 악보 편집</span>
                </div>
              </div>
            )}

            {onboardingStep === 1 && (
              <div className="onboarding-content">
                <span className="page-eyebrow">ENVIRONMENT CHECK</span>
                <h2 id="onboarding-title">실행 환경 확인</h2>
                <p>핵심 채보는 로컬에서 실행되며, LLM/Vision 검증은 선택 사항입니다. 아래 필수 항목이 준비되면 바로 시작할 수 있습니다.</p>
                <div className="check-list">
                  <div><span className={offline ? "check-bad" : "check-good"}>{offline ? "!" : "✓"}</span><strong>AudioScoreTool 백엔드</strong><small>{offline ? "연결되지 않음" : "정상"}</small></div>
                  <div><span className={ready ? "check-good" : "check-warn"}>{ready ? "✓" : "!"}</span><strong>로컬 도구</strong><small>{ready ? "필수 도구 확인됨" : `${health?.preflight.missing?.length ?? 0}개 항목 확인 필요`}</small></div>
                  <div><span className={health?.system.hf_authenticated ? "check-good" : "check-warn"}>{health?.system.hf_authenticated ? "✓" : "!"}</span><strong>Hugging Face</strong><small>{health?.system.hf_authenticated ? "인증됨" : "MuScriptor 선택 시 인증 필요"}</small></div>
                </div>
              </div>
            )}

            {onboardingStep === 2 && (
              <div className="onboarding-content">
                <span className="page-eyebrow">READY</span>
                <h2 id="onboarding-title">준비가 끝났습니다</h2>
                <p>로컬 음원, YouTube 링크, PDF/이미지 악보 중 원하는 입력으로 시작하세요. 결과는 자동으로 곡 라이브러리에 저장됩니다.</p>
                <div className="onboarding-actions-grid">
                  <button onClick={() => finishOnboarding("new")}><strong>새 악보 만들기</strong><span>음원·YouTube·기존 악보에서 시작</span></button>
                  <button onClick={() => finishOnboarding("settings")}><strong>설정 먼저 확인</strong><span>모델·인증·실행 경로 점검</span></button>
                </div>
              </div>
            )}

            <footer className="onboarding-footer">
              <button className="ghost-button" onClick={() => finishOnboarding("new")}>건너뛰기</button>
              <div>
                {onboardingStep > 0 && <button className="secondary-button" onClick={() => setOnboardingStep((step) => step - 1)}>이전</button>}
                {onboardingStep < 2 && <button className="primary-button" onClick={() => setOnboardingStep((step) => step + 1)}>다음</button>}
              </div>
            </footer>
          </section>
        </div>
      )}
    </div>
  );
}
