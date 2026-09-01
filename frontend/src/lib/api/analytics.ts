/**
 * Typed client for the Analytics endpoints — `GET /api/v1/analytics/*`
 * (`docs/API.md` §3.7, roadmap slice 031/032). Six of the seven §3.7
 * endpoints are covered here; `/analytics/summary` feeds a separate
 * today-at-a-glance widget (SPEC §59) outside this slice's scope.
 *
 * Every endpoint takes the same window parameters and echoes back the
 * `AnalyticsWindow` it actually resolved (§3.7: presets resolve against the
 * *receiver's* local calendar, never the browser's), so every response type
 * here carries a `window` field the caller renders rather than re-derives.
 *
 * Reuses the `{"error": {...}}` envelope pattern `lib/api/sightings.ts`
 * established for `/api/v1` — duplicated rather than imported so this module
 * stays a self-contained read of one small file, the same call every other
 * `/api/v1` client in this directory makes.
 */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";

/** §3.7's time presets, spelled as the query values. */
export type AnalyticsPreset = "today" | "7d" | "30d" | "ytd" | "t0";

export const ANALYTICS_PRESETS: readonly AnalyticsPreset[] = [
  "today",
  "7d",
  "30d",
  "ytd",
  "t0",
];

/** The window an analytics response was actually computed over — echoed on
 * every §3.7 payload. `first_day`/`last_day` are receiver-local calendar
 * dates (`YYYY-MM-DD`). */
export interface AnalyticsWindow {
  preset: AnalyticsPreset | null;
  from: string;
  to: string;
  first_day: string;
  last_day: string;
  timezone: string;
}

/** One receiver-local day of the §3.7 `daily` series. `receiver_*` fields are
 * slice 033's joined activity for the same day, `null` where that slice
 * recorded none. */
export interface AnalyticsDailyRow {
  day: string;
  unique_aircraft: number;
  new_aircraft: number;
  sightings: number;
  interesting: number;
  military: number;
  government: number;
  law_enforcement: number;
  max_range_nm: number | null;
  busiest_hour: number | null;
  receiver_messages: number | null;
  receiver_positions: number | null;
  receiver_aircraft_max: number | null;
  receiver_max_range_nm: number | null;
}

export interface AnalyticsDailyResponse {
  window: AnalyticsWindow;
  items: AnalyticsDailyRow[];
}

/** One airframe in a §3.7 ranking or rarity list. `classification` is a
 * short mission-category slug (e.g. `"military_transport"`), not the full
 * `Classification` block the live/history APIs return. */
export interface AnalyticsAircraftRow {
  icao: string;
  registration: string | null;
  type: string | null;
  model: string | null;
  operator: string | null;
  operator_group: string | null;
  classification: string | null;
  military: boolean;
  government: boolean;
  law_enforcement: boolean;
  /** Sightings inside the window; the lifetime total for a since-T0 window. */
  sightings: number;
  first_seen_at: string;
  last_seen_at: string;
  max_range_nm: number | null;
}

export interface AnalyticsAircraftResponse {
  window: AnalyticsWindow;
  items: AnalyticsAircraftRow[];
}

/** One type designator or operator group in a §3.7 ranking. `key` is the
 * stable identifier, `label` what to display. */
export interface AnalyticsGroupRow {
  key: string;
  label: string | null;
  sightings: number;
  unique_aircraft: number;
  days_seen: number;
  first_seen_at: string | null;
  last_seen_at: string | null;
}

export interface AnalyticsGroupResponse {
  window: AnalyticsWindow;
  items: AnalyticsGroupRow[];
}

export interface AnalyticsClassificationResponse {
  window: AnalyticsWindow;
  military: number;
  government: number;
  law_enforcement: number;
  interesting: number;
  series: AnalyticsDailyRow[];
}

/** One locally rare type designator (receiver-relative, since T0). */
export interface AnalyticsRareType {
  type: string;
  unique_aircraft: number;
  total_sightings: number;
  first_seen_at: string;
  last_seen_at: string;
}

export interface AnalyticsRarityResponse {
  window: AnalyticsWindow;
  /** Airframes whose first-ever observation fell inside the window. */
  never_seen_before: number;
  rare_max_sightings: number;
  rare_max_type_aircraft: number;
  rare_aircraft: AnalyticsAircraftRow[];
  rare_types: AnalyticsRareType[];
}

interface ApiV1ErrorBody {
  error?: { code?: string; message?: string; detail?: unknown };
}

/** Thrown for any non-2xx response. `code` is the §2.5 machine-readable
 * slug, `null` when the response did not carry the documented envelope. */
export class AnalyticsApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(status: number, body: ApiV1ErrorBody | undefined) {
    super(body?.error?.message ?? `Request failed with status ${status}`);
    this.name = "AnalyticsApiError";
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
    throw new AnalyticsApiError(response.status, body);
  }
  return (await response.json()) as T;
}

/** Every §3.7 endpoint takes the same `preset` (and an optional `limit` for
 * the ranking endpoints). This slice only ever drives the presets, never an
 * explicit `from`/`to` range — that stays available to a future comparison
 * feature (out of scope here, roadmap slice 032). */
export interface AnalyticsWindowParams {
  preset: AnalyticsPreset;
}

export interface AnalyticsTopParams extends AnalyticsWindowParams {
  limit?: number;
}

export interface AnalyticsRarityParams extends AnalyticsTopParams {
  maxSightings?: number;
}

function windowQuery(params: AnalyticsWindowParams): URLSearchParams {
  return new URLSearchParams({ preset: params.preset });
}

function topQuery(params: AnalyticsTopParams): URLSearchParams {
  const search = windowQuery(params);
  if (params.limit !== undefined) {
    search.set("limit", String(params.limit));
  }
  return search;
}

export function getAnalyticsDaily(
  params: AnalyticsWindowParams,
): Promise<AnalyticsDailyResponse> {
  return apiV1Fetch<AnalyticsDailyResponse>(
    `/api/v1/analytics/daily?${windowQuery(params).toString()}`,
  );
}

export function getAnalyticsClassificationActivity(
  params: AnalyticsWindowParams,
): Promise<AnalyticsClassificationResponse> {
  return apiV1Fetch<AnalyticsClassificationResponse>(
    `/api/v1/analytics/classification-activity?${windowQuery(params).toString()}`,
  );
}

export function getAnalyticsTopAircraft(
  params: AnalyticsTopParams,
): Promise<AnalyticsAircraftResponse> {
  return apiV1Fetch<AnalyticsAircraftResponse>(
    `/api/v1/analytics/top-aircraft?${topQuery(params).toString()}`,
  );
}

export function getAnalyticsTopTypes(
  params: AnalyticsTopParams,
): Promise<AnalyticsGroupResponse> {
  return apiV1Fetch<AnalyticsGroupResponse>(
    `/api/v1/analytics/top-types?${topQuery(params).toString()}`,
  );
}

export function getAnalyticsTopOperators(
  params: AnalyticsTopParams,
): Promise<AnalyticsGroupResponse> {
  return apiV1Fetch<AnalyticsGroupResponse>(
    `/api/v1/analytics/top-operators?${topQuery(params).toString()}`,
  );
}

export function getAnalyticsRarity(
  params: AnalyticsRarityParams,
): Promise<AnalyticsRarityResponse> {
  const search = topQuery(params);
  if (params.maxSightings !== undefined) {
    search.set("max_sightings", String(params.maxSightings));
  }
  return apiV1Fetch<AnalyticsRarityResponse>(
    `/api/v1/analytics/rarity?${search.toString()}`,
  );
}

export const analyticsQueryKeys = {
  daily: (params: AnalyticsWindowParams) =>
    ["analytics", "daily", params] as const,
  classification: (params: AnalyticsWindowParams) =>
    ["analytics", "classification-activity", params] as const,
  topAircraft: (params: AnalyticsTopParams) =>
    ["analytics", "top-aircraft", params] as const,
  topTypes: (params: AnalyticsTopParams) =>
    ["analytics", "top-types", params] as const,
  topOperators: (params: AnalyticsTopParams) =>
    ["analytics", "top-operators", params] as const,
  rarity: (params: AnalyticsRarityParams) =>
    ["analytics", "rarity", params] as const,
};

export function useAnalyticsDailyQuery(
  params: AnalyticsWindowParams,
): UseQueryResult<AnalyticsDailyResponse> {
  return useQuery({
    queryKey: analyticsQueryKeys.daily(params),
    queryFn: () => getAnalyticsDaily(params),
  });
}

export function useAnalyticsClassificationActivityQuery(
  params: AnalyticsWindowParams,
): UseQueryResult<AnalyticsClassificationResponse> {
  return useQuery({
    queryKey: analyticsQueryKeys.classification(params),
    queryFn: () => getAnalyticsClassificationActivity(params),
  });
}

export function useAnalyticsTopAircraftQuery(
  params: AnalyticsTopParams,
): UseQueryResult<AnalyticsAircraftResponse> {
  return useQuery({
    queryKey: analyticsQueryKeys.topAircraft(params),
    queryFn: () => getAnalyticsTopAircraft(params),
  });
}

export function useAnalyticsTopTypesQuery(
  params: AnalyticsTopParams,
): UseQueryResult<AnalyticsGroupResponse> {
  return useQuery({
    queryKey: analyticsQueryKeys.topTypes(params),
    queryFn: () => getAnalyticsTopTypes(params),
  });
}

export function useAnalyticsTopOperatorsQuery(
  params: AnalyticsTopParams,
): UseQueryResult<AnalyticsGroupResponse> {
  return useQuery({
    queryKey: analyticsQueryKeys.topOperators(params),
    queryFn: () => getAnalyticsTopOperators(params),
  });
}

export function useAnalyticsRarityQuery(
  params: AnalyticsRarityParams,
): UseQueryResult<AnalyticsRarityResponse> {
  return useQuery({
    queryKey: analyticsQueryKeys.rarity(params),
    queryFn: () => getAnalyticsRarity(params),
  });
}
