import { vi } from "vitest";

import type {
  AircraftDetail,
  AircraftListResponse,
  AircraftListRow,
} from "@/lib/api/aircraft";
import type { ReceiverInfo } from "@/lib/api/live";
import type { SightingListResponse } from "@/lib/api/sightings";

/** An `AircraftListRow`, defaulting to a fully-resolved example — override
 * just the fields a test cares about. */
export function aircraftListRow(
  overrides: Partial<AircraftListRow> = {},
): AircraftListRow {
  return {
    icao: "ae1463",
    registration: "N302DN",
    aircraft_type: "B738",
    model: "Boeing 737-800",
    operator: "Delta Air Lines",
    operator_group: "Delta Air Lines",
    classification: null,
    first_seen: "2026-04-02T18:11:09.000Z",
    last_seen: "2026-08-30T22:41:55.000Z",
    sighting_count: 41,
    closest_approach_nm: 2.1,
    max_range_nm: 141.8,
    provenance: {},
    ...overrides,
  };
}

/** An `AircraftDetail`, defaulting to a fully-resolved, non-live example. */
export function aircraftDetail(
  overrides: Partial<AircraftDetail> = {},
): AircraftDetail {
  return {
    icao: "ae1463",
    registration: "N302DN",
    aircraft_type: "B738",
    model: "Boeing 737-800",
    manufacture_year: 2018,
    operator: "Delta Air Lines",
    operator_group: "Delta Air Lines",
    owner: null,
    classification: null,
    live: false,
    lifetime: {
      first_seen: "2026-04-02T18:11:09.000Z",
      last_seen: "2026-08-30T22:41:55.000Z",
      sighting_count: 41,
      cumulative_duration_s: 51_840,
      closest_approach_nm: 2.1,
      max_range_nm: 141.8,
      lowest_altitude_ft: 1250,
      highest_altitude_ft: 41_000,
    },
    provenance: {},
    ...overrides,
  };
}

export function defaultReceiverInfo(
  overrides: Partial<ReceiverInfo> = {},
): ReceiverInfo {
  return {
    site_name: "Test Site",
    latitude: 47.62,
    longitude: -122.35,
    antenna_height_ft: 30,
    timezone: "UTC",
    units: "aviation",
    display_radius_nm: 250,
    alert_radius_nm: null,
    demo_mode: false,
    t0: null,
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export interface MockAircraftApiOptions {
  /** Response `GET /api/v1/aircraft` returns — a fixed document, or a
   * function of the parsed request URL for tests that vary the result by
   * `sort`/`order`/`limit`/`offset`. */
  list?: AircraftListResponse | ((url: URL) => AircraftListResponse);
  /** `icao -> AircraftDetail`; an address with no entry 404s the same way
   * the real endpoint does for an address never sighted. */
  detail?: Record<string, AircraftDetail>;
  /** Response `GET /api/v1/aircraft/{icao}/sightings` returns, keyed by
   * icao — the aircraft detail page's "recent sightings" section (roadmap
   * slice 030). An icao with no entry answers an empty list, the same as
   * the real endpoint for an address with no sightings. */
  aircraftSightings?: Record<string, SightingListResponse>;
  receiver?: ReceiverInfo;
}

const EMPTY_LIST: AircraftListResponse = {
  items: [],
  total: 0,
  limit: 50,
  offset: 0,
};

const EMPTY_SIGHTINGS_LIST: SightingListResponse = {
  items: [],
  total: null,
  limit: 5,
  offset: 0,
};

/** Installs a `global.fetch` stub serving `GET /api/v1/aircraft`,
 * `GET /api/v1/aircraft/{icao}`, `GET /api/v1/aircraft/{icao}/sightings`
 * and `GET /api/v1/receiver` so Aircraft page/detail tests can exercise the
 * real `lib/api/aircraft` + `lib/api/sightings` + `lib/api/receiver`
 * clients and TanStack Query hooks without a running backend. Any other URL
 * throws, surfacing an un-mocked request as a test failure instead of a
 * silent network error. */
export function installAircraftApiMock(options: MockAircraftApiOptions = {}) {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const raw = typeof input === "string" ? input : input.toString();
      const method = (init?.method ?? "GET").toUpperCase();
      const url = new URL(raw, "http://localhost");

      if (url.pathname === "/api/v1/receiver" && method === "GET") {
        return jsonResponse(options.receiver ?? defaultReceiverInfo());
      }

      if (url.pathname === "/api/v1/aircraft" && method === "GET") {
        const body =
          typeof options.list === "function"
            ? options.list(url)
            : (options.list ?? EMPTY_LIST);
        return jsonResponse(body);
      }

      const sightingsMatch =
        /^\/api\/v1\/aircraft\/([0-9a-f]{6})\/sightings$/.exec(url.pathname);
      if (sightingsMatch && method === "GET") {
        const icao = sightingsMatch[1] as string;
        return jsonResponse(
          options.aircraftSightings?.[icao] ?? EMPTY_SIGHTINGS_LIST,
        );
      }

      const detailMatch = /^\/api\/v1\/aircraft\/([0-9a-f]{6})$/.exec(
        url.pathname,
      );
      if (detailMatch && method === "GET") {
        const icao = detailMatch[1] as string;
        const detail = options.detail?.[icao];
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

      throw new Error(`Unhandled fetch in test: ${method} ${raw}`);
    },
  );

  vi.stubGlobal("fetch", fetchMock);

  return { fetchMock };
}
