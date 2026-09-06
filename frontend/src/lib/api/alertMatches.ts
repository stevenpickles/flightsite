/**
 * Typed client for the alert match history — `GET /api/v1/alerts/matches`
 * (docs/API.md §3.9, SPEC §43 to §48, roadmap slices 038/041).
 *
 * Reuses the `apiV1Fetch` pattern `lib/api/activity.ts` established for the
 * external `/api/v1` surface's `{"error": {...}}` envelope (§2.5) —
 * duplicated rather than imported so this module stays a self-contained read
 * of one small file, the same call `lib/api/sightings.ts` makes.
 *
 * History is a *record*, not a re-derivation: `reason` is the text recorded
 * when the match happened, so the history keeps saying what the user was
 * actually shown even after the rule behind it is renamed or retuned. This
 * client therefore never recomposes a row from the current rule set.
 */
import {
  keepPreviousData,
  useQuery,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type { AlertSeverity } from "@/lib/api/sightings";

/** The rule an alert match names. `null` on the match itself for a built-in
 * emergency detection, which fires without any rule at all (SPEC §47). */
export interface AlertMatchRuleRef {
  id: number;
  /** `null` only if the rule row vanished between the match and this read. */
  name: string | null;
}

export interface AlertMatch {
  id: number;
  /** UTC ISO-8601 with a `Z` suffix and millisecond precision (§2.2). */
  at: string;
  severity: AlertSeverity;
  reason: string;
  icao: string;
  sighting_id: number;
  /** `null` for a built-in emergency match. */
  rule: AlertMatchRuleRef | null;
  /** `null` for a rule match; a built-in detector's key (e.g.
   * `"emergency_7700"`) otherwise. */
  builtin_key: string | null;
  /**
   * Whether at least one FlightSite client actually showed a browser
   * `Notification` for this match.
   *
   * Not "the backend broadcast it": permission may be denied, the severity
   * may be muted, the tab may already have shown that event. The client that
   * constructed the notification is the only party that knows, so it is the
   * one that asserts it — see {@link markAlertMatchNotified}.
   */
  notified: boolean;
}

export interface AlertMatchListResponse {
  items: AlertMatch[];
  /** Always `null` — the history grows without bound over a multi-year
   * install, so §2.4's allowance to omit an exact filtered count applies and
   * a client pages until a page comes back short of `limit`. */
  total: number | null;
  limit: number;
  offset: number;
}

interface ApiV1ErrorBody {
  error?: { code?: string; message?: string; detail?: unknown };
}

/** Thrown for any non-2xx response. `code` is the §2.5 machine-readable
 * slug, `null` when the response did not carry the documented envelope. */
export class AlertMatchesApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(status: number, body: ApiV1ErrorBody | undefined) {
    super(body?.error?.message ?? `Request failed with status ${status}`);
    this.name = "AlertMatchesApiError";
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
    throw new AlertMatchesApiError(response.status, body);
  }
  return (await response.json()) as T;
}

export interface AlertMatchListParams {
  limit: number;
  offset: number;
  /** Restrict to one severity of the §2.8 ladder. */
  severity?: AlertSeverity;
  /** Restrict to one airframe, as lower-case ICAO hex (§2.9). */
  icao?: string;
  /**
   * Restrict to the matches one rule produced — "show me what this rule has
   * caught" (issue #98).
   *
   * An id no rule owns is not an error: the endpoint answers with an empty
   * page, the same as a rule that has simply never fired. That matters here
   * because a rule can be deleted while its history is on screen, and the
   * honest answer to "what did that rule catch" then really is "nothing" —
   * deleting a rule deletes its matches.
   */
  rule_id?: number;
}

function query(params: AlertMatchListParams): string {
  const search = new URLSearchParams({
    limit: String(params.limit),
    offset: String(params.offset),
  });
  if (params.severity !== undefined) {
    search.set("severity", params.severity);
  }
  if (params.icao !== undefined) {
    search.set("icao", params.icao);
  }
  if (params.rule_id !== undefined) {
    search.set("rule_id", String(params.rule_id));
  }
  return search.toString();
}

export function getAlertMatches(
  params: AlertMatchListParams,
): Promise<AlertMatchListResponse> {
  return apiV1Fetch<AlertMatchListResponse>(
    `/api/v1/alerts/matches?${query(params)}`,
  );
}

/**
 * Records that a browser notification was actually shown for one match —
 * `POST /api/internal/alerts/matches/{id}/notified` (docs/API.md §5, issue
 * #104).
 *
 * The one write on this module, and the one call that reaches the *internal*
 * surface rather than `/api/v1`, which is why it goes through `apiFetch`
 * (`lib/api/client.ts`) instead of the read helper above: the two surfaces
 * shape their errors differently (§2.5's envelope versus FastAPI's `detail`),
 * and each is parsed by the helper written for it.
 *
 * Empty body on purpose: the assertion *is* the request, and there is no value
 * a caller could set. Resolves for a repeat too — the endpoint is idempotent,
 * because "someone was notified" does not become more true the second time two
 * tabs both say it.
 */
export function markAlertMatchNotified(matchId: number): Promise<void> {
  return apiFetch<void>(`/api/internal/alerts/matches/${matchId}/notified`, {
    method: "POST",
  });
}

export const alertMatchesQueryKeys = {
  list: (params: AlertMatchListParams) =>
    ["alert-matches", "list", params] as const,
};

/** One page of the history. `placeholderData: keepPreviousData` keeps the
 * rows on screen while the next page loads, so paging or changing the
 * severity filter does not blank the table between answers. */
export function useAlertMatchesQuery(
  params: AlertMatchListParams,
): UseQueryResult<AlertMatchListResponse> {
  return useQuery({
    queryKey: alertMatchesQueryKeys.list(params),
    queryFn: () => getAlertMatches(params),
    placeholderData: keepPreviousData,
  });
}
