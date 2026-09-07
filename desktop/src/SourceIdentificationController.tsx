import { useEffect, useRef } from "react";

const API = "http://127.0.0.1:8080";

function currentSongId(): string | null {
  const workbench = document.querySelector(".score-workbench");
  const scoreLink = workbench?.querySelector<HTMLAnchorElement>('a[href*="/api/songs/"][href*="/files/"]');
  if (!scoreLink) return null;
  const pathname = new URL(scoreLink.href, window.location.href).pathname;
  const match = pathname.match(/\/api\/songs\/([^/]+)\/files\//);
  return match ? decodeURIComponent(match[1]) : null;
}

export default function SourceIdentificationController() {
  const lastSong = useRef<string | null>(null);

  useEffect(() => {
    const identify = async () => {
      const songId = currentSongId();
      if (!songId || lastSong.current === songId) return;
      lastSong.current = songId;
      try {
        const response = await fetch(`${API}/api/songs/${songId}/identify-source`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            refresh: false,
            apply_high_confidence_metadata: true,
          }),
        });
        if (!response.ok) return;
        const report = await response.json();
        window.dispatchEvent(new CustomEvent("audioscore:source-identified", { detail: report }));
      } catch {
        // Identification is enrichment only; transcription/editing must never depend on it.
      }
    };

    void identify();
    const observer = new MutationObserver(() => void identify());
    observer.observe(document.body, { subtree: true, childList: true });
    return () => observer.disconnect();
  }, []);

  return null;
}
