/**
 * The aviation overlays (airports + airspace), as one thing a page can
 * mount — the same shape `AircraftLayer` gives the live aircraft layer —
 * plus, since roadmap slice 085, the Layers card's range-ring and
 * receiver-marker toggles, applied to the layers `MapLibreMap` itself adds.
 *
 * Rendered as a child of `MapLibreMap`, which is what puts the map instance
 * in context. Renders no DOM of its own: the overlays draw through
 * MapLibre sources/layers these hooks keep fed.
 */

import { useAirportOverlay } from "@/features/map/overlays/useAirportOverlay";
import { useAirspaceOverlay } from "@/features/map/overlays/useAirspaceOverlay";
import { useDisplayLayerVisibility } from "@/features/map/overlays/useDisplayLayerVisibility";

export function OverlaysLayer() {
  useAirportOverlay();
  useAirspaceOverlay();
  useDisplayLayerVisibility();
  return null;
}
