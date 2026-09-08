import { invoke } from "@tauri-apps/api/core";
import { useEffect, useState } from "react";
import "./desktop-updater.css";

type UpdateState = "idle" | "checking" | "available" | "current" | "installing" | "error";

export default function DesktopUpdaterControl() {
  const [configured, setConfigured] = useState(false);
  const [state, setState] = useState<UpdateState>("idle");
  const [version, setVersion] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    void invoke<boolean>("updater_configured")
      .then(setConfigured)
      .catch(() => setConfigured(false));
  }, []);

  if (!configured) return null;

  const check = async () => {
    try {
      setState("checking");
      setMessage("업데이트를 확인하고 있습니다…");
      const nextVersion = await invoke<string | null>("check_for_update");
      setVersion(nextVersion);
      if (nextVersion) {
        setState("available");
        setMessage(`새 버전 v${nextVersion}을 설치할 수 있습니다.`);
      } else {
        setState("current");
        setMessage("현재 최신 버전입니다.");
      }
    } catch (error) {
      setState("error");
      setMessage(error instanceof Error ? error.message : String(error));
    }
  };

  const install = async () => {
    try {
      setState("installing");
      setMessage("업데이트를 내려받아 설치하고 있습니다. 앱이 재시작될 수 있습니다.");
      await invoke("install_pending_update");
    } catch (error) {
      setState("error");
      setMessage(error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <div className="desktop-updater" aria-live="polite">
      <div>
        <strong>앱 업데이트</strong>
        <small>{message || "서명된 안정 버전만 설치합니다."}</small>
      </div>
      {state === "available" ? (
        <button type="button" onClick={() => void install()}>
          v{version} 설치
        </button>
      ) : (
        <button type="button" onClick={() => void check()} disabled={state === "checking" || state === "installing"}>
          {state === "checking" ? "확인 중…" : state === "installing" ? "설치 중…" : "업데이트 확인"}
        </button>
      )}
    </div>
  );
}
