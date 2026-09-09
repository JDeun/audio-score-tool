import { useEffect, useState } from "react";
import "./studio-view-controls.css";

type ViewMode = "page" | "continuous";

const STORAGE = {
  library: "ast-studio-library",
  inspector: "ast-studio-inspector",
  focus: "ast-studio-focus",
  view: "ast-studio-view",
} as const;

function storedBool(key: string, fallback: boolean) {
  const value = window.localStorage.getItem(key);
  if (value === null) return fallback;
  return value === "true";
}

export default function StudioViewControls() {
  const [studioVisible, setStudioVisible] = useState(false);
  const [libraryVisible, setLibraryVisible] = useState(() => storedBool(STORAGE.library, true));
  const [inspectorVisible, setInspectorVisible] = useState(() => storedBool(STORAGE.inspector, true));
  const [focusMode, setFocusMode] = useState(() => storedBool(STORAGE.focus, false));
  const [viewMode, setViewMode] = useState<ViewMode>(() =>
    window.localStorage.getItem(STORAGE.view) === "continuous" ? "continuous" : "page",
  );

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("ast-library-hidden", !libraryVisible);
    root.classList.toggle("ast-inspector-hidden", !inspectorVisible);
    root.classList.toggle("ast-studio-focus", focusMode);
    root.classList.toggle("ast-score-continuous", viewMode === "continuous");

    window.localStorage.setItem(STORAGE.library, String(libraryVisible));
    window.localStorage.setItem(STORAGE.inspector, String(inspectorVisible));
    window.localStorage.setItem(STORAGE.focus, String(focusMode));
    window.localStorage.setItem(STORAGE.view, viewMode);
  }, [libraryVisible, inspectorVisible, focusMode, viewMode]);

  useEffect(() => {
    const refresh = () => setStudioVisible(Boolean(document.querySelector(".song-layout")));
    refresh();
    const observer = new MutationObserver(refresh);
    observer.observe(document.getElementById("root") ?? document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);

  if (!studioVisible) return null;

  return (
    <div className="studio-view-controls" role="toolbar" aria-label="Studio 보기 설정">
      <button
        type="button"
        className={libraryVisible ? "active" : ""}
        aria-pressed={libraryVisible}
        onClick={() => setLibraryVisible((value) => !value)}
        title="곡 라이브러리 표시/숨김"
      >
        Library
      </button>
      <button
        type="button"
        className={inspectorVisible ? "active" : ""}
        aria-pressed={inspectorVisible}
        onClick={() => setInspectorVisible((value) => !value)}
        title="Inspector 표시/숨김"
      >
        Inspector
      </button>
      <span className="studio-view-divider" aria-hidden="true" />
      <button
        type="button"
        className={viewMode === "page" ? "active" : ""}
        aria-pressed={viewMode === "page"}
        onClick={() => setViewMode("page")}
        title="인쇄 페이지 단위로 보기"
      >
        Page
      </button>
      <button
        type="button"
        className={viewMode === "continuous" ? "active" : ""}
        aria-pressed={viewMode === "continuous"}
        onClick={() => setViewMode("continuous")}
        title="페이지 사이 간격을 줄여 연속으로 보기"
      >
        Continuous
      </button>
      <span className="studio-view-divider" aria-hidden="true" />
      <button
        type="button"
        className={focusMode ? "active" : ""}
        aria-pressed={focusMode}
        onClick={() => setFocusMode((value) => !value)}
        title="전역 탐색을 숨기고 악보 편집에 집중"
      >
        Focus
      </button>
    </div>
  );
}
