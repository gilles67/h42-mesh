// Vite: development server and build; Vitest (tests) reads the same file.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Local controller (uvicorn), see CLAUDE.md.
const CONTROLLER = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    // /api goes to the controller: same origin for the browser, as in
    // production behind Traefik, so the session cookie works.
    proxy: { "/api": CONTROLLER },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
