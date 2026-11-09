import { useEffect, useRef, useState } from "react";
import "./enrichment-controller.css";
import { useSelectedSong } from "./SelectedSongContext";

const API = "http://127.0.0.1:8080";

type Candidate = {
  recording_mbid?: string;
  title?: string;
  artist?: string | null;
  first_release_date?: string | null;
  album?: string | null;
  composer?: string | null;
  lyricist?: string | null;
  songwriters_verified?: boolean;
  score: number;
};
type Report = {
  metadata: { candidates: Candidate[]; selected?: Candidate | null; applied: boolean; error?: string | null };
  lyrics?: { provider: string; lyrics: string; synced: boolean } | null;
  lyrics_error?: string | null;
  lyrics_source?: "external_api" | "whisperx" | "unavailable";
  lyric_application?: {
    applied: boolean;
    reason?: string;
    part_id?: string;
    attached_tokens?: number;
    stats?: { exact_token_matches?: number; reference_tokens?: number; coverage?: number };
  } | null;
};
type IdentificationReport = {
  status?: string;
  selected?: { title?: string; artist?: string | null; provider?: string; reason?: string } | null;
  selected_confidence?: number;
  applied?: boolean;
  acoustid?: { attempted?: boolean; error?: string | null };
  musicbrainz_error?: string | null;
};

type CreditFields = {
  album: string;
  performer: string;
  release_date: string;
  composer: string;
  lyricist: string;
};

const emptyCredits: CreditFields = {
  album: "", performer: "", release_date: "", composer: "", lyricist: "",
};

const creditLabels: { key: keyof CreditFields; label: string }[] = [
  { key: "album", label: "앨범명" },
  { key: "performer", label: "가수·연주자" },
  { key: "release_date", label: "발매 정보" },
  { key: "composer", label: "작곡가" },
  { key: "lyricist", label: "작사가" },
];

function metadataFingerprint(title: string, artist: string, credits: CreditFields) {
  return JSON.stringify({ title, artist, credits });
}

export default function EnrichmentController() {
  const { target, notifySongChanged, metadataEditorRequest } = useSelectedSong();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [credits, setCredits] = useState<CreditFields>(emptyCredits);
  const [revision, setRevision] = useState<number | null>(null);
  const [savedFingerprint, setSavedFingerprint] = useState<string | null>(null);
  const [loadingMetadata, setLoadingMetadata] = useState(false);
  const [savingMetadata, setSavingMetadata] = useState(false);
  const activeSongId = useRef<string | null>(null);
  activeSongId.current = target?.songId ?? null;
  const isDirty = savedFingerprint !== null
    && metadataFingerprint(title, artist, credits) !== savedFingerprint;

  const [usageMode, setUsageMode] = useState<"personal" | "commercial">("personal");
  const [commercialEntitlement, setCommercialEntitlement] = useState(false);
  const [acoustidCommercialEntitlement, setAcoustidCommercialEntitlement] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [lyricsProvider, setLyricsProvider] = useState("");
  const [lyricsUrl, setLyricsUrl] = useState("");
  const [lyricsKeyEnv, setLyricsKeyEnv] = useState("");
  const [applyReferenceLyrics, setApplyReferenceLyrics] = useState(true);
  const [busy, setBusy] = useState(false);
  const [identifying, setIdentifying] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const [identification, setIdentification] = useState<IdentificationReport | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    // A modal must never submit data for a song that is no longer selected.
    setOpen(false);
    setReport(null);
    setIdentification(null);
    setMessage("");
    setRevision(null);
    setSavedFingerprint(null);
  }, [target?.songId]);

  useEffect(() => {
    if (metadataEditorRequest?.songId === target?.songId && target?.songId) {
      setOpen(true);
    }
  }, [metadataEditorRequest?.sequence, metadataEditorRequest?.songId, target?.songId]);

  const refreshMetadata = async (songId: string) => {
    const [songResponse, publicationResponse] = await Promise.all([
      fetch(`${API}/api/songs/${songId}`),
      fetch(`${API}/api/songs/${songId}/publication`),
    ]);
    if (!songResponse.ok || !publicationResponse.ok) {
      throw new Error("곡 정보와 악보 크레딧을 불러오지 못했습니다.");
    }
    const song = await songResponse.json();
    const publication = await publicationResponse.json();
    if (activeSongId.current !== songId) return;
    const nextCredits: CreditFields = {
      ...emptyCredits,
      ...(Object.fromEntries(
        creditLabels.map(({ key }) => [key, publication.settings?.[key] ?? ""])
      ) as CreditFields),
    };
    const nextTitle = String(song.title ?? "");
    const nextArtist = String(song.artist ?? "");
    setTitle(nextTitle);
    setArtist(nextArtist);
    setCredits(nextCredits);
    setRevision(Number(song.revision));
    setSavedFingerprint(metadataFingerprint(nextTitle, nextArtist, nextCredits));
  };

  useEffect(() => {
    if (!open || !target) return;
    const songId = target.songId;
    setLoadingMetadata(true);
    setRevision(null);
    setSavedFingerprint(null);
    void Promise.all([
      refreshMetadata(songId),
      fetch(`${API}/api/engines`).then(async (response) => {
        if (!response.ok) return;
        const engines = await response.json();
        if (activeSongId.current === songId) {
          setUsageMode(engines.usage_mode === "commercial" ? "commercial" : "personal");
        }
      }),
    ]).catch((error) => {
      if (activeSongId.current === songId) setMessage(String(error));
    }).finally(() => {
      if (activeSongId.current === songId) setLoadingMetadata(false);
    });
  }, [open, target?.songId]);

  const saveMetadata = async (): Promise<boolean> => {
    if (!target || revision === null || loadingMetadata || busy || identifying) return false;
    if (!isDirty) return true;
    if (!title.trim()) {
      setMessage("곡명을 입력한 후 저장하세요.");
      return false;
    }
    const songId = target.songId;
    setSavingMetadata(true);
    try {
      const response = await fetch(`${API}/api/songs/${songId}/credits`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: title.trim(),
          artist: artist.trim() || null,
          expected_revision: revision,
          ...credits,
        }),
      });
      if (!response.ok) {
        if (response.status === 409) {
          throw new Error("다른 수정 사항이 저장되었습니다. 곡 정보를 새로고침한 뒤 다시 시도하세요.");
        }
        throw new Error(await response.text());
      }
      if (activeSongId.current !== songId) return false;
      await refreshMetadata(songId);
      setReport(null);
      notifySongChanged(songId);
      setMessage("곡 제목·아티스트·앨범·작사·작곡 정보를 악보에 저장했습니다.");
      return true;
    } catch (error) {
      if (activeSongId.current === songId) {
        setMessage(error instanceof Error ? error.message : String(error));
      }
      return false;
    } finally {
      setSavingMetadata(false);
    }
  };

  const identifyOriginal = async () => {
    if (!target) return;
    if (isDirty) {
      setMessage("입력한 메타데이터를 먼저 저장한 다음 원본 식별을 실행하세요.");
      return;
    }
    setIdentifying(true);
    setMessage("");
    setIdentification(null);
    try {
      const response = await fetch(`${API}/api/songs/${target.songId}/identify-source`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          refresh: true,
          apply_high_confidence_metadata: true,
          musicbrainz_commercial_entitlement: commercialEntitlement,
          acoustid_commercial_entitlement: acoustidCommercialEntitlement,
        }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail ?? "원본 음원을 식별하지 못했습니다.");
      setIdentification(body);
      if (body.applied) {
        notifySongChanged(target.songId);
        setMessage("원본 음원을 식별해 신뢰도가 높은 곡 정보를 반영했습니다.");
        await refreshMetadata(target.songId);
      } else if (body.selected) {
        setMessage("원본 음원 식별 후보를 찾았지만 자동 적용 기준을 넘지 않았습니다.");
      } else {
        setMessage("원본 음원에서 신뢰할 수 있는 식별 결과를 찾지 못했습니다.");
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setIdentifying(false);
    }
  };

  const run = async () => {
    if (!target) return;
    if (!title.trim() || title.trim().toLowerCase() === "unknown"
        || !artist.trim() || artist.trim().toLowerCase() === "unknown") {
      setMessage("정확한 곡 제목과 아티스트를 입력하면 다시 조회할 수 있습니다.");
      return;
    }
    // Save before requery so title/artist and all user-edited publication
    // credits are canonical. Verified API matches can only fill missing
    // or auto-generated Unknown fields, not overwrite manual credits.
    if (isDirty && !(await saveMetadata())) return;
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
          require_exact_match: true,
          musicbrainz_commercial_entitlement: commercialEntitlement,
          lyrics_provider_name: advanced && lyricsProvider ? lyricsProvider : null,
          lyrics_url_template: advanced && lyricsUrl ? lyricsUrl : null,
          lyrics_api_key_env: advanced && lyricsKeyEnv ? lyricsKeyEnv : null,
          apply_reference_lyrics: applyReferenceLyrics,
          auto_lyrics: true,
        }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail ?? "외부 정보를 조회하지 못했습니다.");
      setReport(body);
      if (body.metadata?.applied || body.lyric_application?.applied) {
        await refreshMetadata(target.songId);
        notifySongChanged(target.songId);
      }
      if (body.lyric_application?.applied) setMessage("메타데이터를 확인하고 외부 가사를 WhisperX 타이밍에 맞춰 악보에 반영했습니다.");
      else if (body.metadata?.applied) setMessage("신뢰도가 높은 메타데이터를 곡 정보에 반영했습니다.");
      else if (body.lyrics_source === "whisperx") setMessage("외부 가사를 확인하지 못해 기존 WhisperX 음성 인식 가사를 유지했습니다.");
      else if (body.lyrics_source === "external_api") setMessage("외부 가사를 확보했습니다. WhisperX 시간 정보가 있으면 악보에 정렬합니다.");
      else setMessage("확인 가능한 곡 정보와 가사를 찾지 못했습니다. 수동 편집 또는 WhisperX 구성을 확인하세요.");
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
            <header><div><span>DATA ENRICHMENT</span><h2>곡 정보 보강</h2><p>외부 네트워크 조회는 이 화면에서 사용자가 실행할 때만 시작됩니다.</p></div><button type="button" aria-label="곡 정보 보강 닫기" onClick={() => setOpen(false)}>×</button></header>
            <div className="enrichment-policy"><strong>MusicBrainz 앨범·작사·작곡 / 가사 API 우선 / WhisperX 대체</strong><p>이 버튼을 실행할 때 MusicBrainz의 확인된 관계 정보와 개인용 LRCLIB 가사를 조회합니다. API 조회 실패 시 기존 WhisperX 가사를 유지합니다. 앱이 음원 파일 자체를 외부에 업로드하지는 않습니다.</p></div>
            {usageMode === "commercial" && <><label className="enrichment-commercial-check"><input type="checkbox" checked={commercialEntitlement} onChange={(event) => setCommercialEntitlement(event.target.checked)} /><span>MusicBrainz Web Service의 상용 이용 자격/계약을 확인했습니다.</span></label><label className="enrichment-commercial-check"><input type="checkbox" checked={acoustidCommercialEntitlement} onChange={(event) => setAcoustidCommercialEntitlement(event.target.checked)} /><span>AcoustID 서비스의 상용 이용 자격/계약을 확인했습니다.</span></label></>}
            <button className="enrichment-run" type="button" disabled={identifying || busy || savingMetadata || loadingMetadata} onClick={() => void identifyOriginal()}>{identifying ? "원본 식별 중…" : "원본 음원 자동 식별"}</button>
            {usageMode === "commercial" && (
              <small className="enrichment-identification-scope" role="status">
                로컬 음원 태그 식별은 외부 서비스 권한 없이 사용할 수 있습니다. MusicBrainz·AcoustID는 각각 상용 이용 자격을 확인한 경우에만 조회합니다.
              </small>
            )}
            {identification?.selected && <div className="enrichment-message"><strong>{identification.selected.title ?? "제목 미상"}</strong>{identification.selected.artist ? ` · ${identification.selected.artist}` : ""}{typeof identification.selected_confidence === "number" ? ` · ${Math.round(identification.selected_confidence * 100)}%` : ""}</div>}
            <div className="enrichment-fields">
              <label><span>곡명</span><input value={title} disabled={loadingMetadata || busy || savingMetadata} onChange={(event) => setTitle(event.target.value)} placeholder="정확한 곡 제목" /></label>
              <label><span>아티스트</span><input value={artist} disabled={loadingMetadata || busy || savingMetadata} onChange={(event) => setArtist(event.target.value)} placeholder="정확한 가수·밴드명" /></label>
            </div>
            <div className="enrichment-fields metadata-credit-fields">
              {creditLabels.map(({ key, label }) => (
                <label key={key}><span>{label}</span>
                  <input value={credits[key]} disabled={loadingMetadata || busy || savingMetadata}
                    onChange={(event) => setCredits((current) => ({ ...current, [key]: event.target.value }))}
                    placeholder="Unknown이면 직접 입력" />
                </label>
              ))}
            </div>
            <div className="metadata-editor-actions">
              <button className="enrichment-save" type="button"
                disabled={loadingMetadata || busy || identifying || savingMetadata || revision === null || !isDirty || !title.trim()}
                onClick={() => void saveMetadata()}>
                {savingMetadata ? "저장 중…" : "메타데이터 저장"}
              </button>
              <small>저장한 내용은 악보 첫 페이지에 반영되고 Undo가 가능합니다. 외부 조회는 곡명·아티스트가 필요하며 확인된 누락 정보만 채웁니다.</small>
            </div>
            <label className="enrichment-reference-check"><input type="checkbox" checked={applyReferenceLyrics} onChange={(event) => setApplyReferenceLyrics(event.target.checked)} /><span><strong>외부 가사를 악보에 반영</strong><small>원문은 API에서 가져오고 단어별 시점은 WhisperX의 음성 정렬을 사용합니다. 없으면 API 원문만 보존합니다.</small></span></label>
            <button className="enrichment-advanced-toggle" type="button" onClick={() => setAdvanced((value) => !value)}>{advanced ? "별도 가사 API 설정 닫기" : "선택 사항 · 별도 가사 API 연결"}</button>
            {advanced && <div className="enrichment-fields advanced"><label><span>Provider 이름</span><input value={lyricsProvider} onChange={(event) => setLyricsProvider(event.target.value)} placeholder="예: licensed-lyrics" /></label><label><span>HTTPS URL template</span><input value={lyricsUrl} onChange={(event) => setLyricsUrl(event.target.value)} placeholder="https://api.example/lyrics?artist={artist}&title={title}" /></label><label><span>API key 환경변수명</span><input value={lyricsKeyEnv} onChange={(event) => setLyricsKeyEnv(event.target.value)} placeholder="LYRICS_API_KEY" /></label></div>}
            <button className="enrichment-run" type="button" disabled={busy || identifying || savingMetadata || loadingMetadata || !title.trim()} onClick={() => void run()}>{busy ? "조회 중…" : "곡 정보·가사 자동 조회"}</button>
            {message && <div className="enrichment-message" role="status">{message}</div>}
            {report && <div className="enrichment-results">{report.metadata.error && <p>MusicBrainz 조회 오류: {report.metadata.error}</p>}{report.metadata.candidates.map((item, index) => <article key={item.recording_mbid ?? index} className={report.metadata.selected?.recording_mbid === item.recording_mbid ? "selected" : ""}><div><strong>{item.title ?? "제목 없음"}</strong><span>{item.score}% match</span></div><p>{item.artist ?? "아티스트 미상"}{item.album ? ` · 앨범: ${item.album}` : ""}{item.composer ? ` · 작곡: ${item.composer}` : ""}{item.lyricist ? ` · 작사: ${item.lyricist}` : ""}{item.first_release_date ? ` · ${item.first_release_date}` : ""}</p>{item.recording_mbid && <small>MBID {item.recording_mbid}</small>}</article>)}{report.lyrics && <div className="enrichment-lyrics"><strong>가사 provider: {report.lyrics.provider}</strong><span>{report.lyrics.synced ? "동기화 가사" : "일반 가사"}를 provenance와 함께 확보했습니다.</span>{report.lyric_application?.applied && <span>악보 적용 완료 · {report.lyric_application.attached_tokens ?? 0} tokens</span>}{report.lyric_application && !report.lyric_application.applied && <span>악보 미적용: {report.lyric_application.reason}</span>}</div>}{report.lyrics_source === "whisperx" && <small>가사: 외부 API 대신 WhisperX 음성 인식 결과 사용</small>}{report.lyrics_source === "unavailable" && <small>가사: 외부 API와 WhisperX 결과 없음</small>}{report.lyrics_error && <small>가사 API: {report.lyrics_error}</small>}</div>}
          </section>
        </div>
      )}
    </>
  );
}
