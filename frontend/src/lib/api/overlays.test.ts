import { afterEach, describe, expect, it, vi } from "vitest";

import { getAirports, getAirspace } from "@/lib/api/overlays";

const FEATURE_COLLECTION = { type: "FeatureCollection", features: [] };

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getAirports", () => {
  it("requests the bare endpoint when no params are given", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify(FEATURE_COLLECTION), { status: 200 }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getAirports({});

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/airports");
  });

  it("encodes bbox and min_size as query params", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL) =>
      Promise.resolve(
        new Response(JSON.stringify(FEATURE_COLLECTION), { status: 200 }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getAirports({ bbox: "-123,47,-121.9,47.8", minSize: "medium" });

    const url = new URL(
      String(fetchMock.mock.calls[0]?.[0]),
      "http://localhost",
    );
    expect(url.pathname).toBe("/api/v1/airports");
    expect(url.searchParams.get("bbox")).toBe("-123,47,-121.9,47.8");
    expect(url.searchParams.get("min_size")).toBe("medium");
  });

  it("resolves the parsed feature collection on a 2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify(FEATURE_COLLECTION), { status: 200 }),
        ),
      ),
    );

    await expect(getAirports({})).resolves.toEqual(FEATURE_COLLECTION);
  });

  it("rejects with a readable error on a non-2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response("", { status: 503 }))),
    );

    await expect(getAirports({})).rejects.toThrow("status 503");
  });
});

describe("getAirspace", () => {
  it("requests GET /api/v1/airspace and resolves the parsed body", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify(FEATURE_COLLECTION), { status: 200 }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getAirspace()).resolves.toEqual(FEATURE_COLLECTION);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/airspace");
  });

  it("rejects with a readable error on a non-2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response("", { status: 500 }))),
    );

    await expect(getAirspace()).rejects.toThrow("status 500");
  });
});
