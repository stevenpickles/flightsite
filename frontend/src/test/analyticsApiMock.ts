import { vi } from "vitest";

import type {
  AnalyticsAircraftResponse,
  AnalyticsClassificationResponse,
  AnalyticsDailyResponse,
  AnalyticsGroupResponse,
  AnalyticsPreset,
  AnalyticsRarityResponse,
  AnalyticsSummaryResponse,
  AnalyticsWindow,
} from "@/lib/api/analytics";
import type { ReceiverInfo } from "@/lib/api/live";

import { defaultReceiverInfo } from "@/test/aircraftApiMock";

/** A plausible `AnalyticsWindow` for the given preset — every test fixture
 * below echoes one, matching what a real response always carries
 * (`docs/API.md` §3.7). */
export function analyticsWindow(
  preset: AnalyticsPreset = "today",
): AnalyticsWindow {
  return {
    preset,
    from: "2026-08-31T00:00:00.000Z",
    to: "2026-09-01T00:00:00.000Z",
    first_day: "2026-08-31",
    last_day: "2026-08-31",
    timezone: "America/Los_Angeles",
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export interface MockAnalyticsApiOptions {
  receiver?: ReceiverInfo;
  summary?: AnalyticsSummaryResponse;
  /** Serve an error envelope from `GET /api/v1/analytics/summary` instead. */
  summaryStatus?: number;
  daily?: AnalyticsDailyResponse;
  classification?: AnalyticsClassificationResponse;
  topAircraft?: AnalyticsAircraftResponse;
  topTypes?: AnalyticsGroupResponse;
  topOperators?: AnalyticsGroupResponse;
  rarity?: AnalyticsRarityResponse;
}

/** A plausible SPEC §59 summary — every key present, matching what a real
 * response always carries. */
export function analyticsSummaryResponse(
  overrides: Partial<AnalyticsSummaryResponse["summary"]> = {},
): AnalyticsSummaryResponse {
  return {
    window: analyticsWindow("today"),
    summary: {
      unique_aircraft: 12,
      new_aircraft: 3,
      sightings: 18,
      interesting: 0,
      military: 1,
      government: 0,
      law_enforcement: 0,
      max_range_nm: 187.4,
      busiest_hour: 14,
      busiest_hour_source: "receiver_metrics_hourly",
      first_sighting_at: "2026-08-31T13:05:00.000Z",
      last_sighting_at: "2026-08-31T20:41:00.000Z",
      new_milestones: 2,
      ...overrides,
    },
  };
}

const EMPTY_SUMMARY: AnalyticsSummaryResponse = {
  window: analyticsWindow(),
  summary: {
    unique_aircraft: 0,
    new_aircraft: 0,
    sightings: 0,
    interesting: 0,
    military: 0,
    government: 0,
    law_enforcement: 0,
    max_range_nm: null,
    busiest_hour: null,
    busiest_hour_source: null,
    first_sighting_at: null,
    last_sighting_at: null,
    new_milestones: 0,
  },
};

const EMPTY_DAILY: AnalyticsDailyResponse = {
  window: analyticsWindow(),
  items: [],
};
const EMPTY_CLASSIFICATION: AnalyticsClassificationResponse = {
  window: analyticsWindow(),
  military: 0,
  government: 0,
  law_enforcement: 0,
  interesting: 0,
  series: [],
};
const EMPTY_AIRCRAFT: AnalyticsAircraftResponse = {
  window: analyticsWindow(),
  items: [],
};
const EMPTY_GROUP: AnalyticsGroupResponse = {
  window: analyticsWindow(),
  items: [],
};
const EMPTY_RARITY: AnalyticsRarityResponse = {
  window: analyticsWindow(),
  never_seen_before: 0,
  rare_max_sightings: 2,
  rare_max_type_aircraft: 2,
  rare_aircraft: [],
  rare_types: [],
};

/** Installs a `global.fetch` stub serving `GET /api/v1/receiver` and every
 * `/api/v1/analytics/*` endpoint — the six the Analytics page (roadmap slice
 * 032) queries, plus `/summary` (SPEC §59, roadmap slice 036's Today panel) —
 * so tests exercise the real API clients and TanStack Query
 * hooks without a running backend. Any other URL throws, surfacing an
 * un-mocked request as a test failure — the same contract
 * `installSightingsApiMock` establishes. */
export function installAnalyticsApiMock(options: MockAnalyticsApiOptions = {}) {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const raw = typeof input === "string" ? input : input.toString();
      const method = (init?.method ?? "GET").toUpperCase();
      const url = new URL(raw, "http://localhost");

      if (url.pathname === "/api/v1/receiver" && method === "GET") {
        return jsonResponse(options.receiver ?? defaultReceiverInfo());
      }
      if (url.pathname === "/api/v1/analytics/summary" && method === "GET") {
        if (options.summaryStatus !== undefined) {
          return jsonResponse(
            {
              error: {
                code: "internal_error",
                message: "The daily summary is unavailable",
                detail: null,
              },
            },
            options.summaryStatus,
          );
        }
        return jsonResponse(options.summary ?? EMPTY_SUMMARY);
      }
      if (url.pathname === "/api/v1/analytics/daily" && method === "GET") {
        return jsonResponse(options.daily ?? EMPTY_DAILY);
      }
      if (
        url.pathname === "/api/v1/analytics/classification-activity" &&
        method === "GET"
      ) {
        return jsonResponse(options.classification ?? EMPTY_CLASSIFICATION);
      }
      if (
        url.pathname === "/api/v1/analytics/top-aircraft" &&
        method === "GET"
      ) {
        return jsonResponse(options.topAircraft ?? EMPTY_AIRCRAFT);
      }
      if (url.pathname === "/api/v1/analytics/top-types" && method === "GET") {
        return jsonResponse(options.topTypes ?? EMPTY_GROUP);
      }
      if (
        url.pathname === "/api/v1/analytics/top-operators" &&
        method === "GET"
      ) {
        return jsonResponse(options.topOperators ?? EMPTY_GROUP);
      }
      if (url.pathname === "/api/v1/analytics/rarity" && method === "GET") {
        return jsonResponse(options.rarity ?? EMPTY_RARITY);
      }

      throw new Error(`Unhandled fetch in test: ${method} ${raw}`);
    },
  );

  vi.stubGlobal("fetch", fetchMock);

  return { fetchMock };
}
