import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useFilteredLiveAircraft } from "@/features/filters/hooks/useFilteredLiveAircraft";
import { resetFilteredLiveAircraftCache } from "@/features/filters/lib/filteredLiveAircraftCache";
import { useFilterStore } from "@/features/filters/store/useFilterStore";
import { DEFAULT_FILTERS } from "@/features/filters/types";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { DEV_PLACEHOLDER_MAP_CONFIG } from "@/features/map/mapConfig";
import { useMapConfigStore } from "@/features/map/store/useMapConfigStore";
import { makeAircraft } from "@/test/liveAircraftFixtures";

beforeEach(() => {
  resetFilteredLiveAircraftCache();
  useLiveAircraftStore.getState().reset();
  useFilterStore.setState({ filters: DEFAULT_FILTERS });
  useMapConfigStore.setState({ config: DEV_PLACEHOLDER_MAP_CONFIG });
});

describe("useFilteredLiveAircraft", () => {
  it("reflects the live store through the current filters and config", () => {
    act(() => {
      useLiveAircraftStore.getState().applySnapshot({
        aircraft: [
          makeAircraft({ icao: "near", distance_nm: 50 }),
          makeAircraft({ icao: "far", distance_nm: 900 }),
        ],
        receiver: null,
      });
    });

    const { result } = renderHook(() => useFilteredLiveAircraft());
    expect(result.current.visibleIcaos).toEqual(new Set(["near"]));
    expect(result.current.distanceCappedCount).toBe(1);
  });

  it("updates when a filter changes", () => {
    act(() => {
      useLiveAircraftStore.getState().applySnapshot({
        aircraft: [makeAircraft({ icao: "aaaaaa", state: "stale" })],
        receiver: null,
      });
    });

    const { result } = renderHook(() => useFilteredLiveAircraft());
    expect(result.current.aircraft).toHaveLength(1);

    act(() => {
      useFilterStore.getState().setHideStale(true);
    });
    expect(result.current.aircraft).toHaveLength(0);
  });
});
