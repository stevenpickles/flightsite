/**
 * Which built files the service worker precaches (roadmap slice 084) — run
 * at build time by `vite-plugins/serviceWorker.ts` over the finished
 * `dist/` tree, and pure so it is unit-tested beside the routing it feeds.
 *
 * The shell is the app itself and nothing else: `index.html`, the hashed
 * build output under `assets/` (JS, CSS, fonts, images — every one of them
 * content-addressed, so a cached copy can never be stale), and the install
 * surface (manifest, favicon, icons). Deliberately left out:
 *
 * - `sw.js` — the worker never caches itself; the browser's own update
 *   check has to see the real file.
 * - `*.mjs` at the site root — MapLibre's worker scripts, copied un-hashed
 *   by `scripts/copy-maplibre-worker.mjs` and served `no-cache` by nginx; a
 *   cached copy could go out of step with the bundled library after an
 *   upgrade, and without tiles the map is not usable offline anyway (SPEC
 *   §32 keeps offline tiles out of scope).
 * - source maps, and anything else not listed above.
 */

const SHELL_ROOT_FILES = new Set([
  "index.html",
  "manifest.webmanifest",
  "favicon.svg",
]);

const SHELL_DIRECTORIES = ["assets/", "icons/"];

/**
 * Maps `dist`-relative POSIX paths to the sorted URL paths to precache.
 * Sorted so the list — and the version hash derived from it — is stable
 * across builds of the same output.
 */
export function selectShellFiles(relativePaths: readonly string[]): string[] {
  return relativePaths
    .filter((file) => {
      if (file.endsWith(".map")) {
        return false;
      }
      if (SHELL_ROOT_FILES.has(file)) {
        return true;
      }
      return SHELL_DIRECTORIES.some((dir) => file.startsWith(dir));
    })
    .map((file) => `/${file}`)
    .sort();
}
