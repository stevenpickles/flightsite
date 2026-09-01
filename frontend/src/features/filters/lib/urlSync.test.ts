import { describe, expect, it } from "vitest";

import {
  parseFiltersFromSearchParams,
  serializeFiltersToSearchParams,
} from "@/features/filters/lib/urlSync";
import { DEFAULT_FILTERS, type LiveFilters } from "@/features/filters/types";

describe("serializeFiltersToSearchParams", () => {
  it("writes nothing for the defaults — a terse URL for the common case", () => {
    const params = serializeFiltersToSearchParams(DEFAULT_FILTERS);
    expect([...params.keys()]).toHaveLength(0);
  });

  it("writes only the fields that differ from the defaults", () => {
    const params = serializeFiltersToSearchParams({
      ...DEFAULT_FILTERS,
      altitudeMinFt: 1000,
      hideStale: true,
    });
    expect([...params.keys()].sort()).toEqual(["alt_min", "hide_stale"]);
  });
});

describe("parseFiltersFromSearchParams", () => {
  it("returns the defaults for an empty query string", () => {
    expect(parseFiltersFromSearchParams(new URLSearchParams())).toEqual(
      DEFAULT_FILTERS,
    );
  });

  it("degrades an unknown ground mode to the default rather than erroring", () => {
    const parsed = parseFiltersFromSearchParams(
      new URLSearchParams("ground=orbit"),
    );
    expect(parsed.groundTraffic).toBe("show");
  });

  it("drops a classification flag it does not recognize", () => {
    const parsed = parseFiltersFromSearchParams(
      new URLSearchParams("cls=military,bogus"),
    );
    expect(parsed.classifications).toEqual(["military"]);
  });

  it("treats a non-numeric altitude as absent rather than NaN", () => {
    const parsed = parseFiltersFromSearchParams(
      new URLSearchParams("alt_min=not-a-number"),
    );
    expect(parsed.altitudeMinFt).toBeNull();
  });
});

describe("round trip", () => {
  const cases: [string, Partial<LiveFilters>][] = [
    ["altitude range", { altitudeMinFt: 1000, altitudeMaxFt: 35000 }],
    ["distance override", { maxDistanceNm: 75 }],
    ["category text", { categoryText: "737" }],
    ["operator text", { operatorText: "British Airways" }],
    ["operator group text", { operatorGroupText: "Oneworld" }],
    ["classifications", { classifications: ["military", "law_enforcement"] }],
    ["mission categories", { missionCategories: ["medevac", "training"] }],
    ["interesting only", { interestingOnly: true }],
    ["emergency only", { emergencyOnly: true }],
    ["hide non-positioned", { hideNonPositioned: true }],
    ["ground traffic dim", { groundTraffic: "dim" }],
    ["ground traffic hide", { groundTraffic: "hide" }],
    ["hide stale", { hideStale: true }],
    ["live set query", { liveSetQuery: "BAW" }],
    [
      "everything at once",
      {
        altitudeMinFt: 500,
        altitudeMaxFt: 41000,
        maxDistanceNm: 150,
        categoryText: "A320",
        operatorText: "easyJet",
        operatorGroupText: "Star",
        classifications: ["government"],
        missionCategories: ["patrol"],
        interestingOnly: true,
        emergencyOnly: true,
        hideNonPositioned: true,
        groundTraffic: "hide",
        hideStale: true,
        liveSetQuery: "N123",
      },
    ],
  ];

  it.each(cases)("round-trips %s", (_label, overrides) => {
    const filters: LiveFilters = { ...DEFAULT_FILTERS, ...overrides };
    const params = serializeFiltersToSearchParams(filters);
    const restored = parseFiltersFromSearchParams(params);
    expect(restored).toEqual(filters);
  });

  it("round-trips the defaults themselves", () => {
    const params = serializeFiltersToSearchParams(DEFAULT_FILTERS);
    expect(parseFiltersFromSearchParams(params)).toEqual(DEFAULT_FILTERS);
  });
});
