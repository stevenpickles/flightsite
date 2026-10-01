/**
 * The MapLibre source and layers that draw the measure tool (roadmap slice
 * 085): the great-circle line between A and B, the two endpoints, and a
 * small label at the line's midpoint.
 *
 * A *tool*, not an overlay — SPEC §33 caps v1's overlays at airports,
 * airspace and range rings, and this draws only what the user is measuring,
 * only while they measure. Same add-once, `setData`-in-place discipline as
 * every other FlightSite layer (`overlayLayers.ts`); `MeasureControl`
 * re-runs {@link ensureMeasureLayers} on every style load, since a basemap
 * switch discards custom layers.
 */

import type { Feature, FeatureCollection, Geometry } from "geojson";
import type { GeoJSONSource, Map as MapLibreGlMap } from "maplibre-gl";

import type { LatLon } from "@/features/map/geo/rings";
import {
  describeMeasurement,
  greatCircleLine,
  greatCircleMidpoint,
  measure,
} from "@/features/map/measure/measureMath";
import type { UnitSystem } from "@/lib/api/config";

export const MEASURE_SOURCE_ID = "flightsite-measure";
export const MEASURE_LINE_LAYER_ID = "flightsite-measure-line";
export const MEASURE_POINT_LAYER_ID = "flightsite-measure-points";
export const MEASURE_LABEL_LAYER_ID = "flightsite-measure-label";

/** A warm accent kept clear of every other map colour — the ring teal, the
 * receiver red, the selection blue and the trail grey — so a measurement
 * never reads as any of them. */
const MEASURE_COLOR = "#ffd166";

/** What each feature is, for the layer filters. */
type MeasureFeatureKind = "line" | "point" | "label";

export interface MeasureFeatureProperties {
  kind: MeasureFeatureKind;
  /** The readout, on the label feature only; `""` elsewhere. */
  label: string;
}

/**
 * The measure source's contents for `points`: nothing, a lone point A, or
 * the full A-to-B line with both endpoints and a midpoint label. Pure, so
 * the click flow's drawing is testable without a map.
 */
export function buildMeasureFeatureCollection(
  points: readonly LatLon[],
  units: UnitSystem,
): FeatureCollection<Geometry, MeasureFeatureProperties> {
  const features: Feature<Geometry, MeasureFeatureProperties>[] = points
    .slice(0, 2)
    .map((point) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [point.lon, point.lat] },
      properties: { kind: "point", label: "" },
    }));
  const [from, to] = points;
  if (from && to) {
    const measurement = measure(from, to);
    const midpoint = greatCircleMidpoint(measurement);
    features.unshift({
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: greatCircleLine(measurement),
      },
      properties: { kind: "line", label: "" },
    });
    features.push({
      type: "Feature",
      geometry: { type: "Point", coordinates: [midpoint.lon, midpoint.lat] },
      properties: {
        kind: "label",
        label: describeMeasurement(measurement, units),
      },
    });
  }
  return { type: "FeatureCollection", features };
}

const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };

/** Adds the measure source and layers if they are not on `map`'s current
 * style. Idempotent; leaves an existing source's data alone, so calling it
 * again never blanks a measurement in progress. */
export function ensureMeasureLayers(map: MapLibreGlMap): void {
  if (!map.getSource(MEASURE_SOURCE_ID)) {
    map.addSource(MEASURE_SOURCE_ID, { type: "geojson", data: EMPTY });
  }

  if (!map.getLayer(MEASURE_LINE_LAYER_ID)) {
    map.addLayer({
      id: MEASURE_LINE_LAYER_ID,
      type: "line",
      source: MEASURE_SOURCE_ID,
      filter: ["==", ["get", "kind"], "line"],
      layout: { "line-cap": "round" },
      paint: {
        "line-color": MEASURE_COLOR,
        "line-width": 2,
        "line-dasharray": [2, 1.5],
      },
    });
  }

  if (!map.getLayer(MEASURE_POINT_LAYER_ID)) {
    map.addLayer({
      id: MEASURE_POINT_LAYER_ID,
      type: "circle",
      source: MEASURE_SOURCE_ID,
      filter: ["==", ["get", "kind"], "point"],
      paint: {
        "circle-radius": 4,
        "circle-color": MEASURE_COLOR,
        "circle-stroke-color": "#0b1220",
        "circle-stroke-width": 1.5,
      },
    });
  }

  if (!map.getLayer(MEASURE_LABEL_LAYER_ID)) {
    map.addLayer({
      id: MEASURE_LABEL_LAYER_ID,
      type: "symbol",
      source: MEASURE_SOURCE_ID,
      filter: ["==", ["get", "kind"], "label"],
      layout: {
        "text-field": ["get", "label"],
        "text-size": 12,
        "text-anchor": "bottom",
        "text-offset": [0, -0.4],
        // The one label the user asked for: never collided away by an
        // aircraft label, and never hiding one either.
        "text-allow-overlap": true,
        "text-ignore-placement": true,
      },
      paint: {
        "text-color": MEASURE_COLOR,
        "text-halo-color": "#0b1220",
        "text-halo-width": 1.4,
      },
    });
  }
}

/** Replaces the measure source's data in place; a no-op before attach. */
export function setMeasureData(
  map: MapLibreGlMap,
  data: FeatureCollection<Geometry>,
): void {
  (map.getSource(MEASURE_SOURCE_ID) as GeoJSONSource | undefined)?.setData(
    data,
  );
}
