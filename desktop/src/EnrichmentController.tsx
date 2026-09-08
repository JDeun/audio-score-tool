import { useEffect, useState } from "react";
import "./enrichment-controller.css";

const API = "http://127.0.0.1:8080";

type Target = { songId: string; title: string };
type Candidate = {
  recording_mbid?: string;
  title?: string;
  artist?: string | null;
  first_release_date?: string | null;
  album?: string | null;
  score: number;
};
type Report = {
  metadata: { candidates: Candidate[]; selected?: Candidate | null; applied: boolean; error?: string | null };
  lyrics?: { provider: string; lyrics: string; synced: boolean } | null;
  lyrics_error?: string | null;
  lyric_application?: {
    applied: boolean;
    reason?: string;
    part_id?: string;
    attached_tokens?: number;
    stats?: { exact_token_matches?: number; reference_tokens?: number; coverage?: number };
  } | null;
};

function currentTarget(): Target | null {
  const workbench = document.querySelector(".score-workbench");
  const scoreLink = workbench?.querySelector<HTMLAnchorElement>('a[href*="/api/songs/"][href*="/files/"]');
  if (!scoreLink) return null;
  const pathname = new URL(scoreLink.href, window.location.href).pathname;
  const match = pathname.match(/\/api\/songs\/([^/]+)\/files\//);
  if (!match) return null;
  const title = workbench?.querySelector(".score-toolbar h2")?.textContent?.trim() || "악보";
  return { songId: decodeURIComponent(match[1]), title };
}

export default function EnrichmentController() {
  const [target, setTarget] = useState<Target | null>(null);
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [usageMode, setUsageMode] = useState<"personal" | "commercial">("personal");
  const [commercialEntitlement, setCommercialEntitlement] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [lyricsProvider, setLyricsProvider] = useState("");
  const [lyricsUrl, setLyricsUrl] = useState("");
  const [lyricsKeyEnv, setLyricsKeyEnv] = useState("");
  const [applyReferenceLyrics, setApplyReferenceLyrics] = useState(false);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    const refresh = () => setTarget(currentTarget());
    refresh();
    const observer = new MutationObserver(refresh);
    observer.observe(document.body, { subtree: true, childList: true });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!open || !target) return;
    void Promise.all([
      fetch(`${API}/api/songs/${target.songId}`),
      fetch(`${API}/api/engines`),
    ]).then(async ([songResponse, engineResponse]) => {
      if (songResponse.ok) {
        const song = await songResponse.json();
        setTitle(song.title ?? target.title);
        setArtist(song.artist ?? "");
      }
      if (engineResponse.ok) {
        const engines = await engineResponse.json();
        setUsageMode(engines.usage_mode === "commercial" ? "commercial" : "personal");
      }
    }).catch(() => undefined);
  }, [open, target?.songId]);

  const run = async () => {
    if (!target) return;
    setBusy(true);
    setMessage("");
    setReport(null);
    try {
      const response = await fetch(`${API}/api/songs/${target.songId}/enrich`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          artist: artist || null,
          apply_high_confidence_metadata: true,
          metadata_threshold: 92,
          musicbrainz_commercial_entitlement: commercialEntitlement,
          lyrics_provider_name: advanced && lyricsProvider ? lyricsProvider : null,
          lyrics_url_template: advanced && lyricsUrl ? lyricsUrl : null,
          lyrics_api_key_env: advanced && lyricsKeyEnv ? lyricsKeyEnv : null,
          apply_reference_lyrics: advanced && applyReferenceLyrics,
        }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail ?? "외부 정보를 조회하지 못했습니다.");
      setReport(body);
      if (body.lyric_application?.applied) setMessage("메타데이터를 확인하고 외부 가사를 WhisperX 타이밍에 맞춰 악보에 반영했습니다.");
      else if (body.metadata?.applied) setMessage("신뢰도가 높은 메타데이터를 곡 정보에 반영했습니다.");
      else setMessage("후보를 찾았습니다. 자동 적용 기준을 넘지 않은 정보는 저장하지 않았습니다.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  if (!target) return null;

  return (
    <>
      <button className="enrichment-trigger" type="button" onClick={() => setOpen(true)}>곡 정보</button>
      {open && (
        <div className="enrichment-backdrop" onMouseDown={(event) => event.target === event.currentTarget && setOpen(false)}>
          <section className="enrichment-modal" role="dialog" aria-modal="true" aria-label="곡 정보 보강">
            <header><div><span>DATA ENRICHMENT</span><h2>곡 정보 보강</h2><p>모델이 추측하기보다 신뢰 가능한 외부 데이터를 우선 사용합니다.</p></div><button type="button" onClick={() => setOpen(false)}>×</button></header>
            <div className="enrichment-policy"><strong>메타데이터는 MusicBrainz, 가사는 허용된 provider만</strong><p>제목·아티스트·앨범·발매일·MBID 등을 조회합니다. 가사는 저작권 때문에 임의 웹페이지를 스크래핑하지 않으며, 별도 API를 연결하지 않으면 WhisperX 전사를 사용합니다.</p></div>
            {usageMode === "commercial" && <label className="enrichment-commercial-check"><input type="checkbox" checked={commercialEntitlement} onChange={(event) => setCommercialEntitlement(event.target.checked)} /><span>MusicBrainz Web Service의 상용 이용 자격/계약을 확인했습니다.</span></label>}
            <div className="enrichment-fields"><label><span>곡명</span><input value={title} onChange={(event) => setTitle(event.target.value)} /></label><label><span>아티스트</span><input value={artist} onChange={(event) => setArtist(event.target.value)} placeholder="알고 있다면 입력" /></label></div>
            <button className="enrichment-advanced-toggle" type="button" onClick={() => setAdvanced((value) => !value)}>{advanced ? "가사 API 설정 닫기" : "선택 사항 · 가사 API 연결"}</button>
            {advanced && <div className="enrichment-fields advanced"><label><span>Provider 이름</span><input value={lyricsProvider} onChange={(event) => setLyricsProvider(event.target.value)} placeholder="예: licensed-lyrics" /></label><label><span>HTTPS URL template</span><input value={lyricsUrl} onChange={(event) => setLyricsUrl(event.target.value)} placeholder="https://api.example/lyrics?artist={artist}&title={title}" /></label><label><span>API key 환경변수명</span><input value={lyricsKeyEnv} onChange={(event) => setLyricsKeyEnv(event.target.value)} placeholder="LYRICS_API_KEY" /></label><label className="enrichment-reference-check"><input type="checkbox" checked={applyReferenceLyrics} onChange={(event) => setApplyReferenceLyrics(event.target.checked)} /><span><strong>가사 텍스트를 악보에 반영</strong><small>외부 가사는 문자열 교정에만 쓰고, 노래 타이밍은 WhisperX의 원음 기반 timing을 유지합니다.</small></span></label></div>}
            <button className="enrichment-run" type="button" disabled={busy || !title.trim() || (usageMode === "commercial" && !commercialEntitlement)} onClick={() => void run()}>{busy ? "조회 중…" : "외부 데이터로 확인"}</button>
            {message && <div className="enrichment-message">{message}</div>}
            {report && <div className="enrichment-results">{report.metadata.error && <p>MusicBrainz 조회 오류: {report.metadata.error}</p>}{report.metadata.candidates.map((item, index) => <article key={item.recording_mbid ?? index} className={report.metadata.selected?.recording_mbid === item.recording_mbid ? "selected" : ""}><div><strong>{item.title ?? "제목 없음"}</strong><span>{item.score}% match</span></div><p>{item.artist ?? "아티스트 미상"}{item.album ? ` · ${item.album}` : ""}{item.first_release_date ? ` · ${item.first_release_date}` : ""}</p>{item.recording_mbid && <small>MBID {item.recording_mbid}</small>}</article>)}{report.lyrics && <div className="enrichment-lyrics"><strong>가사 provider: {report.lyrics.provider}</strong><span>{report.lyrics.synced ? "동기화 가사" : "일반 가사"}를 provenance와 함께 확보했습니다.</span>{report.lyric_application?.applied && <span>악보 적용 완료 · {report.lyric_application.attached_tokens ?? 0} tokens</span>}{report.lyric_application && !report.lyric_application.applied && <span>악보 미적용: {report.lyric_application.reason}</span>}</div>}{report.lyrics_error && <small>가사 API: {report.lyrics_error}</small>}</div>}
          </section>
        </div>
      )}
    </>
  );
}
