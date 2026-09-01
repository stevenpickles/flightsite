import { beforeEach, describe, expect, it, vi } from "vitest";

import * as applyFiltersModule from "@/features/filters/lib/applyFilters";
import {
  getFilteredLiveAircraft,
  resetFilteredLiveAircraftCache,
} from "@/features/filters/lib/filteredLiveAircraftCache";
import { DEFAULT_FILTERS } from "@/features/filters/types";
import type { LiveAircraftRecord } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { makeAircraft } from "@/test/liveAircraftFixtures";

const CONFIG = { displayRadiusNm: 250 };

function records(): Record<string, LiveAircraftRecord> {
  return {
    aaaaaa: { aircraft: makeAircraft({ icao: "aaaaaa" }), receivedAt: 0 },
  };
}

beforeEach(() => {
  resetFilteredLiveAircraftCache();
});

describe("getFilteredLiveAircraft", () => {
  it("returns the same result object for unchanged inputs", () => {
    const aircraftRecords = records();
    const first = getFilteredLiveAircraft(
      aircraftRecords,
      DEFAULT_FILTERS,
      CONFIG,
    );
    const second = getFilteredLiveAircraft(
      aircraftRecords,
      DEFAULT_FILTERS,
      CONFIG,
    );
    expect(second).toBe(first);
  });

  it("does not re-run applyFilters on a cache hit", () => {
    const spy = vi.spyOn(applyFiltersModule, "applyFilters");
    const aircraftRecords = records();
    getFilteredLiveAircraft(aircraftRecords, DEFAULT_FILTERS, CONFIG);
    getFilteredLiveAircraft(aircraftRecords, DEFAULT_FILTERS, CONFIG);
    expect(spy).toHaveBeenCalledTimes(1);
    spy.mockRestore();
  });

  it("recomputes when the aircraft record map reference changes", () => {
    const first = getFilteredLiveAircraft(records(), DEFAULT_FILTERS, CONFIG);
    const second = getFilteredLiveAircraft(records(), DEFAULT_FILTERS, CONFIG);
    expect(second).not.toBe(first);
    expect(second).toEqual(first);
  });

  it("recomputes when the filters reference changes", () => {
    const aircraftRecords = records();
    const first = getFilteredLiveAircraft(
      aircraftRecords,
      DEFAULT_FILTERS,
      CONFIG,
    );
    const second = getFilteredLiveAircraft(
      aircraftRecords,
      { ...DEFAULT_FILTERS },
      CONFIG,
    );
    expect(second).not.toBe(first);
  });

  it("recomputes when the display radius changes", () => {
    const aircraftRecords = records();
    const first = getFilteredLiveAircraft(
      aircraftRecords,
      DEFAULT_FILTERS,
      CONFIG,
    );
    const second = getFilteredLiveAircraft(aircraftRecords, DEFAULT_FILTERS, {
      displayRadiusNm: 100,
    });
    expect(second).not.toBe(first);
    expect(second.effectiveDistanceCapNm).toBe(100);
  });
});
