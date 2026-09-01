import { describe, expect, it } from "vitest";

import {
  countActiveFilters,
  hasActiveFilters,
} from "@/features/filters/lib/activeFilterCount";
import { DEFAULT_FILTERS, type LiveFilters } from "@/features/filters/types";

function filters(overrides: Partial<LiveFilters> = {}): LiveFilters {
  return { ...DEFAULT_FILTERS, ...overrides };
}

describe("countActiveFilters", () => {
  it("is zero for the defaults", () => {
    expect(countActiveFilters(DEFAULT_FILTERS)).toBe(0);
    expect(hasActiveFilters(DEFAULT_FILTERS)).toBe(false);
  });

  it("counts an altitude range (min or max) as one filter", () => {
    expect(countActiveFilters(filters({ altitudeMinFt: 1000 }))).toBe(1);
    expect(countActiveFilters(filters({ altitudeMaxFt: 30000 }))).toBe(1);
    expect(
      countActiveFilters(
        filters({ altitudeMinFt: 1000, altitudeMaxFt: 30000 }),
      ),
    ).toBe(1);
  });

  it("counts a multi-select classification as one filter regardless of size", () => {
    expect(countActiveFilters(filters({ classifications: ["military"] }))).toBe(
      1,
    );
    expect(
      countActiveFilters(
        filters({ classifications: ["military", "government"] }),
      ),
    ).toBe(1);
  });

  it("ignores whitespace-only text fields", () => {
    expect(countActiveFilters(filters({ categoryText: "   " }))).toBe(0);
  });

  it("sums independent active filters", () => {
    const active = filters({
      maxDistanceNm: 100,
      hideNonPositioned: true,
      hideStale: true,
      groundTraffic: "hide",
    });
    expect(countActiveFilters(active)).toBe(4);
    expect(hasActiveFilters(active)).toBe(true);
  });

  it("counts every remaining single-field filter", () => {
    expect(countActiveFilters(filters({ operatorText: "BA" }))).toBe(1);
    expect(countActiveFilters(filters({ operatorGroupText: "OW" }))).toBe(1);
    expect(
      countActiveFilters(filters({ missionCategories: ["medevac"] })),
    ).toBe(1);
    expect(countActiveFilters(filters({ interestingOnly: true }))).toBe(1);
    expect(countActiveFilters(filters({ emergencyOnly: true }))).toBe(1);
    expect(countActiveFilters(filters({ liveSetQuery: "BAW" }))).toBe(1);
  });
});
