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

type ScoreData = {
  song: Song;
  title?: string | null;
  parts: { part_id: string; name: string; measures: number; notes: number }[];
  notes: NoteRow[];
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
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(null);
  const [partFilter, setPartFilter] = useState("all");
  const [measureFilter, setMeasureFilter] = useState("");
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [noteStep, setNoteStep] = useState("C");
  const [noteAlter, setNoteAlter] = useState("0");
  const [noteOctave, setNoteOctave] = useState("4");
  const [noteLyric, setNoteLyric] = useState("");
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
    const [songResponse, notesResponse, scoreResponse] = await Promise.all([
      fetch(`${API}/api/songs/${songId}`),
      fetch(`${API}/api/songs/${songId}/notes`),
      fetch(`${API}/api/songs/${songId}/score`),
    ]);
    if (!songResponse.ok || !notesResponse.ok || !scoreResponse.ok) {
      throw new Error("곡 작업공간을 불러오지 못했습니다.");
    }
    const nextSong: Song = await songResponse.json();
    const nextScore: ScoreData = await notesResponse.json();
    const nextXml = await scoreResponse.text();
    setSong(nextSong);
    setScore(nextScore);
    setXml(nextXml);
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
    void osmd.load(xml).then(() => {
      if (!cancelled) osmd.render();
    }).catch((error) => {
      if (!cancelled) setMessage(`악보 미리보기 오류: ${String(error)}`);
    });
    return () => { cancelled = true; };
  }, [xml]);

  const selectedNote = useMemo(
    () => score?.notes.find((note) => note.note_id === selectedNoteId) ?? null,
    [score, selectedNoteId],
  );

  useEffect(() => {
    if (!selectedNote) return;
    setNoteStep(selectedNote.step ?? "C");
    setNoteAlter(String(selectedNote.alter ?? 0));
    setNoteOctave(String(selectedNote.octave ?? 4));
    setNoteLyric(selectedNote.lyric ?? "");
  }, [selectedNote]);

  const filteredNotes = useMemo(() => {
    if (!score) return [];
    return score.notes.filter((note) => {
      if (partFilter !== "all" && note.part_id !== partFilter) return false;
      if (measureFilter && note.measure !== measureFilter.trim()) return false;
      return true;
    });
  }, [score, partFilter, measureFilter]);

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
      setMessage("곡 정보를 저장했습니다.");
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

  return (
    <main className="song-shell">
      <header className="song-header">
        <div>
          <div className="eyebrow">SONG WORKSPACE</div>
          <h1>곡 라이브러리</h1>
          <p>채보 결과를 곡 단위로 보관하고, MusicXML을 미리보며 수정한 뒤 내보냅니다.</p>
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
                  <button className="secondary" disabled={busy || song.revision <= 1} onClick={() => void postAction("undo")}>이전 수정 취소</button>
                  <button className="secondary" disabled={busy} onClick={() => void postAction("restore")}>원본 복원</button>
                  <button className="run-button export-button" disabled={busy} onClick={() => void postAction("export")}>현재 악보 내보내기</button>
                </div>
              </div>
              <div className="export-links">
                <a href={`${API}/api/songs/${song.song_id}/files/musicxml`} target="_blank">MusicXML</a>
                {song.exports.pdf && <a href={`${API}/api/songs/${song.song_id}/files/pdf`} target="_blank">PDF</a>}
                {song.exports.midi && <a href={`${API}/api/songs/${song.song_id}/files/midi`} target="_blank">MIDI</a>}
              </div>
              <div className="score-canvas" ref={scoreRef} />
            </>
          )}
        </section>

        <aside className="score-inspector card">
          <span className="eyebrow">INSPECTOR</span>
          {song && (
            <>
              <div className="metadata-editor">
                <label><span>곡 제목</span><input value={title} onChange={(e) => setTitle(e.target.value)} /></label>
                <label><span>아티스트 / 메모</span><input value={artist} onChange={(e) => setArtist(e.target.value)} /></label>
                <button className="secondary" disabled={busy} onClick={() => void saveMetadata()}>곡 정보 저장</button>
              </div>

              <div className="inspector-divider" />
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

              <div className="note-list">
                {filteredNotes.slice(0, 500).map((note) => (
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
          {message && <p className="workspace-message">{message}</p>}
        </aside>
      </section>
    </main>
  );
}
