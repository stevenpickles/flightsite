/**
 * A single-slot memo in front of `applyFilters`, shared by the imperative
 * frame loop (`features/map/aircraft/frame.ts`) and the React hook
 * (`hooks/useFilteredLiveAircraft.ts`) so both read the exact same
 * `FilterResult` object for a given tick — which is what lets the map, the
 * non-positioned panel, and the drawer's counts agree without coordinating.
 *
 * The win: `useAircraftLayer`'s interpolation loop redraws every
 * `FRAME_INTERVAL_MS` (~12.5 Hz) whether or not the store actually changed
 * (dead reckoning needs a fresh frame even between server updates), but the
 * live-aircraft record map and the filter set only change on a real store
 * update or a filter edit. Comparing by reference — the record map is
 * rebuilt wholesale on every `applySnapshot`/`applyDelta`
 * (`useLiveAircraftStore`'s doc comment), and the filters object is
 * replaced wholesale on every store edit (`useFilterStore`) — means an
 * interpolation-only tick hits the cache and never re-filters 500 aircraft
 * for nothing.
 */

import { applyFilters } from "@/features/filters/lib/applyFilters";
import type {
  FilterResult,
  FilterRuntimeConfig,
  LiveFilters,
} from "@/features/filters/types";
import type { LiveAircraftRecord } from "@/features/map/aircraft/store/useLiveAircraftStore";
import type { LiveAircraft } from "@/lib/api/live";

interface CacheEntry {
  aircraftRecords: Record<string, LiveAircraftRecord>;
  filters: LiveFilters;
  displayRadiusNm: number;
  result: FilterResult;
}

let cache: CacheEntry | null = null;

/** Filters the live store's aircraft map, reusing the previous result when
 * none of the inputs have changed by reference/value since the last call. */
export function getFilteredLiveAircraft(
  aircraftRecords: Record<string, LiveAircraftRecord>,
  filters: LiveFilters,
  config: FilterRuntimeConfig,
): FilterResult {
  if (
    cache !== null &&
    cache.aircraftRecords === aircraftRecords &&
    cache.filters === filters &&
    cache.displayRadiusNm === config.displayRadiusNm
  ) {
    return cache.result;
  }

  const list: LiveAircraft[] = [];
  for (const icao in aircraftRecords) {
    const record = aircraftRecords[icao];
    if (record) {
      list.push(record.aircraft);
    }
  }

  const result = applyFilters(list, filters, config);
  cache = {
    aircraftRecords,
    filters,
    displayRadiusNm: config.displayRadiusNm,
    result,
  };
  return result;
}

/** Test-only: clears the module-level memo so one test's object identities
 * never produce a stale cache hit in another. */
export function resetFilteredLiveAircraftCache(): void {
  cache = null;
}
