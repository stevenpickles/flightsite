import { describe, expect, it } from "vitest";

import { MAX_SEARCH_LENGTH } from "@/features/history/lib/search";
import {
  DEFAULT_TABLE_STATE,
  defaultPresetFor,
  parseSightingsTableState,
  serializeSightingsTableState,
  type SightingsTableState,
} from "@/features/sightings/lib/urlState";

describe("parseSightingsTableState", () => {
  it("defaults to today's log: started_at desc, page 1, no filters", () => {
    expect(parseSightingsTableState(new URLSearchParams())).toEqual(
      DEFAULT_TABLE_STATE,
    );
    expect(DEFAULT_TABLE_STATE.preset).toBe("today");
    expect(DEFAULT_TABLE_STATE.group).toBe("sightings");
  });

  it("reads a fully-specified query string", () => {
    const params = new URLSearchParams(
      "preset=30d&group=aircraft&sort=duration_s&order=asc&page=3&icao=ae1463&open=true&type=b738",
    );

    expect(parseSightingsTableState(params)).toEqual({
      preset: "30d",
      group: "aircraft",
      sort: "duration_s",
      order: "asc",
      page: 3,
      icao: "ae1463",
      q: undefined,
      open: true,
      type: "B738",
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

  it("lower-cases a valid icao filter", () => {
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

  it("treats any value other than the literal 'true' as open=false", () => {
    expect(parseSightingsTableState(new URLSearchParams("open=1")).open).toBe(
      false,
    );
    expect(
      parseSightingsTableState(new URLSearchParams("open=false")).open,
    ).toBe(false);
  });

  it("ignores the raw date range the page used before presets", () => {
    // `?from=…&to=…` links predate slice 098; they open today's log rather
    // than failing, and the dead keys are not written back.
    const state = parseSightingsTableState(
      new URLSearchParams("from=2026-08-01&to=2026-08-31"),
    );
    expect(state).toEqual(DEFAULT_TABLE_STATE);
    expect(serializeSightingsTableState(state).toString()).toBe("");
  });
});

describe("the time window (slice 098)", () => {
  it("reads each preset, and falls back to today for anything else", () => {
    for (const preset of ["today", "7d", "30d", "ytd", "t0"] as const) {
      expect(
        parseSightingsTableState(new URLSearchParams({ preset })).preset,
      ).toBe(preset);
    }
    expect(
      parseSightingsTableState(new URLSearchParams("preset=fortnight")).preset,
    ).toBe("today");
  });

  it("means everything, not today, for an exact-aircraft link with no preset", () => {
    // The aircraft detail page's "all sightings" link: `?icao=…` alone.
    expect(defaultPresetFor("ae1463")).toBe("t0");
    expect(defaultPresetFor(undefined)).toBe("today");
    expect(
      parseSightingsTableState(new URLSearchParams("icao=ae1463")).preset,
    ).toBe("t0");
  });

  it("lets an explicit preset win over that default", () => {
    expect(
      parseSightingsTableState(new URLSearchParams("icao=ae1463&preset=7d"))
        .preset,
    ).toBe("7d");
    expect(
      parseSightingsTableState(new URLSearchParams("icao=ae1463&preset=today"))
        .preset,
    ).toBe("today");
  });

  it("writes the preset only when it is not what the URL would mean without it", () => {
    const write = (patch: Partial<SightingsTableState>) =>
      serializeSightingsTableState({ ...DEFAULT_TABLE_STATE, ...patch });

    expect(write({ preset: "today" }).has("preset")).toBe(false);
    expect(write({ preset: "7d" }).get("preset")).toBe("7d");
    // With an exact aircraft, t0 is the implied default and today is not.
    expect(write({ icao: "ae1463", preset: "t0" }).has("preset")).toBe(false);
    expect(write({ icao: "ae1463", preset: "today" }).get("preset")).toBe(
      "today",
    );
  });

  it("round-trips the preset beside an exact aircraft either way", () => {
    for (const preset of ["today", "t0", "30d"] as const) {
      const state = { ...DEFAULT_TABLE_STATE, icao: "ae1463", preset };
      expect(
        parseSightingsTableState(serializeSightingsTableState(state)),
      ).toEqual(state);
    }
  });
});

describe("the grouping and its type filter (slice 098)", () => {
  it("reads each grouping, and falls back to the log", () => {
    for (const group of ["sightings", "aircraft", "types"] as const) {
      expect(
        parseSightingsTableState(new URLSearchParams({ group })).group,
      ).toBe(group);
    }
    expect(
      parseSightingsTableState(new URLSearchParams("group=operators")).group,
    ).toBe("sightings");
  });

  it("upper-cases a type designator and drops anything that is not one", () => {
    expect(
      parseSightingsTableState(new URLSearchParams("type=b738")).type,
    ).toBe("B738");
    expect(parseSightingsTableState(new URLSearchParams("type=P8")).type).toBe(
      "P8",
    );
    expect(
      parseSightingsTableState(new URLSearchParams("type=Boeing%20737")).type,
    ).toBeUndefined();
    expect(
      parseSightingsTableState(new URLSearchParams("type=TOOLONG")).type,
    ).toBeUndefined();
  });

  it("writes the grouping and type only when set", () => {
    const params = serializeSightingsTableState({
      ...DEFAULT_TABLE_STATE,
      group: "aircraft",
      type: "B738",
    });
    expect(params.toString()).toBe("group=aircraft&type=B738");
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
    const state: SightingsTableState = {
      preset: "ytd",
      group: "aircraft",
      sort: "max_range_nm",
      order: "asc",
      page: 2,
      icao: "ae1463",
      q: undefined,
      open: true,
      type: "C172",
    };

    const roundTripped = parseSightingsTableState(
      serializeSightingsTableState(state),
    );

    expect(roundTripped).toEqual(state);
  });
});

describe("the q search key (slice 083)", () => {
  it("round-trips beside the exact icao filter without disturbing it", () => {
    const state: SightingsTableState = {
      ...DEFAULT_TABLE_STATE,
      preset: "t0",
      q: "BAW",
      icao: "ae1463",
    };

    const params = serializeSightingsTableState(state);

    expect(params.get("q")).toBe("BAW");
    expect(params.get("icao")).toBe("ae1463");
    expect(parseSightingsTableState(params)).toEqual(state);
  });

  it("accepts what the exact icao filter rejects: a prefix, a callsign", () => {
    expect(parseSightingsTableState(new URLSearchParams("q=ae14")).q).toBe(
      "ae14",
    );
    expect(parseSightingsTableState(new URLSearchParams("q=dal12")).q).toBe(
      "dal12",
    );
    expect(
      parseSightingsTableState(new URLSearchParams("icao=ae14")).icao,
    ).toBeUndefined();
  });

  it("is trimmed, capped, and absent when blank", () => {
    expect(parseSightingsTableState(new URLSearchParams("q=%20ual%20")).q).toBe(
      "ual",
    );
    expect(
      parseSightingsTableState(new URLSearchParams("q=%20")).q,
    ).toBeUndefined();
    expect(
      parseSightingsTableState(new URLSearchParams({ q: "x".repeat(40) })).q,
    ).toHaveLength(MAX_SEARCH_LENGTH);
    expect(
      serializeSightingsTableState({ ...DEFAULT_TABLE_STATE, q: "  " }).has(
        "q",
      ),
    ).toBe(false);
  });
});
