import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "../server/routepass/static", emptyOutDir: true, chunkSizeWarningLimit: 700 },
  server: {
    proxy: { "/api": "http://localhost:8000", "/mcp": "http://localhost:8000" },
  },
});
