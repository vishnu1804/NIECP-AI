import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build into `static` (served by FastAPI). `dist` is excluded from workspace
// snapshots, so a stable output directory keeps the built app persistent.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "static",
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ["react", "react-dom", "react-router-dom"],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8899",
    },
  },
});
