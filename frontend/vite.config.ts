/// <reference types="vitest/config" />
import path from "node:path";
import { fileURLToPath } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

import { serviceWorkerPlugin } from "./vite-plugins/serviceWorker.ts";

const rootDir = path.dirname(fileURLToPath(import.meta.url));

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    // Production builds only: emits dist/sw.js with the app shell's
    // precache list injected (roadmap slice 084, src/sw/).
    serviceWorkerPlugin({
      entry: path.resolve(rootDir, "src/sw/sw.ts"),
      srcDir: path.resolve(rootDir, "src"),
    }),
  ],
  resolve: {
    alias: {
      "@": path.resolve(rootDir, "./src"),
    },
  },
  server: {
    proxy: {
      // Forwards the internal (§5) and v1 APIs to a locally-running
      // backend (`cd backend && uv run fastapi dev`) so `npm run dev`
      // exercises real config/decoder-test/live data without a separate
      // reverse proxy in front of the dev server. Production instead runs
      // both containers behind the deployment's own proxy (docs/DEVELOPMENT.md).
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        // The live picture is a WebSocket (`/api/v1/ws/live`); without this
        // the upgrade never reaches the backend and the map stays on
        // "Connecting" under `npm run dev`.
        ws: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
    css: true,
    coverage: {
      provider: "v8",
      reporter: ["text", "html", "lcov"],
      reportsDirectory: "./coverage",
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/main.tsx",
        // Event wiring only; its logic is in the tested src/sw modules.
        "src/sw/sw.ts",
        "src/vite-env.d.ts",
        "src/test/**",
        "src/**/*.d.ts",
        "src/**/index.ts",
      ],
      thresholds: {
        lines: 70,
        statements: 70,
        functions: 70,
        branches: 70,
      },
    },
  },
});
