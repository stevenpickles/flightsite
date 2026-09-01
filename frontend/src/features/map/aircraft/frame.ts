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
} from "@/features/map/aircraft/geojson";
import type {
  DepartingRecord,
  LiveAircraftRecord,
} from "@/features/map/aircraft/store/useLiveAircraftStore";
import type { SelectedTrack } from "@/features/map/aircraft/track";

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
}

/** Rebuilds and pushes the aircraft (and optionally track) sources for `now`. */
export function drawAircraftFrame(
  map: MapLibreGlMap,
  state: AircraftFrameState,
  now: number,
  options: DrawFrameOptions = {},
): void {
  setAircraftData(
    map,
    buildAircraftFeatureCollection({
      aircraft: state.aircraft,
      departing: state.departing,
      selectedIcao: state.selectedIcao,
      now,
    }),
  );
  if (options.includeTrack) {
    setTrackData(map, buildTrackFeatureCollection(state.track));
  }
}
