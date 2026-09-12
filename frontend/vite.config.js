import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: `npm run dev` on :5173, proxies /api to the FastAPI backend on :8000.
// Build: emits to ../static, which app.py serves.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8000" },
  },
  build: {
    outDir: "../static",
    emptyOutDir: true,
  },
});
