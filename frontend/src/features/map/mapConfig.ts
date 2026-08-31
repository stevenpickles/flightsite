import type { MapConfig } from "@/features/map/types";

/** Default range ring radii in nautical miles, smallest first. */
export const DEFAULT_RING_RADII_NM: readonly number[] = [
  50, 100, 150, 200, 250,
];

/**
 * Development placeholder map configuration (receiver near Seattle, WA).
 *
 * There is no config API to read a real receiver position from yet: that
 * arrives with slice 004 (configuration system) and is exposed to the
 * frontend via slice 010's receiver-info endpoint. Until those land, the
 * Live Map renders against this fixed placeholder so the map, rings, and
 * marker are all exercisable end-to-end. Replacing it is a matter of
 * swapping the `useMapConfigStore` initial value / wiring a fetch — no
 * other map code depends on this constant being real data.
 */
export const DEV_PLACEHOLDER_MAP_CONFIG: MapConfig = {
  receiver: {
    lat: 47.6,
    lon: -122.3,
    label:
      "Development receiver (placeholder — slice 004/010 will supply the real position)",
  },
  ringRadiiNm: DEFAULT_RING_RADII_NM,
  unit: "nm",
};
