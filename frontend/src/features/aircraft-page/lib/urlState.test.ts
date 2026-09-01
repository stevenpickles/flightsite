import { describe, expect, it } from "vitest";

import {
  DEFAULT_TABLE_STATE,
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
});
