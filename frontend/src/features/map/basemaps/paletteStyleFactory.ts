import type { StyleSpecification } from "maplibre-gl";

/**
 * OpenFreeMap's public tile service (https://tiles.openfreemap.org). No
 * API key, no rate limiting, no usage tracking — see
 * docs/adr/0011-default-basemap-provider.md for the full evaluation. The
 * vector source below follows the OpenMapTiles schema OpenFreeMap serves;
 * layer/source-layer names are verified against the schema OpenFreeMap's
 * own "liberty"/"dark" styles ship (confirmed via their published style
 * JSON at https://tiles.openfreemap.org/styles/{liberty,dark}).
 */
export const OPENFREEMAP_TILE_JSON_URL = "https://tiles.openfreemap.org/planet";
export const OPENFREEMAP_GLYPHS_URL =
  "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf";
export const OPENFREEMAP_ATTRIBUTION =
  '© <a href="https://www.openmaptiles.org/" target="_blank" rel="noreferrer">OpenMapTiles</a> ' +
  '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors';

/** Color tokens an aviation-themed OpenMapTiles style is built from. Kept
 * deliberately small — this is a basemap meant to recede behind aircraft
 * and range rings, not a general-purpose street map. */
export interface AviationPalette {
  background: string;
  water: string;
  waterLabel: string;
  landcover: string;
  landuseResidential: string;
  boundary: string;
  roadCasing: string;
  roadFill: string;
  roadMinor: string;
  railway: string;
  building: string;
  aeroway: string;
  textPrimary: string;
  textHalo: string;
}

/**
 * Builds a compact MapLibre style over OpenFreeMap's OpenMapTiles-schema
 * vector tiles, themed from `palette`. Both the dark-aviation default and
 * the light-aviation alternative share this factory so the two stay
 * visually consistent (same layer set, different colors only).
 */
export function buildAviationStyle(
  id: string,
  palette: AviationPalette,
): StyleSpecification {
  const textPaint = {
    "text-color": palette.textPrimary,
    "text-halo-color": palette.textHalo,
    "text-halo-width": 1.2,
  } as const;

  return {
    version: 8,
    name: `flightsite-${id}`,
    glyphs: OPENFREEMAP_GLYPHS_URL,
    sources: {
      openmaptiles: {
        type: "vector",
        url: OPENFREEMAP_TILE_JSON_URL,
        attribution: OPENFREEMAP_ATTRIBUTION,
      },
    },
    layers: [
      {
        id: "background",
        type: "background",
        paint: { "background-color": palette.background },
      },
      {
        id: "landcover",
        type: "fill",
        source: "openmaptiles",
        "source-layer": "landcover",
        paint: { "fill-color": palette.landcover, "fill-opacity": 0.6 },
      },
      {
        id: "landuse-residential",
        type: "fill",
        source: "openmaptiles",
        "source-layer": "landuse",
        filter: ["==", ["get", "class"], "residential"],
        paint: {
          "fill-color": palette.landuseResidential,
          "fill-opacity": 0.5,
        },
      },
      {
        id: "water",
        type: "fill",
        source: "openmaptiles",
        "source-layer": "water",
        paint: { "fill-color": palette.water },
      },
      {
        id: "building",
        type: "fill",
        source: "openmaptiles",
        "source-layer": "building",
        minzoom: 13,
        paint: { "fill-color": palette.building, "fill-opacity": 0.8 },
      },
      {
        id: "railway",
        type: "line",
        source: "openmaptiles",
        "source-layer": "transportation",
        filter: ["==", ["get", "class"], "rail"],
        minzoom: 9,
        paint: { "line-color": palette.railway, "line-width": 0.6 },
      },
      {
        id: "road-minor",
        type: "line",
        source: "openmaptiles",
        "source-layer": "transportation",
        filter: [
          "in",
          ["get", "class"],
          ["literal", ["minor", "service", "track"]],
        ],
        minzoom: 11,
        paint: { "line-color": palette.roadMinor, "line-width": 0.75 },
      },
      {
        id: "road-major-casing",
        type: "line",
        source: "openmaptiles",
        "source-layer": "transportation",
        filter: [
          "in",
          ["get", "class"],
          [
            "literal",
            ["motorway", "trunk", "primary", "secondary", "tertiary"],
          ],
        ],
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": palette.roadCasing,
          "line-width": ["interpolate", ["linear"], ["zoom"], 5, 0.6, 12, 4],
        },
      },
      {
        id: "road-major-fill",
        type: "line",
        source: "openmaptiles",
        "source-layer": "transportation",
        filter: [
          "in",
          ["get", "class"],
          [
            "literal",
            ["motorway", "trunk", "primary", "secondary", "tertiary"],
          ],
        ],
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": palette.roadFill,
          "line-width": ["interpolate", ["linear"], ["zoom"], 5, 0.3, 12, 2.4],
        },
      },
      {
        id: "aeroway",
        type: "line",
        source: "openmaptiles",
        "source-layer": "aeroway",
        filter: ["in", ["get", "class"], ["literal", ["runway", "taxiway"]]],
        minzoom: 9,
        paint: {
          "line-color": palette.aeroway,
          "line-width": 1.4,
          "line-opacity": 0.85,
        },
      },
      {
        id: "boundary",
        type: "line",
        source: "openmaptiles",
        "source-layer": "boundary",
        filter: ["<=", ["get", "admin_level"], 4],
        paint: {
          "line-color": palette.boundary,
          "line-width": 0.75,
          "line-dasharray": [2, 2],
        },
      },
      {
        id: "water-label",
        type: "symbol",
        source: "openmaptiles",
        "source-layer": "water_name",
        minzoom: 6,
        layout: {
          "text-field": ["get", "name"],
          "text-font": ["Noto Sans Italic"],
          "text-size": 11,
        },
        paint: { ...textPaint, "text-color": palette.waterLabel },
      },
      {
        id: "place-label",
        type: "symbol",
        source: "openmaptiles",
        "source-layer": "place",
        filter: [
          "in",
          ["get", "class"],
          ["literal", ["city", "town", "village", "country"]],
        ],
        layout: {
          "text-field": ["get", "name"],
          "text-font": ["Noto Sans Regular"],
          "text-size": [
            "match",
            ["get", "class"],
            "country",
            13,
            "city",
            12,
            10,
          ],
        },
        paint: textPaint,
      },
    ],
  };
}
