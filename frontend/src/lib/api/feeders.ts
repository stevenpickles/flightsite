/**
 * Typed client for the Feeders page's endpoints — `GET /api/v1/feeders` and
 * `GET /api/v1/feeders/{name}/history` (`docs/design/077-feeders-page.md`
 * "API", roadmap slice 077).
 *
 * Uses `lib/api/client.ts`'s `apiFetch`/`ApiError`/`describeError` rather
 * than the per-module `apiV1Fetch` + `{"error": {...}}` envelope most other
 * `/api/v1` clients duplicate (`lib/api/receiverStats.ts`,
 * `lib/api/diagnostics.ts`, `lib/api/activity.ts`) — the slice-076 refresh
 * settled on `describeError` as the shared error-rendering convention for
 * new pages. CONTRACT GAP: the design record does not pin down which error
 * envelope `/api/v1/feeders` itself emits; `apiFetch` reads a FastAPI-style
 * `{"detail": ...}` body, matching `/api/internal`. If the backend instead
 * emits the `{"error": {code, message}}` envelope the other v1 modules use,
 * a failed request still resolves to a typed `ApiError` (so `describeError`
 * never throws), just with a generic "Request failed with status NNN"
 * message instead of the backend's own text — flagged for the integrator to
 * reconcile once agents A/B's backend lands.
 *
 * The one exception is the per-feeder stats link
 * (`GET /api/internal/feeders/{name}/stats-link`): it is never fetched from
 * this module (or anywhere in the frontend) — `FeederCard` renders it as a
 * plain `<a target="_blank">`, per the design record's redaction rule that
 * the secret URL it 302s to must never reach `/api/v1`, logs, or the DOM.
 */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";

/** The per-feeder state machine's four values (design record "Backend
 * package"). `unknown` covers both "not polled yet" and a socket-only
 * signal read without `docker_socket` configured — never `down`. */
export type FeederState = "up" | "degraded" | "down" | "unknown";

/** How a feeder's status was actually observed — `"none"` is the socket-off
 * case for a kind that needs the Docker socket for anything beyond HTTP
 * (`ultrafeeder`'s ADS-B-out state, `opensky_logs`, `docker_health`). */
export type FeederObservability = "http" | "docker" | "none";

/** Mirrors the `feeders` diagnostics section's own enum
 * (`lib/api/diagnostics.ts`) — reused here for the top-level `docker_socket`
 * field the design record lists on `GET /api/v1/feeders` itself. */
export type DockerSocketState = "available" | "unset" | "unreachable";

export type FeederKind =
  | "readsb"
  | "piaware"
  | "fr24"
  | "ultrafeeder"
  | "opensky_logs"
  | "docker_health"
  | "link_only";

/** The receiver's own uplink summary (`kind: "readsb"`), rendered as tiles
 * at the top of the page rather than a card of its own — `null` when the
 * receiver entry itself is not configured. */
export interface FeederReceiverUplink {
  bytes_out_rate_per_s: number | null;
  messages_per_min: number | null;
  aircraft: number | null;
  mlat_inbound: number | null;
  samples_dropped: number | null;
  max_range_nm: number | null;
}

/** ADS-B Exchange / AeroDataBox MLAT client stats, read over HTTP
 * regardless of the Docker socket (design record's survey table). */
export interface FeederMlatStatus {
  peers: number | null;
  good_sync_pct: number | null;
  bad_sync_timeout_s: number | null;
  last_bad_sync_at: string | null;
}

/** `ultrafeeder`'s BeastReduce ADS-B-out connection state, from container
 * logs — only present with the Docker socket configured. */
export interface FeederAdsbOutStatus {
  connected: boolean;
  since: string | null;
}

export interface FeederEntry {
  name: string;
  label: string;
  kind: FeederKind;
  state: FeederState;
  observability: FeederObservability;
  since: string | null;
  last_polled_at: string | null;
  last_success_at: string | null;
  last_data_sent_at: string | null;
  message: string | null;
  mlat: FeederMlatStatus | null;
  adsb_out: FeederAdsbOutStatus | null;
  /** Kind-specific, already redacted by the backend (design record: "never
   * link `/settings.html`", "never read `/run/adsbexchange-stats/*.json`",
   * FR24's `fr24key`/`feed_alias`/`feed_legacy_id`/`local_ips` stripped,
   * FlightAware's `site_url` withheld). Rendered loosely (kind is not
   * narrowed client-side) since this module's job is to carry the payload,
   * not re-implement each vendor's vocabulary the backend already isolated
   * one module per kind for. */
  detail: Record<string, unknown>;
  web_url: string | null;
  /** Whether `GET /api/internal/feeders/{name}/stats-link` has a secret URL
   * configured for this feeder — never the URL itself. */
  stats_link: boolean;
}

export interface FeederLocalPage {
  label: string;
  url: string;
}

export interface FeedersResponse {
  generated_at: string;
  poll_interval_s: number;
  docker_socket: DockerSocketState;
  receiver: FeederReceiverUplink | null;
  feeders: FeederEntry[];
  local_pages: FeederLocalPage[];
}

export type FeederHistoryWindow = "24h" | "7d" | "30d";

export interface FeederEpisode {
  state: FeederState;
  started_at: string;
  ended_at: string | null;
}

/** Kind-specific sample metrics (MLAT peers, bytes-out rate, positions per
 * minute, …) — loose on purpose: `FeederMetricsChart` reads only the keys a
 * given metric family needs and treats every other key as absent, the same
 * tolerance `detail` above needs for the same reason. */
export type FeederSampleMetrics = Record<string, number | null>;

export interface FeederSample {
  t: string;
  state: FeederState;
  metrics: FeederSampleMetrics;
}

export interface FeederHistory {
  episodes: FeederEpisode[];
  samples: FeederSample[];
  availability_pct: number;
}

/** How often the page re-polls while open — matches the design record's
 * `FEEDERS_POLL_MS = 10_000` and the slice-076 refresh convention of a
 * short, explicit per-query interval rather than the app-wide (no-poll)
 * default (`lib/queryClient.ts`). */
export const FEEDERS_POLL_MS = 10_000;

export const feedersQueryKey = ["feeders"] as const;

export function getFeeders(): Promise<FeedersResponse> {
  return apiFetch<FeedersResponse>("/api/v1/feeders");
}

/** `refetchOnWindowFocus: true` gives a returning user a free extra chance
 * beyond the poll interval (mirrors `RESILIENT_QUERY_OPTIONS` in
 * `lib/api/receiverStats.ts`); a background failure keeps the last good
 * payload in `data` (TanStack Query's default) rather than clearing the
 * page out from under a banner. */
export function useFeedersQuery(): UseQueryResult<FeedersResponse> {
  return useQuery({
    queryKey: feedersQueryKey,
    queryFn: getFeeders,
    refetchInterval: FEEDERS_POLL_MS,
    refetchOnWindowFocus: true,
  });
}

export function getFeederHistory(
  name: string,
  window: FeederHistoryWindow,
): Promise<FeederHistory> {
  return apiFetch<FeederHistory>(
    `/api/v1/feeders/${encodeURIComponent(name)}/history?window=${window}`,
  );
}

export function feederHistoryQueryKey(
  name: string,
  window: FeederHistoryWindow,
) {
  return ["feeders", "history", name, window] as const;
}

export function useFeederHistoryQuery(
  name: string,
  window: FeederHistoryWindow,
): UseQueryResult<FeederHistory> {
  return useQuery({
    queryKey: feederHistoryQueryKey(name, window),
    queryFn: () => getFeederHistory(name, window),
    refetchInterval: FEEDERS_POLL_MS,
    refetchOnWindowFocus: true,
  });
}
