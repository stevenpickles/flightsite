/**
 * The live aircraft layer, as one thing a page can mount.
 *
 * Rendered as a child of `MapLibreMap`, which is what puts the map instance in
 * context and what positions the status chip over the canvas. It renders almost
 * nothing itself: the aircraft are drawn by MapLibre from sources these hooks
 * keep fed, and the only DOM is the connection chip.
 *
 * `useTrackBackfill` is the one hook here that reads the *history* API rather
 * than the live socket, so it needs a `QueryClientProvider` above this
 * component (every route already has one). It fetches only while an aircraft is
 * selected, and only the selected aircraft's open sighting.
 */

import { ConnectionStatusChip } from "@/features/map/aircraft/ConnectionStatusChip";
import { useAircraftLayer } from "@/features/map/aircraft/useAircraftLayer";
import { useLiveConnection } from "@/features/map/aircraft/useLiveConnection";
import { useTrackBackfill } from "@/features/map/aircraft/useTrackBackfill";

export function AircraftLayer() {
  useLiveConnection();
  useAircraftLayer();
  useTrackBackfill();
  return <ConnectionStatusChip />;
}
