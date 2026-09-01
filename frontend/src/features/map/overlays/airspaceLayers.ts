/**
 * MapLibre source and layers for the user-supplied airspace overlay (roadmap
 * slice 028, `docs/adr/0012-airspace-data-source.md`).
 *
 * Two layers share one source: a fill for polygon geometries and a line for
 * every geometry type (a polygon's boundary, or a supplied line/point
 * feature on its own). Styling is class-based when a feature carries a
 * `class` property (MapLibre `match` expressions keyed on it) and a single
 * restrained default otherwise (`docs/PRODUCT.md` §6) — FlightSite has no
 * way to know what vocabulary a user's own file uses, so the fallback has to
 * be sane for a `class` this code has never seen.
 *
 * An empty source (the "no file supplied" / "file failed validation" answer
 * `GET /api/v1/airspace` gives either way) renders nothing and errors at
 * nothing — MapLibre draws zero features from an empty `FeatureCollection`
 * exactly as happily as it draws a full one, which is what keeps this
 * overlay's "no UI noise on absent data" requirement true without any
 * special-cased empty-state branch here.
 */

import type { FeatureCollection, Geometry } from "geojson";
import type { GeoJSONSource, Map as MapLibreGlMap } from "maplibre-gl";

export const AIRSPACE_SOURCE_ID = "flightsite-airspace";
export const AIRSPACE_FILL_LAYER_ID = "flightsite-airspace-fill";
export const AIRSPACE_LINE_LAYER_ID = "flightsite-airspace-line";

export const AIRSPACE_LAYER_IDS: readonly string[] = [
  AIRSPACE_FILL_LAYER_ID,
  AIRSPACE_LINE_LAYER_ID,
];

export const EMPTY_AIRSPACE_FEATURE_COLLECTION: FeatureCollection<Geometry> = {
  type: "FeatureCollection",
  features: [],
};

/** Restrained default — a muted violet-blue, legible on both the dark and
 * light aviation basemaps without competing with aircraft or range rings. */
const DEFAULT_COLOR = "#7c93ff";

/**
 * Adds (or, if already present, leaves in place) the airspace source and its
 * fill/line layers. Idempotent — safe to call after every style load,
 * including on a basemap switch.
 */
export function ensureAirspaceLayers(map: MapLibreGlMap): void {
  if (!map.getSource(AIRSPACE_SOURCE_ID)) {
    map.addSource(AIRSPACE_SOURCE_ID, {
      type: "geojson",
      data: EMPTY_AIRSPACE_FEATURE_COLLECTION,
    });
  }

  if (!map.getLayer(AIRSPACE_FILL_LAYER_ID)) {
    map.addLayer({
      id: AIRSPACE_FILL_LAYER_ID,
      type: "fill",
      source: AIRSPACE_SOURCE_ID,
      // MapLibre's `geometry-type` expression normalizes MultiPolygon to
      // "Polygon" (and MultiLineString/MultiPoint likewise), so this single
      // equality check already covers both Polygon and MultiPolygon
      // features — no separate "MultiPolygon" branch needed.
      filter: ["==", ["geometry-type"], "Polygon"],
      paint: {
        // Buckets a handful of common ICAO/FAA-ish `class` spellings into a
        // restricted/prohibited amber and a controlled-airspace blue;
        // anything this code has never seen (including "no `class` at
        // all") falls through to DEFAULT_COLOR. Case-sensitive, best-effort
        // only — a user's file is free to use any vocabulary.
        "fill-color": [
          "match",
          ["get", "class"],
          ["B", "C", "D", "E"],
          "#5b8def",
          ["R", "P", "MOA", "TFR", "restricted", "prohibited"],
          "#e0a23c",
          DEFAULT_COLOR,
        ],
        "fill-opacity": 0.08,
      },
    });
  }

  if (!map.getLayer(AIRSPACE_LINE_LAYER_ID)) {
    map.addLayer({
      id: AIRSPACE_LINE_LAYER_ID,
      type: "line",
      source: AIRSPACE_SOURCE_ID,
      paint: {
        // Mirrors the fill layer's bucketing above — see that comment.
        "line-color": [
          "match",
          ["get", "class"],
          ["B", "C", "D", "E"],
          "#5b8def",
          ["R", "P", "MOA", "TFR", "restricted", "prohibited"],
          "#e0a23c",
          DEFAULT_COLOR,
        ],
        "line-width": 1.25,
        "line-opacity": 0.65,
      },
    });
  }
}

/** Replaces the airspace source's data in place. */
export function setAirspaceFeatures(
  map: MapLibreGlMap,
  collection: FeatureCollection<Geometry> | undefined,
): void {
  const source = map.getSource(AIRSPACE_SOURCE_ID) as GeoJSONSource | undefined;
  if (!source) {
    return;
  }
  source.setData(collection ?? EMPTY_AIRSPACE_FEATURE_COLLECTION);
}

/** Shows or hides both airspace layers via MapLibre's own `visibility`
 * layout property, so toggling never requires a refetch. */
export function setAirspaceLayersVisible(
  map: MapLibreGlMap,
  visible: boolean,
): void {
  const visibility = visible ? "visible" : "none";
  for (const layerId of AIRSPACE_LAYER_IDS) {
    if (map.getLayer(layerId)) {
      map.setLayoutProperty(layerId, "visibility", visibility);
    }
  }
}
