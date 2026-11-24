import { useEffect, useMemo, useRef, useState } from "react";
import { useSelectedSong } from "./SelectedSongContext";
import SourceAudioReview, { type AudioClip } from "./SourceAudioReview";
import PitchObservationPlot, { parsePitchObservation } from "./PitchObservationPlot";
import "./note-evidence.css";

const API = "http://127.0.0.1:8080";

type PartExport = {
  part_id: string;
  name: string;
  slug: string;
  pdf: boolean;
  musicxml: boolean;
};

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
  parts?: PartExport[];
};

type NoteType = "whole" | "half" | "quarter" | "eighth" | "16th" | "32nd" | "64th";

type NoteRow = {
  note_id: string;
  part_id: string;
  part_name: string;
  measure: string;
  measure_index: number;
  voice?: string | null;
  staff?: string | null;
  rest: boolean;
  step?: string | null;
  alter?: number | null;
  octave?: number | null;
  duration?: number | null;
  type?: NoteType | null;
  dots: number;
  lyric: string;
  ties: string[];
  slurs: string[];
  articulations: string[];
  beam?: string | null;
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
  score_sha256: string;
  evidence_generation: number | null;
  title?: string | null;
  parts: { part_id: string; name: string; measures: number; notes: number }[];
  notes: NoteRow[];
  chords: ChordRow[];
};

type RhythmStatus = {
  songId: string;
  noteId: string;
  revision: number;
  generation: number;
  scoreHash: string;
  message: string;
};

type RhythmOutcome = {
  id: number;
  noteId: string;
  revision: number;
  generation: number;
  scoreHash: string;
  result: { noteIds: unknown } | { error: string };
};

type StableNoteEdit = { noteId: string; selection: number; committedRevision: number | null };

type EvidenceSource = {
  source_id?: string;
  performed_seconds: { start: number; end: number };
  grid_seconds: { start: number; end: number };
  source_audio_seek_seconds: number | null;
  source_audio_seek_basis: string | null;
};
type NoteEvidence = {
  schema_version: 1 | 2;
  status: "linked" | "unavailable" | "ambiguous";
  revision: number;
  score_sha256: string;
  note_id: string;
  evidence_generation?: number;
  pitch_observations?: unknown;
  evidence: (Partial<EvidenceSource> & { sources?: EvidenceSource[];
    written_quarters?: { start: number; end: number } }) | null;
  patch?: object | null;
};

type MeasureRow = {
  measure_index: number;
  number: string;
  divisions: number;
  key_fifths: number;
  key_mode: "major" | "minor";
  beats: number;
  beat_type: number;
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
  album: string;
  performer: string;
  release_date: string;
  composer: string;
  lyricist: string;
  arranger: string;
  rights: string;
};

type InspectorTab = "note" | "chord" | "structure" | "layout" | "credits";

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
  album: "",
  performer: "",
  release_date: "",
  composer: "",
  lyricist: "",
  arranger: "",
  rights: "",
};

const noteTypes: { value: NoteType; label: string }[] = [
  { value: "whole", label: "온음표" },
  { value: "half", label: "2분음표" },
  { value: "quarter", label: "4분음표" },
  { value: "eighth", label: "8분음표" },
  { value: "16th", label: "16분음표" },
  { value: "32nd", label: "32분음표" },
  { value: "64th", label: "64분음표" },
];

const keyNames: Record<number, string> = {
  [-7]: "♭7",
  [-6]: "♭6",
  [-5]: "♭5",
  [-4]: "♭4",
  [-3]: "♭3",
  [-2]: "♭2",
  [-1]: "♭1",
  0: "조표 없음",
  1: "♯1",
  2: "♯2",
  3: "♯3",
  4: "♯4",
  5: "♯5",
  6: "♯6",
  7: "♯7",
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

function toggleValue(values: string[], value: string) {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

export default function SongWorkspace() {
  const { setTarget: setSelectedSong, songChange, openMetadataEditor,
    jobSongRequest, finishJobSongRequest, rhythmEdits, getRhythmEdit, beginRhythmEdit } = useSelectedSong();
  const [songs, setSongs] = useState<Song[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [song, setSong] = useState<Song | null>(null);
  const [score, setScore] = useState<ScoreData | null>(null);
  const [measures, setMeasures] = useState<MeasureRow[]>([]);
  const [xml, setXml] = useState("");
  const [publication, setPublication] = useState<PublicationSettings>(fallbackPublication);
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("note");
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(null);
  const [noteEvidence, setNoteEvidence] = useState<{ key: string; epoch: number; result?: NoteEvidence; message?: string; loading?: boolean } | null>(null);
  const [selectedClip, setSelectedClip] = useState<{ key: string; epoch: number; clip: AudioClip } | null>(null);
  const evidenceRequest = useRef<AbortController | null>(null);
  const evidenceEpoch = useRef(0);
  const evidenceKeyRef = useRef("");
  const evidenceKey = JSON.stringify([song?.song_id, selectedNoteId, score?.song.revision, score?.score_sha256, score?.evidence_generation]);
  if (evidenceKeyRef.current !== evidenceKey) {
    evidenceKeyRef.current = evidenceKey;
    evidenceEpoch.current += 1;
  }
  useEffect(() => {
    evidenceRequest.current?.abort();
    return () => { evidenceRequest.current?.abort(); };
  }, [evidenceKey]);
  const [partFilter, setPartFilter] = useState("all");
  const [measureFilter, setMeasureFilter] = useState("");
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [noteStep, setNoteStep] = useState("C");
  const [noteAlter, setNoteAlter] = useState("0");
  const [noteOctave, setNoteOctave] = useState("4");
  const [noteLyric, setNoteLyric] = useState("");
  const [noteType, setNoteType] = useState<NoteType>("quarter");
  const [leftType, setLeftType] = useState<NoteType>("eighth");
  const [leftDots, setLeftDots] = useState(0);
  const [rhythmStatus, setRhythmStatus] = useState<RhythmStatus | null>(null);
  const [rhythmSnapshotId, setRhythmSnapshotId] = useState<number | null>(null);
  const [scoreLoadFailed, setScoreLoadFailed] = useState(false);
  const rhythmOutcome = useRef<RhythmOutcome | null>(null);
  const rhythmSelection = useRef(0);
  const [noteDots, setNoteDots] = useState(0);
  const [noteRest, setNoteRest] = useState(false);
  const [noteArticulations, setNoteArticulations] = useState<string[]>([]);
  const [noteTies, setNoteTies] = useState<string[]>([]);
  const [noteSlurs, setNoteSlurs] = useState<string[]>([]);
  const [noteBeam, setNoteBeam] = useState("");
  const [insertPosition, setInsertPosition] = useState<"before" | "after">("after");
  const [chordSymbol, setChordSymbol] = useState("");
  const [selectedMeasureIndex, setSelectedMeasureIndex] = useState<number | null>(0);
  const [keyFifths, setKeyFifths] = useState(0);
  const [keyMode, setKeyMode] = useState<"major" | "minor">("major");
  const [beats, setBeats] = useState(4);
  const [beatType, setBeatType] = useState(4);
  const [previewZoom, setPreviewZoom] = useState(90);
  const [otherBusy, setBusy] = useState(false);
  const rhythmEdit = selectedId ? rhythmEdits.get(selectedId) : undefined;
  const rhythmBusy = rhythmEdit?.pending ?? false;
  const settledRhythmId = rhythmEdit?.settledId ?? null;
  const rhythmNeedsReload = rhythmSnapshotId !== settledRhythmId;
  const scoreLocked = rhythmBusy || rhythmNeedsReload || scoreLoadFailed;
  const busy = otherBusy || scoreLocked;
  const [message, setMessage] = useState("");
  const scoreRef = useRef<HTMLDivElement>(null);
  const activeSongId = useRef<string | null>(null);
  const loadVersion = useRef(0);
  const listVersion = useRef(0);
  const selectionResolved = useRef(false);
  const pendingNavigation = useRef(jobSongRequest);
  pendingNavigation.current = jobSongRequest;

  const selectSong = (nextId: string | null, finishNavigation = true) => {
    // Clicking the current list item must not clear its loaded score without
    // changing selectedId (which would leave no selection effect to reload it).
    if (nextId !== null && nextId === activeSongId.current) return;
    // Invalidate any pending response before React starts rendering the new song.
    activeSongId.current = nextId;
    rhythmSelection.current += 1;
    rhythmOutcome.current = null;
    setRhythmStatus(null);
    setRhythmSnapshotId(null);
    setScoreLoadFailed(false);
    loadVersion.current += 1;
    listVersion.current += 1;
    selectionResolved.current = nextId !== null;
    if (nextId) window.sessionStorage.setItem("ast-selected-song-id", nextId);
    else window.sessionStorage.removeItem("ast-selected-song-id");
    if (finishNavigation && pendingNavigation.current) {
      finishJobSongRequest(pendingNavigation.current.sequence);
      pendingNavigation.current = null;
    }
    setSelectedId(nextId);
    setSong(null);
    setScore(null);
    setMeasures([]);
    setXml("");
    setSelectedNoteId(null);
    setSelectedMeasureIndex(0);
    setMessage("");
  };

  const refreshSongs = async () => {
    const requestVersion = ++listVersion.current;
    const navigation = pendingNavigation.current;
    const response = await fetch(`${API}/api/songs`);
    if (requestVersion !== listVersion.current) return;
    if (!response.ok) throw new Error(await response.text());
    const body = await response.json();
    if (requestVersion !== listVersion.current) return;
    const next: Song[] = body.songs ?? [];
    setSongs(next);
    if (navigation) {
      if (pendingNavigation.current?.sequence !== navigation.sequence) return;
      const matchingSong = next.find((item) => item.job_id === navigation.jobId);
      selectSong(matchingSong?.song_id ?? null);
      // A missing/deleted result must never silently open an unrelated score.
      selectionResolved.current = true;
      if (!matchingSong) setMessage("이 작업의 악보를 찾을 수 없습니다. 삭제되었거나 아직 라이브러리에 등록되지 않았습니다.");
    } else if (!activeSongId.current && !selectionResolved.current && next.length) {
      const rememberedId = window.sessionStorage.getItem("ast-selected-song-id");
      selectSong(next.find((item) => item.song_id === rememberedId)?.song_id ?? next[0].song_id);
    }
  };

  const loadSong = async (songId: string, stableNoteEdit?: StableNoteEdit) => {
    if (activeSongId.current !== songId) return;
    const requestVersion = ++loadVersion.current;
    const editId = getRhythmEdit(songId)?.settledId ?? null;
    const current = () => requestVersion === loadVersion.current && activeSongId.current === songId
      && editId === (getRhythmEdit(songId)?.settledId ?? null);
    try {
      const responses = await Promise.all([
        fetch(`${API}/api/songs/${encodeURIComponent(songId)}`, { method: "GET", cache: "no-store" }),
        fetch(`${API}/api/songs/${encodeURIComponent(songId)}/notes`, { method: "GET", cache: "no-store" }),
        fetch(`${API}/api/songs/${encodeURIComponent(songId)}/structure`, { method: "GET", cache: "no-store" }),
        fetch(`${API}/api/songs/${encodeURIComponent(songId)}/score`, { method: "GET", cache: "no-store" }),
        fetch(`${API}/api/songs/${encodeURIComponent(songId)}/publication`, { method: "GET", cache: "no-store" }),
      ]);
      if (responses.some(response => !response.ok)) throw new Error("곡 작업공간을 불러오지 못했습니다.");
      const [songResponse, notesResponse, structureResponse, scoreResponse, publicationResponse] = responses;
      const [nextSong, nextScore, structureBody, scoreBytes, publicationBody]: [
        Song, ScoreData, { song: Song; score_sha256: string; measures: MeasureRow[] }, ArrayBuffer, { settings?: Partial<PublicationSettings> },
      ] = await Promise.all([songResponse.json(), notesResponse.json(), structureResponse.json(), scoreResponse.arrayBuffer(), publicationResponse.json()]);
      if (!current()) return;
      const digest = await crypto.subtle.digest("SHA-256", scoreBytes);
      const previewHash = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
      if (!current()) return;
      const hash = nextScore.score_sha256;
      if (nextSong.song_id !== songId || nextScore.song.song_id !== songId
          || nextSong.revision !== nextScore.song.revision
          || structureBody.song?.song_id !== songId || structureBody.song.revision !== nextSong.revision
          || structureBody.score_sha256 !== hash || previewHash !== hash) {
        throw new Error("악보를 불러오는 중 변경되었습니다.");
      }
      setScoreLoadFailed(false);
      if (scoreLoadFailed) setMessage("");
      setRhythmSnapshotId(editId);
      setSong(nextSong);
      setScore(nextScore);
      setMeasures(structureBody.measures ?? []);
      setXml(new TextDecoder().decode(scoreBytes));
      setPublication({ ...fallbackPublication, ...(publicationBody.settings ?? {}) });
      setTitle(nextSong.title);
      setArtist(nextSong.artist ?? "");

      const hasNote = (id: unknown): id is string => typeof id === "string" && nextScore.notes.some(note => note.note_id === id);
      if (editId === rhythmSnapshotId) {
        const snapshotChanged = score && (nextSong.revision !== score.song.revision
          || hash !== score.score_sha256 || nextScore.evidence_generation !== score.evidence_generation);
        if (snapshotChanged) {
          const noteId = stableNoteEdit && stableNoteEdit.selection === rhythmSelection.current
            && stableNoteEdit.committedRevision === nextSong.revision && nextSong.revision === score.song.revision + 1
            && score.evidence_generation != null && nextScore.evidence_generation === score.evidence_generation + 1
            && hasNote(stableNoteEdit.noteId) ? stableNoteEdit.noteId : null;
          setSelectedNoteId(noteId);
          if (!noteId) setSelectedMeasureIndex(null);
        } else {
          setSelectedNoteId(noteId => hasNote(noteId) ? noteId : null);
        }
        return nextScore;
      }

      const outcome = rhythmOutcome.current;
      rhythmOutcome.current = null;
      let noteId: string | null = null;
      let status = "";
      if (outcome?.id === editId) {
        if ("error" in outcome.result) {
          if (nextSong.revision === outcome.revision && nextScore.evidence_generation === outcome.generation
              && hash === outcome.scoreHash && hasNote(outcome.noteId)) {
            noteId = outcome.noteId;
            status = outcome.result.error;
          } else {
            setMessage(outcome.result.error);
          }
        } else if (nextSong.revision === outcome.revision + 1
            && nextScore.evidence_generation === outcome.generation + 1 && Array.isArray(outcome.result.noteIds)) {
          noteId = outcome.result.noteIds.find(hasNote) ?? null;
          status = "리듬 편집을 적용했습니다.";
        }
      }
      setSelectedNoteId(noteId);
      if (!noteId) setSelectedMeasureIndex(null);
      setRhythmStatus(noteId && nextScore.evidence_generation != null ? {
        songId, noteId, revision: nextSong.revision, generation: nextScore.evidence_generation, scoreHash: hash, message: status,
      } : null);
      return nextScore;
    } catch (error) {
      if (!current()) return;
      rhythmSelection.current += 1;
      rhythmOutcome.current = null;
      setSelectedNoteId(null);
      setSelectedMeasureIndex(null);
      setRhythmStatus(null);
      setScoreLoadFailed(true);
      throw error;
    }
  };

  useEffect(() => {
    if (jobSongRequest) selectSong(null, false);
    let cancelled = false;
    void refreshSongs().catch((error) => {
      if (!cancelled) setMessage(String(error));
    });
    return () => {
      cancelled = true;
      listVersion.current += 1;
    };
  }, [jobSongRequest?.sequence]);

  useEffect(() => {
    if (!selectedId) return;
    const load = settledRhythmId ? reload() : loadSong(selectedId);
    void load.catch((error) => {
      if (activeSongId.current === selectedId) setMessage(String(error));
    });
  }, [selectedId, settledRhythmId]);

  useEffect(() => {
    const current = song?.song_id === selectedId ? song : null;
    setSelectedSong(current ? { songId: current.song_id, title: current.title } : null);
    return () => setSelectedSong(null);
  }, [selectedId, song?.song_id, song?.title, setSelectedSong]);

  useEffect(() => () => {
    activeSongId.current = null;
    loadVersion.current += 1;
    listVersion.current += 1;
  }, []);

  useEffect(() => {
    if (!xml || !scoreRef.current) return;
    let cancelled = false;
    const target = scoreRef.current;
    target.innerHTML = "";

    void (async () => {
      try {
        const { OpenSheetMusicDisplay } = await import("opensheetmusicdisplay");
        if (cancelled) return;
        const osmd = new OpenSheetMusicDisplay(target, {
          autoResize: true,
          drawTitle: true,
          drawPartNames: true,
          backend: "svg",
        });
        osmd.Zoom = previewZoom / 100;
        await osmd.load(xml);
        if (!cancelled) osmd.render();
      } catch (error) {
        if (!cancelled) setMessage(`악보 미리보기 오류: ${String(error)}`);
      }
    })();

    return () => { cancelled = true; };
  }, [xml, previewZoom]);

  const selectedNote = useMemo(
    () => score?.notes.find((note) => note.note_id === selectedNoteId) ?? null,
    [score, selectedNoteId],
  );

  const visibleEvidence = noteEvidence?.key === evidenceKey && noteEvidence.epoch === evidenceEpoch.current ? noteEvidence : null;
  const evidenceSources = useMemo(() => {
    const result = visibleEvidence?.result;
    if (result?.status !== "linked" || !result.evidence) return [];
    return result.schema_version === 2 ? result.evidence.sources ?? [] : [result.evidence as EvidenceSource];
  }, [visibleEvidence]);
  const verifiedClips = useMemo(() => evidenceSources.map((evidence): AudioClip | null => {
    const seek = evidence.source_audio_seek_seconds;
    const grid = evidence.grid_seconds;
    if (typeof seek !== "number" || !Number.isFinite(seek) || seek < 0 || !grid
        || !Number.isFinite(grid.start) || !Number.isFinite(grid.end)
        || evidence.source_audio_seek_basis !== "interpreted_grid" || seek !== grid.start || grid.end <= seek) return null;
    return { start_seconds: seek, end_seconds: grid.end };
  }), [evidenceSources]);
  const pitchObservation = useMemo(() => parsePitchObservation(visibleEvidence?.result?.pitch_observations,
    visibleEvidence?.result?.evidence_generation, score?.evidence_generation ?? null,
    evidenceSources.map(source => source.source_id)), [visibleEvidence, score?.evidence_generation, evidenceSources]);
  const pitchClasses: Record<string, number> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
  const writtenMidiCandidate = selectedNote && !selectedNote.rest && selectedNote.step != null
    && pitchClasses[selectedNote.step] !== undefined && Number.isFinite(selectedNote.octave)
    && Number.isFinite(selectedNote.alter ?? 0)
    ? (selectedNote.octave! + 1) * 12 + pitchClasses[selectedNote.step] + (selectedNote.alter ?? 0) : null;
  const writtenMidi = writtenMidiCandidate !== null && Number.isFinite(writtenMidiCandidate)
    && writtenMidiCandidate >= 0 && writtenMidiCandidate <= 127 ? writtenMidiCandidate : null;
  const sourceClip = selectedClip?.key === evidenceKey && selectedClip.epoch === evidenceEpoch.current
    ? selectedClip.clip : null;

  const loadNoteEvidence = async () => {
    if (!song || !score || !selectedNote || scoreLocked || score.evidence_generation == null) return;
    evidenceRequest.current?.abort();
    const controller = new AbortController();
    evidenceRequest.current = controller;
    const epoch = ++evidenceEpoch.current;
    const key = evidenceKey;
    setNoteEvidence({ key, epoch, loading: true });
    const query = new URLSearchParams({ expected_revision: String(score.song.revision),
      expected_score_sha256: score.score_sha256, expected_generation: String(score.evidence_generation),
      include_pitch_observations: "true" });
    try {
      const response = await fetch(`${API}/api/songs/${encodeURIComponent(song.song_id)}/notes/${encodeURIComponent(selectedNote.note_id)}/evidence?${query}`, { method: "GET", signal: controller.signal });
      if (response.status === 409) throw new Error("악보가 변경되었습니다. 새로고침 후 다시 확인하세요.");
      if (!response.ok) throw new Error("모델 근거를 불러오지 못했습니다. 다시 시도하세요.");
      const result: NoteEvidence = await response.json();
      if (result.note_id !== selectedNote.note_id || result.revision !== score.song.revision || result.score_sha256 !== score.score_sha256) throw new Error("악보가 변경되었습니다. 새로고침 후 다시 확인하세요.");
      if (result.status === "linked" && result.evidence) {
        if (result.schema_version !== 1 && result.schema_version !== 2) throw new Error("지원하지 않는 모델 근거 형식입니다.");
        const sources = result.schema_version === 2 ? result.evidence.sources : [result.evidence];
        const written = result.evidence.written_quarters;
        if (!sources?.length || (result.schema_version === 2 && (!written || !Number.isFinite(written.start)
            || !Number.isFinite(written.end) || written.start < 0 || written.end <= written.start))
            || sources.some(source => !source.performed_seconds || !source.grid_seconds
              || !Number.isFinite(source.performed_seconds.start) || !Number.isFinite(source.performed_seconds.end)
              || source.performed_seconds.start < 0 || source.performed_seconds.end <= source.performed_seconds.start
              || !Number.isFinite(source.grid_seconds.start) || !Number.isFinite(source.grid_seconds.end)
              || source.grid_seconds.start < 0 || source.grid_seconds.end <= source.grid_seconds.start)) {
          throw new Error("모델 근거의 시간 정보를 확인할 수 없습니다.");
        }
      }
      if (!controller.signal.aborted && epoch === evidenceEpoch.current && key === evidenceKeyRef.current) setNoteEvidence({ key, epoch, result });
    } catch (error) {
      if (!controller.signal.aborted && epoch === evidenceEpoch.current && key === evidenceKeyRef.current) setNoteEvidence({ key, epoch, message: error instanceof Error ? error.message : "모델 근거를 불러오지 못했습니다. 다시 시도하세요." });
    }
  };

  const unresolvedMetadata = Boolean(
    song && [
      song.title,
      song.artist,
      publication.album,
      publication.performer,
      publication.composer,
      publication.lyricist,
      publication.release_date,
    ].some((value) => (value ?? "").trim().toLowerCase() === "unknown")
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
    setNoteType(selectedNote.type ?? "quarter");
    setNoteDots(selectedNote.dots ?? 0);
    setNoteRest(selectedNote.rest);
    setNoteArticulations(selectedNote.articulations ?? []);
    setNoteTies(selectedNote.ties ?? []);
    setNoteSlurs(selectedNote.slurs ?? []);
    setNoteBeam(selectedNote.beam ?? "");
    setChordSymbol(chordMap.get(selectedNote.note_id) ?? "");
    setSelectedMeasureIndex(selectedNote.measure_index ?? 0);
  }, [selectedNote, chordMap]);

  useEffect(() => {
    const measure = measures.find((item) => item.measure_index === selectedMeasureIndex);
    if (!measure) return;
    setKeyFifths(measure.key_fifths);
    setKeyMode(measure.key_mode);
    setBeats(measure.beats);
    setBeatType(measure.beat_type);
  }, [measures, selectedMeasureIndex]);

  const filteredNotes = useMemo(() => {
    if (!score) return [];
    return score.notes.filter((note) => {
      if (partFilter !== "all" && note.part_id !== partFilter) return false;
      if (measureFilter && note.measure !== measureFilter.trim()) return false;
      return true;
    });
  }, [score, partFilter, measureFilter]);

  const reload = async (stableNoteEdit?: StableNoteEdit) => {
    if (!selectedId) return;
    const [updated] = await Promise.all([loadSong(selectedId, stableNoteEdit), refreshSongs()]);
    return updated;
  };

  const refreshScore = () => {
    setMessage("");
    void reload().catch((error) => {
      if (activeSongId.current === selectedId) setMessage(String(error));
    });
  };

  const nextRhythmNote = useMemo(() => {
    if (!score || !selectedNote) return null;
    const index = score.notes.findIndex(note => note.note_id === selectedNote.note_id);
    const next = score.notes[index + 1];
    return next && next.part_id === selectedNote.part_id && next.measure_index === selectedNote.measure_index ? next : null;
  }, [score, selectedNote]);

  const chooseNote = (noteId: string) => {
    if (busy) return;
    rhythmSelection.current += 1;
    setRhythmStatus(null);
    setSelectedNoteId(noteId);
  };

  const editRhythm = async (action: "split" | "merge" | "boundary" | "delete") => {
    if (!song || !score || !selectedNote || score.evidence_generation == null || busy) return;
    if ((action === "merge" || action === "boundary") && !nextRhythmNote) return;
    const songId = song.song_id;
    const attempt = beginRhythmEdit(songId);
    if (!attempt) return;
    const noteId = selectedNote.note_id;
    const revision = score.song.revision;
    const generation = score.evidence_generation;
    const selection = rhythmSelection.current;
    const noteIds = [noteId, ...((action === "merge" || action === "boundary") ? [nextRhythmNote!.note_id] : [])];
    evidenceRequest.current?.abort();
    evidenceEpoch.current += 1;
    setNoteEvidence(null);
    setRhythmStatus(null);
    let result: RhythmOutcome["result"];
    try {
      const body = { action, note_ids: noteIds, expected_revision: revision,
        expected_score_sha256: score.score_sha256, expected_generation: generation,
        ...((action === "split" || action === "boundary") ? { left_note_type: leftType, left_dots: leftDots } : {}) };
      const response = await fetch(`${API}/api/songs/${encodeURIComponent(songId)}/notes/rhythm-edit`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      if (response.status === 409) throw new Error("악보가 변경되었습니다. 악보 새로고침 후 다시 시도하세요.");
      if (!response.ok) {
        const detail = await response.json().catch(() => null);
        throw new Error(response.status === 422 && typeof detail?.detail === "string"
          ? `리듬 편집을 적용할 수 없습니다: ${detail.detail}` : "리듬 편집을 적용할 수 없습니다.");
      }
      const bodyResult = await response.json();
      result = { noteIds: bodyResult.result?.result_note_ids };
    } catch (error) {
      result = { error: error instanceof Error ? error.message : "리듬 편집을 적용할 수 없습니다." };
    }
    if (selection === rhythmSelection.current && activeSongId.current === songId) {
      rhythmOutcome.current = { id: attempt.id, noteId, revision, generation, scoreHash: score.score_sha256, result };
    }
    attempt.settle();
  };

  useEffect(() => {
    // Auxiliary controllers mutate the same canonical Song through their own APIs.
    // Reload both the score editor and song list after a confirmed mutation;
    // never allow a late notice for a different song to change the selection.
    if (!songChange || songChange.songId !== activeSongId.current) return;
    void reload().catch((error) => {
      if (activeSongId.current === songChange.songId) setMessage(String(error));
    });
  }, [songChange]);

  const withBusy = async (operation: () => Promise<void>) => {
    const edit = selectedId ? getRhythmEdit(selectedId) : undefined;
    if (busy || edit?.pending || rhythmSnapshotId !== (edit?.settledId ?? null)) return;
    setBusy(true);
    setMessage("");
    try {
      await operation();
    } catch (error) {
      if (activeSongId.current === selectedId) setMessage(String(error));
    } finally {
      setBusy(false);
    }
  };

  const scoreStamp = score && {
    expected_revision: score.song.revision,
    expected_score_sha256: score.score_sha256,
    ...(score.evidence_generation == null ? {} : { expected_generation: score.evidence_generation }),
  };
  const scoreQuery = scoreStamp && new URLSearchParams(
    Object.entries(scoreStamp).map(([key, value]) => [key, String(value)]),
  );

  const checkPositionalEdit = async (response: Response) => {
    if (response.status === 409) {
      if (activeSongId.current === selectedId) {
        setSelectedNoteId(null);
        setSelectedMeasureIndex(null);
        await reload();
      }
      throw new Error("악보가 변경되었습니다. 음표나 마디를 다시 선택하세요.");
    }
    if (!response.ok) throw new Error(await response.text());
  };

  const reloadStableNoteEdit = async (response: Response, noteId: string, selection: number) => {
    await checkPositionalEdit(response);
    const receipt = await response.json().catch(() => null);
    const revision: unknown = receipt?.song?.revision;
    const committedRevision = receipt?.song?.song_id === selectedId && typeof revision === "number" ? revision : null;
    await reload({ noteId, selection, committedRevision });
  };

  const saveNote = async () => {
    if (!song || !selectedNote || !scoreStamp) return;
    const selection = rhythmSelection.current;
    await withBusy(async () => {
      // A sparse patch represents the *actual* changed correction dimensions.
      // Sending the entire inspector form on every save incorrectly inflated
      // lyric corrections and created empty revisions.
      const body: Record<string, unknown> = {};
      const changedList = (current: string[], original?: string[]) =>
        current.length !== (original ?? []).length ||
        current.some((value, index) => value !== (original ?? [])[index]);

      if (noteRest !== selectedNote.rest) body.rest = noteRest;
      if (!noteRest) {
        if (selectedNote.rest || noteStep !== (selectedNote.step ?? "C")) body.step = noteStep;
        if (selectedNote.rest || Number(noteAlter) !== (selectedNote.alter ?? 0)) body.alter = Number(noteAlter);
        if (selectedNote.rest || Number(noteOctave) !== (selectedNote.octave ?? 4)) body.octave = Number(noteOctave);
      }
      if (noteLyric !== (selectedNote.lyric ?? "")) body.lyric = noteLyric;
      if (noteType !== (selectedNote.type ?? "quarter")) body.type = noteType;
      if (noteDots !== (selectedNote.dots ?? 0)) body.dots = noteDots;
      if (changedList(noteArticulations, selectedNote.articulations)) body.articulations = noteArticulations;
      if (changedList(noteTies, selectedNote.ties)) body.ties = noteTies;
      if (changedList(noteSlurs, selectedNote.slurs)) body.slurs = noteSlurs;
      if (noteBeam !== (selectedNote.beam ?? "")) body.beam = noteBeam || null;

      if (Object.keys(body).length === 0) {
        setMessage("변경된 노트 항목이 없습니다.");
        return;
      }
      const response = await fetch(`${API}/api/songs/${song.song_id}/notes/${selectedNote.note_id}/structure`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...body, ...scoreStamp }),
      });
      await reloadStableNoteEdit(response, selectedNote.note_id, selection);
      setMessage(`${selectedNote.part_name} M${selectedNote.measure}의 노트·리듬·표현을 저장했습니다.`);
    });
  };

  const insertSelectedNote = async () => {
    if (!song || !selectedNote || !scoreStamp) return;
    await withBusy(async () => {
      const response = await fetch(`${API}/api/songs/${song.song_id}/notes/${selectedNote.note_id}/insert`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          position: insertPosition,
          rest: noteRest,
          step: noteStep,
          alter: Number(noteAlter),
          octave: Number(noteOctave),
          type: noteType,
          dots: noteDots,
          lyric: noteLyric,
          ...scoreStamp,
        }),
      });
      await checkPositionalEdit(response);
      const body = await response.json();
      const updated = await reload();
      const id: unknown = body.result?.note_id;
      if (updated) setSelectedNoteId(updated.song.revision === scoreStamp.expected_revision + 1
        && typeof id === "string" && updated.notes.some(note => note.note_id === id) ? id : null);
      setMessage("선택한 설정으로 새 음표/쉼표를 삽입했습니다.");
    });
  };

  const deleteSelectedNote = async () => {
    if (!song || !selectedNote || !scoreQuery || busy) return;
    if (!window.confirm(`${selectedNote.part_name} M${selectedNote.measure}의 선택 음표를 삭제할까요?`)) return;
    await withBusy(async () => {
      const response = await fetch(`${API}/api/songs/${song.song_id}/notes/${selectedNote.note_id}?${scoreQuery}`, { method: "DELETE" });
      await checkPositionalEdit(response);
      setSelectedNoteId(null);
      await reload();
      setMessage("선택 음표를 삭제했습니다.");
    });
  };

  const saveChord = async (symbol = chordSymbol) => {
    if (!song || !selectedNote || !scoreStamp) return;
    const selection = rhythmSelection.current;
    await withBusy(async () => {
      const response = await fetch(`${API}/api/songs/${song.song_id}/notes/${selectedNote.note_id}/chord`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol, ...scoreStamp }),
      });
      await reloadStableNoteEdit(response, selectedNote.note_id, selection);
      setMessage(symbol.trim() ? `${symbol} 코드를 악보에 표시했습니다.` : "선택 위치의 코드를 삭제했습니다.");
    });
  };

  const saveSignature = async () => {
    if (!song || !scoreStamp || selectedMeasureIndex === null) return;
    await withBusy(async () => {
      const response = await fetch(`${API}/api/songs/${song.song_id}/measures/${selectedMeasureIndex}/signature`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key_fifths: keyFifths, key_mode: keyMode, beats, beat_type: beatType, ...scoreStamp }),
      });
      await checkPositionalEdit(response);
      await reload();
      setMessage(`M${selectedMeasureIndex + 1}부터 표시할 조표·박자표를 적용했습니다.`);
    });
  };

  const insertMeasureAfter = async () => {
    if (!song || !scoreStamp || !scoreQuery || selectedMeasureIndex === null) return;
    await withBusy(async () => {
      const response = await fetch(`${API}/api/songs/${song.song_id}/measures/${selectedMeasureIndex}/insert-after?${scoreQuery}`, { method: "POST" });
      await checkPositionalEdit(response);
      const body = await response.json();
      const updated = await reload();
      if (updated?.song.revision === scoreStamp.expected_revision + 1) {
        setSelectedMeasureIndex(body.result?.measure_index ?? selectedMeasureIndex + 1);
      }
      setMessage("모든 파트에 새 마디를 삽입했습니다.");
    });
  };

  const removeMeasure = async () => {
    if (!song || !scoreQuery || selectedMeasureIndex === null || busy) return;
    if (!window.confirm(`모든 파트에서 M${selectedMeasureIndex + 1}을 삭제할까요?`)) return;
    await withBusy(async () => {
      const response = await fetch(`${API}/api/songs/${song.song_id}/measures/${selectedMeasureIndex}?${scoreQuery}`, { method: "DELETE" });
      await checkPositionalEdit(response);
      setSelectedNoteId(null);
      await reload();
      setMessage("선택 마디를 모든 파트에서 삭제했습니다.");
    });
  };

  const savePublication = async (fields: Partial<PublicationSettings>, success: string) => {
    if (!song) return;
    await withBusy(async () => {
      const response = await fetch(`${API}/api/songs/${song.song_id}/publication`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields),
      });
      if (!response.ok) throw new Error(await response.text());
      await reload();
      setMessage(success);
    });
  };

  const saveCredits = async () => {
    if (!song) return;
    await withBusy(async () => {
      // First-page title, song metadata and publication credits are one
      // canonical edit/Undo revision, never two partial PATCH requests.
      const response = await fetch(`${API}/api/songs/${song.song_id}/credits`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          artist,
          expected_revision: song.revision,
          subtitle: publication.subtitle,
          album: publication.album,
          performer: publication.performer,
          release_date: publication.release_date,
          composer: publication.composer,
          lyricist: publication.lyricist,
          arranger: publication.arranger,
          rights: publication.rights,
          title_font_size: publication.title_font_size,
          subtitle_font_size: publication.subtitle_font_size,
          credit_font_size: publication.credit_font_size,
        }),
      });
      if (!response.ok) throw new Error(await response.text());
      await reload();
      setMessage("첫 페이지 제목과 크레딧 정보를 반영했습니다.");
    });
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
    await withBusy(async () => {
      const response = await fetch(`${API}/api/songs/${song.song_id}/${action}`, { method: "POST" });
      if (!response.ok) throw new Error(await response.text());
      await reload();
      setMessage(action === "export" ? "현재 수정본으로 Full Score와 파트별 PDF/MIDI를 생성했습니다." : "악보를 갱신했습니다.");
    });
  };

  const deleteSong = async () => {
    if (!song || !window.confirm(`‘${song.title}’을 곡 라이브러리에서 삭제할까요?`)) return;
    await withBusy(async () => {
      const response = await fetch(`${API}/api/songs/${song.song_id}`, { method: "DELETE" });
      if (!response.ok) throw new Error(await response.text());
      selectSong(null);
      await refreshSongs();
      setMessage("곡을 라이브러리에서 삭제했습니다. 원본 채보 Job은 History에 유지됩니다.");
    });
  };

  const filters = (
    <div className="note-filter-grid">
      <label>
        <span>파트</span>
        <select value={partFilter} onChange={(event) => setPartFilter(event.target.value)}>
          <option value="all">전체</option>
          {score?.parts.map((part) => <option key={part.part_id} value={part.part_id}>{part.name}</option>)}
        </select>
      </label>
      <label><span>마디</span><input placeholder="예: 12" value={measureFilter} onChange={(event) => setMeasureFilter(event.target.value)} /></label>
    </div>
  );

  const expressionToggle = (label: string, value: string, values: string[], setter: (next: string[]) => void) => (
    <label className="check-chip">
      <input type="checkbox" checked={values.includes(value)} onChange={() => setter(toggleValue(values, value))} />
      <span>{label}</span>
    </label>
  );

  return (
    <main className="song-shell">
      <header className="song-header">
        <div>
          <div className="eyebrow">SCORE PUBLISHING WORKSPACE</div>
          <h1>곡 라이브러리</h1>
          <p>자동 채보된 곡을 완성 악보로 다듬고, 파트별 악보와 출판 파일을 생성합니다.</p>
        </div>
        <button className="secondary" onClick={() => void refreshSongs()}>새로고침</button>
      </header>

      <section className="song-layout">
        <aside className="song-library card">
          <div className="library-head">
            <div><span className="eyebrow">LIBRARY</span><strong>{songs.length}곡</strong></div>
          </div>
          <div className="song-list">
            {songs.length === 0 && <p className="muted">완료된 채보가 아직 없습니다.</p>}
            {songs.map((item) => (
              <button key={item.song_id} className={`song-item ${selectedId === item.song_id ? "active" : ""}`} onClick={() => selectSong(item.song_id)}>
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
              {selectedId && scoreLoadFailed ? (
                <><h2>악보를 불러오지 못했습니다.</h2><button className="secondary" disabled={rhythmBusy} onClick={refreshScore}>악보 새로고침</button></>
              ) : (
                <><h2>편집할 곡을 선택하세요</h2><p className="muted">완료된 채보는 자동으로 곡 라이브러리에 등록됩니다.</p></>
              )}
            </div>
          ) : (
            <>
              <div className="score-toolbar">
                <div><span className="eyebrow">CURRENT SCORE</span><h2>{song.title}</h2><span className="revision-pill">Revision {song.revision}</span></div>
                <div className="score-actions">
                  <label className="zoom-control"><span>미리보기</span><input type="range" min="55" max="130" value={previewZoom} onChange={(event) => setPreviewZoom(Number(event.target.value))} /><strong>{previewZoom}%</strong></label>
                  <button className="secondary" disabled={otherBusy || rhythmBusy} onClick={refreshScore}>악보 새로고침</button>
                  <button className="secondary" disabled={busy || song.revision <= 1} onClick={() => void postAction("undo")}>실행 취소</button>
                  <button className="secondary" disabled={busy} onClick={() => void postAction("restore")}>원본 복원</button>
                  <button className="run-button export-button" disabled={busy} onClick={() => void postAction("export")}>최종 파일 생성</button>
                </div>
              </div>
              {rhythmBusy && <p role="status">리듬을 수정하고 있습니다…</p>}
              {!rhythmBusy && rhythmNeedsReload && !scoreLoadFailed && <p role="status">수정한 악보를 불러오고 있습니다…</p>}
              {!rhythmBusy && scoreLoadFailed && <p role="status">{rhythmNeedsReload
                ? "수정 결과를 확인하려면 악보 새로고침을 눌러 주세요."
                : "편집을 계속하려면 악보 새로고침을 눌러 주세요."}</p>}
              <SourceAudioReview key={`${song.song_id}:${song.revision}`} songId={song.song_id} revision={song.revision} clip={sourceClip} />
              {unresolvedMetadata && (
                <div className="metadata-review-notice" role="status">
                  <div><strong>곡 정보 확인이 필요합니다.</strong><p>자동 식별되지 않은 항목은 Unknown으로 표시됩니다. 제목·가수·작곡·작사 등을 확인한 뒤 재조회할 수 있습니다.</p></div>
                  <div className="metadata-review-actions">
                    <button className="secondary" type="button" onClick={() => setInspectorTab("credits")}>악보 정보 직접 수정</button>
                    <button className="secondary" type="button" onClick={() => openMetadataEditor(song.song_id)}>메타데이터 관리·재조회</button>
                  </div>
                </div>
              )}
              <div className="export-links">
                <span>Full Score</span>
                <a href={`${API}/api/songs/${song.song_id}/files/musicxml`} target="_blank">MusicXML</a>
                {song.exports.pdf && <a href={`${API}/api/songs/${song.song_id}/files/pdf`} target="_blank">PDF</a>}
                {song.exports.midi && <a href={`${API}/api/songs/${song.song_id}/files/midi`} target="_blank">MIDI</a>}
                {!song.exports.pdf && <small>수정 후 PDF/MIDI는 다시 생성해야 합니다.</small>}
              </div>
              {song.parts && song.parts.length > 0 && (
                <div className="part-export-strip">
                  <span>파트별 악보</span>
                  {song.parts.map((part) => (
                    <div key={part.part_id} className="part-export-item">
                      <strong>{part.name}</strong>
                      {part.musicxml && <a href={`${API}/api/songs/${song.song_id}/files/parts/${part.slug}/musicxml`} target="_blank">XML</a>}
                      {part.pdf && <a href={`${API}/api/songs/${song.song_id}/files/parts/${part.slug}/pdf`} target="_blank">PDF</a>}
                    </div>
                  ))}
                </div>
              )}
              <div className="score-canvas" ref={scoreRef} />
            </>
          )}
        </section>

        <aside className="score-inspector card">
          <div className="inspector-tabs inspector-tabs-five">
            <button className={inspectorTab === "note" ? "active" : ""} onClick={() => setInspectorTab("note")}>노트</button>
            <button className={inspectorTab === "chord" ? "active" : ""} onClick={() => setInspectorTab("chord")}>코드</button>
            <button className={inspectorTab === "structure" ? "active" : ""} onClick={() => setInspectorTab("structure")}>마디·조성</button>
            <button className={inspectorTab === "layout" ? "active" : ""} onClick={() => setInspectorTab("layout")}>레이아웃</button>
            <button className={inspectorTab === "credits" ? "active" : ""} onClick={() => setInspectorTab("credits")}>제목·정보</button>
          </div>

          {song && inspectorTab === "note" && (
            <>
              {filters}
              <div className="note-list">
                {filteredNotes.slice(0, 1000).map((note) => (
                  <button key={note.note_id} className={selectedNoteId === note.note_id ? "active" : ""} disabled={busy} onClick={() => chooseNote(note.note_id)}>
                    <span>M{note.measure}</span><strong>{pitchLabel(note)}</strong><small>{note.type ?? "?"}{note.dots ? ` · dot×${note.dots}` : ""} · {note.lyric || "—"}</small>
                  </button>
                ))}
              </div>
              {selectedNote && (
                <div className="note-editor advanced-note-editor">
                  <div className="note-editor-head"><strong>{selectedNote.part_name} · M{selectedNote.measure}</strong><code>{selectedNote.note_id}</code></div>
                  <div className="note-evidence">
                    <button type="button" className="secondary" disabled={scoreLocked || visibleEvidence?.loading || score?.evidence_generation == null} onClick={() => void loadNoteEvidence()}>{visibleEvidence?.loading ? "근거 확인 중…" : "모델 근거 확인"}</button>
                    {score?.evidence_generation == null && <p>이 악보에는 연결된 모델 근거가 없어 확인을 보류합니다.</p>}
                    {visibleEvidence?.message && <p role="status">{visibleEvidence.message}</p>}
                    {pitchObservation.message && <p role="status">{pitchObservation.message}</p>}
                    {visibleEvidence?.result && (visibleEvidence.result.status !== "linked" || !visibleEvidence.result.evidence
                      ? <p role="status">이 음표의 모델 근거를 확정할 수 없어 확인을 보류합니다.</p>
                      : <div role="status">
                        {visibleEvidence.result.evidence.written_quarters && <p>현재 기보 위치 (4분음표 기준) {visibleEvidence.result.evidence.written_quarters.start.toFixed(2)}–{visibleEvidence.result.evidence.written_quarters.end.toFixed(2)}</p>}
                        {visibleEvidence.result.patch && <p>이 버전에서 음표를 수정했습니다.</p>}
                        {evidenceSources.map((source, index) => <div key={index} className="note-evidence-source">
                          {evidenceSources.length > 1 && <strong>원본 {index + 1}</strong>}
                          <p>모델 연주 시각 {source.performed_seconds.start.toFixed(2)}–{source.performed_seconds.end.toFixed(2)}초</p>
                          <p>원본 기보 격자 시각 {source.grid_seconds.start.toFixed(2)}–{source.grid_seconds.end.toFixed(2)}초</p>
                          {source.source_id && pitchObservation.windows?.has(source.source_id) && <PitchObservationPlot window={pitchObservation.windows.get(source.source_id)!} writtenMidi={writtenMidi} />}
                          <p>{verifiedClips[index] ? "원음 구간은 해석된 기보 시간이며 실제 음의 시작이나 정확도 판정이 아닙니다." : "원음 구간을 확인할 수 없어 재생 연결을 보류합니다."}</p>
                          {verifiedClips[index] && <button type="button" className="secondary" onClick={() => setSelectedClip({ key: evidenceKey, epoch: evidenceEpoch.current, clip: { ...verifiedClips[index]! } })}>{evidenceSources.length > 1 ? `원음 구간 확인 ${index + 1}` : "원음 구간 확인"}</button>}
                        </div>)}
                      </div>)}
                  </div>
                  <div className="note-rhythm-edit">
                    <strong>구간 리듬 수정</strong>
                    <p>{nextRhythmNote ? `합치기·경계 이동은 현재와 같은 마디의 바로 다음 M${nextRhythmNote.measure} ${pitchLabel(nextRhythmNote)}를 대상으로 합니다.` : "같은 마디에 바로 다음 음표나 쉼표가 없습니다."}</p>
                    <div className="layout-two">
                      <label><span>왼쪽 길이</span><select aria-label="왼쪽 길이" value={leftType} onChange={(event) => setLeftType(event.target.value as NoteType)}>{noteTypes.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
                      <label><span>왼쪽 점</span><select aria-label="왼쪽 점" value={leftDots} onChange={(event) => setLeftDots(Number(event.target.value))}><option value={0}>없음</option><option value={1}>1점</option><option value={2}>2점</option></select></label>
                    </div>
                    {score?.evidence_generation == null && <p>이 악보의 리듬 편집 상태를 확인할 수 없습니다. 새로고침 후 다시 시도하세요.</p>}
                    {rhythmStatus && rhythmStatus.songId === song.song_id && rhythmStatus.noteId === selectedNote.note_id
                      && rhythmStatus.revision === score?.song.revision && rhythmStatus.generation === score.evidence_generation
                      && rhythmStatus.scoreHash === score.score_sha256
                      && <p role="status">{rhythmStatus.message}</p>}
                    <div className="note-rhythm-actions">
                      <button type="button" className="secondary" disabled={busy || selectedNote.rest || score?.evidence_generation == null} onClick={() => void editRhythm("split")}>음표 나누기</button>
                      <button type="button" className="secondary" disabled={busy || !nextRhythmNote || score?.evidence_generation == null} onClick={() => void editRhythm("merge")}>다음과 합치기</button>
                      <button type="button" className="secondary" disabled={busy || !nextRhythmNote || score?.evidence_generation == null} onClick={() => void editRhythm("boundary")}>경계 옮기기</button>
                      <button type="button" className="secondary" disabled={busy || selectedNote.rest || score?.evidence_generation == null} onClick={() => void editRhythm("delete")}>같은 길이 쉼표로 바꾸기</button>
                    </div>
                  </div>
                  <label className="switch-row"><span>쉼표</span><input type="checkbox" checked={noteRest} onChange={(event) => setNoteRest(event.target.checked)} /></label>
                  {!noteRest && (
                    <div className="pitch-fields">
                      <label><span>음</span><select value={noteStep} onChange={(event) => setNoteStep(event.target.value)}>{["C","D","E","F","G","A","B"].map((value) => <option key={value}>{value}</option>)}</select></label>
                      <label><span>반음</span><select value={noteAlter} onChange={(event) => setNoteAlter(event.target.value)}><option value="-2">♭♭</option><option value="-1">♭</option><option value="0">♮</option><option value="1">♯</option><option value="2">♯♯</option></select></label>
                      <label><span>옥타브</span><input type="number" min="0" max="9" value={noteOctave} onChange={(event) => setNoteOctave(event.target.value)} /></label>
                    </div>
                  )}
                  <div className="layout-two">
                    <label><span>리듬값</span><select value={noteType} onChange={(event) => setNoteType(event.target.value as NoteType)}>{noteTypes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
                    <label><span>점음표</span><select value={noteDots} onChange={(event) => setNoteDots(Number(event.target.value))}><option value={0}>없음</option><option value={1}>1점</option><option value={2}>2점</option></select></label>
                  </div>
                  <label className="lyric-field"><span>가사</span><input value={noteLyric} onChange={(event) => setNoteLyric(event.target.value)} placeholder="이 노트의 가사" /></label>
                  <div className="inspector-divider" />
                  <span className="field-section-title">아티큘레이션</span>
                  <div className="chip-grid">
                    {expressionToggle("스타카토", "staccato", noteArticulations, setNoteArticulations)}
                    {expressionToggle("테누토", "tenuto", noteArticulations, setNoteArticulations)}
                    {expressionToggle("악센트", "accent", noteArticulations, setNoteArticulations)}
                    {expressionToggle("마르카토", "strong-accent", noteArticulations, setNoteArticulations)}
                  </div>
                  <span className="field-section-title">타이 / 슬러</span>
                  <div className="chip-grid">
                    {expressionToggle("타이 시작", "start", noteTies, setNoteTies)}
                    {expressionToggle("타이 종료", "stop", noteTies, setNoteTies)}
                    {expressionToggle("슬러 시작", "start", noteSlurs, setNoteSlurs)}
                    {expressionToggle("슬러 종료", "stop", noteSlurs, setNoteSlurs)}
                  </div>
                  <label><span>빔</span><select value={noteBeam} onChange={(event) => setNoteBeam(event.target.value)}><option value="">자동/없음</option><option value="begin">시작</option><option value="continue">계속</option><option value="end">종료</option><option value="forward hook">앞 훅</option><option value="backward hook">뒤 훅</option></select></label>
                  <button className="run-button" disabled={busy} onClick={() => void saveNote()}>노트 전체 저장</button>
                  <div className="inspector-divider" />
                  <span className="field-section-title">음표/쉼표 삽입·삭제</span>
                  <div className="insert-note-controls">
                    <select value={insertPosition} onChange={(event) => setInsertPosition(event.target.value as "before" | "after")}><option value="before">선택 앞에 삽입</option><option value="after">선택 뒤에 삽입</option></select>
                    <button className="secondary" disabled={busy} onClick={() => void insertSelectedNote()}>현재 설정으로 삽입</button>
                    <button className="delete-song-button compact-delete" disabled={busy} onClick={() => void deleteSelectedNote()}>선택 음표 삭제</button>
                  </div>
                </div>
              )}
            </>
          )}

          {song && inspectorTab === "chord" && (
            <>
              <div className="inspector-intro"><strong>코드 심벌</strong><p>자동 추정된 코드가 틀린 위치만 수정합니다. 한 마디 안에서도 여러 코드 변화를 지정할 수 있습니다.</p></div>
              {filters}
              <div className="note-list chord-note-list">
                {filteredNotes.slice(0, 1000).map((note) => (
                  <button key={note.note_id} className={selectedNoteId === note.note_id ? "active" : ""} disabled={busy} onClick={() => chooseNote(note.note_id)}><span>M{note.measure}</span><strong>{chordMap.get(note.note_id) || "·"}</strong><small>{pitchLabel(note)} {note.lyric || ""}</small></button>
                ))}
              </div>
              {selectedNote && (
                <div className="chord-editor note-editor">
                  <div className="note-editor-head"><strong>M{selectedNote.measure} · {pitchLabel(selectedNote)} 위치</strong><code>{selectedNote.note_id}</code></div>
                  <label className="lyric-field"><span>코드</span><input value={chordSymbol} onChange={(event) => setChordSymbol(event.target.value)} placeholder="예: Cmaj7, Am7, F#7, G/B" /></label>
                  <div className="chord-examples">C · Cm · C7 · Cmaj7 · Cm7 · Csus4 · Cdim7 · F♯m7 · B♭7 · G/B</div>
                  <div className="chord-actions"><button className="run-button" disabled={busy} onClick={() => void saveChord()}>코드 적용</button><button className="secondary" disabled={busy || !chordMap.get(selectedNote.note_id)} onClick={() => void saveChord("")}>코드 삭제</button></div>
                </div>
              )}
            </>
          )}

          {song && inspectorTab === "structure" && (
            <div className="publication-editor structure-editor">
              <div className="inspector-intro"><strong>마디 · 조표 · 박자표</strong><p>이 탭의 마디 삽입/삭제와 조표·박자 변경은 Full Score의 모든 파트에 동일하게 적용됩니다.</p></div>
              <label><span>편집 마디</span><select value={selectedMeasureIndex ?? ""} disabled={busy} onChange={(event) => setSelectedMeasureIndex(Number(event.target.value))}><option value="" disabled>마디 선택</option>{measures.map((measure) => <option key={measure.measure_index} value={measure.measure_index}>M{measure.number}</option>)}</select></label>
              <div className="layout-two">
                <label><span>조표</span><select value={keyFifths} onChange={(event) => setKeyFifths(Number(event.target.value))}>{Object.entries(keyNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
                <label><span>조성</span><select value={keyMode} onChange={(event) => setKeyMode(event.target.value as "major" | "minor")}><option value="major">Major</option><option value="minor">Minor</option></select></label>
              </div>
              <div className="layout-two">
                <label><span>박자 분자</span><input type="number" min="1" max="32" value={beats} onChange={(event) => setBeats(Number(event.target.value))} /></label>
                <label><span>박자 분모</span><select value={beatType} onChange={(event) => setBeatType(Number(event.target.value))}>{[1,2,4,8,16,32].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
              </div>
              <button className="run-button" disabled={busy || selectedMeasureIndex === null || measures.length === 0} onClick={() => void saveSignature()}>조표·박자표 적용</button>
              <div className="inspector-divider" />
              <span className="field-section-title">마디 구조</span>
              <div className="measure-actions">
                <button className="secondary" disabled={busy || selectedMeasureIndex === null || measures.length === 0} onClick={() => void insertMeasureAfter()}>이 마디 뒤에 새 마디</button>
                <button className="delete-song-button compact-delete" disabled={busy || selectedMeasureIndex === null || measures.length <= 1} onClick={() => void removeMeasure()}>이 마디 삭제</button>
              </div>
              <div className="layout-summary">현재 {measures.length}마디{selectedMeasureIndex !== null && ` · M${selectedMeasureIndex + 1}: ${beats}/${beatType}, ${keyNames[keyFifths]} ${keyMode}`}</div>
            </div>
          )}

          {song && inspectorTab === "layout" && (
            <div className="publication-editor">
              <div className="inspector-intro"><strong>출판 레이아웃</strong><p>문서의 자간·행간처럼 악보 밀도와 페이지 조판을 조절합니다.</p></div>
              <div className="layout-two">
                <label><span>용지</span><select value={publication.page_size} onChange={(event) => setPublication((current) => ({ ...current, page_size: event.target.value as PublicationSettings["page_size"] }))}><option value="A4">A4</option><option value="LETTER">Letter</option></select></label>
                <label><span>방향</span><select value={publication.orientation} onChange={(event) => setPublication((current) => ({ ...current, orientation: event.target.value as PublicationSettings["orientation"] }))}><option value="portrait">세로</option><option value="landscape">가로</option></select></label>
              </div>
              <div className="layout-two">
                <label><span>한 줄당 마디</span><input type="number" min="1" max="12" value={publication.bars_per_system} onChange={(event) => setPublication((current) => ({ ...current, bars_per_system: Number(event.target.value) }))} /></label>
                <label><span>페이지당 악보 줄</span><input type="number" min="1" max="12" value={publication.systems_per_page} onChange={(event) => setPublication((current) => ({ ...current, systems_per_page: Number(event.target.value) }))} /></label>
              </div>
              <label className="range-field"><span>악보 줄 간격 <strong>{publication.system_distance_mm} mm</strong></span><input type="range" min="3" max="40" step="0.5" value={publication.system_distance_mm} onChange={(event) => setPublication((current) => ({ ...current, system_distance_mm: Number(event.target.value) }))} /></label>
              <label className="range-field"><span>첫 페이지 제목 영역 <strong>{publication.first_page_title_space_mm} mm</strong></span><input type="range" min="15" max="90" step="1" value={publication.first_page_title_space_mm} onChange={(event) => setPublication((current) => ({ ...current, first_page_title_space_mm: Number(event.target.value) }))} /></label>
              <div className="inspector-divider" />
              <span className="field-section-title">페이지 여백</span>
              <div className="margin-grid">
                {(["top_margin_mm", "bottom_margin_mm", "left_margin_mm", "right_margin_mm"] as const).map((key) => {
                  const labels = { top_margin_mm: "위", bottom_margin_mm: "아래", left_margin_mm: "왼쪽", right_margin_mm: "오른쪽" };
                  return <label key={key}><span>{labels[key]}</span><input type="number" min="5" max="40" step="0.5" value={publication[key]} onChange={(event) => setPublication((current) => ({ ...current, [key]: Number(event.target.value) }))} /></label>;
                })}
              </div>
              <div className="layout-summary">한 줄 {publication.bars_per_system}마디 × 페이지당 {publication.systems_per_page}줄 = 약 {publication.bars_per_system * publication.systems_per_page}마디/페이지</div>
              <button className="run-button" disabled={busy} onClick={() => void saveLayout()}>조판 적용 및 미리보기</button>
            </div>
          )}

          {song && inspectorTab === "credits" && (
            <div className="publication-editor credits-editor">
              <div className="inspector-intro"><strong>첫 페이지 제목 영역</strong><p>상용 악보처럼 제목, 부제, 작사·작곡·편곡 및 저작권 정보를 배치합니다.</p></div>
              <label><span>곡 제목</span><input value={title} onChange={(event) => setTitle(event.target.value)} /></label>
              <label><span>부제 / 버전</span><input value={publication.subtitle} onChange={(event) => setPublication((current) => ({ ...current, subtitle: event.target.value }))} placeholder="예: Piano & Vocal / Original Key" /></label>
              <div className="layout-two">
                <label><span>앨범명</span><input value={publication.album} onChange={(event) => setPublication((current) => ({ ...current, album: event.target.value }))} /></label>
                <label><span>가수 / 연주자</span><input value={publication.performer} onChange={(event) => setPublication((current) => ({ ...current, performer: event.target.value }))} /></label>
              </div>
              <label><span>발매 정보</span><input value={publication.release_date} onChange={(event) => setPublication((current) => ({ ...current, release_date: event.target.value }))} placeholder="예: 2004-09-21" /></label>
              <label><span>라이브러리 아티스트 / 메모</span><input value={artist} onChange={(event) => setArtist(event.target.value)} /></label>
              <div className="layout-two"><label><span>작곡</span><input value={publication.composer} onChange={(event) => setPublication((current) => ({ ...current, composer: event.target.value }))} /></label><label><span>작사</span><input value={publication.lyricist} onChange={(event) => setPublication((current) => ({ ...current, lyricist: event.target.value }))} /></label></div>
              <label><span>편곡</span><input value={publication.arranger} onChange={(event) => setPublication((current) => ({ ...current, arranger: event.target.value }))} /></label>
              <label><span>저작권 / 출처</span><textarea rows={3} value={publication.rights} onChange={(event) => setPublication((current) => ({ ...current, rights: event.target.value }))} placeholder="© 2026 ..." /></label>
              <div className="inspector-divider" />
              <span className="field-section-title">글자 크기</span>
              <div className="layout-three"><label><span>제목</span><input type="number" min="14" max="48" value={publication.title_font_size} onChange={(event) => setPublication((current) => ({ ...current, title_font_size: Number(event.target.value) }))} /></label><label><span>부제</span><input type="number" min="8" max="28" value={publication.subtitle_font_size} onChange={(event) => setPublication((current) => ({ ...current, subtitle_font_size: Number(event.target.value) }))} /></label><label><span>크레딧</span><input type="number" min="7" max="18" step="0.5" value={publication.credit_font_size} onChange={(event) => setPublication((current) => ({ ...current, credit_font_size: Number(event.target.value) }))} /></label></div>
              <button className="run-button" disabled={busy} onClick={() => void saveCredits()}>제목 영역 적용</button>
              <button className="secondary" type="button" disabled={busy} onClick={() => openMetadataEditor(song.song_id)}>메타데이터 관리·외부 API 재조회</button>
              <button className="delete-song-button" disabled={busy} onClick={() => void deleteSong()}>이 곡을 라이브러리에서 삭제</button>
            </div>
          )}

          {message && <p className="workspace-message">{message}</p>}
        </aside>
      </section>
    </main>
  );
}
