import { useCallback, useEffect, useRef, useState } from "react";
import "./source-audio-review.css";

const API = "http://127.0.0.1:8080";
export type AudioClip = { start_seconds: number; end_seconds: number };

export default function SourceAudioReview({ songId, revision, clip }: { songId: string; revision: number; clip?: AudioClip | null }) {
  const [url, setUrl] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [duration, setDuration] = useState<number | null>(null);
  const [repeat, setRepeat] = useState(false);
  const audio = useRef<HTMLAudioElement | null>(null);
  const request = useRef<AbortController | null>(null);
  const objectUrl = useRef<string | null>(null);
  const frame = useRef<number | null>(null);
  const bounded = useRef(false);
  const repeatRef = useRef(false);
  const identity = useRef(`${songId}:${revision}`);
  const currentIdentity = `${songId}:${revision}`;
  identity.current = currentIdentity;
  const stopWatch = () => { if (frame.current !== null) cancelAnimationFrame(frame.current); frame.current = null; };
  const setAudio = useCallback((player: HTMLAudioElement | null) => {
    if (audio.current && audio.current !== player) {
      audio.current.pause();
      if (frame.current !== null) cancelAnimationFrame(frame.current);
      frame.current = null;
      bounded.current = false;
    }
    audio.current = player;
  }, []);

  useEffect(() => {
    setUrl(null); setDuration(null); setLoading(false); setMessage(""); setRepeat(false);
    bounded.current = false; repeatRef.current = false;
    return () => {
      request.current?.abort(); bounded.current = false; stopWatch(); audio.current?.pause();
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
      objectUrl.current = null;
    };
  }, [songId, revision]);
  useEffect(() => { bounded.current = false; stopWatch(); audio.current?.pause(); }, [clip]);
  const start = clip && duration !== null ? Math.max(0, clip.start_seconds - .3) : null;
  const end = clip && duration !== null ? Math.min(duration, clip.end_seconds + .3) : null;
  const validClip = start !== null && end !== null && Number.isFinite(start) && Number.isFinite(end) && start < end;

  const load = async () => {
    request.current?.abort();
    bounded.current = false; stopWatch(); audio.current?.pause();
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    objectUrl.current = null; setUrl(null); setDuration(null);
    const controller = new AbortController(); request.current = controller;
    const requestedIdentity = currentIdentity;
    setLoading(true); setMessage("");
    try {
      const response = await fetch(`${API}/api/songs/${encodeURIComponent(songId)}/source-audio?expected_revision=${revision}`, { method: "GET", signal: controller.signal });
      if (response.status === 404) throw new Error("보존된 원음이 없습니다. 원음이 있는 곡을 선택하세요.");
      if (response.status === 409) throw new Error("악보가 변경되었습니다. 곡을 새로고침한 뒤 다시 불러오세요.");
      if (!response.ok) throw new Error("원음을 불러오지 못했습니다. 연결을 확인하고 다시 시도하세요.");
      const blob = await response.blob();
      if (controller.signal.aborted || request.current !== controller || identity.current !== requestedIdentity) return;
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
      objectUrl.current = URL.createObjectURL(blob); setUrl(objectUrl.current);
    } catch (error) {
      if (!controller.signal.aborted && request.current === controller && identity.current === requestedIdentity) {
        const detail = error instanceof Error ? error.message : "";
        setMessage(detail.startsWith("보존된") || detail.startsWith("악보가") ? detail : "원음을 불러오지 못했습니다. 연결을 확인하고 다시 시도하세요.");
      }
    } finally { if (request.current === controller && identity.current === requestedIdentity) setLoading(false); }
  };
  const watch = () => {
    stopWatch();
    const tick = () => {
      const player = audio.current;
      if (!player || player.paused || !bounded.current || !validClip) return;
      if (player.currentTime < start) player.currentTime = start;
      if (player.currentTime >= end) {
        if (repeatRef.current) player.currentTime = start;
        else { player.pause(); player.currentTime = end; bounded.current = false; return; }
      }
      frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);
  };
  const playClip = async () => {
    const player = audio.current;
    if (!player || !validClip) return;
    const requestedIdentity = currentIdentity;
    bounded.current = true; player.currentTime = start;
    try {
      await player.play();
      if (audio.current !== player || identity.current !== requestedIdentity || !bounded.current) { player.pause(); return; }
      watch();
    } catch {
      if (audio.current === player && identity.current === requestedIdentity) { bounded.current = false; setMessage("원음을 재생할 수 없습니다. 브라우저에서 지원하는 음원인지 확인하세요."); }
    }
  };
  return <section className="source-audio-review" aria-label="원음 검수">
    <div className="source-audio-heading"><strong>원음 검수</strong><button type="button" className="secondary" disabled={loading} onClick={() => void load()}>{loading ? "불러오는 중…" : url ? "원음 다시 불러오기" : "원음 불러오기"}</button></div>
    {message && <p role="status">{message}</p>}
    {url && <audio ref={setAudio} src={url} controls aria-label="원음 재생" onLoadedMetadata={(event) => { const value = event.currentTarget.duration; setDuration(Number.isFinite(value) && value > 0 ? value : null); }} onPlay={watch} onPause={stopWatch} onEnded={() => { stopWatch(); if (bounded.current && repeatRef.current && validClip && audio.current) { audio.current.currentTime = start; void audio.current.play().catch(() => setMessage("원음을 재생할 수 없습니다. 다시 시도하세요.")); } }} onError={() => setMessage("원음을 재생할 수 없습니다. 브라우저에서 지원하는 음원인지 확인하세요.")} />}
    {clip && <div className="source-audio-clip"><p>악보 시간표로 찾은 구간으로 실제 시작점과 차이 날 수 있습니다.</p>{validClip ? <><span>확인 구간 {start.toFixed(2)}–{end.toFixed(2)}초</span><div className="source-audio-actions"><button type="button" className="secondary" onClick={() => void playClip()}>구간 재생</button><label><input type="checkbox" checked={repeat} onChange={(event) => { repeatRef.current = event.target.checked; setRepeat(event.target.checked); }} /> 반복</label></div></> : <span>{url ? "재생 가능한 구간이 없습니다." : "원음을 불러오면 구간을 재생할 수 있습니다."}</span>}</div>}
  </section>;
}
