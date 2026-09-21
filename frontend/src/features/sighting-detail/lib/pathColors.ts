/**
 * The altitude ramp the sighting path is drawn with — one definition read
 * by both the MapLibre paint expression that colours the line and the
 * legend that keys it (review R2-17).
 *
 * Its own module rather than a constant beside the layer component, so the
 * legend can import it without pulling a component's module in, and so
 * neither surface can restate the ramp from memory and drift from the
 * other. A colour with no key is colour used as the only channel; a key
 * that disagrees with the map is worse than none.
 */

export interface AltitudeStop {
  /** Feet — the canonical unit (`CLAUDE.md`); the legend converts for
   * display, the paint expression interpolates over it directly. */
  ft: number;
  color: string;
}

export const ALTITUDE_RAMP: readonly AltitudeStop[] = [
  { ft: 0, color: "#2ecc71" },
  { ft: 20_000, color: "#f1c40f" },
  { ft: 45_000, color: "#e74c3c" },
];
