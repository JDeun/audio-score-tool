import { useEffect, useRef } from "react";

const API = "http://127.0.0.1:8080";

type SongSummary = { song_id: string };

export default function SourceIdentificationController() {
  const completed = useRef(new Set<string>());
  const inFlight = useRef(new Set<string>());

  useEffect(() => {
    let cancelled = false;

    const identifyNewSongs = async () => {
      try {
        const listResponse = await fetch(`${API}/api/songs`);
        if (!listResponse.ok) return;
        const body = await listResponse.json();
        const songs: SongSummary[] = body.songs ?? [];
        for (const song of songs) {
          if (cancelled || completed.current.has(song.song_id) || inFlight.current.has(song.song_id)) continue;
          inFlight.current.add(song.song_id);
          try {
            const response = await fetch(`${API}/api/songs/${song.song_id}/identify-source`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                refresh: false,
                apply_high_confidence_metadata: true,
              }),
            });
            // Only successful responses are terminal for this desktop session. A transient
            // 5xx/network failure must be retried on the next interval instead of being
            // permanently suppressed by the client-side de-duplication set.
            if (!response.ok) continue;
            const report = await response.json();
            completed.current.add(song.song_id);
            window.dispatchEvent(new CustomEvent("audioscore:source-identified", { detail: report }));
          } catch {
            // Per-song identification is enrichment only; retry transient failures later.
          } finally {
            inFlight.current.delete(song.song_id);
          }
        }
      } catch {
        // Backend reconnection is handled elsewhere; retry on the next interval.
      }
    };

    void identifyNewSongs();
    const timer = window.setInterval(() => void identifyNewSongs(), 10000);
    const handler = () => void identifyNewSongs();
    window.addEventListener("audioscore:job-completed", handler);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener("audioscore:job-completed", handler);
    };
  }, []);

  return null;
}
