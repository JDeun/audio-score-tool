import { useEffect, useMemo, useRef, useState } from "react";
import { OpenSheetMusicDisplay } from "opensheetmusicdisplay";

const API = "http://127.0.0.1:8080";

type Song = {
  song_id: string;
  job_id?: string;
  title: string;
  artist?: string | null;
  source_kind: string;
  revision: number;
  created_at?: string;
  updated_at?: string;
  exports: { pdf: boolean; midi: boolean; musicxml: boolean };
};

type NoteRow = {
  note_id: string;
  part_id: string;
  part_name: string;
  measure: string;
  voice?: string | null;
  staff?: string | null;
  rest: boolean;
  step?: string | null;
  alter?: number | null;
  octave?: number | null;
  duration?: number | null;
  type?: string | null;
  lyric: string;
};

type ChordRow = {
  note_id: string;
  part_id: string;
  part_name: string;
  measure: string;
  symbol: string;
};

type ScoreData = {
  song: Song;
  title?: string | null;
  parts: { part_id: string; name: string; measures: number; notes: number }[];
  notes: NoteRow[];
  chords: ChordRow[];
};

type PublicationSettings = {
  page_size: "A4" | "LETTER";
  orientation: "portrait" | "landscape";
  bars_per_system: number;
  systems_per_page: number;
  system_distance_mm: number;
  first_page_title_space_mm: number;
  top_margin_mm: number;
  bottom_margin_mm: number;
  left_margin_mm: number;
  right_margin_mm: number;
  title_font_size: number;
  subtitle_font_size: number;
  credit_font_size: number;
  subtitle: string;
  composer: string;
  lyricist: string;
  arranger: string;
  rights: string;
};

type InspectorTab = "note" | "chord" | "layout" | "credits";

const fallbackPublication: PublicationSettings = {
  page_size: "A4",
  orientation: "portrait",
  bars_per_system: 4,
  systems_per_page: 5,
  system_distance_mm: 10,
  first_page_title_space_mm: 34,
  top_margin_mm: 12,
  bottom_margin_mm: 12,
  left_margin_mm: 14,
  right_margin_mm: 14,
  title_font_size: 24,
  subtitle_font_size: 12,
  credit_font_size: 9.5,
  subtitle: "",
  composer: "",
  lyricist: "",
  arranger: "",
  rights: "",
};

function formatDate(value?: string) {
  if (!value) return "";
  return new Date(value).toLocaleString();
}

function pitchLabel(note: NoteRow) {
  if (note.rest) return "쉼표";
  const accidental = note.alter === 1 ? "♯" : note.alter === -1 ? "♭" : note.alter === 2 ? "𝄪" : note.alter === -2 ? "𝄫" : "";
  return `${note.step ?? "?"}${accidental}${note.octave ?? ""}`;
}

export default function SongWorkspace() {
  const [songs, setSongs] = useState<Song[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [song, setSong] = useState<Song | null>(null);
  const [score, setScore] = useState<ScoreData | null>(null);
  const [xml, setXml] = useState("");
  const [publication, setPublication] = useState<PublicationSettings>(fallbackPublication);
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("note");
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(null);
  const [partFilter, setPartFilter] = useState("all");
  const [measureFilter, setMeasureFilter] = useState("");
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [noteStep, setNoteStep] = useState("C");
  const [noteAlter, setNoteAlter] = useState("0");
  const [noteOctave, setNoteOctave] = useState("4");
  const [noteLyric, setNoteLyric] = useState("");
  const [chordSymbol, setChordSymbol] = useState("");
  const [previewZoom, setPreviewZoom] = useState(90);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const scoreRef = useRef<HTMLDivElement>(null);

  const refreshSongs = async () => {
    const response = await fetch(`${API}/api/songs`);
    if (!response.ok) throw new Error(await response.text());
    const body = await response.json();
    const next: Song[] = body.songs ?? [];
    setSongs(next);
    if (!selectedId && next.length) setSelectedId(next[0].song_id);
  };

  const loadSong = async (songId: string) => {
    const [songResponse, notesResponse, scoreResponse, publicationResponse] = await Promise.all([
      fetch(`${API}/api/songs/${songId}`),
      fetch(`${API}/api/songs/${songId}/notes`),
      fetch(`${API}/api/songs/${songId}/score`),
      fetch(`${API}/api/songs/${songId}/publication`),
    ]);
    if (!songResponse.ok || !notesResponse.ok || !scoreResponse.ok || !publicationResponse.ok) {
      throw new Error("곡 작업공간을 불러오지 못했습니다.");
    }
    const nextSong: Song = await songResponse.json();
    const nextScore: ScoreData = await notesResponse.json();
    const nextXml = await scoreResponse.text();
    const publicationBody = await publicationResponse.json();
    setSong(nextSong);
    setScore(nextScore);
    setXml(nextXml);
    setPublication({ ...fallbackPublication, ...(publicationBody.settings ?? {}) });
    setTitle(nextSong.title);
    setArtist(nextSong.artist ?? "");
    setSelectedNoteId((current) => current && nextScore.notes.some((n) => n.note_id === current) ? current : null);
  };

  useEffect(() => {
    void refreshSongs().catch((error) => setMessage(String(error)));
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    void loadSong(selectedId).catch((error) => setMessage(String(error)));
  }, [selectedId]);

  useEffect(() => {
    if (!xml || !scoreRef.current) return;
    let cancelled = false;
    const target = scoreRef.current;
    target.innerHTML = "";
    const osmd = new OpenSheetMusicDisplay(target, {
      autoResize: true,
      drawTitle: true,
      drawPartNames: true,
      backend: "svg",
    });
    osmd.Zoom = previewZoom / 100;
    void osmd.load(xml).then(() => {
      if (!cancelled) osmd.render();
    }).catch((error) => {
      if (!cancelled) setMessage(`악보 미리보기 오류: ${String(error)}`);
    });
    return () => { cancelled = true; };
  }, [xml, previewZoom]);

  const selectedNote = useMemo(
    () => score?.notes.find((note) => note.note_id === selectedNoteId) ?? null,
    [score, selectedNoteId],
  );

  const chordMap = useMemo(() => {
    const map = new Map<string, string>();
    score?.chords?.forEach((chord) => map.set(chord.note_id, chord.symbol));
    return map;
  }, [score]);

  useEffect(() => {
    if (!selectedNote) return;
    setNoteStep(selectedNote.step ?? "C");
    setNoteAlter(String(selectedNote.alter ?? 0));
    setNoteOctave(String(selectedNote.octave ?? 4));
    setNoteLyric(selectedNote.lyric ?? "");
    setChordSymbol(chordMap.get(selectedNote.note_id) ?? "");
  }, [selectedNote, chordMap]);

  const filteredNotes = useMemo(() => {
    if (!score) return [];
    return score.notes.filter((note) => {
      if (partFilter !== "all" && note.part_id !== partFilter) return false;
      if (measureFilter && note.measure !== measureFilter.trim()) return false;
      return true;
    });
  }, [score, partFilter, measureFilter]);

  const chordCandidates = useMemo(
    () => filteredNotes.filter((note) => !note.rest),
    [filteredNotes],
  );

  const reload = async () => {
    if (!selectedId) return;
    await Promise.all([loadSong(selectedId), refreshSongs()]);
  };

  const saveMetadata = async () => {
    if (!song) return;
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${API}/api/songs/${song.song_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, artist }),
      });
      if (!response.ok) throw new Error(await response.text());
      await reload();
      setMessage("곡 제목과 라이브러리 정보를 저장했습니다.");
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(false);
    }
  };

  const saveNote = async () => {
    if (!song || !selectedNote) return;
    setBusy(true);
    setMessage("");
    try {
      const body = selectedNote.rest ? { lyric: noteLyric } : {
        step: noteStep,
        alter: Number(noteAlter),
        octave: Number(noteOctave),
        lyric: noteLyric,
      };
      const response = await fetch(`${API}/api/songs/${song.song_id}/notes/${selectedNote.note_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(await response.text());
      await reload();
      setMessage(`${selectedNote.note_id} 수정 내용을 저장했습니다.`);
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(false);
    }
  };

  const saveChord = async (symbol = chordSymbol) => {
    if (!song || !selectedNote) return;
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${API}/api/songs/${song.song_id}/notes/${selectedNote.note_id}/chord`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol }),
      });
      if (!response.ok) throw new Error(await response.text());
      await reload();
      setMessage(symbol.trim() ? `${symbol} 코드를 악보에 표시했습니다.` : "선택 위치의 코드를 삭제했습니다.");
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(false);
    }
  };

  const savePublication = async (fields: Partial<PublicationSettings>, success: string) => {
    if (!song) return;
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${API}/api/songs/${song.song_id}/publication`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields),
      });
      if (!response.ok) throw new Error(await response.text());
      await reload();
      setMessage(success);
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(false);
    }
  };

  const saveCredits = async () => {
    await saveMetadata();
    await savePublication(
      {
        subtitle: publication.subtitle,
        composer: publication.composer,
        lyricist: publication.lyricist,
        arranger: publication.arranger,
        rights: publication.rights,
        title_font_size: publication.title_font_size,
        subtitle_font_size: publication.subtitle_font_size,
        credit_font_size: publication.credit_font_size,
      },
      "첫 페이지 제목과 크레딧 정보를 반영했습니다.",
    );
  };

  const saveLayout = async () => {
    await savePublication(
      {
        page_size: publication.page_size,
        orientation: publication.orientation,
        bars_per_system: publication.bars_per_system,
        systems_per_page: publication.systems_per_page,
        system_distance_mm: publication.system_distance_mm,
        first_page_title_space_mm: publication.first_page_title_space_mm,
        top_margin_mm: publication.top_margin_mm,
        bottom_margin_mm: publication.bottom_margin_mm,
        left_margin_mm: publication.left_margin_mm,
        right_margin_mm: publication.right_margin_mm,
      },
      "출판 레이아웃을 적용했습니다. 미리보기에서 페이지 조판을 확인하세요.",
    );
  };

  const postAction = async (action: "undo" | "restore" | "export") => {
    if (!song) return;
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${API}/api/songs/${song.song_id}/${action}`, { method: "POST" });
      if (!response.ok) throw new Error(await response.text());
      await reload();
      setMessage(action === "export" ? "현재 수정본으로 PDF/MIDI를 생성했습니다." : "악보를 갱신했습니다.");
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(false);
    }
  };

  const deleteSong = async () => {
    if (!song || !window.confirm(`‘${song.title}’을 곡 라이브러리에서 삭제할까요?`)) return;
    setBusy(true);
    try {
      const response = await fetch(`${API}/api/songs/${song.song_id}`, { method: "DELETE" });
      if (!response.ok) throw new Error(await response.text());
      setSelectedId(null);
      setSong(null);
      setScore(null);
      setXml("");
      await refreshSongs();
      setMessage("곡을 라이브러리에서 삭제했습니다. 원본 채보 Job은 History에 유지됩니다.");
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(false);
    }
  };

  const filters = (
    <div className="note-filter-grid">
      <label>
        <span>파트</span>
        <select value={partFilter} onChange={(e) => setPartFilter(e.target.value)}>
          <option value="all">전체</option>
          {score?.parts.map((part) => <option key={part.part_id} value={part.part_id}>{part.name}</option>)}
        </select>
      </label>
      <label><span>마디</span><input placeholder="예: 12" value={measureFilter} onChange={(e) => setMeasureFilter(e.target.value)} /></label>
    </div>
  );

  return (
    <main className="song-shell">
      <header className="song-header">
        <div>
          <div className="eyebrow">SCORE PUBLISHING WORKSPACE</div>
          <h1>곡 라이브러리</h1>
          <p>곡 단위로 채보를 보관하고, 노트·가사·코드·출판 조판을 수정한 뒤 최종 악보를 내보냅니다.</p>
        </div>
        <button className="secondary" onClick={() => void refreshSongs()}>새로고침</button>
      </header>

      <section className="song-layout">
        <aside className="song-library card">
          <div className="library-head">
            <div>
              <span className="eyebrow">LIBRARY</span>
              <strong>{songs.length}곡</strong>
            </div>
          </div>
          <div className="song-list">
            {songs.length === 0 && <p className="muted">완료된 채보가 아직 없습니다.</p>}
            {songs.map((item) => (
              <button
                key={item.song_id}
                className={`song-item ${selectedId === item.song_id ? "active" : ""}`}
                onClick={() => setSelectedId(item.song_id)}
              >
                <strong>{item.title}</strong>
                <span>{item.artist || (item.source_kind === "youtube" ? "YouTube" : "로컬 음원")}</span>
                <small>Revision {item.revision} · {formatDate(item.updated_at)}</small>
              </button>
            ))}
          </div>
        </aside>

        <section className="score-workbench card">
          {!song ? (
            <div className="empty-score">
              <span className="music-icon">♫</span>
              <h2>편집할 곡을 선택하세요</h2>
              <p className="muted">Transcribe에서 완료된 작업은 자동으로 곡 라이브러리에 등록됩니다.</p>
            </div>
          ) : (
            <>
              <div className="score-toolbar">
                <div>
                  <span className="eyebrow">CURRENT SCORE</span>
                  <h2>{song.title}</h2>
                  <span className="revision-pill">Revision {song.revision}</span>
                </div>
                <div className="score-actions">
                  <label className="zoom-control"><span>미리보기</span><input type="range" min="55" max="130" value={previewZoom} onChange={(e) => setPreviewZoom(Number(e.target.value))} /><strong>{previewZoom}%</strong></label>
                  <button className="secondary" disabled={busy || song.revision <= 1} onClick={() => void postAction("undo")}>실행 취소</button>
                  <button className="secondary" disabled={busy} onClick={() => void postAction("restore")}>원본 복원</button>
                  <button className="run-button export-button" disabled={busy} onClick={() => void postAction("export")}>최종 파일 생성</button>
                </div>
              </div>
              <div className="export-links">
                <span>현재 Revision</span>
                <a href={`${API}/api/songs/${song.song_id}/files/musicxml`} target="_blank">MusicXML</a>
                {song.exports.pdf && <a href={`${API}/api/songs/${song.song_id}/files/pdf`} target="_blank">PDF</a>}
                {song.exports.midi && <a href={`${API}/api/songs/${song.song_id}/files/midi`} target="_blank">MIDI</a>}
                {!song.exports.pdf && <small>수정 후 PDF/MIDI는 다시 생성해야 합니다.</small>}
              </div>
              <div className="score-canvas" ref={scoreRef} />
            </>
          )}
        </section>

        <aside className="score-inspector card">
          <div className="inspector-tabs">
            <button className={inspectorTab === "note" ? "active" : ""} onClick={() => setInspectorTab("note")}>노트</button>
            <button className={inspectorTab === "chord" ? "active" : ""} onClick={() => setInspectorTab("chord")}>코드</button>
            <button className={inspectorTab === "layout" ? "active" : ""} onClick={() => setInspectorTab("layout")}>레이아웃</button>
            <button className={inspectorTab === "credits" ? "active" : ""} onClick={() => setInspectorTab("credits")}>제목·정보</button>
          </div>

          {song && inspectorTab === "note" && (
            <>
              {filters}
              <div className="note-list">
                {filteredNotes.slice(0, 700).map((note) => (
                  <button
                    key={note.note_id}
                    className={selectedNoteId === note.note_id ? "active" : ""}
                    onClick={() => setSelectedNoteId(note.note_id)}
                  >
                    <span>M{note.measure}</span>
                    <strong>{pitchLabel(note)}</strong>
                    <small>{note.lyric || "—"}</small>
                  </button>
                ))}
              </div>
              {selectedNote && (
                <div className="note-editor">
                  <div className="note-editor-head">
                    <strong>{selectedNote.part_name} · M{selectedNote.measure}</strong>
                    <code>{selectedNote.note_id}</code>
                  </div>
                  {!selectedNote.rest && (
                    <div className="pitch-fields">
                      <label><span>음</span><select value={noteStep} onChange={(e) => setNoteStep(e.target.value)}>{["C","D","E","F","G","A","B"].map((v) => <option key={v}>{v}</option>)}</select></label>
                      <label><span>반음</span><select value={noteAlter} onChange={(e) => setNoteAlter(e.target.value)}><option value="-2">♭♭</option><option value="-1">♭</option><option value="0">♮</option><option value="1">♯</option><option value="2">♯♯</option></select></label>
                      <label><span>옥타브</span><input type="number" min="0" max="9" value={noteOctave} onChange={(e) => setNoteOctave(e.target.value)} /></label>
                    </div>
                  )}
                  <label className="lyric-field"><span>가사</span><input value={noteLyric} onChange={(e) => setNoteLyric(e.target.value)} placeholder="이 노트의 가사" /></label>
                  <div className="note-readonly">길이 {selectedNote.type ?? selectedNote.duration ?? "—"} · Voice {selectedNote.voice ?? "—"}</div>
                  <button className="run-button" disabled={busy} onClick={() => void saveNote()}>선택 노트 저장</button>
                </div>
              )}
            </>
          )}

          {song && inspectorTab === "chord" && (
            <>
              <div className="inspector-intro">
                <strong>코드 심벌</strong>
                <p>코드는 선택한 음표의 시점 위에 표시됩니다. 한 마디 안에서도 여러 코드 변화를 넣을 수 있습니다.</p>
              </div>
              {filters}
              <div className="note-list chord-note-list">
                {chordCandidates.slice(0, 700).map((note) => (
                  <button key={note.note_id} className={selectedNoteId === note.note_id ? "active" : ""} onClick={() => setSelectedNoteId(note.note_id)}>
                    <span>M{note.measure}</span>
                    <strong>{chordMap.get(note.note_id) || "·"}</strong>
                    <small>{pitchLabel(note)} {note.lyric || ""}</small>
                  </button>
                ))}
              </div>
              {selectedNote && !selectedNote.rest && (
                <div className="chord-editor note-editor">
                  <div className="note-editor-head"><strong>M{selectedNote.measure} · {pitchLabel(selectedNote)} 위치</strong><code>{selectedNote.note_id}</code></div>
                  <label className="lyric-field"><span>코드</span><input value={chordSymbol} onChange={(e) => setChordSymbol(e.target.value)} placeholder="예: Cmaj7, Am7, F#7, G/B" /></label>
                  <div className="chord-examples">C · Cm · C7 · Cmaj7 · Cm7 · Csus4 · Cdim7 · F♯m7 · B♭7 · G/B</div>
                  <div className="chord-actions"><button className="run-button" disabled={busy} onClick={() => void saveChord()}>코드 적용</button><button className="secondary" disabled={busy || !chordMap.get(selectedNote.note_id)} onClick={() => void saveChord("")}>코드 삭제</button></div>
                </div>
              )}
            </>
          )}

          {song && inspectorTab === "layout" && (
            <div className="publication-editor">
              <div className="inspector-intro"><strong>출판 레이아웃</strong><p>문서의 자간·행간처럼 악보 밀도와 페이지 조판을 조절합니다.</p></div>
              <div className="layout-two">
                <label><span>용지</span><select value={publication.page_size} onChange={(e) => setPublication((p) => ({ ...p, page_size: e.target.value as PublicationSettings["page_size"] }))}><option value="A4">A4</option><option value="LETTER">Letter</option></select></label>
                <label><span>방향</span><select value={publication.orientation} onChange={(e) => setPublication((p) => ({ ...p, orientation: e.target.value as PublicationSettings["orientation"] }))}><option value="portrait">세로</option><option value="landscape">가로</option></select></label>
              </div>
              <div className="layout-two">
                <label><span>한 줄당 마디</span><input type="number" min="1" max="12" value={publication.bars_per_system} onChange={(e) => setPublication((p) => ({ ...p, bars_per_system: Number(e.target.value) }))} /></label>
                <label><span>페이지당 악보 줄</span><input type="number" min="1" max="12" value={publication.systems_per_page} onChange={(e) => setPublication((p) => ({ ...p, systems_per_page: Number(e.target.value) }))} /></label>
              </div>
              <label className="range-field"><span>악보 줄 간격 <strong>{publication.system_distance_mm} mm</strong></span><input type="range" min="3" max="40" step="0.5" value={publication.system_distance_mm} onChange={(e) => setPublication((p) => ({ ...p, system_distance_mm: Number(e.target.value) }))} /></label>
              <label className="range-field"><span>첫 페이지 제목 영역 <strong>{publication.first_page_title_space_mm} mm</strong></span><input type="range" min="15" max="90" step="1" value={publication.first_page_title_space_mm} onChange={(e) => setPublication((p) => ({ ...p, first_page_title_space_mm: Number(e.target.value) }))} /></label>
              <div className="inspector-divider" />
              <span className="field-section-title">페이지 여백</span>
              <div className="margin-grid">
                {(["top_margin_mm", "bottom_margin_mm", "left_margin_mm", "right_margin_mm"] as const).map((key) => {
                  const labels = { top_margin_mm: "위", bottom_margin_mm: "아래", left_margin_mm: "왼쪽", right_margin_mm: "오른쪽" };
                  return <label key={key}><span>{labels[key]}</span><input type="number" min="5" max="40" step="0.5" value={publication[key]} onChange={(e) => setPublication((p) => ({ ...p, [key]: Number(e.target.value) }))} /></label>;
                })}
              </div>
              <div className="layout-summary">현재 설정: 한 줄 {publication.bars_per_system}마디 × 페이지당 {publication.systems_per_page}줄 = 약 {publication.bars_per_system * publication.systems_per_page}마디/페이지</div>
              <button className="run-button" disabled={busy} onClick={() => void saveLayout()}>조판 적용 및 미리보기</button>
            </div>
          )}

          {song && inspectorTab === "credits" && (
            <div className="publication-editor credits-editor">
              <div className="inspector-intro"><strong>첫 페이지 제목 영역</strong><p>상용 악보처럼 제목, 부제, 작사·작곡·편곡 및 저작권 정보를 배치합니다.</p></div>
              <label><span>곡 제목</span><input value={title} onChange={(e) => setTitle(e.target.value)} /></label>
              <label><span>부제 / 버전</span><input value={publication.subtitle} onChange={(e) => setPublication((p) => ({ ...p, subtitle: e.target.value }))} placeholder="예: Piano & Vocal / Original Key" /></label>
              <label><span>라이브러리 아티스트 / 메모</span><input value={artist} onChange={(e) => setArtist(e.target.value)} /></label>
              <div className="layout-two"><label><span>작곡</span><input value={publication.composer} onChange={(e) => setPublication((p) => ({ ...p, composer: e.target.value }))} /></label><label><span>작사</span><input value={publication.lyricist} onChange={(e) => setPublication((p) => ({ ...p, lyricist: e.target.value }))} /></label></div>
              <label><span>편곡</span><input value={publication.arranger} onChange={(e) => setPublication((p) => ({ ...p, arranger: e.target.value }))} /></label>
              <label><span>저작권 / 출처</span><textarea rows={3} value={publication.rights} onChange={(e) => setPublication((p) => ({ ...p, rights: e.target.value }))} placeholder="© 2026 ..." /></label>
              <div className="inspector-divider" />
              <span className="field-section-title">글자 크기</span>
              <div className="layout-three"><label><span>제목</span><input type="number" min="14" max="48" value={publication.title_font_size} onChange={(e) => setPublication((p) => ({ ...p, title_font_size: Number(e.target.value) }))} /></label><label><span>부제</span><input type="number" min="8" max="28" value={publication.subtitle_font_size} onChange={(e) => setPublication((p) => ({ ...p, subtitle_font_size: Number(e.target.value) }))} /></label><label><span>크레딧</span><input type="number" min="7" max="18" step="0.5" value={publication.credit_font_size} onChange={(e) => setPublication((p) => ({ ...p, credit_font_size: Number(e.target.value) }))} /></label></div>
              <button className="run-button" disabled={busy} onClick={() => void saveCredits()}>제목 영역 적용</button>
              <button className="delete-song-button" disabled={busy} onClick={() => void deleteSong()}>이 곡을 라이브러리에서 삭제</button>
            </div>
          )}

          {message && <p className="workspace-message">{message}</p>}
        </aside>
      </section>
    </main>
  );
}
