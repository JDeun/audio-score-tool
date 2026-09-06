import { useEffect, useState } from "react";
import App from "./App";
import SongWorkspace from "./SongWorkspace";
import "./song-workspace.css";

type ProductMode = "transcribe" | "songs";

export default function ProductRoot() {
  const [mode, setMode] = useState<ProductMode>(() => {
    const saved = window.localStorage.getItem("ast-product-mode");
    return saved === "songs" ? "songs" : "transcribe";
  });

  useEffect(() => {
    window.localStorage.setItem("ast-product-mode", mode);
  }, [mode]);

  return (
    <>
      {mode === "transcribe" ? <App /> : <SongWorkspace />}
      <nav className="product-mode-switch" aria-label="제품 작업공간 전환">
        <button className={mode === "transcribe" ? "active" : ""} onClick={() => setMode("transcribe")}>채보</button>
        <button className={mode === "songs" ? "active" : ""} onClick={() => setMode("songs")}>곡 라이브러리</button>
      </nav>
    </>
  );
}
