import path from "node:path";
import branding from "../config/branding.json";
import developmentBackends from "../config/development-backends.json";
import { developmentApiTarget } from "./dev/backendRouting";

const escapeHtml = (value: string): string => value.replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]!);
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const apiProxy = {
  "/api": {
    // One backend identity for both development and built-app preview.
    target: developmentApiTarget(process.env.VCC_PREVIEW_API_TARGET ?? "http://127.0.0.1:8000", developmentBackends),
    changeOrigin: true,
    ws: true,
  },
};

export default defineConfig({
  plugins: [react(), {
    name: "configured-branding",
    transformIndexHtml(html) {
      return html.replaceAll("__PRODUCT_NAME__", () => escapeHtml(branding.productName))
        .replaceAll("__PRODUCT_DESCRIPTION__", () => escapeHtml(`${branding.productName} — ${branding.tagline}`));
    },
  }],
  resolve: {
    alias: {
      "@config": path.resolve(__dirname, "../config"),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    allowedHosts: ['.trycloudflare.com'],
    proxy: apiProxy,
  },
  preview: {
    proxy: apiProxy,
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
});
