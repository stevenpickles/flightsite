import type { MapConfig } from "@/features/map/types";

/** Default range ring radii in nautical miles, smallest first. */
export const DEFAULT_RING_RADII_NM: readonly number[] = [
  50, 100, 150, 200, 250,
];

/**
 * Fallback map configuration (receiver near Seattle, WA).
 *
 * The setup wizard (slice 018) now wires the real receiver position into
 * `useMapConfigStore` — see `src/features/setup/lib/mapConfigSync.ts`,
 * called from `RootLayout` on every config load and again once the wizard
 * finishes. This constant is what the store initializes with before that
 * first config load resolves, and what the map keeps rendering against if
 * the receiver location has never been configured (`location.latitude` /
 * `location.longitude` are `null` — a valid, if incomplete, config state)
 * — so the Live Map is always exercisable end-to-end, never blank.
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
