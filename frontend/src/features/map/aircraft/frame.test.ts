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
import { resetDensityLatch } from "@/features/map/labels/densityLatch";
import {
  DENSITY_CALLSIGN_ENTER,
  DENSITY_CALLSIGN_EXIT,
} from "@/features/map/labels/priority";
import { makeAircraft } from "@/test/liveAircraftFixtures";

interface DrawnFeature {
  properties: { label: string };
}

function fakeMap(): {
  map: MapLibreGlMap;
  dataByFeatureCount: () => number;
  firstLabel: () => string | undefined;
} {
  let lastData: { features?: DrawnFeature[] } = { features: [] };
  const map = {
    getSource: () => ({
      setData: (data: { features?: DrawnFeature[] }) => {
        lastData = data;
      },
    }),
    getZoom: () => 10,
  } as unknown as MapLibreGlMap;
  return {
    map,
    dataByFeatureCount: () => lastData.features?.length ?? 0,
    firstLabel: () => lastData.features?.[0]?.properties.label,
  };
}

/** `count` distinct positioned aircraft, all inside the default radius. */
function crowd(count: number): ReturnType<typeof makeAircraft>[] {
  return Array.from({ length: count }, (_, index) =>
    makeAircraft({
      icao: index.toString(16).padStart(6, "0"),
      callsign: `AA${index}`,
    }),
  );
}

function state(aircraftList: ReturnType<typeof makeAircraft>[]) {
  const aircraft: Record<
    string,
    {
      aircraft: ReturnType<typeof makeAircraft>;
      receivedAt: number;
      positionChangedAt: number;
    }
  > = {};
  for (const entry of aircraftList) {
    aircraft[entry.icao] = {
      aircraft: entry,
      receivedAt: 0,
      positionChangedAt: 0,
    };
  }
  return { aircraft, departing: {}, selectedIcao: null, track: null };
}

beforeEach(() => {
  resetFilteredLiveAircraftCache();
  resetDensityLatch();
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

describe("drawAircraftFrame label-density hysteresis", () => {
  // Issue #143: the frame loop is what turns the pure band into a latch, so
  // the sequence of frames — not any one of them — is the behaviour.
  const FULL = "AA0\nFL310";
  const CALLSIGN_ONLY = "AA0";

  it("keeps the full stack while a rising count is still inside the band", () => {
    const { map, firstLabel } = fakeMap();
    drawAircraftFrame(map, state(crowd(DENSITY_CALLSIGN_EXIT + 1)), 0);
    expect(firstLabel()).toBe(FULL);
    drawAircraftFrame(map, state(crowd(DENSITY_CALLSIGN_ENTER)), 0);
    expect(firstLabel()).toBe(FULL);
  });

  it("stays on callsign-only once latched, until the count clears the lower edge", () => {
    const { map, firstLabel } = fakeMap();
    // Above the upper edge: latch on.
    drawAircraftFrame(map, state(crowd(DENSITY_CALLSIGN_ENTER + 1)), 0);
    expect(firstLabel()).toBe(CALLSIGN_ONLY);

    // Back inside the band — the flapping that produced the blink. The
    // label content must not move.
    for (const count of [
      DENSITY_CALLSIGN_ENTER - 1,
      DENSITY_CALLSIGN_ENTER + 1,
      DENSITY_CALLSIGN_EXIT + 1,
      DENSITY_CALLSIGN_ENTER,
    ]) {
      drawAircraftFrame(map, state(crowd(count)), 0);
      expect(firstLabel()).toBe(CALLSIGN_ONLY);
    }

    // Below the lower edge: the picture really has thinned out.
    drawAircraftFrame(map, state(crowd(DENSITY_CALLSIGN_EXIT - 1)), 0);
    expect(firstLabel()).toBe(FULL);
  });

  it("latches on the labelled count, not the size of the live set", () => {
    // Issue #147: `visibleIcaos` is the live set, which includes Mode S
    // contacts with no position. They never become a feature and never
    // occupy a label, so they must not push the labels of the aircraft that
    // *are* drawn down a tier. Well over the upper edge by live count, well
    // under the lower edge by labelled count.
    const { map, firstLabel, dataByFeatureCount } = fakeMap();
    const positioned = crowd(DENSITY_CALLSIGN_EXIT - 1);
    const modeSOnly = Array.from(
      { length: DENSITY_CALLSIGN_ENTER },
      (_entry, index) =>
        makeAircraft({
          icao: `f${index.toString(16).padStart(5, "0")}`,
          callsign: `MS${index}`,
          position: null,
          distance_nm: null,
        }),
    );

    drawAircraftFrame(map, state([...positioned, ...modeSOnly]), 0);

    expect(dataByFeatureCount()).toBe(positioned.length);
    expect(firstLabel()).toBe(FULL);
  });

  it("unlatches once the picture empties, so a reconnect starts fresh", () => {
    const { map, firstLabel } = fakeMap();
    drawAircraftFrame(map, state(crowd(DENSITY_CALLSIGN_ENTER + 1)), 0);
    expect(firstLabel()).toBe(CALLSIGN_ONLY);
    drawAircraftFrame(map, state([]), 0);
    drawAircraftFrame(map, state(crowd(DENSITY_CALLSIGN_ENTER)), 0);
    expect(firstLabel()).toBe(FULL);
  });
});
