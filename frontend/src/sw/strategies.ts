/**
 * What the service worker does once `routing.ts` has decided (roadmap slice
 * 084): install-time precaching, activate-time cleanup, and the two
 * response strategies. Written against injected `caches` and `fetch` so
 * vitest can drive them with in-memory fakes; `sw.ts` only wires them to
 * the worker's events.
 *
 * One cache per build, named by the build's version hash, so a new deploy
 * installs into a fresh cache beside the old one and the old one is deleted
 * only once the new worker activates — the page on screen keeps its own
 * shell until the user accepts the update.
 */

import {
  routeRequest,
  SHELL_DOCUMENT,
  type RoutingContext,
} from "@/sw/routing";

export interface SwDeps {
  caches: CacheStorage;
  fetch: (request: Request) => Promise<Response>;
}

export const SHELL_CACHE_PREFIX = "flightsite-shell-";

export function shellCacheName(version: string): string {
  return `${SHELL_CACHE_PREFIX}${version}`;
}

/** Install: fetch and store every shell file. `addAll` is atomic — one
 * failed file fails the install, and the previous worker stays in charge
 * rather than a half-cached shell taking over. */
export async function precacheShell(
  deps: SwDeps,
  version: string,
  urls: readonly string[],
): Promise<void> {
  const cache = await deps.caches.open(shellCacheName(version));
  await cache.addAll([...urls]);
}

/** Activate: drop every earlier build's shell cache. Caches this worker did
 * not name with its own prefix are left alone. */
export async function deleteStaleShellCaches(
  deps: SwDeps,
  version: string,
): Promise<void> {
  const current = shellCacheName(version);
  const keys = await deps.caches.keys();
  await Promise.all(
    keys
      .filter((key) => key.startsWith(SHELL_CACHE_PREFIX) && key !== current)
      .map((key) => deps.caches.delete(key)),
  );
}

/** Cache-first for a precached shell file; the network only if the cache
 * has somehow lost it. Nothing fetched here is written back — the shell
 * cache holds exactly what install put there. */
async function serveShell(
  request: Request,
  deps: SwDeps,
  version: string,
): Promise<Response> {
  const cache = await deps.caches.open(shellCacheName(version));
  const hit = await cache.match(request, { ignoreSearch: true });
  return hit ?? deps.fetch(request);
}

/** Network-first for a page load, so a deploy is live on the next
 * navigation; the precached `index.html` only when the network fails. The
 * network response is never cached. */
async function serveNavigation(
  request: Request,
  deps: SwDeps,
  version: string,
): Promise<Response> {
  try {
    return await deps.fetch(request);
  } catch (error) {
    const cache = await deps.caches.open(shellCacheName(version));
    const fallback = await cache.match(SHELL_DOCUMENT);
    if (fallback) {
      return fallback;
    }
    throw error;
  }
}

/**
 * The fetch handler's whole body: a response promise to hand to
 * `respondWith`, or `null` for a passthrough — in which case the worker
 * must not call `respondWith` at all, leaving the request to the browser
 * untouched.
 */
export function handleFetch(
  request: Request,
  context: RoutingContext,
  deps: SwDeps,
  version: string,
): Promise<Response> | null {
  switch (routeRequest(request, context)) {
    case "shell":
      return serveShell(request, deps, version);
    case "navigation":
      return serveNavigation(request, deps, version);
    case "passthrough":
      return null;
  }
}
