/**
 * Draws one sighting's simplified path on the enclosing `MapLibreMap`: a
 * line (colored by altitude when at least two points carry one, a plain
 * accent color otherwise — "if cheap, else plain accent" per the roadmap),
 * start/end markers, and a fit-bounds to the path. Client-drawn GeoJSON, the
 * same pattern `features/map/overlayLayers.ts` uses for the range rings and
 * receiver marker: no library beyond MapLibre's own paint expressions.
 *
 * Re-attaches after every style load (`styleEpoch`, e.g. a basemap switch)
 * and re-fits whenever the path itself changes — the route stays mounted
 * across a sighting-to-sighting navigation (`/sightings/:id`'s param
 * changes without unmounting the page), so this cannot assume "mount" and
 * "new path" are the same event.
 */

import { useEffect, useRef } from "react";

import type { GeoJSONSource, Map as MapLibreGlMap } from "maplibre-gl";

import { useMapInstance } from "@/features/map/MapInstanceContext";
import { buildPathGeojson } from "@/features/sighting-detail/lib/pathGeojson";
import type { SightingPathPoint } from "@/lib/api/sightings";

export const PATH_LINE_SOURCE_ID = "flightsite-sighting-path";
export const PATH_LINE_LAYER_ID = "flightsite-sighting-path-line";
export const PATH_ENDPOINTS_SOURCE_ID = "flightsite-sighting-endpoints";
export const PATH_ENDPOINTS_LAYER_ID = "flightsite-sighting-endpoints-dot";

const ACCENT_COLOR = "#4dd8cf";
const START_COLOR = "#2ecc71";
const END_COLOR = "#ff5a5f";

function upsertSource(
  map: MapLibreGlMap,
  id: string,
  data: GeoJSON.FeatureCollection,
): void {
  const existing = map.getSource(id) as GeoJSONSource | undefined;
  if (existing) {
    existing.setData(data);
  } else {
    map.addSource(id, { type: "geojson", data });
  }
}

function ensureLayers(map: MapLibreGlMap, altitudeColored: boolean): void {
  if (!map.getLayer(PATH_LINE_LAYER_ID)) {
    map.addLayer({
      id: PATH_LINE_LAYER_ID,
      type: "line",
      source: PATH_LINE_SOURCE_ID,
      paint: {
        "line-color": altitudeColored
          ? [
              "interpolate",
              ["linear"],
              ["coalesce", ["get", "altitude_ft"], 0],
              0,
              "#2ecc71",
              20000,
              "#f1c40f",
              45000,
              "#e74c3c",
            ]
          : ACCENT_COLOR,
        "line-width": 3,
        "line-opacity": 0.85,
      },
    });
  }
  if (!map.getLayer(PATH_ENDPOINTS_LAYER_ID)) {
    map.addLayer({
      id: PATH_ENDPOINTS_LAYER_ID,
      type: "circle",
      source: PATH_ENDPOINTS_SOURCE_ID,
      paint: {
        "circle-radius": 6,
        "circle-color": [
          "match",
          ["get", "kind"],
          "start",
          START_COLOR,
          "end",
          END_COLOR,
          ACCENT_COLOR,
        ],
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 1.5,
      },
    });
  }
}

export interface SightingPathLayerProps {
  path: SightingPathPoint[];
}

export function SightingPathLayer({ path }: SightingPathLayerProps) {
  const { map, styleEpoch } = useMapInstance();
  const fittedForRef = useRef<string | null>(null);

  useEffect(() => {
    if (!map || styleEpoch === 0) {
      return;
    }
    const geojson = buildPathGeojson(path);
    upsertSource(map, PATH_LINE_SOURCE_ID, geojson.line);
    upsertSource(map, PATH_ENDPOINTS_SOURCE_ID, geojson.endpoints);
    ensureLayers(map, geojson.altitudeRangeFt !== null);

    // Fit once per distinct path (identified by its point count and first
    // timestamp — cheap and stable across re-renders of the same sighting),
    // not on every render: a user panning/zooming the map must not be
    // fought back to the fitted view.
    const identity = `${path.length}:${path[0]?.t ?? ""}`;
    if (geojson.bounds && fittedForRef.current !== identity) {
      fittedForRef.current = identity;
      map.fitBounds(geojson.bounds, { padding: 48, maxZoom: 12, duration: 0 });
    }
  }, [map, styleEpoch, path]);

  return null;
}
