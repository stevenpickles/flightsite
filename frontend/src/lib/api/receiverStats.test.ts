import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ReceiverStatsApiError,
  getReceiverLifetimeStats,
  getReceiverMetricSeries,
  getReceiverRangeByBearing,
  getReceiverScorecard,
  getReceiverSignalDistribution,
} from "@/lib/api/receiverStats";

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

describe("getReceiverScorecard", () => {
  it("requests the scorecard path and resolves the parsed body", async () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(
        jsonResponse({
          current_visible: 3,
          current_positioned: 2,
          messages_per_sec: 10,
          positions_per_sec: 1,
          max_range_today_nm: null,
          max_range_ever_nm: null,
          unique_aircraft_today: 0,
          unique_aircraft_since_t0: 0,
          decoder_uptime_s: null,
          flightsite_uptime_s: 5,
          health: "unknown",
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getReceiverScorecard();

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/receiver/scorecard");
    expect(result.current_visible).toBe(3);
    expect(result.health).toBe("unknown");
  });

  it("throws ReceiverStatsApiError carrying the §2.5 code on a non-2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
        Promise.resolve(
          jsonResponse(
            {
              error: {
                code: "service_unavailable",
                message: "db down",
                detail: null,
              },
            },
            503,
          ),
        ),
      ),
    );

    await expect(getReceiverScorecard()).rejects.toMatchObject({
      status: 503,
      code: "service_unavailable",
      message: "db down",
    });
  });

  it("still throws ReceiverStatsApiError when the error response has no JSON body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
        Promise.resolve(new Response("", { status: 500 })),
      ),
    );

    const error = await getReceiverScorecard().catch(
      (caught: unknown) => caught,
    );

    expect(error).toBeInstanceOf(ReceiverStatsApiError);
    expect((error as ReceiverStatsApiError).status).toBe(500);
    expect((error as ReceiverStatsApiError).code).toBeNull();
  });
});

describe("getReceiverMetricSeries", () => {
  it("sends metric/resolution and omits unset from/to", async () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(
        jsonResponse({
          metric: "messages_per_sec",
          resolution: "hourly",
          points: [],
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getReceiverMetricSeries({
      metric: "messages_per_sec",
      resolution: "hourly",
    });

    const url = new URL(
      String(fetchMock.mock.calls[0]?.[0]),
      "http://localhost",
    );
    expect(url.pathname).toBe("/api/v1/receiver/metrics");
    expect(url.searchParams.get("metric")).toBe("messages_per_sec");
    expect(url.searchParams.get("resolution")).toBe("hourly");
    expect(url.searchParams.has("from")).toBe(false);
    expect(url.searchParams.has("to")).toBe(false);
  });

  it("adds from/to when given", async () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(
        jsonResponse({
          metric: "max_range_nm",
          resolution: "daily",
          points: [],
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getReceiverMetricSeries({
      metric: "max_range_nm",
      resolution: "daily",
      from: "2026-08-01T00:00:00.000Z",
      to: "2026-08-31T00:00:00.000Z",
    });

    const url = new URL(
      String(fetchMock.mock.calls[0]?.[0]),
      "http://localhost",
    );
    expect(url.searchParams.get("from")).toBe("2026-08-01T00:00:00.000Z");
    expect(url.searchParams.get("to")).toBe("2026-08-31T00:00:00.000Z");
  });
});

describe("getReceiverRangeByBearing", () => {
  it("requests the range-by-bearing path", async () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(
        jsonResponse({ sector_width_deg: 5, today: [], ever: [] }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getReceiverRangeByBearing();

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/v1/receiver/range-by-bearing",
    );
  });
});

describe("getReceiverSignalDistribution", () => {
  it("requests the bare path when no params are given", async () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(
        jsonResponse({
          from_ts: null,
          to_ts: null,
          bucket_width_db: 3,
          buckets: [],
          sample_count: 0,
          min_db: null,
          max_db: null,
          avg_db: null,
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getReceiverSignalDistribution();

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/v1/receiver/signal-distribution",
    );
  });

  it("adds from/to/bucketWidthDb when given", async () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(
        jsonResponse({
          from_ts: null,
          to_ts: null,
          bucket_width_db: 5,
          buckets: [],
          sample_count: 0,
          min_db: null,
          max_db: null,
          avg_db: null,
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getReceiverSignalDistribution({
      from: "2026-08-01T00:00:00.000Z",
      to: "2026-08-31T00:00:00.000Z",
      bucketWidthDb: 5,
    });

    const url = new URL(
      String(fetchMock.mock.calls[0]?.[0]),
      "http://localhost",
    );
    expect(url.pathname).toBe("/api/v1/receiver/signal-distribution");
    expect(url.searchParams.get("from")).toBe("2026-08-01T00:00:00.000Z");
    expect(url.searchParams.get("to")).toBe("2026-08-31T00:00:00.000Z");
    expect(url.searchParams.get("bucket_width_db")).toBe("5");
  });
});

describe("getReceiverLifetimeStats", () => {
  it("requests the lifetime path", async () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(
        jsonResponse({
          since: null,
          unique_aircraft: 0,
          total_sightings: 0,
          total_positions: null,
          total_messages: null,
          max_range: null,
          peak_message_rate_per_sec: null,
          peak_position_rate_per_sec: null,
          max_simultaneous_aircraft: null,
          busiest_day: null,
          most_frequent_aircraft: null,
          common_type: null,
          common_model: null,
          common_operator: null,
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getReceiverLifetimeStats();

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/receiver/lifetime");
  });
});
