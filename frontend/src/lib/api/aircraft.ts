/**
 * Typed client for the Aircraft page's endpoints — `GET /api/v1/aircraft`
 * and `GET /api/v1/aircraft/{icao}` (`docs/API.md` §3.5, roadmap slice 029).
 *
 * These are the one corner of `/api/v1` (docs/API.md §2.5) this frontend
 * talks to directly rather than through the WebSocket-fed live store, so
 * this module — unlike `lib/api/client.ts`'s `apiFetch`, which parses the
 * unversioned internal API's `{"detail": ...}` error body — parses the
 * external API's `{"error": {"code", "message", "detail"}}` envelope.
 */
import {
  keepPreviousData,
  useQuery,
  type UseQueryResult,
} from "@tanstack/react-query";

import type { Classification } from "@/lib/api/live";

/** §3.5's documented sort keys. */
export type AircraftSortKey =
  | "registration"
  | "icao"
  | "type"
  | "operator"
  | "classification"
  | "first_seen"
  | "last_seen"
  | "sighting_count"
  | "closest_approach_nm"
  | "max_range_nm";

export type SortOrder = "asc" | "desc";

/** SPEC §53's lifetime record block. */
export interface LifetimeRecord {
  first_seen: string;
  last_seen: string;
  sighting_count: number;
  cumulative_duration_s: number;
  closest_approach_nm: number | null;
  max_range_nm: number | null;
  lowest_altitude_ft: number | null;
  highest_altitude_ft: number | null;
}

/** One row of the Aircraft page (SPEC §56). Field names mirror
 * `LiveAircraft` where the same fact appears, so both feed
 * `IdentityMetadataSection` without reshaping. */
export interface AircraftListRow {
  icao: string;
  registration: string | null;
  aircraft_type: string | null;
  model: string | null;
  operator: string | null;
  operator_group: string | null;
  classification: Classification | null;
  first_seen: string;
  last_seen: string;
  sighting_count: number;
  closest_approach_nm: number | null;
  max_range_nm: number | null;
  provenance: Record<string, string>;
}

export interface AircraftListResponse {
  items: AircraftListRow[];
  /** May be `null` (§2.4 allows omitting/approximating it); this endpoint
   * currently always returns an exact count. */
  total: number | null;
  limit: number;
  offset: number;
}

/** `GET /api/v1/aircraft/{icao}` — identity, metadata, classification and
 * the lifetime block for one airframe, live or not. */
export interface AircraftDetail {
  icao: string;
  registration: string | null;
  aircraft_type: string | null;
  model: string | null;
  manufacture_year: number | null;
  operator: string | null;
  operator_group: string | null;
  owner: string | null;
  classification: Classification | null;
  /** Whether this airframe is in the live picture right now. */
  live: boolean;
  lifetime: LifetimeRecord;
  provenance: Record<string, string>;
}

interface ApiV1ErrorBody {
  error?: { code?: string; message?: string; detail?: unknown };
}

/** Thrown for any non-2xx response from `/api/v1`. `code` is the §2.5
 * machine-readable slug (`"not_found"`, `"validation_error"`, …), `null`
 * when the response did not carry the documented envelope at all. */
export class ApiV1Error extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(status: number, body: ApiV1ErrorBody | undefined) {
    super(body?.error?.message ?? `Request failed with status ${status}`);
    this.name = "ApiV1Error";
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
    throw new ApiV1Error(response.status, body);
  }
  return (await response.json()) as T;
}

export interface AircraftListParams {
  limit: number;
  offset: number;
  sort: AircraftSortKey;
  order: SortOrder;
  classification?: string;
  operatorGroup?: string;
  type?: string;
}

function listPath(params: AircraftListParams): string {
  const query = new URLSearchParams({
    limit: String(params.limit),
    offset: String(params.offset),
    sort: params.sort,
    order: params.order,
  });
  if (params.classification !== undefined) {
    query.set("classification", params.classification);
  }
  if (params.operatorGroup !== undefined) {
    query.set("operator_group", params.operatorGroup);
  }
  if (params.type !== undefined) {
    query.set("type", params.type);
  }
  return `/api/v1/aircraft?${query.toString()}`;
}

export function getAircraftList(
  params: AircraftListParams,
): Promise<AircraftListResponse> {
  return apiV1Fetch<AircraftListResponse>(listPath(params));
}

export function getAircraftDetail(icao: string): Promise<AircraftDetail> {
  return apiV1Fetch<AircraftDetail>(
    `/api/v1/aircraft/${encodeURIComponent(icao)}`,
  );
}

/** Query key namespace shared by both hooks below, so a detail fetch (e.g.
 * after a row click) can share cache identity with the list it came from. */
export const aircraftQueryKeys = {
  list: (params: AircraftListParams) => ["aircraft", "list", params] as const,
  detail: (icao: string) => ["aircraft", "detail", icao] as const,
};

/** One page of the Aircraft page's table. `placeholderData: keepPreviousData`
 * keeps the previous page's rows on screen while the next page loads, so
 * sorting/paging never flashes to an empty table. */
export function useAircraftListQuery(
  params: AircraftListParams,
): UseQueryResult<AircraftListResponse> {
  return useQuery({
    queryKey: aircraftQueryKeys.list(params),
    queryFn: () => getAircraftList(params),
    placeholderData: keepPreviousData,
  });
}

/** One aircraft's full detail. `enabled: false` when `icao` is absent so a
 * route rendered without one (never expected, but TypeScript-visible) does
 * not fire a request that can only 422. */
export function useAircraftDetailQuery(
  icao: string | undefined,
): UseQueryResult<AircraftDetail> {
  return useQuery({
    queryKey: aircraftQueryKeys.detail(icao ?? ""),
    queryFn: () => getAircraftDetail(icao as string),
    enabled: icao !== undefined,
    retry: (failureCount, error) =>
      // A 404 is a real answer ("never sighted"), not a transient failure —
      // retrying it would just show a spinner for three round trips before
      // reaching the same not-found state.
      !(error instanceof ApiV1Error && error.status === 404) &&
      failureCount < 2,
    // A short, fixed delay rather than TanStack Query's default exponential
    // backoff: a genuinely transient failure on a detail page a person is
    // actively looking at should settle in well under a second, not climb
    // toward a 30s ceiling.
    retryDelay: 100,
  });
}
