import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  build: {
    // OpenSheetMusicDisplay is intentionally bundled with the offline desktop client.
    // Keep the threshold explicit so unexpected growth above the current dependency envelope warns.
    chunkSizeWarningLimit: 1600,
  },
  server: {
    port: 5173,
    strictPort: true,
  },
});
