/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync, existsSync } from "node:fs";

// One VERSION file for backend, frontend and releases: repo root in a checkout,
// /VERSION inside the Docker build stage.
const versionFile = ["../../VERSION", "/VERSION"].find((f) => existsSync(f));
const appVersion = versionFile ? readFileSync(versionFile, "utf8").trim() : "0.0.0";

export default defineConfig({
  define: { __APP_VERSION__: JSON.stringify(appVersion) },
  plugins: [react()],
  server: {
    port: 5176,
    proxy: {
      "/api": {
        target: "http://localhost:8003",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.js"],
    css: false,
  },
});
