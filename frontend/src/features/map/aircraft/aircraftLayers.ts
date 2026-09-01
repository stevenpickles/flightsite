/**
 * The MapLibre sources and layers that draw live aircraft.
 *
 * Same discipline as `@/features/map/overlayLayers`: sources and layers are
 * added once and then **mutated in place** with `setData`. Re-adding a layer on
 * every frame would rebuild the style, drop the render cache, and make the
 * 500-aircraft target unreachable; `setData` on an existing source is the one
 * cheap update path MapLibre offers.
 *
 * Six layers, bottom to top:
 *
 * 1. the selected aircraft's track polyline;
 * 2. the selection halo — a ring under the selected icon (SPEC §36 "strong
 *    selection highlight");
 * 3. the MLAT ring — a *dashed* ring under multilaterated positions, so the
 *    position source is distinguishable without relying on colour (SPEC §36);
 * 4. the aircraft symbols themselves, rotated to `track_deg`;
 * 5. non-selected aircraft labels — `text-allow-overlap: false`, so
 *    MapLibre's own collision system hides whichever labels lose the
 *    `symbol-sort-key` contest (roadmap slice 015: "MapLibre's own collision
 *    system plus zoom/density-driven tiering");
 * 6. the selected aircraft's label — its own layer because
 *    `text-allow-overlap`/`text-ignore-placement` are layer-level, not
 *    data-driven, and the selected label must never be the one collision
 *    hides (roadmap slice 015 acceptance criterion: "selected aircraft
 *    always fully labeled").
 *
 * Every style decision reads a feature property that
 * `@/features/map/aircraft/geojson` computed, so the expressions stay trivial
 * and the logic stays testable without a renderer. That includes *which*
 * lines a label shows: `geojson.ts` already tiers the text by zoom and
 * density (`@/features/map/labels`) before it ever reaches these layers, so
 * the layers themselves only ever decide *whether a placed label survives a
 * collision*, never how much text it carries.
 */

import type { FeatureCollection, Geometry } from "geojson";
import type {
  ExpressionSpecification,
  GeoJSONSource,
  Map as MapLibreGlMap,
  PointLike,
} from "maplibre-gl";

import { MLAT_RING_IMAGE_ID } from "@/features/map/aircraft/icons/silhouettes";
import {
  SORT_KEY_DEFAULT,
  SORT_KEY_INTERESTING,
} from "@/features/map/labels/priority";

export const AIRCRAFT_SOURCE_ID = "flightsite-aircraft";
export const AIRCRAFT_TRACK_SOURCE_ID = "flightsite-aircraft-track";
export const AIRCRAFT_TRACK_LAYER_ID = "flightsite-aircraft-track-line";
export const AIRCRAFT_SELECTION_LAYER_ID = "flightsite-aircraft-selection";
export const AIRCRAFT_MLAT_RING_LAYER_ID = "flightsite-aircraft-mlat-ring";
export const AIRCRAFT_SYMBOL_LAYER_ID = "flightsite-aircraft-symbols";
export const AIRCRAFT_LABEL_LAYER_ID = "flightsite-aircraft-labels";
export const AIRCRAFT_SELECTED_LABEL_LAYER_ID =
  "flightsite-aircraft-labels-selected";

/** Selection accent. Fixed rather than theme-driven, for the same reason the
 * range rings are: it has to read identically on every basemap. Deliberately
 * distinct from the ring teal and the receiver red already on the map. */
const SELECTION_COLOR = "#8ab4ff";

/** Label text fill and halo. Deliberately the same values as the aircraft
 * icon palette (`icons/silhouettes.ts`'s `BODY`/`INK`) rather than importing
 * them — that module stays free of a label-layer dependency — but the design
 * decision is identical: a light fill with a dark halo reads on the dark
 * aviation basemap, the light one, and OSM raster imagery alike, so labels
 * do not need a theme of their own. */
const LABEL_TEXT_COLOR = "#f2f6ff";
const LABEL_HALO_COLOR = "#0b1220";
const LABEL_HALO_WIDTH = 1.2;

const EMPTY: FeatureCollection<Geometry> = {
  type: "FeatureCollection",
  features: [],
};

/**
 * Icon scale by zoom, with the selected aircraft drawn a quarter larger at
 * every stop — a size cue that survives the halo being hidden under a dense
 * cluster. Small enough at wide zooms that a busy 250 nm picture does not
 * become a solid mat of silhouettes, close to life size once the view is
 * down to terminal-area scale.
 *
 * The style spec requires a `["zoom"]` expression to be the *direct* input
 * of a top-level `interpolate`/`step` — it cannot be nested inside another
 * expression (e.g. multiplying a separate zoom-`interpolate` by a
 * selection factor, which is invalid and fails style validation silently:
 * MapLibre fires an `error` event rather than throwing, so the layer is
 * simply never added and no aircraft render). Folding the selection
 * multiplier into each stop's *output* instead keeps `interpolate`/`zoom`
 * at the top level while still varying by both zoom and selection.
 */
const ICON_SIZE: ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["zoom"],
  3,
  ["case", ["get", "selected"], 0.75, 0.6],
  7,
  ["case", ["get", "selected"], 1.0, 0.8],
  11,
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

  if (!map.getLayer(AIRCRAFT_LABEL_LAYER_ID)) {
    map.addLayer({
      id: AIRCRAFT_LABEL_LAYER_ID,
      type: "symbol",
      source: AIRCRAFT_SOURCE_ID,
      // Only a feature with something to say, and not the selected aircraft
      // — that one gets its own always-visible layer below. An empty
      // `label` is filtered out here rather than left to MapLibre so a tier
      // of "none" (`@/features/map/labels`) never occupies a collision slot
      // another aircraft's label could have used.
      filter: [
        "all",
        ["!=", ["get", "label"], ""],
        ["==", ["get", "selected"], false],
      ],
      layout: {
        "text-field": ["get", "label"],
        "text-size": 11,
        "text-anchor": "top",
        "text-offset": [0, 1],
        "text-line-height": 1.15,
        // MapLibre's own collision system: a label that loses the
        // placement contest is hidden rather than drawn over its neighbour.
        "text-allow-overlap": false,
        "text-optional": true,
        // Interesting aircraft win a collision against an ordinary one;
        // selected is excluded by the filter above. Mirrors
        // `labels/priority.ts`'s `deriveLabelSortKey`.
        "symbol-sort-key": [
          "case",
          ["get", "interesting"],
          SORT_KEY_INTERESTING,
          SORT_KEY_DEFAULT,
        ],
      },
      paint: {
        "text-color": LABEL_TEXT_COLOR,
        "text-halo-color": LABEL_HALO_COLOR,
        "text-halo-width": LABEL_HALO_WIDTH,
        "text-opacity": ["get", "opacity"],
      },
    });
  }

  if (!map.getLayer(AIRCRAFT_SELECTED_LABEL_LAYER_ID)) {
    map.addLayer({
      id: AIRCRAFT_SELECTED_LABEL_LAYER_ID,
      type: "symbol",
      source: AIRCRAFT_SOURCE_ID,
      filter: ["==", ["get", "selected"], true],
      layout: {
        "text-field": ["get", "label"],
        "text-size": 12,
        "text-anchor": "top",
        "text-offset": [0, 1],
        "text-line-height": 1.15,
        // The selected aircraft's label is never allowed to collide away —
        // roadmap slice 015's "selected aircraft always fully labeled"
        // acceptance criterion — so both overlap and placement collision
        // are off. `text-allow-overlap`/`text-ignore-placement` are
        // layer-level rather than data-driven, which is why this cannot
        // just be a `case` expression on the shared label layer above.
        "text-allow-overlap": true,
        "text-ignore-placement": true,
      },
      paint: {
        "text-color": LABEL_TEXT_COLOR,
        "text-halo-color": LABEL_HALO_COLOR,
        "text-halo-width": LABEL_HALO_WIDTH,
        "text-opacity": ["get", "opacity"],
      },
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
