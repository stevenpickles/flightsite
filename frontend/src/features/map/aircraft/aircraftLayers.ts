/**
 * The MapLibre sources and layers that draw live aircraft.
 *
 * Same discipline as `@/features/map/overlayLayers`: sources and layers are
 * added once and then **mutated in place** with `setData`. Re-adding a layer on
 * every frame would rebuild the style, drop the render cache, and make the
 * 500-aircraft target unreachable; `setData` on an existing source is the one
 * cheap update path MapLibre offers.
 *
 * Four layers, bottom to top:
 *
 * 1. the selected aircraft's track polyline;
 * 2. the selection halo — a ring under the selected icon (SPEC §36 "strong
 *    selection highlight");
 * 3. the MLAT ring — a *dashed* ring under multilaterated positions, so the
 *    position source is distinguishable without relying on colour (SPEC §36);
 * 4. the aircraft symbols themselves, rotated to `track_deg`.
 *
 * Every style decision reads a feature property that
 * `@/features/map/aircraft/geojson` computed, so the expressions stay trivial
 * and the logic stays testable without a renderer.
 */

import type { FeatureCollection, Geometry } from "geojson";
import type {
  ExpressionSpecification,
  GeoJSONSource,
  Map as MapLibreGlMap,
  PointLike,
} from "maplibre-gl";

import { MLAT_RING_IMAGE_ID } from "@/features/map/aircraft/icons/silhouettes";

export const AIRCRAFT_SOURCE_ID = "flightsite-aircraft";
export const AIRCRAFT_TRACK_SOURCE_ID = "flightsite-aircraft-track";
export const AIRCRAFT_TRACK_LAYER_ID = "flightsite-aircraft-track-line";
export const AIRCRAFT_SELECTION_LAYER_ID = "flightsite-aircraft-selection";
export const AIRCRAFT_MLAT_RING_LAYER_ID = "flightsite-aircraft-mlat-ring";
export const AIRCRAFT_SYMBOL_LAYER_ID = "flightsite-aircraft-symbols";

/** Selection accent. Fixed rather than theme-driven, for the same reason the
 * range rings are: it has to read identically on every basemap. Deliberately
 * distinct from the ring teal and the receiver red already on the map. */
const SELECTION_COLOR = "#8ab4ff";

const EMPTY: FeatureCollection<Geometry> = {
  type: "FeatureCollection",
  features: [],
};

/** Icon scale by zoom. Small enough at wide zooms that a busy 250 nm picture
 * does not become a solid mat of silhouettes, close to life size once the view
 * is down to terminal-area scale. */
const ICON_SIZE_BY_ZOOM: ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["zoom"],
  3,
  0.6,
  7,
  0.8,
  11,
  1,
];

/** The selected aircraft is drawn a quarter larger — a size cue that survives
 * the halo being hidden under a dense cluster. */
const ICON_SIZE: ExpressionSpecification = [
  "*",
  ICON_SIZE_BY_ZOOM,
  ["case", ["get", "selected"], 1.25, 1],
];

function upsertGeoJsonSource(
  map: MapLibreGlMap,
  id: string,
  data: FeatureCollection<Geometry>,
): void {
  const existing = map.getSource(id) as GeoJSONSource | undefined;
  if (existing) {
    existing.setData(data);
  } else {
    map.addSource(id, { type: "geojson", data });
  }
}

/**
 * Adds the aircraft sources and layers if they are not already on `map`'s
 * current style. Idempotent, and safe to call again after a basemap switch —
 * `setStyle` clears custom layers, so the caller re-runs this on every
 * `style.load` exactly as it does for the range-ring overlays.
 *
 * The icons must already be registered (see `registerAircraftIcons`): a symbol
 * layer whose `icon-image` names an unknown image draws nothing and warns per
 * feature per frame.
 */
export function ensureAircraftLayers(map: MapLibreGlMap): void {
  upsertGeoJsonSource(map, AIRCRAFT_SOURCE_ID, EMPTY);
  upsertGeoJsonSource(map, AIRCRAFT_TRACK_SOURCE_ID, EMPTY);

  if (!map.getLayer(AIRCRAFT_TRACK_LAYER_ID)) {
    map.addLayer({
      id: AIRCRAFT_TRACK_LAYER_ID,
      type: "line",
      source: AIRCRAFT_TRACK_SOURCE_ID,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": SELECTION_COLOR,
        "line-width": 2,
        "line-opacity": 0.8,
      },
    });
  }

  if (!map.getLayer(AIRCRAFT_SELECTION_LAYER_ID)) {
    map.addLayer({
      id: AIRCRAFT_SELECTION_LAYER_ID,
      type: "circle",
      source: AIRCRAFT_SOURCE_ID,
      filter: ["==", ["get", "selected"], true],
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 14, 11, 22],
        "circle-color": SELECTION_COLOR,
        "circle-opacity": 0.18,
        "circle-stroke-color": SELECTION_COLOR,
        "circle-stroke-width": 2.5,
      },
    });
  }

  if (!map.getLayer(AIRCRAFT_MLAT_RING_LAYER_ID)) {
    map.addLayer({
      id: AIRCRAFT_MLAT_RING_LAYER_ID,
      type: "symbol",
      source: AIRCRAFT_SOURCE_ID,
      filter: ["==", ["get", "mlat"], true],
      layout: {
        "icon-image": MLAT_RING_IMAGE_ID,
        "icon-size": ICON_SIZE,
        // Viewport-aligned: the ring is a badge, not part of the airframe, so
        // it must not spin with the aircraft's track.
        "icon-rotation-alignment": "viewport",
        "icon-allow-overlap": true,
        "icon-ignore-placement": true,
      },
      paint: { "icon-opacity": ["get", "opacity"] },
    });
  }

  if (!map.getLayer(AIRCRAFT_SYMBOL_LAYER_ID)) {
    map.addLayer({
      id: AIRCRAFT_SYMBOL_LAYER_ID,
      type: "symbol",
      source: AIRCRAFT_SOURCE_ID,
      layout: {
        "icon-image": ["get", "icon"],
        "icon-size": ICON_SIZE,
        "icon-rotate": ["get", "track"],
        // Map-aligned rotation: `track_deg` is a compass bearing, so the icon
        // must turn with the map rather than with the screen.
        "icon-rotation-alignment": "map",
        "icon-allow-overlap": true,
        "icon-ignore-placement": true,
        // Draw the selection last so it wins any overlap with its neighbours.
        "symbol-sort-key": ["case", ["get", "selected"], 1, 0],
      },
      paint: { "icon-opacity": ["get", "opacity"] },
    });
  }
}

/** Replaces the aircraft symbol source's data in place. */
export function setAircraftData(
  map: MapLibreGlMap,
  data: FeatureCollection<Geometry>,
): void {
  (map.getSource(AIRCRAFT_SOURCE_ID) as GeoJSONSource | undefined)?.setData(
    data,
  );
}

/** Replaces the selected aircraft's track polyline in place. */
export function setTrackData(
  map: MapLibreGlMap,
  data: FeatureCollection<Geometry>,
): void {
  (
    map.getSource(AIRCRAFT_TRACK_SOURCE_ID) as GeoJSONSource | undefined
  )?.setData(data);
}

/**
 * The ICAO of the aircraft under a click, or `null` for empty map.
 *
 * A single map-level click handler plus a rendered-feature query is used rather
 * than a layer-scoped handler, because selection and *de*selection are one
 * decision: a click that hits nothing must clear the selection, and two
 * competing handlers would have to coordinate to work that out.
 */
export function aircraftIcaoAtPoint(
  map: MapLibreGlMap,
  point: PointLike,
): string | null {
  if (!map.getLayer(AIRCRAFT_SYMBOL_LAYER_ID)) {
    return null;
  }
  const [hit] = map.queryRenderedFeatures(point, {
    layers: [AIRCRAFT_SYMBOL_LAYER_ID],
  });
  const icao = hit?.properties?.icao;
  return typeof icao === "string" ? icao : null;
}
