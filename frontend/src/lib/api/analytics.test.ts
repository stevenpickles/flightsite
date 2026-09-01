import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AnalyticsApiError,
  getAnalyticsClassificationActivity,
  getAnalyticsDaily,
  getAnalyticsRarity,
  getAnalyticsTopAircraft,
  getAnalyticsTopOperators,
  getAnalyticsTopTypes,
} from "@/lib/api/analytics";

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

const EMPTY_WINDOW = {
  preset: "today",
  from: "2026-08-31T00:00:00.000Z",
  to: "2026-09-01T00:00:00.000Z",
  first_day: "2026-08-31",
  last_day: "2026-08-31",
  timezone: "UTC",
};

describe("getAnalyticsDaily", () => {
  it("sends only the preset by default", async () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(jsonResponse({ window: EMPTY_WINDOW, items: [] })),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getAnalyticsDaily({ preset: "7d" });

    const url = new URL(
      String(fetchMock.mock.calls[0]?.[0]),
      "http://localhost",
    );
    expect(url.pathname).toBe("/api/v1/analytics/daily");
    expect(url.searchParams.get("preset")).toBe("7d");
    expect(url.searchParams.has("limit")).toBe(false);
  });

  it("throws AnalyticsApiError carrying the §2.5 code and message on a non-2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
        Promise.resolve(
          jsonResponse(
            {
              error: {
                code: "validation_error",
                message: "bad preset",
                detail: null,
              },
            },
            422,
          ),
        ),
      ),
    );

    await expect(getAnalyticsDaily({ preset: "today" })).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      message: "bad preset",
    });
  });

  it("still throws AnalyticsApiError when the error response has no JSON body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
        Promise.resolve(new Response("", { status: 500 })),
      ),
    );

    const error = await getAnalyticsDaily({ preset: "today" }).catch(
      (caught: unknown) => caught,
    );

    expect(error).toBeInstanceOf(AnalyticsApiError);
    expect((error as AnalyticsApiError).status).toBe(500);
    expect((error as AnalyticsApiError).code).toBeNull();
  });
});

describe("getAnalyticsClassificationActivity", () => {
  it("requests the classification-activity path", async () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(
        jsonResponse({
          window: EMPTY_WINDOW,
          military: 0,
          government: 0,
          law_enforcement: 0,
          interesting: 0,
          series: [],
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getAnalyticsClassificationActivity({ preset: "ytd" });

    const url = new URL(
      String(fetchMock.mock.calls[0]?.[0]),
      "http://localhost",
    );
    expect(url.pathname).toBe("/api/v1/analytics/classification-activity");
    expect(url.searchParams.get("preset")).toBe("ytd");
  });
});

describe("ranking endpoints", () => {
  it("getAnalyticsTopAircraft includes limit when given", async () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(jsonResponse({ window: EMPTY_WINDOW, items: [] })),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getAnalyticsTopAircraft({ preset: "t0", limit: 5 });

    const url = new URL(
      String(fetchMock.mock.calls[0]?.[0]),
      "http://localhost",
    );
    expect(url.pathname).toBe("/api/v1/analytics/top-aircraft");
    expect(url.searchParams.get("limit")).toBe("5");
  });

  it("getAnalyticsTopTypes and getAnalyticsTopOperators hit their own paths", async () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(jsonResponse({ window: EMPTY_WINDOW, items: [] })),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getAnalyticsTopTypes({ preset: "30d" });
    await getAnalyticsTopOperators({ preset: "30d" });

    expect(
      new URL(String(fetchMock.mock.calls[0]?.[0]), "http://localhost")
        .pathname,
    ).toBe("/api/v1/analytics/top-types");
    expect(
      new URL(String(fetchMock.mock.calls[1]?.[0]), "http://localhost")
        .pathname,
    ).toBe("/api/v1/analytics/top-operators");
  });
});

describe("getAnalyticsRarity", () => {
  it("includes limit and max_sightings when given", async () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(
        jsonResponse({
          window: EMPTY_WINDOW,
          never_seen_before: 0,
          rare_max_sightings: 2,
          rare_max_type_aircraft: 2,
          rare_aircraft: [],
          rare_types: [],
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getAnalyticsRarity({ preset: "today", limit: 8, maxSightings: 3 });

    const url = new URL(
      String(fetchMock.mock.calls[0]?.[0]),
      "http://localhost",
    );
    expect(url.pathname).toBe("/api/v1/analytics/rarity");
    expect(url.searchParams.get("limit")).toBe("8");
    expect(url.searchParams.get("max_sightings")).toBe("3");
  });

  it("omits limit and max_sightings when not given", async () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(
        jsonResponse({
          window: EMPTY_WINDOW,
          never_seen_before: 0,
          rare_max_sightings: 2,
          rare_max_type_aircraft: 2,
          rare_aircraft: [],
          rare_types: [],
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getAnalyticsRarity({ preset: "today" });

    const url = new URL(
      String(fetchMock.mock.calls[0]?.[0]),
      "http://localhost",
    );
    expect(url.searchParams.has("limit")).toBe(false);
    expect(url.searchParams.has("max_sightings")).toBe(false);
  });
});
