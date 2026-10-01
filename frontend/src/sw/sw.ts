/**
 * FlightSite's service worker (roadmap slice 084, issue #227): precaches the
 * built app shell so the app installs and opens offline, and otherwise
 * stays out of the way.
 *
 * This file is only wiring. The decisions live in pure, unit-tested
 * modules: `routing.ts` (what a request gets — and the rule that `/api/`,
 * `/ws/`, tiles and every cross-origin request are never intercepted),
 * `strategies.ts` (precache, cleanup, cache-first shell, network-first
 * navigation) and `precache.ts` (which built files count as the shell).
 *
 * Built separately from the app, as a classic (non-module) script at
 * `/sw.js`, by `vite-plugins/serviceWorker.ts`, which also defines the two
 * build-time constants below from the finished `dist/` tree. Type-checked by
 * `tsconfig.sw.json` against the WebWorker library rather than the DOM one.
 *
 * Update flow: a new build installs beside the running one and then waits.
 * It never calls `skipWaiting` on its own; the page asks it to
 * (`SKIP_WAITING_MESSAGE`) only when the user accepts the "new version"
 * prompt, and only an activation the user asked for claims open clients.
 */

import { isSkipWaitingMessage } from "@/sw/messages";
import {
  deleteStaleShellCaches,
  handleFetch,
  precacheShell,
  type SwDeps,
} from "@/sw/strategies";

declare const self: ServiceWorkerGlobalScope;

/** The shell's URL paths, from `precache.ts`'s `selectShellFiles`. */
declare const __SW_PRECACHE__: string[];
/** A hash of the shell's paths and contents: this build's cache name. */
declare const __SW_VERSION__: string;

const deps: SwDeps = {
  caches: self.caches,
  fetch: (request) => self.fetch(request),
};

const context = {
  origin: self.location.origin,
  shellPaths: new Set(__SW_PRECACHE__),
};

/** Set when the user accepted the update prompt; see the module comment. */
let claimOnActivate = false;

self.addEventListener("install", (event) => {
  event.waitUntil(precacheShell(deps, __SW_VERSION__, __SW_PRECACHE__));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      await deleteStaleShellCaches(deps, __SW_VERSION__);
      if (claimOnActivate) {
        await self.clients.claim();
      }
    })(),
  );
});

self.addEventListener("message", (event) => {
  if (isSkipWaitingMessage(event.data)) {
    claimOnActivate = true;
    void self.skipWaiting();
  }
});

self.addEventListener("fetch", (event) => {
  const response = handleFetch(event.request, context, deps, __SW_VERSION__);
  // `null` is a passthrough: no `respondWith`, so the browser performs the
  // request itself exactly as it would with no worker installed.
  if (response !== null) {
    event.respondWith(response);
  }
});
