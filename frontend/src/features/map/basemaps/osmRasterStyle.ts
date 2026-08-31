import type { StyleSpecification } from "maplibre-gl";

/**
 * Universal raster fallback: OpenStreetMap's standard tile layer
 * (tile.openstreetmap.org), served directly by the OSM Foundation with no
 * API key.
 *
 * OSMF tile usage policy (operations.osmfoundation.org/policies/tiles/):
 * this is the *standard* tile layer, intended for light/moderate use with
 * clear attribution and a valid HTTP User-Agent (browsers supply one
 * automatically); heavy or bulk automated use is disallowed, and the
 * policy asks bigger deployments to run their own tile server. FlightSite
 * ships this as a manually-selected fallback option — not the default
 * (see docs/adr/0011-default-basemap-provider.md) — which keeps typical
 * per-install traffic well inside "light use."
 */
export const OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
export const OSM_ATTRIBUTION =
  '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors';

export const osmRasterStyle: StyleSpecification = {
  version: 8,
  name: "flightsite-osm-raster",
  sources: {
    osm: {
      type: "raster",
      tiles: [OSM_TILE_URL],
      tileSize: 256,
      maxzoom: 19,
      attribution: OSM_ATTRIBUTION,
    },
  },
  layers: [
    // Dark fallback background so the frame around/behind raster tiles
    // (before load, and at zoom levels beyond maxzoom) stays consistent
    // with the app's instrument-panel look rather than flashing white.
    {
      id: "background",
      type: "background",
      paint: { "background-color": "#0a0e1a" },
    },
    { id: "osm-raster", type: "raster", source: "osm" },
  ],
};
