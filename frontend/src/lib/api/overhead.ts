/**
 * Typed client for "What was that?" — `GET /api/v1/overhead`
 * (`docs/API.md` §3.7.1, roadmap slice 090, issue #233).
 *
 * The sightings whose **closest stored position fix** within `window`
 * minutes either side of `at` came nearest the receiver, nearest first. Every
 * row is a point the sighting actually stored — never an interpolated
 * position — and `method` says so on every response.
 *
 * Reuses the `apiV1Fetch` pattern `lib/api/activity.ts` documents for the
 * `/api/v1` error envelope (§2.5), duplicated rather than imported for the
 * reason that module gives.
 */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";

/** How the ranked distance was measured: line of sight when the fix carries
 * an altitude, over the ground when it does not. */
export type OverheadDistanceKind = "slant" | "ground";

export interface OverheadPass {
  sighting_id: number;
  icao: string;
  callsign: string | null;
  registration: string | null;
  aircraft_type: string | null;
  model: string | null;
  operator: string | null;
  /** The sighting has not closed yet. */
  open: boolean;
  /** When the closest stored fix was recorded — UTC ISO-8601 (§2.2). */
  fix_at: string;
  lat: number;
  lon: number;
  altitude_ft: number | null;
  /** What results are ranked by — see `distance_kind`. */
  distance_nm: number;
  distance_kind: OverheadDistanceKind;
  ground_distance_nm: number;
  bearing_deg: number;
  position_source: "adsb" | "mlat" | "none" | "other";
}

export interface OverheadResponse {
  at: string;
  window_minutes: number;
  window_start: string;
  window_end: string;
  method: "closest_position_fix";
  /** `false` with `reason: "receiver_location_unset"` and no items when
   * there is no receiver position to measure from. */
  receiver_configured: boolean;
  reason: "receiver_location_unset" | null;
  candidates: number;
  truncated: boolean;
  items: OverheadPass[];
}

export interface OverheadParams {
  /** A full UTC ISO instant; omitted means "now" (the server's clock). */
  at?: string;
  /** Minutes either side of `at` (1–60). */
  window: number;
  limit?: number;
}

interface ApiV1ErrorBody {
  error?: { code?: string; message?: string; detail?: unknown };
}

/** Thrown for any non-2xx response, with the §2.5 `code` when present. */
export class OverheadApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(status: number, body: ApiV1ErrorBody | undefined) {
    super(body?.error?.message ?? `Request failed with status ${status}`);
    this.name = "OverheadApiError";
    this.status = status;
    this.code = body?.error?.code ?? null;
  }
}

export function overheadPath(params: OverheadParams): string {
  const search = new URLSearchParams({ window: String(params.window) });
  if (params.at !== undefined) {
    search.set("at", params.at);
  }
  if (params.limit !== undefined) {
    search.set("limit", String(params.limit));
  }
  return `/api/v1/overhead?${search.toString()}`;
}

export async function getOverhead(
  params: OverheadParams,
): Promise<OverheadResponse> {
  const response = await fetch(overheadPath(params));
  if (!response.ok) {
    let body: ApiV1ErrorBody | undefined;
    try {
      body = (await response.json()) as ApiV1ErrorBody;
    } catch {
      body = undefined;
    }
    throw new OverheadApiError(response.status, body);
  }
  return (await response.json()) as OverheadResponse;
}

export const overheadQueryKeys = {
  lookup: (params: OverheadParams) => ["overhead", params] as const,
};

/**
 * One lookup, fetched only while `enabled` (the dialog is open).
 * `staleTime: 0` because "now" moves: reopening the dialog on the default
 * moment must ask again rather than show the last answer.
 */
export function useOverheadQuery(
  params: OverheadParams,
  { enabled }: { enabled: boolean },
): UseQueryResult<OverheadResponse, OverheadApiError> {
  return useQuery({
    queryKey: overheadQueryKeys.lookup(params),
    queryFn: () => getOverhead(params),
    enabled,
    staleTime: 0,
  });
}
