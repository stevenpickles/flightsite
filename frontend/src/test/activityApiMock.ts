import { vi } from "vitest";

import type { ReceiverInfo } from "@/lib/api/live";
import type { ActivityEvent, ActivityListResponse } from "@/lib/api/activity";

import { defaultReceiverInfo } from "@/test/aircraftApiMock";

/** An `ActivityEvent`, defaulting to a fully-resolved first-ever sighting —
 * override just the fields a test cares about. */
export function activityEvent(
  overrides: Partial<ActivityEvent> = {},
): ActivityEvent {
  return {
    id: 4021,
    type: "first_ever_aircraft",
    severity: "info",
    at: "2026-08-31T14:03:22.418Z",
    icao: "ae1463",
    sighting_id: 88213,
    payload: {
      icao: "ae1463",
      registration: "N302DN",
      type_code: "B738",
      model: "Boeing 737-800",
      operator: "Delta Air Lines",
    },
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export interface MockActivityApiOptions {
  /** Response `GET /api/v1/activity` returns — a fixed document, or a
   * function of the parsed request URL for tests that vary the result by
   * filter or page. */
  list?: ActivityListResponse | ((url: URL) => ActivityListResponse);
  /** Serve an error envelope from `GET /api/v1/activity` instead. */
  listStatus?: number;
  receiver?: ReceiverInfo;
}

const EMPTY_LIST: ActivityListResponse = {
  items: [],
  total: null,
  limit: 50,
  offset: 0,
};

/** A `ActivityListResponse` wrapping `items`, with the `total: null` the
 * endpoint always returns (§2.4). */
export function activityList(
  items: ActivityEvent[],
  overrides: Partial<ActivityListResponse> = {},
): ActivityListResponse {
  return { items, total: null, limit: 50, offset: 0, ...overrides };
}

/** Installs a `global.fetch` stub serving `GET /api/v1/activity` plus
 * `GET /api/v1/receiver` (every row formats its timestamp in the receiver's
 * zone), so feed tests exercise the real API client and TanStack Query hooks
 * without a running backend. Any other URL throws, surfacing an un-mocked
 * request as a test failure rather than a silent empty render. */
export function installActivityApiMock(options: MockActivityApiOptions = {}) {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const raw = typeof input === "string" ? input : input.toString();
      const method = (init?.method ?? "GET").toUpperCase();
      const url = new URL(raw, "http://localhost");

      if (url.pathname === "/api/v1/receiver" && method === "GET") {
        return jsonResponse(options.receiver ?? defaultReceiverInfo());
      }

      if (url.pathname === "/api/v1/activity" && method === "GET") {
        if (options.listStatus !== undefined) {
          return jsonResponse(
            {
              error: {
                code: "internal_error",
                message: "The activity feed is unavailable",
                detail: null,
              },
            },
            options.listStatus,
          );
        }
        const body =
          typeof options.list === "function"
            ? options.list(url)
            : (options.list ?? EMPTY_LIST);
        return jsonResponse(body);
      }

      throw new Error(`Unhandled fetch in test: ${method} ${raw}`);
    },
  );

  vi.stubGlobal("fetch", fetchMock);

  return { fetchMock };
}
