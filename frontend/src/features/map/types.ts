/** Distance unit for map display. Canonical storage/API unit is always nm
 * (CLAUDE.md); this only controls presentation. Metric mode is a per-user
 * display preference wired fully by the settings page (slice 019). */
export type DistanceUnit = "nm" | "km";

/** A receiver (or, later, any reference) position in decimal degrees. */
export interface ReceiverPosition {
  lat: number;
  lon: number;
  /** Human-readable site label, shown in marker tooltips. */
  label: string;
}

/**
 * Map configuration consumed by the Live Map: receiver position, range
 * rings, and display unit. This is a thin, typed seam — slice 004
 * (configuration system) and slice 010 (live API / receiver info endpoint)
 * are the real sources of this data once they land; until then it is
 * satisfied by `DEV_PLACEHOLDER_MAP_CONFIG` (see mapConfig.ts).
 */
export interface MapConfig {
  receiver: ReceiverPosition;
  /** Range ring radii, in nautical miles, smallest first. */
  ringRadiiNm: readonly number[];
  unit: DistanceUnit;
  /** SPEC §66 default distance cap for the Live Map's aircraft render set
   * (roadmap slice 017) — `FlightSiteConfig.display_radius_nm`. Aircraft
   * beyond it stay in the live store, `/api/v1` responses, and range
   * records; only what the map/filters draw shrinks. An explicit
   * user-chosen max distance (`features/filters`) overrides this default
   * either way, larger or smaller. */
  displayRadiusNm: number;
}
