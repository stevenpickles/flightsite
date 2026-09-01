import { describe, expect, it } from "vitest";

import {
  DEFAULT_TABLE_STATE,
  endOfDayIso,
  parseSightingsTableState,
  serializeSightingsTableState,
  startOfDayIso,
} from "@/features/sightings/lib/urlState";

describe("parseSightingsTableState", () => {
  it("defaults to started_at desc, page 1, no filters for an empty query string", () => {
    expect(parseSightingsTableState(new URLSearchParams())).toEqual(
      DEFAULT_TABLE_STATE,
    );
  });

  it("reads a fully-specified query string", () => {
    const params = new URLSearchParams(
      "sort=duration_s&order=asc&page=3&icao=ae1463&from=2026-08-01&to=2026-08-31&open=true",
    );

    expect(parseSightingsTableState(params)).toEqual({
      sort: "duration_s",
      order: "asc",
      page: 3,
      icao: "ae1463",
      from: "2026-08-01",
      to: "2026-08-31",
      open: true,
    });
  });

  it("falls back to defaults for an unrecognized sort key", () => {
    const params = new URLSearchParams("sort=icao");

    expect(parseSightingsTableState(params).sort).toBe("started_at");
  });

  it("falls back to defaults for a malformed order", () => {
    const params = new URLSearchParams("order=sideways");

    expect(parseSightingsTableState(params).order).toBe("desc");
  });

  it("falls back to page 1 for a non-positive or non-integer page", () => {
    expect(parseSightingsTableState(new URLSearchParams("page=0")).page).toBe(
      1,
    );
    expect(parseSightingsTableState(new URLSearchParams("page=-3")).page).toBe(
      1,
    );
    expect(parseSightingsTableState(new URLSearchParams("page=abc")).page).toBe(
      1,
    );
  });

  it("lowercases and accepts a valid icao filter", () => {
    const params = new URLSearchParams("icao=AE1463");

    expect(parseSightingsTableState(params).icao).toBe("ae1463");
  });

  it("drops a malformed icao filter rather than passing it through", () => {
    expect(
      parseSightingsTableState(new URLSearchParams("icao=not-hex")).icao,
    ).toBeUndefined();
    expect(
      parseSightingsTableState(new URLSearchParams("icao=ae146")).icao,
    ).toBeUndefined();
  });

  it("drops a malformed date filter rather than passing it through", () => {
    expect(
      parseSightingsTableState(new URLSearchParams("from=not-a-date")).from,
    ).toBeUndefined();
    expect(
      parseSightingsTableState(new URLSearchParams("to=2026/08/01")).to,
    ).toBeUndefined();
  });

  it("treats any value other than the literal 'true' as open=false", () => {
    expect(parseSightingsTableState(new URLSearchParams("open=1")).open).toBe(
      false,
    );
    expect(
      parseSightingsTableState(new URLSearchParams("open=false")).open,
    ).toBe(false);
  });
});

describe("serializeSightingsTableState", () => {
  it("writes nothing for the default state", () => {
    expect(serializeSightingsTableState(DEFAULT_TABLE_STATE).toString()).toBe(
      "",
    );
  });

  it("writes only the fields that differ from the default", () => {
    const params = serializeSightingsTableState({
      ...DEFAULT_TABLE_STATE,
      page: 4,
    });

    expect(params.toString()).toBe("page=4");
  });

  it("round-trips a fully non-default state", () => {
    const state = {
      sort: "max_range_nm" as const,
      order: "asc" as const,
      page: 2,
      icao: "ae1463",
      from: "2026-08-01",
      to: "2026-08-31",
      open: true,
    };

    const roundTripped = parseSightingsTableState(
      serializeSightingsTableState(state),
    );

    expect(roundTripped).toEqual(state);
  });
});

describe("startOfDayIso / endOfDayIso", () => {
  it("produces the inclusive UTC day bounds an API filter expects", () => {
    expect(startOfDayIso("2026-08-30")).toBe("2026-08-30T00:00:00.000Z");
    expect(endOfDayIso("2026-08-30")).toBe("2026-08-30T23:59:59.999Z");
  });
});
