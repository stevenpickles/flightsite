/**
 * Typed client for the Sightings endpoints — `GET /api/v1/sightings`,
 * `GET /api/v1/sightings/{id}` and `GET /api/v1/aircraft/{icao}/sightings`
 * (`docs/API.md` §3.6, roadmap slice 030).
 *
 * Reuses `ApiV1Error`/the `apiV1Fetch` pattern `lib/api/aircraft.ts`
 * established for the external `/api/v1` surface's `{"error": {...}}`
 * envelope (§2.5) — duplicated rather than imported so this module stays a
 * self-contained read of one small file, the same call `aircraft.ts` itself
 * makes relative to `lib/api/client.ts`'s internal-API helper.
 */
import {
  keepPreviousData,
  useQuery,
  type UseQueryResult,
} from "@tanstack/react-query";

import type { Classification, PositionSource, RouteInfo } from "@/lib/api/live";

/** §3.6's documented sort keys. */
export type SightingSortKey =
  "started_at" | "duration_s" | "closest_approach_nm" | "max_range_nm";

export type SortOrder = "asc" | "desc";

/** §2.8's `closure_reason` vocabulary. */
export type ClosureReason = "gap_timeout" | "shutdown_recovery" | "data_reset";

/** §2.8's alert severity ladder. */
export type AlertSeverity = "info" | "interesting" | "high" | "critical";

/** `docs/DATA_MODEL.md` §2.5's `sighting_events.type` vocabulary. */
export type SightingEventType =
  | "callsign_change"
  | "squawk_change"
  | "emergency_start"
  | "emergency_end"
  | "route_enriched"
  | "classification_available"
  | "alert_matched"
  | "alert_severity_upgraded";

/** One row of the Sightings page (SPEC §57). Field names mirror
 * `AircraftListRow` where the same fact appears. */
export interface SightingRow {
  id: number;
  icao: string;
  callsign: string | null;
  registration: string | null;
  aircraft_type: string | null;
  model: string | null;
  operator: string | null;
  operator_group: string | null;
  classification: Classification | null;
  started_at: string;
  ended_at: string | null;
  duration_s: number | null;
  closure_reason: ClosureReason | null;
  closest_approach_nm: number | null;
  max_range_nm: number | null;
  lowest_altitude_ft: number | null;
  highest_altitude_ft: number | null;
  position_count: number;
  had_emergency: boolean;
  max_alert_severity: AlertSeverity | null;
  provenance: Record<string, string>;
}

export interface SightingListResponse {
  items: SightingRow[];
  /** Always `null` — §2.4 names `/sightings` the canonical case for omitting
   * an exact filtered count at multi-year scale. */
  total: number | null;
  limit: number;
  offset: number;
}

export interface ReceptionStats {
  rssi_peak_db: number | null;
  rssi_avg_db: number | null;
  rssi_min_db: number | null;
  message_count: number;
  position_count: number;
  pct_with_position: number | null;
}

export interface SightingRecords {
  closest_approach_nm: number | null;
  max_range_nm: number | null;
  lowest_altitude_ft: number | null;
  highest_altitude_ft: number | null;
}

export interface SightingEvent {
  at: string;
  type: SightingEventType;
  detail: Record<string, string | null> | null;
}

export interface SightingPathPoint {
  t: string;
  lat: number;
  lon: number;
  altitude_ft: number | null;
  source: PositionSource;
}

/** `GET /api/v1/sightings/{id}` — flight context, reception stats, records,
 * the event timeline and the simplified (or, for an open sighting,
 * checkpointed) path. */
export interface SightingDetail {
  id: number;
  icao: string;
  callsign: string | null;
  squawk: string | null;
  started_at: string;
  ended_at: string | null;
  duration_s: number | null;
  closure_reason: ClosureReason | null;
  route: RouteInfo;
  reception: ReceptionStats;
  records: SightingRecords;
  events: SightingEvent[];
  path: SightingPathPoint[];
  provenance: Record<string, string>;
}

interface ApiV1ErrorBody {
  error?: { code?: string; message?: string; detail?: unknown };
}

/** Thrown for any non-2xx response. `code` is the §2.5 machine-readable
 * slug, `null` when the response did not carry the documented envelope. */
export class SightingsApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(status: number, body: ApiV1ErrorBody | undefined) {
    super(body?.error?.message ?? `Request failed with status ${status}`);
    this.name = "SightingsApiError";
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
    throw new SightingsApiError(response.status, body);
  }
  return (await response.json()) as T;
}

export interface SightingListParams {
  limit: number;
  offset: number;
  sort: SightingSortKey;
  order: SortOrder;
  icao?: string;
  /** Inclusive lower bound on `started_at`, as a full ISO instant. */
  from?: string;
  /** Inclusive upper bound on `started_at`, as a full ISO instant. */
  to?: string;
  interesting?: boolean;
  open?: boolean;
}

function query(params: SightingListParams): string {
  const search = new URLSearchParams({
    limit: String(params.limit),
    offset: String(params.offset),
    sort: params.sort,
    order: params.order,
  });
  if (params.icao !== undefined) {
    search.set("icao", params.icao);
  }
  if (params.from !== undefined) {
    search.set("from", params.from);
  }
  if (params.to !== undefined) {
    search.set("to", params.to);
  }
  if (params.interesting !== undefined) {
    search.set("interesting", String(params.interesting));
  }
  if (params.open !== undefined) {
    search.set("open", String(params.open));
  }
  return search.toString();
}

export function getSightingList(
  params: SightingListParams,
): Promise<SightingListResponse> {
  return apiV1Fetch<SightingListResponse>(`/api/v1/sightings?${query(params)}`);
}

export function getSightingDetail(id: number): Promise<SightingDetail> {
  return apiV1Fetch<SightingDetail>(`/api/v1/sightings/${id}`);
}

export interface AircraftSightingsParams {
  icao: string;
  limit: number;
  offset: number;
  sort?: SightingSortKey;
  order?: SortOrder;
}

export function getAircraftSightings(
  params: AircraftSightingsParams,
): Promise<SightingListResponse> {
  const search = new URLSearchParams({
    limit: String(params.limit),
    offset: String(params.offset),
    sort: params.sort ?? "started_at",
    order: params.order ?? "desc",
  });
  return apiV1Fetch<SightingListResponse>(
    `/api/v1/aircraft/${encodeURIComponent(params.icao)}/sightings?${search.toString()}`,
  );
}

export const sightingsQueryKeys = {
  list: (params: SightingListParams) => ["sightings", "list", params] as const,
  detail: (id: number) => ["sightings", "detail", id] as const,
  aircraft: (params: AircraftSightingsParams) =>
    ["sightings", "aircraft", params] as const,
};

/** One page of the Sightings table. `placeholderData: keepPreviousData`
 * keeps the previous page's rows on screen while the next page loads. */
export function useSightingListQuery(
  params: SightingListParams,
): UseQueryResult<SightingListResponse> {
  return useQuery({
    queryKey: sightingsQueryKeys.list(params),
    queryFn: () => getSightingList(params),
    placeholderData: keepPreviousData,
  });
}

/** One sighting's full detail. `enabled: false` when `id` is absent so a
 * route rendered without one never fires a request that can only 422. */
export function useSightingDetailQuery(
  id: number | undefined,
): UseQueryResult<SightingDetail> {
  return useQuery({
    queryKey: sightingsQueryKeys.detail(id ?? -1),
    queryFn: () => getSightingDetail(id as number),
    enabled: id !== undefined,
    retry: (failureCount, error) =>
      // A 404 is a real answer ("no such sighting"), not a transient failure.
      !(error instanceof SightingsApiError && error.status === 404) &&
      failureCount < 2,
    retryDelay: 100,
  });
}

/** One aircraft's recent sightings, for the aircraft detail page's History
 * section. */
export function useAircraftSightingsQuery(
  params: AircraftSightingsParams | undefined,
): UseQueryResult<SightingListResponse> {
  return useQuery({
    queryKey: sightingsQueryKeys.aircraft(
      params ?? { icao: "", limit: 0, offset: 0 },
    ),
    queryFn: () => getAircraftSightings(params as AircraftSightingsParams),
    enabled: params !== undefined,
  });
}
