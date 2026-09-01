/**
 * Zoom-density thresholds for the airport overlay (roadmap slice 028): which
 * size classes are worth fetching and drawing at a given zoom level, so a
 * wide, zoomed-out view is not a wall of heliport markers and a close-in
 * view still shows every field. Pure functions, so the thresholds are
 * testable without a map instance.
 */

import type { AirportSizeClass } from "@/lib/api/overlays";

/** Zoom level at which each size class starts appearing — both fetched
 * (`minSizeForZoom`) and drawn (each symbol layer's MapLibre `minzoom`,
 * `airportLayers.ts`). Large fields are useful reference points even
 * zoomed far out; heliports only make sense once a viewport is close
 * enough that dozens of them would not be noise. */
export const AIRPORT_MIN_ZOOM: Readonly<Record<AirportSizeClass, number>> = {
  large: 6,
  medium: 8,
  small: 10,
  heliport: 11,
};

/** Size classes, largest first — the same order the backend's cap sorts by
 * (`flightsite.airports.overlay.SIZE_PRIORITY`). */
export const AIRPORT_SIZE_CLASSES_LARGEST_FIRST: readonly AirportSizeClass[] = [
  "large",
  "medium",
  "small",
  "heliport",
];

/**
 * The `min_size` query value to request at `zoom`, or `null` below the
 * lowest threshold — nothing to show at that zoom, so nothing to fetch.
 *
 * `min_size` is inclusive-of-larger (`"medium"` returns large *and* medium
 * airports), so the right value at a given zoom is the *smallest* class
 * whose own threshold the zoom has already reached.
 */
export function minSizeForZoom(zoom: number): AirportSizeClass | null {
  let result: AirportSizeClass | null = null;
  for (const sizeClass of AIRPORT_SIZE_CLASSES_LARGEST_FIRST) {
    if (zoom >= AIRPORT_MIN_ZOOM[sizeClass]) {
      result = sizeClass;
    }
  }
  return result;
}
