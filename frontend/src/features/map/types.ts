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
  /**
   * Whether {@link receiver} is a *real* position somebody configured, as
   * opposed to a centre to point the camera at before one exists.
   *
   * A map still needs a centre before the receiver location is known, so
   * `receiver` is never null; what this says is whether that centre may be
   * *drawn* as geography. The receiver marker and the range rings assert
   * "the antenna is here, and it reaches this far", and asserting that at
   * `DEV_PLACEHOLDER_MAP_CONFIG`'s Seattle placeholder is how issue R1-05
   * put a receiver 1,400 nm from the actual site on a production install
   * whose config fetch lost a race with the style load. When this is false
   * {@link ensureOverlayLayers} draws neither: an empty picture is the
   * honest one, and the layers are still in place to fill the instant a
   * real location arrives.
   */
  receiverConfigured: boolean;
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
