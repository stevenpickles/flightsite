import type { StyleSpecification } from "maplibre-gl";

import { buildAviationStyle } from "@/features/map/basemaps/paletteStyleFactory";

/**
 * Default basemap: a near-black, blue-tinted "dark aviation" theme built on
 * OpenFreeMap's OpenMapTiles vector tiles. Colors are hand-tuned to sit
 * alongside the app's dark theme tokens (see src/index.css `.dark`:
 * --background ≈ oklch(0.145 0.02 250)), so the map reads as part of the
 * instrument panel rather than an embedded third-party widget. Airport
 * runways/taxiways are picked out in the app's teal accent so airfields
 * stay legible under aircraft traffic.
 */
export const darkAviationStyle: StyleSpecification = buildAviationStyle(
  "dark-aviation",
  {
    background: "#0a0e1a",
    water: "#0e1c30",
    waterLabel: "#5b7aa0",
    landcover: "#0f1a16",
    landuseResidential: "#101827",
    boundary: "#3a4a63",
    roadCasing: "#1c2940",
    roadFill: "#31435f",
    roadMinor: "#182338",
    railway: "#243149",
    building: "#131b2c",
    aeroway: "#4dd8cf",
    textPrimary: "#c7d2e3",
    textHalo: "#0a0e1a",
  },
);
