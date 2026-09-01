/**
 * Typed client for the Receiver stats endpoints — `docs/API.md` §3.8
 * (roadmap slice 034): scorecard, time-series, range-by-bearing,
 * signal-distribution, lifetime.
 *
 * Reuses the `ApiV1Error`/`apiV1Fetch` pattern `lib/api/sightings.ts`
 * established for the external `/api/v1` surface's `{"error": {...}}`
 * envelope (§2.5) — duplicated rather than imported, the same call that
 * module itself makes relative to `aircraft.ts`.
 */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";

/** `docs/API.md` §3.8's receiver-health summary — deliberately coarse; full
 * diagnostics is roadmap slice 042's scope. */
export type ReceiverHealth = "ok" | "no_stats" | "unknown" | "demo";

export interface ReceiverScorecard {
  current_visible: number;
  current_positioned: number;
  messages_per_sec: number | null;
  positions_per_sec: number | null;
  max_range_today_nm: number | null;
  max_range_ever_nm: number | null;
  unique_aircraft_today: number;
  unique_aircraft_since_t0: number;
  decoder_uptime_s: number | null;
  flightsite_uptime_s: number;
  health: ReceiverHealth;
}

/** SPEC §62's v1 chart catalog, minus the two endpoints with their own shape
 * (range-by-bearing, signal-distribution). */
export type ReceiverSeriesMetric =
  | "messages_per_sec"
  | "positions_per_sec"
  | "aircraft_count"
  | "max_range_nm"
  | "messages_total"
  | "positions_total"
  | "unique_aircraft";

export type ReceiverSeriesResolution = "high" | "hourly" | "daily";

export interface ReceiverSeriesPoint {
  t: string;
  value: number | null;
}

export interface ReceiverMetricSeries {
  metric: ReceiverSeriesMetric;
  resolution: ReceiverSeriesResolution;
  points: ReceiverSeriesPoint[];
}

export interface ReceiverBearingSector {
  /** Sector midpoint, degrees true. 0 is North, increasing clockwise. */
  bearing_deg: number;
  max_range_nm: number | null;
  at: string | null;
  icao: string | null;
}

export interface ReceiverRangeByBearing {
  sector_width_deg: number;
  today: ReceiverBearingSector[];
  ever: ReceiverBearingSector[];
}

export interface ReceiverSignalBucket {
  min_db: number;
  max_db: number;
  count: number;
}

export interface ReceiverSignalDistribution {
  from_ts: string | null;
  to_ts: string | null;
  bucket_width_db: number;
  buckets: ReceiverSignalBucket[];
  sample_count: number;
  min_db: number | null;
  max_db: number | null;
  avg_db: number | null;
}

export interface ReceiverMaxRangeRecord {
  nm: number;
  at: string;
  bearing_deg: number;
  icao: string | null;
}

export interface ReceiverBusiestDay {
  day: string;
  message_count: number;
}

export interface ReceiverFrequentAircraft {
  icao: string;
  registration: string | null;
  sighting_count: number;
}

export interface ReceiverCommonRecord {
  value: string;
  aircraft_count: number;
}

export interface ReceiverLifetimeStats {
  since: string | null;
  unique_aircraft: number;
  total_sightings: number;
  total_positions: number | null;
  total_messages: number | null;
  max_range: ReceiverMaxRangeRecord | null;
  peak_message_rate_per_sec: number | null;
  peak_position_rate_per_sec: number | null;
  max_simultaneous_aircraft: number | null;
  busiest_day: ReceiverBusiestDay | null;
  most_frequent_aircraft: ReceiverFrequentAircraft | null;
  common_type: ReceiverCommonRecord | null;
  common_model: ReceiverCommonRecord | null;
  common_operator: ReceiverCommonRecord | null;
}

interface ApiV1ErrorBody {
  error?: { code?: string; message?: string; detail?: unknown };
}

/** Thrown for any non-2xx response. `code` is the §2.5 machine-readable
 * slug, `null` when the response did not carry the documented envelope. */
export class ReceiverStatsApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(status: number, body: ApiV1ErrorBody | undefined) {
    super(body?.error?.message ?? `Request failed with status ${status}`);
    this.name = "ReceiverStatsApiError";
    this.status = status;
    this.code = body?.error?.code ?? null;
  }
}

async function apiV1Fetch<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    let body: ApiV1ErrorBody | undefined;
    try {
      body = (await response.json()) as ApiV1ErrorBody;
    } catch {
      body = undefined;
    }
    throw new ReceiverStatsApiError(response.status, body);
  }
  return (await response.json()) as T;
}

/** How often the scorecard is re-polled while the page is visible — short
 * enough that "current visible"/"messages per sec" reads as live without a
 * WebSocket subscription of its own. */
export const SCORECARD_POLL_MS = 5_000;

export function getReceiverScorecard(): Promise<ReceiverScorecard> {
  return apiV1Fetch<ReceiverScorecard>("/api/v1/receiver/scorecard");
}

export function useReceiverScorecardQuery(): UseQueryResult<ReceiverScorecard> {
  return useQuery({
    queryKey: ["receiver", "scorecard"],
    queryFn: getReceiverScorecard,
    refetchInterval: SCORECARD_POLL_MS,
  });
}

export interface ReceiverMetricSeriesParams {
  metric: ReceiverSeriesMetric;
  resolution: ReceiverSeriesResolution;
  /** Full ISO instant. Omit for the endpoint's resolution-sized default lookback. */
  from?: string;
  to?: string;
}

function seriesQuery(params: ReceiverMetricSeriesParams): string {
  const search = new URLSearchParams({
    metric: params.metric,
    resolution: params.resolution,
  });
  if (params.from !== undefined) {
    search.set("from", params.from);
  }
  if (params.to !== undefined) {
    search.set("to", params.to);
  }
  return search.toString();
}

export function getReceiverMetricSeries(
  params: ReceiverMetricSeriesParams,
): Promise<ReceiverMetricSeries> {
  return apiV1Fetch<ReceiverMetricSeries>(
    `/api/v1/receiver/metrics?${seriesQuery(params)}`,
  );
}

export function useReceiverMetricSeriesQuery(
  params: ReceiverMetricSeriesParams,
): UseQueryResult<ReceiverMetricSeries> {
  return useQuery({
    queryKey: ["receiver", "metrics", params],
    queryFn: () => getReceiverMetricSeries(params),
  });
}

export function getReceiverRangeByBearing(): Promise<ReceiverRangeByBearing> {
  return apiV1Fetch<ReceiverRangeByBearing>(
    "/api/v1/receiver/range-by-bearing",
  );
}

export function useReceiverRangeByBearingQuery(): UseQueryResult<ReceiverRangeByBearing> {
  return useQuery({
    queryKey: ["receiver", "range-by-bearing"],
    queryFn: getReceiverRangeByBearing,
  });
}

export interface ReceiverSignalDistributionParams {
  from?: string;
  to?: string;
  bucketWidthDb?: number;
}

function signalQuery(params: ReceiverSignalDistributionParams): string {
  const search = new URLSearchParams();
  if (params.from !== undefined) {
    search.set("from", params.from);
  }
  if (params.to !== undefined) {
    search.set("to", params.to);
  }
  if (params.bucketWidthDb !== undefined) {
    search.set("bucket_width_db", String(params.bucketWidthDb));
  }
  return search.toString();
}

export function getReceiverSignalDistribution(
  params: ReceiverSignalDistributionParams = {},
): Promise<ReceiverSignalDistribution> {
  const search = signalQuery(params);
  const path = search
    ? `/api/v1/receiver/signal-distribution?${search}`
    : "/api/v1/receiver/signal-distribution";
  return apiV1Fetch<ReceiverSignalDistribution>(path);
}

export function useReceiverSignalDistributionQuery(
  params: ReceiverSignalDistributionParams = {},
): UseQueryResult<ReceiverSignalDistribution> {
  return useQuery({
    queryKey: ["receiver", "signal-distribution", params],
    queryFn: () => getReceiverSignalDistribution(params),
  });
}

export function getReceiverLifetimeStats(): Promise<ReceiverLifetimeStats> {
  return apiV1Fetch<ReceiverLifetimeStats>("/api/v1/receiver/lifetime");
}

export function useReceiverLifetimeStatsQuery(): UseQueryResult<ReceiverLifetimeStats> {
  return useQuery({
    queryKey: ["receiver", "lifetime"],
    queryFn: getReceiverLifetimeStats,
  });
}
