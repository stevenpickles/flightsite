/**
 * Wires the server's receiver location into the Live Map, replacing the
 * slice-013 `DEV_PLACEHOLDER_MAP_CONFIG` placeholder wherever a real
 * location is configured. Called from `RootLayout` on every config load
 * (covers a returning user reopening the app) and from the wizard's
 * review/finish step (covers finishing setup in the current session).
 *
 * The derived config also carries `display_radius_nm` (SPEC §66) through as
 * `displayRadiusNm` — the default distance cap `features/filters` applies to
 * the map's render set (roadmap slice 017).
 */
import { DEFAULT_RING_RADII_NM } from "@/features/map/mapConfig";
import { useMapConfigStore } from "@/features/map/store/useMapConfigStore";
import type { MapConfig } from "@/features/map/types";
import type { FlightSiteConfig } from "@/lib/api/config";

/** Derives the Live Map's `MapConfig` from the server's effective config.
 * Returns `null` when no receiver location is configured yet
 * (`LocationSettings` requires both `latitude` and `longitude` together,
 * or neither) — callers should keep whatever fallback is already active. */
export function deriveMapConfig(config: FlightSiteConfig): MapConfig | null {
  const { latitude, longitude, site_name } = config.location;
  if (latitude === null || longitude === null) {
    return null;
  }
  const ringRadiiNm =
    config.map.range_ring_radii_nm.length > 0
      ? config.map.range_ring_radii_nm
      : DEFAULT_RING_RADII_NM;
  const label =
    site_name && site_name.trim().length > 0 ? site_name : "Receiver";

  return {
    receiver: { lat: latitude, lon: longitude, label },
    ringRadiiNm,
    unit: config.units === "metric" ? "km" : "nm",
    displayRadiusNm: config.display_radius_nm,
  };
}

/** Applies the derived map config to `useMapConfigStore`, a no-op when the
 * server config has no receiver location yet. */
export function applyServerConfigToMapStore(config: FlightSiteConfig): void {
  const derived = deriveMapConfig(config);
  if (derived) {
    useMapConfigStore.getState().setConfig(derived);
  }
}
