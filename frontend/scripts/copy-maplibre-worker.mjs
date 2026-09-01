#!/usr/bin/env node
/**
 * Copies maplibre-gl's worker script into `public/` so Vite serves it at a
 * stable, predictable URL (`/maplibre-gl-worker.mjs`) in both `npm run dev`
 * and the production build.
 *
 * Why this exists: MapLibre GL JS computes its worker URL at runtime as a
 * sibling of its OWN module's `import.meta.url`
 * (`node_modules/maplibre-gl/dist/maplibre-gl-dev.mjs`'s `defaultWorkerUrl`).
 * That assumption holds when the package is loaded as a separate file, but
 * Vite inlines `maplibre-gl` into the app's own bundle — so at runtime
 * `import.meta.url` resolves to the app bundle's own URL
 * (`/assets/index-<hash>.js`), and MapLibre goes looking for
 * `/assets/maplibre-gl-worker.mjs`, which Vite never emits (nothing in the
 * app imports it directly, so there is nothing for the bundler to see and
 * copy). The worker script then 404s, the worker never starts, and without
 * it MapLibre can tile/process GeoJSON sources at all — nothing (range
 * rings, the receiver marker, aircraft) ever renders, in every browser,
 * silently (no thrown error reaches the app).
 *
 * The fix: serve the worker ourselves at a fixed path and tell MapLibre to
 * use it explicitly (`setWorkerUrl`, called once in `MapLibreMap.tsx`)
 * instead of relying on its runtime-relative guess. This script copies the
 * files fresh from whatever `maplibre-gl` version is installed rather than
 * committing a copy to git, so they can never silently drift out of sync
 * with the installed package (a version-mismatched worker can speak a
 * different internal protocol than the main thread). Wired as
 * `predev`/`prebuild` in package.json so it always runs before Vite does.
 *
 * `maplibre-gl-worker.mjs` is not self-contained: it's an ES module that
 * imports shared code from a sibling file, `./maplibre-gl-shared.mjs`
 * (maplibre-gl's own internal chunk split). A module `Worker` resolves that
 * relative import against the worker script's own URL — so it has to sit
 * next to it in `public/` too, or the worker fails to initialize (silently:
 * no error reaches the main thread, the worker is just created and
 * immediately closed). Both files are copied verbatim as a pair for
 * exactly that reason.
 */

import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, "..");

const distDir = path.join(frontendRoot, "node_modules", "maplibre-gl", "dist");
const destDir = path.join(frontendRoot, "public");

// The worker's own import target must keep this exact filename.
const files = ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"];

mkdirSync(destDir, { recursive: true });
for (const file of files) {
  const source = path.join(distDir, file);
  if (!existsSync(source)) {
    console.error(
      `[copy-maplibre-worker] ${source} not found — is maplibre-gl installed (npm install)?`,
    );
    process.exit(1);
  }
  const dest = path.join(destDir, file);
  copyFileSync(source, dest);
  console.log(
    `[copy-maplibre-worker] copied to ${path.relative(frontendRoot, dest)}`,
  );
}
