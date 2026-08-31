import { DEFAULT_BASEMAP_ID, isValidBasemapId } from "@/features/map/basemaps";

export const BASEMAP_STORAGE_KEY = "flightsite-map-basemap";

/** Reads the persisted basemap choice. Falls back to the registry default
 * on any error (private browsing, disabled storage) or on an unrecognized
 * stored id (e.g. from a registry entry removed in a later release) —
 * mirrors the guarded pattern in src/lib/theme.ts. */
export function readStoredBasemapId(): string {
  try {
    const stored = window.localStorage.getItem(BASEMAP_STORAGE_KEY);
    return stored !== null && isValidBasemapId(stored)
      ? stored
      : DEFAULT_BASEMAP_ID;
  } catch {
    return DEFAULT_BASEMAP_ID;
  }
}

/** Persists the basemap choice. Silently no-ops if storage is unavailable. */
export function writeStoredBasemapId(id: string): void {
  try {
    window.localStorage.setItem(BASEMAP_STORAGE_KEY, id);
  } catch {
    // Storage unavailable (private browsing, quota, disabled) — selection
    // still applies for this session via in-memory state.
  }
}
