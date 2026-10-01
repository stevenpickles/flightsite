/**
 * The service worker's fetch routing (roadmap slice 084, issue #227) — the
 * single decision of what the worker does with a request, as a pure
 * function so the rules are unit-tested without a service worker runtime.
 *
 * The worker exists to make FlightSite installable and to open its shell
 * offline; it must never stand between the app and live data. So the rules
 * are an **allowlist**: the worker answers only
 *
 * - `shell` — a GET for one of the exact same-origin paths the build
 *   precached (`index.html` and the hashed JS/CSS/fonts/icons under
 *   `/assets/`, plus the manifest and icons): served cache-first, since a
 *   hashed filename's content never changes; and
 * - `navigation` — a same-origin page load: network-first, falling back to
 *   the precached `index.html` only when the network fails, so a deploy is
 *   picked up on the next load and an offline load still opens the app.
 *
 * Everything else is `passthrough`: the worker does not call `respondWith`
 * at all, so the browser handles the request exactly as if no worker were
 * installed. That covers, explicitly and ahead of every other rule,
 *
 * - anything under `/api/` or `/ws/` — REST responses, the live WebSocket
 *   (`/api/v1/ws/live`), and any page navigation into them (the API docs);
 * - every cross-origin request — basemap tiles, glyphs and sprites
 *   (OpenFreeMap, OSM; SPEC §32 keeps offline tiles out of scope), external
 *   tracker links;
 * - every non-GET request.
 *
 * and, by default, any same-origin path the build did not list, such as the
 * un-hashed MapLibre worker scripts at the site root.
 */

export type SwRoute = "passthrough" | "navigation" | "shell";

/** The parts of a `Request` the routing reads — a structural subset, so
 * tests can pass plain objects. */
export interface RoutableRequest {
  url: string;
  method: string;
  mode: string;
}

export interface RoutingContext {
  /** The worker's own origin (`self.location.origin`). */
  origin: string;
  /** The precached shell's paths, e.g. `/index.html`,
   * `/assets/index-abc123.js`. */
  shellPaths: ReadonlySet<string>;
}

/** Path prefixes the worker never answers, whatever the request. A bare
 * `/api` or `/ws` (no trailing slash) is matched too. */
export const NEVER_CACHED_PREFIXES: readonly string[] = ["/api/", "/ws/"];

/** The precached document every navigation falls back to offline. */
export const SHELL_DOCUMENT = "/index.html";

function isNeverCached(pathname: string): boolean {
  return NEVER_CACHED_PREFIXES.some(
    (prefix) => pathname.startsWith(prefix) || pathname === prefix.slice(0, -1),
  );
}

export function routeRequest(
  request: RoutableRequest,
  context: RoutingContext,
): SwRoute {
  if (request.method !== "GET") {
    return "passthrough";
  }
  let url: URL;
  try {
    url = new URL(request.url);
  } catch {
    return "passthrough";
  }
  if (url.origin !== context.origin) {
    return "passthrough";
  }
  if (isNeverCached(url.pathname)) {
    return "passthrough";
  }
  if (request.mode === "navigate") {
    return "navigation";
  }
  // Exact path only: a query string never selects a different shell file,
  // but it must not smuggle a non-shell path in either.
  if (context.shellPaths.has(url.pathname)) {
    return "shell";
  }
  return "passthrough";
}
