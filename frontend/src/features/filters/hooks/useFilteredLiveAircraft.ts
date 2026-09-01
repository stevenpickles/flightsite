/**
 * The React-facing half of `lib/filteredLiveAircraftCache.ts` — every
 * component that needs "what's currently visible" (the drawer's counts,
 * the non-positioned panel, the display-radius indicator) reads through
 * this hook so they see the exact same `FilterResult` the map itself just
 * drew, not a separately-computed approximation of it.
 */

import { useFilterStore } from "@/features/filters/store/useFilterStore";
import { getFilteredLiveAircraft } from "@/features/filters/lib/filteredLiveAircraftCache";
import type { FilterResult } from "@/features/filters/types";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { useMapConfigStore } from "@/features/map/store/useMapConfigStore";

export function useFilteredLiveAircraft(): FilterResult {
  const aircraftRecords = useLiveAircraftStore((state) => state.aircraft);
  const filters = useFilterStore((state) => state.filters);
  const displayRadiusNm = useMapConfigStore(
    (state) => state.config.displayRadiusNm,
  );
  return getFilteredLiveAircraft(aircraftRecords, filters, {
    displayRadiusNm,
  });
}
