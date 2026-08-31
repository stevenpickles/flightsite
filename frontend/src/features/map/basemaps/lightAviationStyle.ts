import type { StyleSpecification } from "maplibre-gl";

import { buildAviationStyle } from "@/features/map/basemaps/paletteStyleFactory";

/**
 * Light-theme counterpart to `darkAviationStyle`, built from the same
 * OpenFreeMap vector source and layer set so switching basemaps while
 * toggling the app theme doesn't reshuffle the map's content — only its
 * palette changes. Colors are tuned to sit alongside the light theme
 * tokens in src/index.css (`:root` — background ≈ oklch(0.985 0.003 240)).
 */
export const lightAviationStyle: StyleSpecification = buildAviationStyle(
  "light-aviation",
  {
    background: "#f6f7f9",
    water: "#dbe6f0",
    waterLabel: "#4f6d90",
    landcover: "#e8ede3",
    landuseResidential: "#eef0f3",
    boundary: "#a9b4c4",
    roadCasing: "#c7cdd6",
    roadFill: "#ffffff",
    roadMinor: "#e2e5ea",
    railway: "#b7bfc9",
    building: "#e2e6ec",
    aeroway: "#0f9a91",
    textPrimary: "#26314a",
    textHalo: "#f6f7f9",
  },
);
