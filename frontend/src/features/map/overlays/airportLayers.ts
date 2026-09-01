/**
 * MapLibre source and symbol layers for the airport overlay (roadmap slice
 * 028) — one layer per size class, each carrying its own glyph
 * (`airportIcons.ts`) and an `ident` label, gated by that class's
 * `AIRPORT_MIN_ZOOM` threshold (`airportDensity.ts`) so the overlay declutters
 * itself as the view zooms out rather than needing JS-driven visibility
 * logic: MapLibre's own `minzoom` does the density gating.
 *
 * Follows the same idempotent ensure/upsert shape as `overlayLayers.ts` (the
 * range rings and receiver marker) and `aircraft/aircraftLayers.ts`: safe to
 * call again after a basemap switch discards the style's custom layers.
 */

import type { FeatureCollection, Point } from "geojson";
import type { GeoJSONSource, Map as MapLibreGlMap } from "maplibre-gl";

import { airportIconImageId } from "@/features/map/overlays/airportIcons";
import { AIRPORT_MIN_ZOOM } from "@/features/map/overlays/airportDensity";
import type { AirportSizeClass } from "@/lib/api/overlays";

export const AIRPORTS_SOURCE_ID = "flightsite-airports";

const SIZE_CLASSES: readonly AirportSizeClass[] = [
  "large",
  "medium",
  "small",
  "heliport",
];

export function airportLayerId(sizeClass: AirportSizeClass): string {
  return `flightsite-airports-${sizeClass}`;
}

/** Every layer id this overlay owns, in registration order. */
export const AIRPORT_LAYER_IDS: readonly string[] =
  SIZE_CLASSES.map(airportLayerId);

export const EMPTY_AIRPORT_FEATURE_COLLECTION: FeatureCollection<Point> = {
  type: "FeatureCollection",
  features: [],
};

/**
 * Adds (or, if already present, leaves in place) the airport source and its
 * four size-class symbol layers. Idempotent — safe to call after every
 * style load, including on a basemap switch.
 */
export function ensureAirportLayers(map: MapLibreGlMap): void {
  if (!map.getSource(AIRPORTS_SOURCE_ID)) {
    map.addSource(AIRPORTS_SOURCE_ID, {
      type: "geojson",
      data: EMPTY_AIRPORT_FEATURE_COLLECTION,
    });
  }

  for (const sizeClass of SIZE_CLASSES) {
    const layerId = airportLayerId(sizeClass);
    if (map.getLayer(layerId)) {
      continue;
    }
    map.addLayer({
      id: layerId,
      type: "symbol",
      source: AIRPORTS_SOURCE_ID,
      filter: ["==", ["get", "size_class"], sizeClass],
      minzoom: AIRPORT_MIN_ZOOM[sizeClass],
      layout: {
        "icon-image": airportIconImageId(sizeClass),
        "icon-size": 1,
        "icon-allow-overlap": true,
        "text-field": ["get", "ident"],
        "text-size": 10,
        "text-anchor": "top",
        "text-offset": [0, 0.6],
        "text-optional": true,
        "text-allow-overlap": false,
      },
      paint: {
        "text-color": "#f2b134",
        "text-halo-color": "#0a0e1a",
        "text-halo-width": 1,
      },
    });
  }
}

/** Replaces the airport source's data in place. */
export function setAirportFeatures(
  map: MapLibreGlMap,
  collection: FeatureCollection<Point> | undefined,
): void {
  const source = map.getSource(AIRPORTS_SOURCE_ID) as GeoJSONSource | undefined;
  if (!source) {
    return;
  }
  source.setData(collection ?? EMPTY_AIRPORT_FEATURE_COLLECTION);
}

/** Shows or hides every airport layer via MapLibre's own `visibility`
 * layout property, so toggling never requires a refetch. */
export function setAirportLayersVisible(
  map: MapLibreGlMap,
  visible: boolean,
): void {
  const visibility = visible ? "visible" : "none";
  for (const layerId of AIRPORT_LAYER_IDS) {
    if (map.getLayer(layerId)) {
      map.setLayoutProperty(layerId, "visibility", visibility);
    }
  }
}
