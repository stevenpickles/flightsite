import type { FeatureCollection } from "geojson";
import { vi } from "vitest";

/** An empty `FeatureCollection` — the default response for both endpoints,
 * matching what a stock backend answers (an empty `airports` table, or no
 * `airspace.geojson` supplied). */
export const EMPTY_FEATURE_COLLECTION: FeatureCollection = {
  type: "FeatureCollection",
  features: [],
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export interface MockOverlaysApiOptions {
  /** Response `GET /api/v1/airports` returns — a fixed document, or a
   * function of the parsed request URL for tests that vary the result by
   * `bbox`/`min_size`. */
  airports?: FeatureCollection | ((url: URL) => FeatureCollection);
  /** Response `GET /api/v1/airspace` returns. */
  airspace?: FeatureCollection;
}

/** Installs a `global.fetch` stub serving `GET /api/v1/airports` and
 * `GET /api/v1/airspace` (roadmap slice 028) so map-overlay tests can
 * exercise the real `lib/api/overlays` client and TanStack Query hooks
 * without a running backend. Any other URL throws, surfacing an un-mocked
 * request as a test failure instead of a silent network error. */
export function installOverlaysApiMock(options: MockOverlaysApiOptions = {}) {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const raw = typeof input === "string" ? input : input.toString();
      const method = (init?.method ?? "GET").toUpperCase();
      const url = new URL(raw, "http://localhost");

      if (url.pathname === "/api/v1/airports" && method === "GET") {
        const body =
          typeof options.airports === "function"
            ? options.airports(url)
            : (options.airports ?? EMPTY_FEATURE_COLLECTION);
        return jsonResponse(body);
      }

      if (url.pathname === "/api/v1/airspace" && method === "GET") {
        return jsonResponse(options.airspace ?? EMPTY_FEATURE_COLLECTION);
      }

      throw new Error(`Unhandled fetch in test: ${method} ${raw}`);
    },
  );

  vi.stubGlobal("fetch", fetchMock);

  return { fetchMock };
}
