import type { FeatureCollection } from "geojson";
import { vi } from "vitest";

import type { SightingDetail, SightingListResponse } from "@/lib/api/sightings";

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
  /** Response `GET /api/v1/sightings` returns — the selected aircraft's open
   * sighting lookup (roadmap slice 061). Defaults to no sightings, which is
   * the "aircraft just appeared, nothing checkpointed yet" case and the one
   * every test that never selects an aircraft is in anyway. */
  sightings?: SightingListResponse | ((url: URL) => SightingListResponse);
  /** `id -> SightingDetail` for `GET /api/v1/sightings/{id}`; an id with no
   * entry 404s. */
  sightingDetail?: Record<number, SightingDetail>;
}

/** The `GET /api/v1/sightings` default: no open sighting for anything. */
const EMPTY_SIGHTING_LIST: SightingListResponse = {
  items: [],
  total: null,
  limit: 1,
  offset: 0,
};

/** Installs a `global.fetch` stub serving `GET /api/v1/airports` and
 * `GET /api/v1/airspace` (roadmap slice 028), plus the two sightings reads the
 * Live Map itself makes when an aircraft is selected — `GET /api/v1/sightings`
 * and `GET /api/v1/sightings/{id}`, which back the track backfill (roadmap
 * slice 061) — so map tests can exercise the real API clients and TanStack
 * Query hooks without a running backend. Any other URL throws, surfacing an
 * un-mocked request as a test failure instead of a silent network error. */
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

      if (url.pathname === "/api/v1/sightings" && method === "GET") {
        const body =
          typeof options.sightings === "function"
            ? options.sightings(url)
            : (options.sightings ?? EMPTY_SIGHTING_LIST);
        return jsonResponse(body);
      }

      const sightingDetailMatch = /^\/api\/v1\/sightings\/(\d+)$/.exec(
        url.pathname,
      );
      if (sightingDetailMatch && method === "GET") {
        const detail = options.sightingDetail?.[Number(sightingDetailMatch[1])];
        if (detail === undefined) {
          return jsonResponse(
            {
              error: {
                code: "not_found",
                message: `No sighting with id ${sightingDetailMatch[1]}`,
                detail: null,
              },
            },
            404,
          );
        }
        return jsonResponse(detail);
      }

      throw new Error(`Unhandled fetch in test: ${method} ${raw}`);
    },
  );

  vi.stubGlobal("fetch", fetchMock);

  return { fetchMock };
}
