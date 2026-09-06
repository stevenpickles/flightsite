/**
 * One rendered frame: store state in, `setData` calls out.
 *
 * Split out from the layer definitions so the whole data-building path — store
 * → interpolation → icon resolution → GeoJSON → `setData` — is callable
 * without React and without a renderer. That is what the perf check measures
 * (`frame.perf.test.ts`) and what the integration tests assert on.
 */

import type { Map as MapLibreGlMap } from "maplibre-gl";

import {
  setAircraftData,
  setTrackData,
} from "@/features/map/aircraft/aircraftLayers";
import {
  buildAircraftFeatureCollection,
  buildTrackFeatureCollection,
  countLabelledAircraft,
} from "@/features/map/aircraft/geojson";
import type {
  DepartingRecord,
  LiveAircraftRecord,
} from "@/features/map/aircraft/store/useLiveAircraftStore";
import type { SelectedTrack } from "@/features/map/aircraft/track";
import { updateDensityLatch } from "@/features/map/labels/densityLatch";
import { DEFAULT_DISPLAY_RADIUS_NM } from "@/features/map/mapConfig";
import { getFilteredLiveAircraft } from "@/features/filters/lib/filteredLiveAircraftCache";
import { DEFAULT_FILTERS, type LiveFilters } from "@/features/filters/types";

/** The slice of the live store a frame is drawn from. */
export interface AircraftFrameState {
  aircraft: Record<string, LiveAircraftRecord>;
  departing: Record<string, DepartingRecord>;
  selectedIcao: string | null;
  track: SelectedTrack | null;
}

export interface DrawFrameOptions {
  /** Whether to rebuild the track polyline too. The track only changes when
   * the store changes, so interpolation frames skip it — re-serializing up to
   * 900 coordinates ten times a second for an unchanged line is the kind of
   * per-frame waste that shows up first on a Pi. */
  includeTrack?: boolean;
  /** The active live filters (`features/filters`). Defaults to
   * `DEFAULT_FILTERS` (no filtering) for callers — mostly tests — that
   * predate filtering and never heard of the store. */
  filters?: LiveFilters;
  /** The display-radius default the distance cap falls back to when
   * `filters.maxDistanceNm` is unset. Defaults to the schema default. */
  displayRadiusNm?: number;
}

/** Rebuilds and pushes the aircraft (and optionally track) sources for `now`.
 * Filtering happens here, once, through `getFilteredLiveAircraft` — the same
 * memoized selector React components read via
 * `useFilteredLiveAircraft` — so the map, the non-positioned panel, and the
 * drawer's counts are always describing the same filtered set. */
export function drawAircraftFrame(
  map: MapLibreGlMap,
  state: AircraftFrameState,
  now: number,
  options: DrawFrameOptions = {},
): void {
  const filters = options.filters ?? DEFAULT_FILTERS;
  const displayRadiusNm = options.displayRadiusNm ?? DEFAULT_DISPLAY_RADIUS_NM;
  const filterResult = getFilteredLiveAircraft(state.aircraft, filters, {
    displayRadiusNm,
  });

  setAircraftData(
    map,
    buildAircraftFeatureCollection({
      aircraft: state.aircraft,
      departing: state.departing,
      selectedIcao: state.selectedIcao,
      now,
      zoom: map.getZoom(),
      visibleIcaos: filterResult.visibleIcaos,
      dimmedIcaos: filterResult.dimmedIcaos,
      // The frame loop is the one caller that draws a *sequence*, so it is
      // the one that owns the label-density latch (issue #143). Advancing it
      // here — once per frame, on the same post-filter count `geojson.ts`
      // would have derived — keeps the builder itself pure. The count is of
      // the aircraft that will actually be labelled, not the whole live set
      // (issue #147): a position-less Mode S contact crowds nothing.
      densityLatched: updateDensityLatch(
        countLabelledAircraft(state.aircraft, filterResult.visibleIcaos),
      ),
    }),
  );
  if (options.includeTrack) {
    setTrackData(map, buildTrackFeatureCollection(state.track));
  }
}
