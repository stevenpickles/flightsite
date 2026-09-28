import { describe, expect, it } from "vitest";

import {
  DEFAULT_TABLE_STATE,
  MAX_SEARCH_LENGTH,
  normalizeSearch,
  parseAircraftTableState,
  serializeAircraftTableState,
} from "@/features/aircraft-page/lib/urlState";

describe("parseAircraftTableState", () => {
  it("defaults to last_seen desc, page 1 for an empty query string", () => {
    expect(parseAircraftTableState(new URLSearchParams())).toEqual(
      DEFAULT_TABLE_STATE,
    );
  });

  it("reads a fully-specified query string", () => {
    const params = new URLSearchParams(
      "sort=closest_approach_nm&order=asc&page=3",
    );

    expect(parseAircraftTableState(params)).toEqual({
      sort: "closest_approach_nm",
      order: "asc",
      page: 3,
    });
  });

  it("falls back to defaults for an unrecognized sort key", () => {
    const params = new URLSearchParams("sort=altitude_ft");

    expect(parseAircraftTableState(params).sort).toBe("last_seen");
  });

  it("falls back to defaults for a malformed order", () => {
    const params = new URLSearchParams("order=sideways");

    expect(parseAircraftTableState(params).order).toBe("desc");
  });

  it("falls back to page 1 for a non-positive or non-integer page", () => {
    expect(parseAircraftTableState(new URLSearchParams("page=0")).page).toBe(1);
    expect(parseAircraftTableState(new URLSearchParams("page=-3")).page).toBe(
      1,
    );
    expect(parseAircraftTableState(new URLSearchParams("page=abc")).page).toBe(
      1,
    );
    expect(parseAircraftTableState(new URLSearchParams("page=2.5")).page).toBe(
      1,
    );
  });
});

describe("serializeAircraftTableState", () => {
  it("writes nothing for the default state", () => {
    expect(serializeAircraftTableState(DEFAULT_TABLE_STATE).toString()).toBe(
      "",
    );
  });

  it("writes only the fields that differ from the default", () => {
    const params = serializeAircraftTableState({
      sort: "last_seen",
      order: "desc",
      page: 4,
    });

    expect(params.toString()).toBe("page=4");
  });

  it("round-trips a fully non-default state", () => {
    const state = {
      sort: "sighting_count" as const,
      order: "asc" as const,
      page: 2,
    };

    const roundTripped = parseAircraftTableState(
      serializeAircraftTableState(state),
    );

    expect(roundTripped).toEqual(state);
  });

  it("round-trips a search alongside sort and page (slice 083)", () => {
    const state = {
      sort: "registration" as const,
      order: "asc" as const,
      page: 2,
      q: "G-EZ",
    };

    const params = serializeAircraftTableState(state);

    expect(params.get("q")).toBe("G-EZ");
    expect(parseAircraftTableState(params)).toEqual(state);
  });

  it("writes no q for a blank search", () => {
    expect(
      serializeAircraftTableState({ ...DEFAULT_TABLE_STATE, q: "   " }).has(
        "q",
      ),
    ).toBe(false);
  });
});

describe("the q search key", () => {
  it("is absent by default", () => {
    expect(parseAircraftTableState(new URLSearchParams()).q).toBeUndefined();
  });

  it("is trimmed, and blank means no search", () => {
    expect(
      parseAircraftTableState(new URLSearchParams("q=%20%20baw%20")).q,
    ).toBe("baw");
    expect(
      parseAircraftTableState(new URLSearchParams("q=%20%20")).q,
    ).toBeUndefined();
  });

  it("is capped at the API's length, so a hand-edited link cannot 422", () => {
    const long = "x".repeat(MAX_SEARCH_LENGTH + 10);

    expect(
      parseAircraftTableState(new URLSearchParams({ q: long })).q,
    ).toHaveLength(MAX_SEARCH_LENGTH);
  });

  it("is kept literally — wildcards are the server's to escape", () => {
    expect(parseAircraftTableState(new URLSearchParams("q=N_%251")).q).toBe(
      "N_%1",
    );
  });
});

describe("normalizeSearch", () => {
  it.each([
    [undefined, undefined],
    [null, undefined],
    ["", undefined],
    [" \t ", undefined],
    ["  a1b2 ", "a1b2"],
  ])("normalizes %j to %j", (raw, expected) => {
    expect(normalizeSearch(raw)).toBe(expected);
  });

  it("trims again after capping, so the cap never leaves a trailing space", () => {
    const raw = `${"x".repeat(MAX_SEARCH_LENGTH - 1)} tail`;

    expect(normalizeSearch(raw)).toBe("x".repeat(MAX_SEARCH_LENGTH - 1));
  });
});
