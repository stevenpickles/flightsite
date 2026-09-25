import type { MapConfig } from "@/features/map/types";

/** Default range ring radii in nautical miles, smallest first. */
export const DEFAULT_RING_RADII_NM: readonly number[] = [
  50, 100, 150, 200, 250,
];

/** Schema default for `display_radius_nm`
 * (`backend/src/flightsite/config/models.py`) — the fallback distance cap
 * used before the server's real config has loaded. */
export const DEFAULT_DISPLAY_RADIUS_NM = 250;

/**
 * Fallback map configuration: a camera position near Seattle, WA, and
 * nothing that claims to be a receiver.
 *
 * The setup wizard (slice 018) wires the real receiver position into
 * `useMapConfigStore` — see `src/features/setup/lib/mapConfigSync.ts`,
 * called from `RootLayout` on every config load and again once the wizard
 * finishes. This constant is what the store initializes with before that
 * first config load resolves, and what the map keeps rendering against if
 * the receiver location has never been configured (`location.latitude` /
 * `location.longitude` are `null` — a valid, if incomplete, config state)
 * — so the Live Map is always exercisable end-to-end, never blank.
 *
 * `receiverConfigured: false` is what keeps that fallback honest (issue
 * R1-05). These coordinates are a place to point the camera, not a claim
 * about where an antenna is, so no receiver marker and no range rings are
 * drawn from them; aircraft, which are positioned by their own reports,
 * render exactly as before. A production build can therefore never draw
 * the placeholder as geography however the config fetch and the style load
 * race each other.
 */
export const DEV_PLACEHOLDER_MAP_CONFIG: MapConfig = {
  receiver: {
    lat: 47.6,
    lon: -122.3,
    label: "Receiver location not configured",
  },
  receiverConfigured: false,
  ringRadiiNm: DEFAULT_RING_RADII_NM,
  unit: "nm",
  displayRadiusNm: DEFAULT_DISPLAY_RADIUS_NM,
};
