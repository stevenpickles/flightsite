import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiV1Error,
  getAircraftDetail,
  getAircraftList,
} from "@/lib/api/aircraft";

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

describe("getAircraftList", () => {
  it("always sends limit/offset/sort/order", async () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(
        jsonResponse({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getAircraftList({
      limit: 50,
      offset: 0,
      sort: "last_seen",
      order: "desc",
    });

    const url = new URL(
      String(fetchMock.mock.calls[0]?.[0]),
      "http://localhost",
    );
    expect(url.pathname).toBe("/api/v1/aircraft");
    expect(url.searchParams.get("limit")).toBe("50");
    expect(url.searchParams.get("offset")).toBe("0");
    expect(url.searchParams.get("sort")).toBe("last_seen");
    expect(url.searchParams.get("order")).toBe("desc");
    expect(url.searchParams.has("classification")).toBe(false);
    expect(url.searchParams.has("operator_group")).toBe(false);
    expect(url.searchParams.has("type")).toBe(false);
  });

  it("adds the optional classification/operator_group/type filters when given", async () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(
        jsonResponse({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getAircraftList({
      limit: 50,
      offset: 0,
      sort: "last_seen",
      order: "desc",
      classification: "military",
      operatorGroup: "us-military",
      type: "B738",
    });

    const url = new URL(
      String(fetchMock.mock.calls[0]?.[0]),
      "http://localhost",
    );
    expect(url.searchParams.get("classification")).toBe("military");
    expect(url.searchParams.get("operator_group")).toBe("us-military");
    expect(url.searchParams.get("type")).toBe("B738");
  });

  it("throws ApiV1Error carrying the §2.5 code and message on a non-2xx response", async () => {
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
      getAircraftList({
        limit: 50,
        offset: 0,
        sort: "last_seen",
        order: "desc",
      }),
    ).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      message: "bad sort key",
    });
  });

  it("still throws ApiV1Error when the error response has no JSON body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response("", { status: 500 }))),
    );

    const error = await getAircraftDetail("ae1463").catch(
      (caught: unknown) => caught,
    );

    expect(error).toBeInstanceOf(ApiV1Error);
    expect((error as ApiV1Error).status).toBe(500);
    expect((error as ApiV1Error).code).toBeNull();
    expect((error as ApiV1Error).message).toBe(
      "Request failed with status 500",
    );
  });
});

describe("getAircraftDetail", () => {
  it("requests the icao-scoped path", async () => {
    const fetchMock = vi.fn((_input?: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(
        jsonResponse({
          icao: "ae1463",
          registration: null,
          aircraft_type: null,
          model: null,
          manufacture_year: null,
          operator: null,
          operator_group: null,
          owner: null,
          classification: null,
          live: false,
          lifetime: {
            first_seen: "2026-01-01T00:00:00.000Z",
            last_seen: "2026-01-01T00:00:00.000Z",
            sighting_count: 1,
            cumulative_duration_s: 1,
            closest_approach_nm: null,
            max_range_nm: null,
            lowest_altitude_ft: null,
            highest_altitude_ft: null,
          },
          provenance: {},
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const detail = await getAircraftDetail("ae1463");

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/aircraft/ae1463");
    expect(detail.icao).toBe("ae1463");
  });
});
