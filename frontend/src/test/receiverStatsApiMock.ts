import { vi } from "vitest";

import type {
  ReceiverCoverage,
  ReceiverCoverageBandKey,
  ReceiverLifetimeStats,
  ReceiverMetricSeries,
  ReceiverRangeByBearing,
  ReceiverScorecard,
  ReceiverSeriesMetric,
  ReceiverSignalDistribution,
} from "@/lib/api/receiverStats";
import type { FeedersResponse } from "@/lib/api/feeders";

import { defaultReceiverInfo } from "@/test/aircraftApiMock";
import { feedersResponse } from "@/test/feedersApiMock";

export function scorecard(
  overrides: Partial<ReceiverScorecard> = {},
): ReceiverScorecard {
  return {
    current_visible: 12,
    current_positioned: 9,
    messages_per_sec: 145.2,
    positions_per_sec: 8.4,
    max_range_today_nm: 87.3,
    max_range_ever_nm: 241.6,
    unique_aircraft_today: 34,
    unique_aircraft_since_t0: 5821,
    decoder_uptime_s: 356_412,
    flightsite_uptime_s: 91_004,
    health: "ok",
    ...overrides,
  };
}

export function metricSeries(
  overrides: Partial<ReceiverMetricSeries> = {},
): ReceiverMetricSeries {
  return {
    metric: "messages_per_sec",
    resolution: "hourly",
    points: [
      { t: "2026-08-30T00:00:00.000Z", value: 100 },
      { t: "2026-08-30T01:00:00.000Z", value: 120 },
      { t: "2026-08-30T02:00:00.000Z", value: null },
    ],
    ...overrides,
  };
}

/** 72 sectors ascending from bucket 0 (bearing 2.5deg) — the shape
 * `GET /api/v1/receiver/range-by-bearing` always returns. Every sector
 * defaults to no data; pass `withData` for the sectors a test cares about. */
export function rangeByBearing(
  overrides: {
    today?: Record<number, number>;
    ever?: Record<number, number>;
  } = {},
): ReceiverRangeByBearing {
  const sector = (
    bucket: number,
    values: Record<number, number> | undefined,
  ) => {
    const value = values?.[bucket];
    return {
      bearing_deg: bucket * 5 + 2.5,
      max_range_nm: value ?? null,
      at: value === undefined ? null : "2026-08-30T12:00:00.000Z",
      icao: value === undefined ? null : "ae1463",
    };
  };
  return {
    sector_width_deg: 5,
    today: Array.from({ length: 72 }, (_, bucket) =>
      sector(bucket, overrides.today),
    ),
    ever: Array.from({ length: 72 }, (_, bucket) =>
      sector(bucket, overrides.ever),
    ),
  };
}

/** `GET /api/v1/receiver/coverage`'s shape: three bands of 72 sectors.
 * Every sector defaults to no data and the antenna height to unset; pass
 * `ranges` (band -> bucket -> nm) for the sectors a test cares about. */
export function coverage(
  overrides: {
    antennaHeightFt?: number | null;
    horizons?: Partial<Record<ReceiverCoverageBandKey, number>>;
    ranges?: Partial<Record<ReceiverCoverageBandKey, Record<number, number>>>;
  } & Partial<Pick<ReceiverCoverage, "findings" | "window">> = {},
): ReceiverCoverage {
  const bands: Array<{
    key: ReceiverCoverageBandKey;
    label: string;
    min_ft: number | null;
    max_ft: number | null;
    reference_ft: number;
  }> = [
    {
      key: "below_10k",
      label: "Below 10,000 ft",
      min_ft: null,
      max_ft: 10000,
      reference_ft: 3000,
    },
    {
      key: "10k_25k",
      label: "10,000 to 25,000 ft",
      min_ft: 10000,
      max_ft: 25000,
      reference_ft: 10000,
    },
    {
      key: "above_25k",
      label: "25,000 ft and above",
      min_ft: 25000,
      max_ft: null,
      reference_ft: 25000,
    },
  ];
  const antenna = overrides.antennaHeightFt ?? null;
  return {
    window: overrides.window ?? "30d",
    from_day: "2026-09-01",
    to_day: "2026-09-30",
    sector_width_deg: 5,
    antenna_height_ft: antenna,
    criteria: { share_below: 0.6, min_samples: 30, min_days: 3 },
    bands: bands.map((band) => {
      const horizon =
        antenna === null ? null : (overrides.horizons?.[band.key] ?? null);
      return {
        ...band,
        horizon_nm: horizon,
        sectors: Array.from({ length: 72 }, (_, bucket) => {
          const value = overrides.ranges?.[band.key]?.[bucket];
          return {
            bearing_deg: bucket * 5 + 2.5,
            max_range_nm: value ?? null,
            at: value === undefined ? null : "2026-09-29T12:00:00.000Z",
            icao: value === undefined ? null : "ae1463",
            samples: value === undefined ? 0 : 40,
            days: value === undefined ? 0 : 4,
            share_of_horizon:
              value === undefined || horizon === null ? null : value / horizon,
          };
        }),
      };
    }),
    findings: overrides.findings ?? [],
  };
}

export function signalDistribution(
  overrides: Partial<ReceiverSignalDistribution> = {},
): ReceiverSignalDistribution {
  return {
    from_ts: null,
    to_ts: null,
    bucket_width_db: 3,
    buckets: [
      { min_db: -30, max_db: -27, count: 5 },
      { min_db: -27, max_db: -24, count: 41 },
      { min_db: -24, max_db: -21, count: 12 },
    ],
    sample_count: 58,
    min_db: -29.1,
    max_db: -22.3,
    avg_db: -25.6,
    ...overrides,
  };
}

export function lifetimeStats(
  overrides: Partial<ReceiverLifetimeStats> = {},
): ReceiverLifetimeStats {
  return {
    since: "2026-01-15T00:00:00.000Z",
    unique_aircraft: 5821,
    total_sightings: 40213,
    total_positions: 12_400_000,
    total_messages: 980_000_000,
    max_range: {
      nm: 241.6,
      at: "2026-05-02T14:00:00.000Z",
      bearing_deg: 87.5,
      icao: "ae1463",
    },
    peak_message_rate_per_sec: 512.4,
    peak_position_rate_per_sec: 44.1,
    max_simultaneous_aircraft: 61,
    busiest_day: { day: "2026-07-04", message_count: 5_100_000 },
    most_frequent_aircraft: {
      icao: "a1b2c3",
      registration: "N123AB",
      sighting_count: 812,
    },
    common_type: { value: "B738", aircraft_count: 240 },
    common_model: { value: "Boeing 737-800", aircraft_count: 240 },
    common_operator: { value: "Delta Air Lines", aircraft_count: 180 },
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export interface MockReceiverStatsApiOptions {
  receiver?: ReturnType<typeof defaultReceiverInfo>;
  scorecard?: ReceiverScorecard;
  /** Response for `GET /api/v1/receiver/metrics`, keyed by `metric`. A
   * metric with no entry falls back to `metricSeries({ metric })`. */
  series?: Partial<Record<ReceiverSeriesMetric, ReceiverMetricSeries>>;
  rangeByBearing?: ReceiverRangeByBearing;
  signalDistribution?: ReceiverSignalDistribution;
  /** `GET /api/v1/receiver/coverage` (slice 087). `"error"` answers 404
   * with no body — what a HAR recorded before the endpoint existed serves. */
  coverage?: ReceiverCoverage | "error";
  lifetime?: ReceiverLifetimeStats;
  /** `GET /api/v1/feeders` — `ReceiverPage` mounts `FeedersSummaryCard`
   * (roadmap slice 077), which queries this endpoint on its own. Defaults
   * to an empty roster: most Receiver-page tests have nothing to do with
   * feeders, and an empty roster keeps the summary card's own assertions
   * ("No feeders configured") out of their way. */
  feeders?: FeedersResponse;
}

/** Installs a `global.fetch` stub serving `GET /api/v1/receiver` plus every
 * `docs/API.md` §3.8 receiver-stats endpoint, so Receiver page tests can
 * exercise the real API clients and TanStack Query hooks without a running
 * backend. Any other URL throws, surfacing an un-mocked request as a test
 * failure. */
export function installReceiverStatsApiMock(
  options: MockReceiverStatsApiOptions = {},
) {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const raw = typeof input === "string" ? input : input.toString();
      const method = (init?.method ?? "GET").toUpperCase();
      const url = new URL(raw, "http://localhost");

      if (url.pathname === "/api/v1/receiver" && method === "GET") {
        return jsonResponse(options.receiver ?? defaultReceiverInfo());
      }
      if (url.pathname === "/api/v1/receiver/scorecard" && method === "GET") {
        return jsonResponse(options.scorecard ?? scorecard());
      }
      if (url.pathname === "/api/v1/receiver/metrics" && method === "GET") {
        const metric = url.searchParams.get("metric") as ReceiverSeriesMetric;
        const resolution = url.searchParams.get("resolution") ?? "hourly";
        const body =
          options.series?.[metric] ??
          metricSeries({
            metric,
            resolution: resolution as ReceiverMetricSeries["resolution"],
          });
        return jsonResponse(body);
      }
      if (
        url.pathname === "/api/v1/receiver/range-by-bearing" &&
        method === "GET"
      ) {
        return jsonResponse(options.rangeByBearing ?? rangeByBearing());
      }
      if (
        url.pathname === "/api/v1/receiver/signal-distribution" &&
        method === "GET"
      ) {
        return jsonResponse(options.signalDistribution ?? signalDistribution());
      }
      if (url.pathname === "/api/v1/receiver/coverage" && method === "GET") {
        if (options.coverage === "error") {
          return new Response(null, { status: 404 });
        }
        return jsonResponse(options.coverage ?? coverage());
      }
      if (url.pathname === "/api/v1/receiver/lifetime" && method === "GET") {
        return jsonResponse(options.lifetime ?? lifetimeStats());
      }
      if (url.pathname === "/api/v1/feeders" && method === "GET") {
        return jsonResponse(
          options.feeders ?? feedersResponse({ feeders: [] }),
        );
      }

      throw new Error(`Unhandled fetch in test: ${method} ${raw}`);
    },
  );

  vi.stubGlobal("fetch", fetchMock);

  return { fetchMock };
}
