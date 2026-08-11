import react from "@vitejs/plugin-react";
// defineConfig uit vitest/config kent naast de Vite-opties ook het test-blok.
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    // In ontwikkeling draait Vite apart van de server; de proxy zorgt dat de
    // app dezelfde relatieve API-paden gebruikt als in productie.
    proxy: {
      "/api": {
        target: process.env.BOOKPAL_API ?? "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
});
