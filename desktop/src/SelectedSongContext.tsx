import { createContext, useCallback, useContext, useMemo, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";

export type SelectedSongTarget = { songId: string; title: string };
export type SongChangeNotice = { songId: string; sequence: number };
export type MetadataEditorRequest = { songId: string; sequence: number };

type SelectedSongState = {
  target: SelectedSongTarget | null;
  setTarget: Dispatch<SetStateAction<SelectedSongTarget | null>>;
  songChange: SongChangeNotice | null;
  notifySongChanged: (songId: string) => void;
  metadataEditorRequest: MetadataEditorRequest | null;
  openMetadataEditor: (songId: string) => void;
};

const SelectedSongContext = createContext<SelectedSongState | null>(null);

export function SelectedSongProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<SelectedSongTarget | null>(null);
  const [songChange, setSongChange] = useState<SongChangeNotice | null>(null);
  const [metadataEditorRequest, setMetadataEditorRequest] = useState<MetadataEditorRequest | null>(null);
  const openMetadataEditor = useCallback((songId: string) => {
    setMetadataEditorRequest((previous) => ({
      songId, sequence: (previous?.sequence ?? 0) + 1,
    }));
  }, []);
  const notifySongChanged = useCallback((songId: string) => {
    setSongChange((previous) => ({ songId, sequence: (previous?.sequence ?? 0) + 1 }));
  }, []);
  const value = useMemo(
    () => ({ target, setTarget, songChange, notifySongChanged, metadataEditorRequest, openMetadataEditor }),
    [target, songChange, notifySongChanged, metadataEditorRequest, openMetadataEditor],
  );
  return <SelectedSongContext.Provider value={value}>{children}</SelectedSongContext.Provider>;
}

export function useSelectedSong(): SelectedSongState {
  const context = useContext(SelectedSongContext);
  if (context === null) throw new Error("SelectedSongProvider is required");
  return context;
}
