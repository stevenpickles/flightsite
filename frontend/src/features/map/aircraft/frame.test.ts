/**
 * `drawAircraftFrame` is the single rebuild path filters plug into — see
 * `features/filters/lib/applyFilters.ts`'s doc comment. These tests cover
 * the wiring itself (defaults, an explicit filter set, the display-radius
 * fallback); the filter predicate matrix lives in
 * `features/filters/lib/applyFilters.test.ts` and is not re-duplicated
 * here.
 */

import type { Map as MapLibreGlMap } from "maplibre-gl";
import { beforeEach, describe, expect, it } from "vitest";

import { resetFilteredLiveAircraftCache } from "@/features/filters/lib/filteredLiveAircraftCache";
import { DEFAULT_FILTERS } from "@/features/filters/types";
import { drawAircraftFrame } from "@/features/map/aircraft/frame";
import { makeAircraft } from "@/test/liveAircraftFixtures";

function fakeMap(): {
  map: MapLibreGlMap;
  dataByFeatureCount: () => number;
} {
  let lastData: { features?: unknown[] } = { features: [] };
  const map = {
    getSource: () => ({
      setData: (data: { features?: unknown[] }) => {
        lastData = data;
      },
    }),
    getZoom: () => 10,
  } as unknown as MapLibreGlMap;
  return { map, dataByFeatureCount: () => lastData.features?.length ?? 0 };
}

function state(aircraftList: ReturnType<typeof makeAircraft>[]) {
  const aircraft: Record<
    string,
    { aircraft: ReturnType<typeof makeAircraft>; receivedAt: number }
  > = {};
  for (const entry of aircraftList) {
    aircraft[entry.icao] = { aircraft: entry, receivedAt: 0 };
  }
  return { aircraft, departing: {}, selectedIcao: null, track: null };
}

beforeEach(() => {
  resetFilteredLiveAircraftCache();
});

describe("drawAircraftFrame filtering", () => {
  it("draws everything with no options — back-compat with pre-filter callers", () => {
    const { map, dataByFeatureCount } = fakeMap();
    drawAircraftFrame(
      map,
      state([
        makeAircraft({ icao: "aaaaaa" }),
        makeAircraft({ icao: "bbbbbb" }),
      ]),
      0,
    );
    expect(dataByFeatureCount()).toBe(2);
  });

  it("applies the schema default (250 nm) distance cap even with no explicit displayRadiusNm", () => {
    const { map, dataByFeatureCount } = fakeMap();
    drawAircraftFrame(
      map,
      state([makeAircraft({ icao: "far", distance_nm: 900 })]),
      0,
    );
    expect(dataByFeatureCount()).toBe(0);
  });

  it("honors an explicit displayRadiusNm from map config", () => {
    const { map, dataByFeatureCount } = fakeMap();
    drawAircraftFrame(
      map,
      state([makeAircraft({ icao: "aaaaaa", distance_nm: 300 })]),
      0,
      { displayRadiusNm: 400 },
    );
    expect(dataByFeatureCount()).toBe(1);
  });

  it("applies an explicit filter set", () => {
    const { map, dataByFeatureCount } = fakeMap();
    drawAircraftFrame(
      map,
      state([
        makeAircraft({ icao: "ground", on_ground: true }),
        makeAircraft({ icao: "air", on_ground: false }),
      ]),
      0,
      { filters: { ...DEFAULT_FILTERS, groundTraffic: "hide" } },
    );
    expect(dataByFeatureCount()).toBe(1);
  });
});
