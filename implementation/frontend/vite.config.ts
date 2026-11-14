import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@config": path.resolve(__dirname, "../config"),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    allowedHosts: true,
    proxy: {
      "/api": {
        // Server-side routing only; never expose credentials through VITE_*.
        target: process.env.VCC_PREVIEW_API_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        ws: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
});
