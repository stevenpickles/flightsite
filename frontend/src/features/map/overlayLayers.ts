import type { FeatureCollection } from "geojson";
import type { GeoJSONSource, Map as MapLibreGlMap } from "maplibre-gl";

import {
  generateRangeRingLabelsGeoJSON,
  generateRangeRingsGeoJSON,
  generateReceiverPointGeoJSON,
} from "@/features/map/geo/rings";
import type { MapConfig } from "@/features/map/types";

/** Every source and layer this app adds to a style is named with this
 * prefix, which is what lets map-level event handling tell FlightSite's own
 * client-drawn GeoJSON apart from the basemap's network-backed sources. */
export const FLIGHTSITE_SOURCE_PREFIX = "flightsite-";

export const RANGE_RINGS_SOURCE_ID = "flightsite-range-rings";
export const RANGE_RING_LABELS_SOURCE_ID = "flightsite-range-ring-labels";
export const RECEIVER_SOURCE_ID = "flightsite-receiver";
export const RANGE_RING_LINE_LAYER_ID = "flightsite-range-rings-line";
export const RANGE_RING_LABEL_LAYER_ID = "flightsite-range-rings-label";
export const RECEIVER_HALO_LAYER_ID = "flightsite-receiver-halo";
export const RECEIVER_DOT_LAYER_ID = "flightsite-receiver-dot";

// Fixed accent colors (not theme-driven): range rings and the receiver
// marker must read identically regardless of which basemap is active, so
// they stay legible across both the dark and light aviation styles and
// the OSM raster fallback.
const RING_COLOR = "#4dd8cf";
const RECEIVER_COLOR = "#ff5a5f";

/**
 * Adds (or, if already present, updates in place) the range-ring and
 * receiver-marker sources/layers on `map`. These are always client-drawn
 * GeoJSON — generated locally, never fetched — so they render regardless
 * of whether basemap tiles load successfully. That's what keeps the map
 * usable during a tile outage (roadmap slice 013 acceptance criteria).
 * Idempotent: safe to call again, including after a basemap switch
 * replaces the underlying style and clears its layers.
 *
 * Both overlays draw nothing at all while `config.receiverConfigured` is
 * false — see that field. Rendering regardless of the tiles is the point;
 * rendering regardless of whether the position is real is how issue R1-05
 * drew a Seattle placeholder on an install in Kansas.
 */
export function ensureOverlayLayers(
  map: MapLibreGlMap,
  config: MapConfig,
): void {
  ensureRangeRingLayers(map, config);
  ensureReceiverLayers(map, config);
}

function upsertGeoJsonSource(
  map: MapLibreGlMap,
  id: string,
  data: FeatureCollection,
): void {
  const existing = map.getSource(id) as GeoJSONSource | undefined;
  if (existing) {
    existing.setData(data);
  } else {
    map.addSource(id, { type: "geojson", data });
  }
}

/** Nothing to draw — the shape an overlay source takes when the receiver
 * position it would be generated from is not a real one (issue R1-05). */
const EMPTY_FEATURES: FeatureCollection = {
  type: "FeatureCollection",
  features: [],
};

function ensureRangeRingLayers(map: MapLibreGlMap, config: MapConfig): void {
  // Rings are a claim about how far *this receiver* reaches, so they are
  // drawn only around a receiver that exists. The layers are still added
  // either way: the config that finally carries a real location arrives as
  // a `setData` on a source already on the map, not as a fresh style edit.
  upsertGeoJsonSource(
    map,
    RANGE_RINGS_SOURCE_ID,
    config.receiverConfigured
      ? generateRangeRingsGeoJSON(config)
      : EMPTY_FEATURES,
  );
  upsertGeoJsonSource(
    map,
    RANGE_RING_LABELS_SOURCE_ID,
    config.receiverConfigured
      ? generateRangeRingLabelsGeoJSON(config)
      : EMPTY_FEATURES,
  );

  if (!map.getLayer(RANGE_RING_LINE_LAYER_ID)) {
    map.addLayer({
      id: RANGE_RING_LINE_LAYER_ID,
      type: "line",
      source: RANGE_RINGS_SOURCE_ID,
      paint: {
        "line-color": RING_COLOR,
        "line-width": 1,
        "line-opacity": 0.55,
        "line-dasharray": [3, 2],
      },
    });
  }

  if (!map.getLayer(RANGE_RING_LABEL_LAYER_ID)) {
    map.addLayer({
      id: RANGE_RING_LABEL_LAYER_ID,
      type: "symbol",
      source: RANGE_RING_LABELS_SOURCE_ID,
      layout: {
        "text-field": ["get", "label"],
        "text-size": 10,
        "text-anchor": "bottom",
        "text-allow-overlap": true,
      },
      paint: {
        "text-color": RING_COLOR,
        "text-halo-color": "#0a0e1a",
        "text-halo-width": 1,
      },
    });
  }
}

function ensureReceiverLayers(map: MapLibreGlMap, config: MapConfig): void {
  upsertGeoJsonSource(
    map,
    RECEIVER_SOURCE_ID,
    config.receiverConfigured
      ? {
          type: "FeatureCollection",
          features: [generateReceiverPointGeoJSON(config.receiver)],
        }
      : EMPTY_FEATURES,
  );

  if (!map.getLayer(RECEIVER_HALO_LAYER_ID)) {
    map.addLayer({
      id: RECEIVER_HALO_LAYER_ID,
      type: "circle",
      source: RECEIVER_SOURCE_ID,
      paint: {
        "circle-radius": 10,
        "circle-color": RECEIVER_COLOR,
        "circle-opacity": 0.2,
      },
    });
  }

  if (!map.getLayer(RECEIVER_DOT_LAYER_ID)) {
    map.addLayer({
      id: RECEIVER_DOT_LAYER_ID,
      type: "circle",
      source: RECEIVER_SOURCE_ID,
      paint: {
        "circle-radius": 4,
        "circle-color": RECEIVER_COLOR,
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 1,
      },
    });
  }
}
