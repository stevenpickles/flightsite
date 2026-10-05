import { vi } from "vitest";

import type { AircraftDetail } from "@/lib/api/aircraft";
import type {
  AnalyticsCountsResponse,
  AnalyticsPreset,
  AnalyticsSeenAircraftRow,
  AnalyticsSeenTypeRow,
  AnalyticsWindow,
} from "@/lib/api/analytics";
import type { ReceiverInfo } from "@/lib/api/live";
import type {
  SightingDetail,
  SightingListResponse,
  SightingRow,
} from "@/lib/api/sightings";

import { aircraftDetail, defaultReceiverInfo } from "@/test/aircraftApiMock";

/**
 * `open` / `elapsed_s` (§3.7) derived from whatever `ended_at` the test
 * asked for, unless the test named them itself.
 *
 * Without this, `sightingRow({ ended_at: null })` would produce a row the
 * server could never send — open by its `ended_at` and closed by its `open`
 * flag — and every test of open-sighting rendering would be testing a shape
 * that does not exist.
 */
function openFields(
  endedAt: string | null,
  overrides: { open?: boolean; elapsed_s?: number | null },
): { open: boolean; elapsed_s: number | null } {
  const open = overrides.open ?? endedAt === null;
  return {
    open,
    elapsed_s: overrides.elapsed_s ?? (open ? 964 : null),
  };
}

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
    ...openFields(
      overrides.ended_at === undefined
        ? "2026-08-30T22:41:55.000Z"
        : overrides.ended_at,
      overrides,
    ),
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
    ...openFields(
      overrides.ended_at === undefined
        ? "2026-08-30T22:41:55.000Z"
        : overrides.ended_at,
      overrides,
    ),
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
  /** Serve an error envelope from `GET /api/v1/sightings` instead — a fixed
   * status, or a function of the request URL returning `null` to let the
   * normal `list` response through, which is how a test fails a *refresh*
   * rather than the first load (review R2-04). */
  listStatus?: number | ((url: URL) => number | null);
  /** The same, for `GET /api/v1/sightings/{id}`. */
  detailStatus?: number | ((id: number) => number | null);
  /** `id -> SightingDetail`; an id with no entry 404s. */
  detail?: Record<number, SightingDetail>;
  /** Response `GET /api/v1/aircraft/{icao}/sightings` returns, keyed by icao. */
  aircraftSightings?: Record<string, SightingListResponse>;
  /** `icao -> AircraftDetail`, for the detail page's registration lookup. */
  aircraft?: Record<string, AircraftDetail>;
  receiver?: ReceiverInfo;
  /** `GET /api/v1/analytics/counts` — the Sightings page's summary line
   * (slice 098). Defaults to zeros for the requested preset. */
  counts?:
    | Partial<Omit<AnalyticsCountsResponse, "window">>
    | ((url: URL) => Partial<Omit<AnalyticsCountsResponse, "window">>);
  /** `GET /api/v1/analytics/aircraft` — the aircraft grouping. */
  seenAircraft?:
    AnalyticsSeenAircraftRow[] | ((url: URL) => AnalyticsSeenAircraftRow[]);
  /** `GET /api/v1/analytics/types` — the type grouping. */
  seenTypes?: AnalyticsSeenTypeRow[] | ((url: URL) => AnalyticsSeenTypeRow[]);
}

/** The window block a "what the window held" response echoes for a preset. */
function mockWindow(url: URL): AnalyticsWindow {
  const preset = (url.searchParams.get("preset") ?? "today") as AnalyticsPreset;
  return {
    preset,
    from: "2026-08-31T07:00:00.000Z",
    to: "2026-09-01T07:00:00.000Z",
    first_day: "2026-08-31",
    last_day: "2026-08-31",
    timezone: "America/Los_Angeles",
  };
}

/** A distinct-aircraft row for the aircraft grouping. */
export function seenAircraftRow(
  overrides: Partial<AnalyticsSeenAircraftRow> = {},
): AnalyticsSeenAircraftRow {
  return {
    icao: "a1b2c3",
    registration: "N228BZ",
    type: "BCS3",
    model: "Airbus A220-300",
    operator: "Breeze Airways",
    owner: null,
    operator_group: "Breeze",
    classification: "commercial_passenger",
    military: false,
    government: false,
    law_enforcement: false,
    sightings: 4,
    first_seen_at: "2026-08-02T14:10:03.000Z",
    last_seen_at: "2026-08-31T18:41:20.000Z",
    max_range_nm: 201.4,
    new: false,
    ...overrides,
  };
}

/** A distinct-type row for the type grouping. */
export function seenTypeRow(
  overrides: Partial<AnalyticsSeenTypeRow> = {},
): AnalyticsSeenTypeRow {
  return {
    type: "BCS3",
    description: "Airbus A220-300",
    sightings: 11,
    unique_aircraft: 3,
    first_seen_at: "2026-08-02T14:10:03.000Z",
    last_seen_at: "2026-08-31T18:41:20.000Z",
    new: false,
    ...overrides,
  };
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

      if (url.pathname === "/api/v1/analytics/counts" && method === "GET") {
        const counts =
          typeof options.counts === "function"
            ? options.counts(url)
            : (options.counts ?? {});
        return jsonResponse({
          window: mockWindow(url),
          sightings: 0,
          unique_aircraft: 0,
          unique_types: 0,
          new_aircraft: 0,
          ...counts,
        });
      }
      if (
        (url.pathname === "/api/v1/analytics/aircraft" ||
          url.pathname === "/api/v1/analytics/types") &&
        method === "GET"
      ) {
        const source =
          url.pathname === "/api/v1/analytics/aircraft"
            ? options.seenAircraft
            : options.seenTypes;
        const items =
          typeof source === "function" ? source(url) : (source ?? []);
        return jsonResponse({
          window: mockWindow(url),
          items,
          total: items.length,
          limit: Number(url.searchParams.get("limit") ?? 50),
          offset: Number(url.searchParams.get("offset") ?? 0),
        });
      }

      if (url.pathname === "/api/v1/sightings" && method === "GET") {
        const status =
          typeof options.listStatus === "function"
            ? options.listStatus(url)
            : (options.listStatus ?? null);
        if (status !== null) {
          return jsonResponse(
            {
              error: {
                code: "internal_error",
                message: "The sightings log is unavailable",
                detail: null,
              },
            },
            status,
          );
        }
        const body =
          typeof options.list === "function"
            ? options.list(url)
            : (options.list ?? EMPTY_LIST);
        return jsonResponse(body);
      }

      const detailMatch = /^\/api\/v1\/sightings\/(\d+)$/.exec(url.pathname);
      if (detailMatch && method === "GET") {
        const id = Number(detailMatch[1]);
        const detailStatus =
          typeof options.detailStatus === "function"
            ? options.detailStatus(id)
            : (options.detailStatus ?? null);
        if (detailStatus !== null) {
          return jsonResponse(
            {
              error: {
                code: "internal_error",
                message: "This sighting is unavailable",
                detail: null,
              },
            },
            detailStatus,
          );
        }
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
