import { vi } from "vitest";

import type {
  FeederEntry,
  FeederEpisode,
  FeederHistory,
  FeederHistoryWindow,
  FeederReceiverUplink,
  FeedersResponse,
  FeederSample,
} from "@/lib/api/feeders";

import { defaultReceiverInfo } from "@/test/aircraftApiMock";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function receiverUplink(
  overrides: Partial<FeederReceiverUplink> = {},
): FeederReceiverUplink {
  return {
    bytes_out_rate_per_s: 18_432,
    messages_per_min: 8_710,
    aircraft: 12,
    mlat_inbound: 9,
    samples_dropped: 0,
    max_range_nm: 241.6,
    ...overrides,
  };
}

/** A single, generally-healthy feeder — every test overrides the one field
 * it is about, the same "healthy install first" convention
 * `test/diagnosticsApiMock.ts` uses. */
export function feeder(overrides: Partial<FeederEntry> = {}): FeederEntry {
  return {
    name: "flightaware",
    label: "FlightAware",
    kind: "piaware",
    state: "up",
    observability: "http",
    since: "2026-09-25T12:00:00.000Z",
    last_polled_at: "2026-09-26T13:59:50.000Z",
    last_success_at: "2026-09-26T13:59:50.000Z",
    last_data_sent_at: "2026-09-26T13:59:45.000Z",
    message: null,
    mlat: null,
    adsb_out: null,
    detail: {},
    web_url: "http://fermi.local:8081/",
    stats_link: true,
    ...overrides,
  };
}

export function feedersResponse(
  overrides: Partial<FeedersResponse> = {},
): FeedersResponse {
  return {
    generated_at: "2026-09-26T14:00:00.000Z",
    poll_interval_s: 15,
    docker_socket: "available",
    receiver: receiverUplink(),
    feeders: [
      feeder(),
      feeder({
        name: "adsbx",
        label: "ADS-B Exchange",
        kind: "ultrafeeder",
        mlat: {
          peers: 6,
          good_sync_pct: 98.4,
          bad_sync_timeout_s: 0,
          last_bad_sync_at: null,
        },
        adsb_out: { connected: true, since: "2026-09-25T12:00:00.000Z" },
        web_url: "http://fermi.local:8080/",
        stats_link: true,
      }),
      feeder({
        name: "fr24",
        label: "FlightRadar24",
        kind: "fr24",
        state: "down",
        message: "Remote server disconnected",
        web_url: "http://fermi.local:8754/",
        stats_link: false,
      }),
    ],
    local_pages: [
      { label: "tar1090", url: "http://fermi.local:8080/" },
      { label: "graphs1090", url: "http://fermi.local:8080/graphs1090/" },
      { label: "SkyAware", url: "http://fermi.local:8081/" },
      { label: "FR24 feeder", url: "http://fermi.local:8754/" },
    ],
    ...overrides,
  };
}

export function feederEpisode(
  overrides: Partial<FeederEpisode> = {},
): FeederEpisode {
  return {
    state: "up",
    started_at: "2026-09-25T12:00:00.000Z",
    ended_at: null,
    ...overrides,
  };
}

export function feederSample(
  overrides: Partial<FeederSample> = {},
): FeederSample {
  return {
    t: "2026-09-26T13:00:00.000Z",
    state: "up",
    metrics: {
      mlat_peers: 6,
      bytes_out_rate_per_s: 18_000,
      positions_per_min: 42,
    },
    ...overrides,
  };
}

export function feederHistory(
  overrides: Partial<FeederHistory> = {},
): FeederHistory {
  return {
    episodes: [feederEpisode()],
    samples: [
      feederSample({ t: "2026-09-26T12:00:00.000Z" }),
      feederSample({ t: "2026-09-26T13:00:00.000Z" }),
    ],
    availability_pct: 100,
    ...overrides,
  };
}

export interface MockFeedersApiOptions {
  feeders?: FeedersResponse;
  /** Response for `GET /api/v1/feeders/{name}/history`, keyed by
   * `name:window`. A request with no entry falls back to `feederHistory()`. */
  history?: Partial<Record<string, FeederHistory>>;
  receiver?: ReturnType<typeof defaultReceiverInfo>;
  /** Serve this status instead of a body for `GET /api/v1/feeders`,
   * for error-path tests. */
  status?: number;
}

function historyKey(name: string, window: FeederHistoryWindow): string {
  return `${name}:${window}`;
}

/** Installs a `global.fetch` stub serving `GET /api/v1/feeders`,
 * `GET /api/v1/feeders/{name}/history` and `GET /api/v1/receiver` (the
 * page's timezone/units source, the same `useReceiverQuery` every other
 * page reads), so Feeders page tests can exercise the real API clients and
 * TanStack Query hooks without a running backend. Any other URL throws,
 * surfacing an un-mocked request as a test failure. */
export function installFeedersApiMock(options: MockFeedersApiOptions = {}) {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const raw = typeof input === "string" ? input : input.toString();
      const method = (init?.method ?? "GET").toUpperCase();
      const url = new URL(raw, "http://localhost");

      if (url.pathname === "/api/v1/receiver" && method === "GET") {
        return jsonResponse(options.receiver ?? defaultReceiverInfo());
      }

      if (url.pathname === "/api/v1/feeders" && method === "GET") {
        if (options.status !== undefined && options.status >= 400) {
          return jsonResponse(
            { detail: "Feeders unavailable" },
            options.status,
          );
        }
        return jsonResponse(options.feeders ?? feedersResponse());
      }

      const historyMatch = /^\/api\/v1\/feeders\/([^/]+)\/history$/.exec(
        url.pathname,
      );
      if (historyMatch && method === "GET") {
        const name = decodeURIComponent(historyMatch[1] ?? "");
        const window = (url.searchParams.get("window") ??
          "24h") as FeederHistoryWindow;
        const body =
          options.history?.[historyKey(name, window)] ?? feederHistory();
        return jsonResponse(body);
      }

      throw new Error(`Unhandled fetch in test: ${method} ${raw}`);
    },
  );

  vi.stubGlobal("fetch", fetchMock);

  return { fetchMock };
}
