/**
 * The live aircraft layer, as one thing a page can mount.
 *
 * Rendered as a child of `MapLibreMap`, which is what puts the map instance in
 * context and what positions the status chip over the canvas. It renders almost
 * nothing itself: the aircraft are drawn by MapLibre from sources these hooks
 * keep fed, and the only DOM is the connection chip.
 */

import { ConnectionStatusChip } from "@/features/map/aircraft/ConnectionStatusChip";
import { useAircraftLayer } from "@/features/map/aircraft/useAircraftLayer";
import { useLiveConnection } from "@/features/map/aircraft/useLiveConnection";

export function AircraftLayer() {
  useLiveConnection();
  useAircraftLayer();
  return <ConnectionStatusChip />;
}
