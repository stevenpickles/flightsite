import { afterEach, describe, expect, it, vi } from "vitest";

import {
  SightingsApiError,
  getAircraftSightings,
  getSightingDetail,
  getSightingList,
} from "@/lib/api/sightings";

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

describe("getSightingList", () => {
  it("always sends limit/offset/sort/order and omits unset filters", async () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(
        jsonResponse({ items: [], total: null, limit: 50, offset: 0 }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getSightingList({
      limit: 50,
      offset: 0,
      sort: "started_at",
      order: "desc",
    });

    const url = new URL(
      String(fetchMock.mock.calls[0]?.[0]),
      "http://localhost",
    );
    expect(url.pathname).toBe("/api/v1/sightings");
    expect(url.searchParams.get("limit")).toBe("50");
    expect(url.searchParams.get("offset")).toBe("0");
    expect(url.searchParams.get("sort")).toBe("started_at");
    expect(url.searchParams.get("order")).toBe("desc");
    expect(url.searchParams.has("icao")).toBe(false);
    expect(url.searchParams.has("from")).toBe(false);
    expect(url.searchParams.has("to")).toBe(false);
    expect(url.searchParams.has("interesting")).toBe(false);
    expect(url.searchParams.has("open")).toBe(false);
  });

  it("adds the optional filters when given", async () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(
        jsonResponse({ items: [], total: null, limit: 50, offset: 0 }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getSightingList({
      limit: 50,
      offset: 0,
      sort: "started_at",
      order: "desc",
      icao: "ae1463",
      from: "2026-08-01T00:00:00.000Z",
      to: "2026-08-31T23:59:59.999Z",
      interesting: true,
      open: true,
    });

    const url = new URL(
      String(fetchMock.mock.calls[0]?.[0]),
      "http://localhost",
    );
    expect(url.searchParams.get("icao")).toBe("ae1463");
    expect(url.searchParams.get("from")).toBe("2026-08-01T00:00:00.000Z");
    expect(url.searchParams.get("to")).toBe("2026-08-31T23:59:59.999Z");
    expect(url.searchParams.get("interesting")).toBe("true");
    expect(url.searchParams.get("open")).toBe("true");
  });

  it("throws SightingsApiError carrying the §2.5 code and message on a non-2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          jsonResponse(
            {
              error: {
                code: "validation_error",
                message: "bad sort key",
                detail: null,
              },
            },
            422,
          ),
        ),
      ),
    );

    await expect(
      getSightingList({
        limit: 50,
        offset: 0,
        sort: "started_at",
        order: "desc",
      }),
    ).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      message: "bad sort key",
    });
  });

  it("still throws SightingsApiError when the error response has no JSON body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response("", { status: 500 }))),
    );

    const error = await getSightingDetail(1).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(SightingsApiError);
    expect((error as SightingsApiError).status).toBe(500);
    expect((error as SightingsApiError).code).toBeNull();
  });
});

describe("getSightingDetail", () => {
  it("requests the id-scoped path", async () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(jsonResponse({ id: 88213, icao: "ae1463" })),
    );
    vi.stubGlobal("fetch", fetchMock);

    const detail = await getSightingDetail(88213);

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/sightings/88213");
    expect(detail.id).toBe(88213);
  });
});

describe("getAircraftSightings", () => {
  it("requests the icao-scoped path with defaulted sort/order", async () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(
        jsonResponse({ items: [], total: null, limit: 5, offset: 0 }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getAircraftSightings({ icao: "ae1463", limit: 5, offset: 0 });

    const url = new URL(
      String(fetchMock.mock.calls[0]?.[0]),
      "http://localhost",
    );
    expect(url.pathname).toBe("/api/v1/aircraft/ae1463/sightings");
    expect(url.searchParams.get("sort")).toBe("started_at");
    expect(url.searchParams.get("order")).toBe("desc");
  });
});
