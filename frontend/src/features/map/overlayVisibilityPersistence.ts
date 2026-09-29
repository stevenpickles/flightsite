/**
 * Persisted per-browser visibility for the map's overlay layers (roadmap
 * slice 028) — Airports and Airspace, alongside the basemap choice
 * (`basemapPersistence.ts`) — and, since roadmap slice 085 (issue #228), the
 * rest of the Layers card's display controls: the range rings, the receiver
 * marker and the aircraft labels.
 *
 * Same guarded-localStorage shape as that module: falls back to the
 * documented default on any error (private browsing, disabled storage) or a
 * malformed stored value, and never throws. Every member falls back on its
 * own, so a value stored before a member existed — every browser that used
 * the Layers card before slice 085 — keeps the choices it made and picks up
 * the new members' defaults.
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
  /** The receiver's range rings and their distance labels (SPEC §33).
   * Defaults ON — the map as it has always been drawn. */
  rangeRings: boolean;
  /** The receiver marker (dot and halo). Defaults ON. */
  receiver: boolean;
  /** Aircraft labels (SPEC §35). Defaults ON. Hides every *unselected*
   * aircraft's label; the selected aircraft keeps its own, since selecting
   * an aircraft is an explicit request to read it (slice 015's "selected
   * aircraft always fully labeled"). */
  labels: boolean;
}

export const DEFAULT_OVERLAY_VISIBILITY: OverlayVisibility = {
  airports: true,
  airspace: true,
  rangeRings: true,
  receiver: true,
  labels: true,
};

function booleanOr(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
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
    const candidate = parsed as Partial<
      Record<keyof OverlayVisibility, unknown>
    >;
    const fallback = DEFAULT_OVERLAY_VISIBILITY;
    return {
      airports: booleanOr(candidate.airports, fallback.airports),
      airspace: booleanOr(candidate.airspace, fallback.airspace),
      rangeRings: booleanOr(candidate.rangeRings, fallback.rangeRings),
      receiver: booleanOr(candidate.receiver, fallback.receiver),
      labels: booleanOr(candidate.labels, fallback.labels),
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
