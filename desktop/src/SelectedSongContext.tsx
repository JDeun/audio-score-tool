import { createContext, useCallback, useContext, useMemo, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";

export type SelectedSongTarget = { songId: string; title: string };
export type SongChangeNotice = { songId: string; sequence: number };

type SelectedSongState = {
  target: SelectedSongTarget | null;
  setTarget: Dispatch<SetStateAction<SelectedSongTarget | null>>;
  songChange: SongChangeNotice | null;
  notifySongChanged: (songId: string) => void;
};

const SelectedSongContext = createContext<SelectedSongState | null>(null);

export function SelectedSongProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<SelectedSongTarget | null>(null);
  const [songChange, setSongChange] = useState<SongChangeNotice | null>(null);
  const notifySongChanged = useCallback((songId: string) => {
    setSongChange((previous) => ({ songId, sequence: (previous?.sequence ?? 0) + 1 }));
  }, []);
  const value = useMemo(
    () => ({ target, setTarget, songChange, notifySongChanged }),
    [target, songChange, notifySongChanged],
  );
  return <SelectedSongContext.Provider value={value}>{children}</SelectedSongContext.Provider>;
}

export function useSelectedSong(): SelectedSongState {
  const context = useContext(SelectedSongContext);
  if (context === null) throw new Error("SelectedSongProvider is required");
  return context;
}
