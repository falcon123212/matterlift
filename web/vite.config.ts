import { defineConfig } from "vite";

// In dev the API runs on API_PORT (default 8001); VITE_API_URL overrides it for a deployed front.
const api = `http://localhost:${process.env.API_PORT ?? "8001"}`;

export default defineConfig({
  base: "./",
  server: { port: 5173, proxy: { "/materials": api, "/libraries": api, "/understand": api, "/health": api } },
});
