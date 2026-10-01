/**
 * Builds FlightSite's service worker (`src/sw/sw.ts`) into `dist/sw.js` with
 * the list of files to precache injected (roadmap slice 084, issue #227).
 *
 * A small hand-written plugin instead of `vite-plugin-pwa`/Workbox: the
 * worker's whole job is a fixed precache list plus three routing rules
 * (`src/sw/routing.ts`), and owning those rules outright is what lets them
 * be unit-tested and read in one place — in particular the guarantee that
 * `/api/`, `/ws/`, map tiles and cross-origin requests are never touched.
 * No new dependency, nothing new in `docs/LICENSES.md`.
 *
 * How, at the end of `vite build` (`closeBundle`, after every file —
 * `public/` included — is written):
 *
 * 1. walk `dist/` and pick the shell with `selectShellFiles`
 *    (`src/sw/precache.ts`): `index.html`, `assets/**`, icons, manifest,
 *    favicon;
 * 2. hash those paths and their bytes into a version string, so any change
 *    to the shell changes `sw.js`'s bytes — which is what makes the browser
 *    install the new worker — and names a fresh cache;
 * 3. run a second, config-less Vite build of `src/sw/sw.ts` as a classic
 *    IIFE script at `dist/sw.js`, with `__SW_PRECACHE__` and
 *    `__SW_VERSION__` defined.
 *
 * Build-only (`apply: "build"`): `npm run dev` and vitest never produce or
 * register a worker.
 */

import { createHash } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { build, type Plugin } from "vite";

import { selectShellFiles } from "../src/sw/precache.ts";

/** Every file under `dir`, as POSIX paths relative to it. */
function listFiles(dir: string, prefix = ""): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const relative = prefix === "" ? entry.name : `${prefix}/${entry.name}`;
    if (entry.isDirectory()) {
      files.push(...listFiles(path.join(dir, entry.name), relative));
    } else if (entry.isFile()) {
      files.push(relative);
    }
  }
  return files;
}

export function serviceWorkerPlugin({
  entry,
  srcDir,
}: {
  /** Absolute path of the worker's TypeScript entry. */
  entry: string;
  /** Absolute path the `@/` alias resolves to. */
  srcDir: string;
}): Plugin {
  let outDir = "";
  let root = "";

  return {
    name: "flightsite-service-worker",
    apply: "build",
    configResolved(config) {
      root = config.root;
      outDir = path.resolve(config.root, config.build.outDir);
    },
    async closeBundle() {
      const shell = selectShellFiles(listFiles(outDir));
      const hash = createHash("sha256");
      for (const url of shell) {
        hash.update(url);
        hash.update(readFileSync(path.join(outDir, url.slice(1))));
      }
      const version = hash.digest("hex").slice(0, 16);

      await build({
        configFile: false,
        root,
        logLevel: "warn",
        publicDir: false,
        resolve: { alias: { "@": srcDir } },
        define: {
          __SW_PRECACHE__: JSON.stringify(shell),
          __SW_VERSION__: JSON.stringify(version),
        },
        build: {
          outDir,
          emptyOutDir: false,
          copyPublicDir: false,
          sourcemap: false,
          lib: {
            entry,
            formats: ["iife"],
            name: "flightsiteServiceWorker",
            fileName: () => "sw.js",
          },
        },
      });

      console.log(
        `[service-worker] dist/sw.js: ${shell.length} shell files precached, version ${version}`,
      );
    },
  };
}
