import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";

export type SelectedSongTarget = { songId: string; title: string };
export type SongChangeNotice = { songId: string; sequence: number };
export type MetadataEditorRequest = { songId: string; sequence: number };
export type JobSongRequest = { jobId: string; sequence: number };
type RhythmEditState = { pending: boolean; settledId: number | null };

type SelectedSongState = {
  target: SelectedSongTarget | null;
  setTarget: Dispatch<SetStateAction<SelectedSongTarget | null>>;
  songChange: SongChangeNotice | null;
  notifySongChanged: (songId: string) => void;
  rhythmEdits: ReadonlyMap<string, RhythmEditState>;
  getRhythmEdit: (songId: string) => RhythmEditState | undefined;
  beginRhythmEdit: (songId: string) => { id: number; settle: () => void } | null;
  metadataEditorRequest: MetadataEditorRequest | null;
  openMetadataEditor: (songId: string) => void;
  jobSongRequest: JobSongRequest | null;
  openJobSong: (jobId: string) => void;
  finishJobSongRequest: (sequence: number) => void;
};

const SelectedSongContext = createContext<SelectedSongState | null>(null);

export function SelectedSongProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<SelectedSongTarget | null>(null);
  const [songChange, setSongChange] = useState<SongChangeNotice | null>(null);
  // The workspace can unmount while a score mutation is still in flight.
  const rhythmEditsRef = useRef<ReadonlyMap<string, RhythmEditState>>(new Map());
  const [rhythmEdits, setRhythmEdits] = useState(rhythmEditsRef.current);
  const rhythmSequence = useRef(0);
  const getRhythmEdit = useCallback((songId: string) => rhythmEditsRef.current.get(songId), []);
  const beginRhythmEdit = useCallback((songId: string) => {
    const previous = getRhythmEdit(songId);
    if (previous?.pending) return null;
    const update = (edit: RhythmEditState) => {
      rhythmEditsRef.current = new Map(rhythmEditsRef.current).set(songId, edit);
      setRhythmEdits(rhythmEditsRef.current);
    };
    const id = ++rhythmSequence.current;
    update({ pending: true, settledId: previous?.settledId ?? null });
    return { id, settle: () => update({ pending: false, settledId: id }) };
  }, [getRhythmEdit]);
  const [metadataEditorRequest, setMetadataEditorRequest] = useState<MetadataEditorRequest | null>(null);
  const [jobSongRequest, setJobSongRequest] = useState<JobSongRequest | null>(() => {
    const jobId = window.sessionStorage.getItem("ast-pending-job-song");
    return jobId ? { jobId, sequence: 1 } : null;
  });
  const navigationSequence = useRef(jobSongRequest?.sequence ?? 0);
  useEffect(() => {
    if (jobSongRequest) window.sessionStorage.setItem("ast-pending-job-song", jobSongRequest.jobId);
    else window.sessionStorage.removeItem("ast-pending-job-song");
  }, [jobSongRequest]);
  const openJobSong = useCallback((jobId: string) => {
    setJobSongRequest({ jobId, sequence: ++navigationSequence.current });
  }, []);
  const finishJobSongRequest = useCallback((sequence: number) => {
    setJobSongRequest((current) => {
      // A late response must never consume a newer navigation request.
      if (current?.sequence !== sequence) return current;
      return null;
    });
  }, []);
  const openMetadataEditor = useCallback((songId: string) => {
    setMetadataEditorRequest((previous) => ({
      songId, sequence: (previous?.sequence ?? 0) + 1,
    }));
  }, []);
  const notifySongChanged = useCallback((songId: string) => {
    setSongChange((previous) => ({ songId, sequence: (previous?.sequence ?? 0) + 1 }));
  }, []);
  const value = useMemo(
    () => ({ target, setTarget, songChange, notifySongChanged, rhythmEdits, getRhythmEdit, beginRhythmEdit, metadataEditorRequest, openMetadataEditor,
      jobSongRequest, openJobSong, finishJobSongRequest }),
    [target, songChange, notifySongChanged, rhythmEdits, getRhythmEdit, beginRhythmEdit, metadataEditorRequest, openMetadataEditor,
      jobSongRequest, openJobSong, finishJobSongRequest],
  );
  return <SelectedSongContext.Provider value={value}>{children}</SelectedSongContext.Provider>;
}

export function useSelectedSong(): SelectedSongState {
  const context = useContext(SelectedSongContext);
  if (context === null) throw new Error("SelectedSongProvider is required");
  return context;
}
