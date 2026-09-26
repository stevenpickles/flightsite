import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getFeederHistory,
  getFeeders,
  useFeederHistoryQuery,
  useFeedersQuery,
} from "@/lib/api/feeders";
import { ApiError, NetworkError } from "@/lib/api/client";
import { createQueryWrapper } from "@/test/queryWrapper";
import {
  feederHistory,
  feedersResponse,
  installFeedersApiMock,
} from "@/test/feedersApiMock";

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("getFeeders", () => {
  it("requests /api/v1/feeders and resolves the parsed body", async () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(jsonResponse(feedersResponse())),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getFeeders();

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/feeders");
    expect(result.feeders.length).toBeGreaterThan(0);
    expect(result.docker_socket).toBe("available");
  });

  it("throws ApiError on a non-2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(jsonResponse({ detail: "Feeders unavailable" }, 503)),
      ),
    );

    await expect(getFeeders()).rejects.toBeInstanceOf(ApiError);
  });

  it("throws NetworkError when fetch itself rejects", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))),
    );

    await expect(getFeeders()).rejects.toBeInstanceOf(NetworkError);
  });
});

describe("getFeederHistory", () => {
  it("requests the per-feeder history path with the window query param", async () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(jsonResponse(feederHistory())),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getFeederHistory("adsbx", "7d");

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/v1/feeders/adsbx/history?window=7d",
    );
    expect(result.availability_pct).toBe(100);
  });

  it("encodes the feeder name in the path", async () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(jsonResponse(feederHistory())),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getFeederHistory("a b", "24h");

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/v1/feeders/a%20b/history?window=24h",
    );
  });
});

describe("useFeedersQuery", () => {
  it("resolves the feeders payload through the query hook", async () => {
    installFeedersApiMock();

    const { result } = renderHook(() => useFeedersQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.feeders.length).toBeGreaterThan(0);
  });
});

describe("useFeederHistoryQuery", () => {
  it("resolves the history payload for the given feeder and window", async () => {
    installFeedersApiMock({
      history: {
        "adsbx:30d": feederHistory({ availability_pct: 87.5 }),
      },
    });

    const { result } = renderHook(() => useFeederHistoryQuery("adsbx", "30d"), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.availability_pct).toBe(87.5);
  });
});
