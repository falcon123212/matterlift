import { defineConfig } from "vite";

// In dev the API runs on :8000; VITE_API_URL overrides it for a deployed front.
export default defineConfig({
  base: "./",
  server: { port: 5173, proxy: { "/materials": "http://localhost:8000", "/health": "http://localhost:8000" } },
});
