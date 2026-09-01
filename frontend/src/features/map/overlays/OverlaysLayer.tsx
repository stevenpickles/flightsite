/**
 * The aviation overlays (airports + airspace), as one thing a page can
 * mount — the same shape `AircraftLayer` gives the live aircraft layer.
 *
 * Rendered as a child of `MapLibreMap`, which is what puts the map instance
 * in context. Renders no DOM of its own: both overlays draw through
 * MapLibre sources/layers these hooks keep fed.
 */

import { useAirportOverlay } from "@/features/map/overlays/useAirportOverlay";
import { useAirspaceOverlay } from "@/features/map/overlays/useAirspaceOverlay";

export function OverlaysLayer() {
  useAirportOverlay();
  useAirspaceOverlay();
  return null;
}
