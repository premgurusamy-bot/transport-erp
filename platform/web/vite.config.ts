import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: the web app proxies /api to the FastAPI backend (no client ever connects to the database).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://localhost:8000" } },
  build: { outDir: "dist", sourcemap: false },
});
