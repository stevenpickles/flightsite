import { vi } from "vitest";

import type { AircraftDetail } from "@/lib/api/aircraft";
import type { ReceiverInfo } from "@/lib/api/live";
import type {
  SightingDetail,
  SightingListResponse,
  SightingRow,
} from "@/lib/api/sightings";

import { aircraftDetail, defaultReceiverInfo } from "@/test/aircraftApiMock";

/** A `SightingRow`, defaulting to a fully-resolved, closed example —
 * override just the fields a test cares about. */
export function sightingRow(overrides: Partial<SightingRow> = {}): SightingRow {
  return {
    id: 88213,
    icao: "ae1463",
    callsign: "RCH492",
    registration: "N302DN",
    aircraft_type: "B738",
    model: "Boeing 737-800",
    operator: "Delta Air Lines",
    operator_group: "Delta Air Lines",
    classification: null,
    started_at: "2026-08-30T22:02:10.000Z",
    ended_at: "2026-08-30T22:41:55.000Z",
    duration_s: 2385,
    closure_reason: "gap_timeout",
    closest_approach_nm: 11.2,
    max_range_nm: 96.0,
    lowest_altitude_ft: 21000,
    highest_altitude_ft: 28000,
    position_count: 2210,
    had_emergency: false,
    max_alert_severity: null,
    provenance: {},
    ...overrides,
  };
}

/** A `SightingDetail`, defaulting to a fully-resolved, closed example with a
 * short two-point path and one event. */
export function sightingDetail(
  overrides: Partial<SightingDetail> = {},
): SightingDetail {
  return {
    id: 88213,
    icao: "ae1463",
    callsign: "RCH492",
    squawk: "4521",
    started_at: "2026-08-30T22:02:10.000Z",
    ended_at: "2026-08-30T22:41:55.000Z",
    duration_s: 2385,
    closure_reason: "gap_timeout",
    route: {
      origin: "KTCM",
      destination: "PHIK",
      origin_name: "Tacoma McChord Field",
      destination_name: "Hickam Air Force Base",
    },
    reception: {
      rssi_peak_db: -3.2,
      rssi_avg_db: -11.8,
      rssi_min_db: -27.4,
      message_count: 48210,
      position_count: 2210,
      pct_with_position: 92.4,
    },
    records: {
      closest_approach_nm: 11.2,
      max_range_nm: 96.0,
      lowest_altitude_ft: 21000,
      highest_altitude_ft: 28000,
    },
    events: [
      {
        at: "2026-08-30T22:14:31.000Z",
        type: "route_enriched",
        detail: { source: "aerodatabox", origin: "KTCM", destination: "PHIK" },
      },
    ],
    path: [
      {
        t: "2026-08-30T22:02:10.000Z",
        lat: 47.11,
        lon: -121.8,
        altitude_ft: 21000,
        source: "adsb",
      },
      {
        t: "2026-08-30T22:03:42.000Z",
        lat: 47.19,
        lon: -121.88,
        altitude_ft: 21850,
        source: "adsb",
      },
    ],
    provenance: { route: "aerodatabox" },
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export interface MockSightingsApiOptions {
  /** Response `GET /api/v1/sightings` returns — a fixed document, or a
   * function of the parsed request URL for tests that vary the result by
   * filter/sort/page. */
  list?: SightingListResponse | ((url: URL) => SightingListResponse);
  /** `id -> SightingDetail`; an id with no entry 404s. */
  detail?: Record<number, SightingDetail>;
  /** Response `GET /api/v1/aircraft/{icao}/sightings` returns, keyed by icao. */
  aircraftSightings?: Record<string, SightingListResponse>;
  /** `icao -> AircraftDetail`, for the detail page's registration lookup. */
  aircraft?: Record<string, AircraftDetail>;
  receiver?: ReceiverInfo;
}

const EMPTY_LIST: SightingListResponse = {
  items: [],
  total: null,
  limit: 50,
  offset: 0,
};

/** Installs a `global.fetch` stub serving the Sightings endpoints plus
 * `GET /api/v1/receiver` and `GET /api/v1/aircraft/{icao}` (the detail
 * page's registration lookup), so Sightings page/detail tests can exercise
 * the real API clients and TanStack Query hooks without a running backend.
 * Any other URL throws, surfacing an un-mocked request as a test failure. */
export function installSightingsApiMock(options: MockSightingsApiOptions = {}) {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const raw = typeof input === "string" ? input : input.toString();
      const method = (init?.method ?? "GET").toUpperCase();
      const url = new URL(raw, "http://localhost");

      if (url.pathname === "/api/v1/receiver" && method === "GET") {
        return jsonResponse(options.receiver ?? defaultReceiverInfo());
      }

      const aircraftSightingsMatch =
        /^\/api\/v1\/aircraft\/([0-9a-f]{6})\/sightings$/.exec(url.pathname);
      if (aircraftSightingsMatch && method === "GET") {
        const icao = aircraftSightingsMatch[1] as string;
        return jsonResponse(options.aircraftSightings?.[icao] ?? EMPTY_LIST);
      }

      const aircraftDetailMatch = /^\/api\/v1\/aircraft\/([0-9a-f]{6})$/.exec(
        url.pathname,
      );
      if (aircraftDetailMatch && method === "GET") {
        const icao = aircraftDetailMatch[1] as string;
        const detail = options.aircraft?.[icao];
        if (detail === undefined) {
          return jsonResponse(
            {
              error: {
                code: "not_found",
                message: `No aircraft with ICAO ${icao}`,
                detail: null,
              },
            },
            404,
          );
        }
        return jsonResponse(detail);
      }

      if (url.pathname === "/api/v1/sightings" && method === "GET") {
        const body =
          typeof options.list === "function"
            ? options.list(url)
            : (options.list ?? EMPTY_LIST);
        return jsonResponse(body);
      }

      const detailMatch = /^\/api\/v1\/sightings\/(\d+)$/.exec(url.pathname);
      if (detailMatch && method === "GET") {
        const id = Number(detailMatch[1]);
        const detail = options.detail?.[id];
        if (detail === undefined) {
          return jsonResponse(
            {
              error: {
                code: "not_found",
                message: `No sighting with id ${id}`,
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

export { aircraftDetail };
