/**
 * Persisted per-browser visibility for the map's overlay layers (roadmap
 * slice 028) — Airports and Airspace, alongside the basemap choice
 * (`basemapPersistence.ts`). Same guarded-localStorage shape as that module:
 * falls back to the documented default on any error (private browsing,
 * disabled storage) or a malformed stored value, and never throws.
 */

export const OVERLAY_VISIBILITY_STORAGE_KEY =
  "flightsite-map-overlay-visibility";

export interface OverlayVisibility {
  /** Airport markers (`GET /api/v1/airports`). Defaults ON. */
  airports: boolean;
  /** The user-supplied airspace overlay (`GET /api/v1/airspace`). Defaults
   * ON — an install with no `airspace.geojson` simply renders nothing
   * (`airspaceLayers.ts`'s empty-collection behavior), so "on" costs
   * nothing when there is no data and needs no separate "on if data
   * exists" state to track. */
  airspace: boolean;
}

export const DEFAULT_OVERLAY_VISIBILITY: OverlayVisibility = {
  airports: true,
  airspace: true,
};

function isBoolean(value: unknown): value is boolean {
  return typeof value === "boolean";
}

/** Reads the persisted overlay visibility. Falls back to
 * {@link DEFAULT_OVERLAY_VISIBILITY} — as a whole, or member-by-member for a
 * partially-valid stored value — on any error or malformed content. */
export function readStoredOverlayVisibility(): OverlayVisibility {
  try {
    const stored = window.localStorage.getItem(OVERLAY_VISIBILITY_STORAGE_KEY);
    if (stored === null) {
      return DEFAULT_OVERLAY_VISIBILITY;
    }
    const parsed: unknown = JSON.parse(stored);
    if (typeof parsed !== "object" || parsed === null) {
      return DEFAULT_OVERLAY_VISIBILITY;
    }
    const candidate = parsed as Partial<OverlayVisibility>;
    return {
      airports: isBoolean(candidate.airports)
        ? candidate.airports
        : DEFAULT_OVERLAY_VISIBILITY.airports,
      airspace: isBoolean(candidate.airspace)
        ? candidate.airspace
        : DEFAULT_OVERLAY_VISIBILITY.airspace,
    };
  } catch {
    return DEFAULT_OVERLAY_VISIBILITY;
  }
}

/** Persists the overlay visibility. Silently no-ops if storage is
 * unavailable — selection still applies for this session via in-memory
 * state. */
export function writeStoredOverlayVisibility(
  visibility: OverlayVisibility,
): void {
  try {
    window.localStorage.setItem(
      OVERLAY_VISIBILITY_STORAGE_KEY,
      JSON.stringify(visibility),
    );
  } catch {
    // Storage unavailable (private browsing, quota, disabled).
  }
}
