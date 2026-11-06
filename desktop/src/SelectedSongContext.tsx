import { createContext, useContext, useMemo, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";

export type SelectedSongTarget = { songId: string; title: string };

type SelectedSongState = {
  target: SelectedSongTarget | null;
  setTarget: Dispatch<SetStateAction<SelectedSongTarget | null>>;
};

const SelectedSongContext = createContext<SelectedSongState | null>(null);

export function SelectedSongProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<SelectedSongTarget | null>(null);
  const value = useMemo(() => ({ target, setTarget }), [target]);
  return <SelectedSongContext.Provider value={value}>{children}</SelectedSongContext.Provider>;
}

export function useSelectedSong(): SelectedSongState {
  const context = useContext(SelectedSongContext);
  if (context === null) throw new Error("SelectedSongProvider is required");
  return context;
}
