import { isValidBasemapId } from "@/features/map/basemaps";

export const BASEMAP_STORAGE_KEY = "flightsite-map-basemap";

/**
 * Reads the user's *explicit* basemap choice, or `null` when they have
 * never made one.
 *
 * `null` rather than the registry default is the whole of issue R1-14. With
 * a default substituted here, "the user picked dark aviation" and "the user
 * has picked nothing yet" were the same value, so nothing downstream could
 * tell them apart — and the light theme therefore kept the near-black
 * default basemap under its bright panels forever, with
 * `BasemapDefinition.themeAffinity` sitting unread in the registry. A stored
 * id is a decision to respect; its absence is a decision to make, and
 * `resolveActiveBasemap` makes it from the theme.
 *
 * Falls back to `null` on any error (private browsing, disabled storage) or
 * on an unrecognized stored id (e.g. from a registry entry removed in a
 * later release) — mirrors the guarded pattern in src/lib/theme.ts.
 */
export function readStoredBasemapId(): string | null {
  try {
    const stored = window.localStorage.getItem(BASEMAP_STORAGE_KEY);
    return stored !== null && isValidBasemapId(stored) ? stored : null;
  } catch {
    return null;
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
