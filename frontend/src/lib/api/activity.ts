/**
 * Typed client for the activity feed — `GET /api/v1/activity`
 * (`docs/API.md` §3.9, SPEC §55, roadmap slice 035).
 *
 * Reuses the `apiV1Fetch` pattern `lib/api/aircraft.ts` established for the
 * external `/api/v1` surface's `{"error": {...}}` envelope (§2.5) —
 * duplicated rather than imported so this module stays a self-contained read
 * of one small file, the same call `lib/api/sightings.ts` makes.
 *
 * The event shape here is the whole client-side contract for the feed: it is
 * what `GET /api/v1/activity` returns *and* what the WebSocket's `activity`
 * frame carries (§4.4), because the backend builds both from one serializer.
 * `lib/ws/protocol.ts` therefore imports {@link ActivityEvent} from here
 * rather than declaring a parallel shape — the dependency runs one way, from
 * the socket's parsing layer towards the API types, and `lib/api/live.ts`
 * (which protocol.ts already reads) imports nothing at all, so there is no
 * cycle to worry about.
 */
import {
  keepPreviousData,
  useQuery,
  type UseQueryResult,
} from "@tanstack/react-query";

import type { AlertSeverity } from "@/lib/api/sightings";

/**
 * §3.9 / SPEC §55's event vocabulary.
 *
 * `alert_triggered` and `emergency_squawk` arrive from slice 038's alert
 * engine, which emits one event per match it actually recorded — the two are
 * separate types because SPEC §47 wants an emergency squawk prominent rather
 * than one entry among the alerts, and a feed filtered to `emergency_squawk`
 * is a question users genuinely ask.
 */
export type ActivityEventType =
  | "alert_triggered"
  | "first_ever_aircraft"
  | "new_type"
  | "range_record"
  | "receiver_record"
  | "emergency_squawk"
  | "receiver_offline"
  | "receiver_restored"
  | "metadata_updated"
  | "milestone";

/** Which rolling receiver record a `receiver_record` event describes. A new
 * furthest detection is *not* one of these — §3.9 gives it its own
 * `range_record` type. */
export type ReceiverRecordKind =
  "max_simultaneous" | "busiest_day" | "longest_sighting";

/**
 * One activity event (§3.9), identical over REST and over the `activity`
 * frame.
 *
 * `payload` is deliberately open. Each type carries the facts needed to
 * render *that* type, and the backend ships structured values rather than
 * prose — turning them into a sentence is
 * `features/activity/lib/describeActivityEvent.ts`'s job, which is why this
 * type stops at `Record<string, unknown>` and does not attempt a
 * discriminated union it would have to widen every time a producer learns to
 * say something more.
 */
export interface ActivityEvent {
  id: number;
  type: ActivityEventType;
  severity: AlertSeverity;
  /** UTC ISO-8601 with a `Z` suffix and millisecond precision (§2.2). */
  at: string;
  /** The airframe this event is about; `null` for a receiver-wide one. */
  icao: string | null;
  /** The sighting it happened during, where there is one. */
  sighting_id: number | null;
  payload: Record<string, unknown>;
}

export interface ActivityListResponse {
  items: ActivityEvent[];
  /** Always `null` — like `/sightings`, the feed grows without bound over a
   * multi-year install, so §2.4's allowance to omit an exact filtered count
   * applies and a client pages until a page comes back short of `limit`. */
  total: number | null;
  limit: number;
  offset: number;
}

interface ApiV1ErrorBody {
  error?: { code?: string; message?: string; detail?: unknown };
}

/** Thrown for any non-2xx response. `code` is the §2.5 machine-readable
 * slug, `null` when the response did not carry the documented envelope. */
export class ActivityApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(status: number, body: ApiV1ErrorBody | undefined) {
    super(body?.error?.message ?? `Request failed with status ${status}`);
    this.name = "ActivityApiError";
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
    throw new ActivityApiError(response.status, body);
  }
  return (await response.json()) as T;
}

export interface ActivityListParams {
  limit: number;
  offset: number;
  /** Restrict to these event types. Repeated as one `type=` parameter each —
   * which is what the endpoint accepts, and what keeps a filter chip's value
   * a value rather than a string the client has to escape. An empty array
   * means "no filter" and is omitted entirely. */
  types?: readonly ActivityEventType[];
  /** Inclusive lower bound on `at`, as a full ISO instant. */
  from?: string;
  /** Inclusive upper bound on `at`, as a full ISO instant. */
  to?: string;
}

function query(params: ActivityListParams): string {
  const search = new URLSearchParams({
    limit: String(params.limit),
    offset: String(params.offset),
  });
  for (const type of params.types ?? []) {
    search.append("type", type);
  }
  if (params.from !== undefined) {
    search.set("from", params.from);
  }
  if (params.to !== undefined) {
    search.set("to", params.to);
  }
  return search.toString();
}

export function getActivity(
  params: ActivityListParams,
): Promise<ActivityListResponse> {
  return apiV1Fetch<ActivityListResponse>(`/api/v1/activity?${query(params)}`);
}

export const activityQueryKeys = {
  list: (params: ActivityListParams) => ["activity", "list", params] as const,
};

/** One page of the feed. `placeholderData: keepPreviousData` keeps the rows
 * on screen while the next page loads — which matters more here than on a
 * table, because the Live Map panel re-runs this query on a filter change
 * and a flash of "Loading…" over a map control reads as a glitch. */
export function useActivityQuery(
  params: ActivityListParams,
): UseQueryResult<ActivityListResponse> {
  return useQuery({
    queryKey: activityQueryKeys.list(params),
    queryFn: () => getActivity(params),
    placeholderData: keepPreviousData,
  });
}
