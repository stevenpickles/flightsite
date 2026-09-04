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
 *
 * **It no longer owns the connection.** The socket moved to
 * `components/shell/AppShell` in ADR-0015 so that alerts reach every route
 * (issue #105); `ConnectionStatusChip` reads the same store field it always
 * did, now kept current by the shell. What is still the map's, and is torn
 * down here, is the map's own session state:
 *
 * - **The selection**, and with it the track and the backfill bookkeeping that
 *   hang off it (`selectAircraft(null)` clears all three). Leaving the map is
 *   leaving the thing that lets a user select anything, so a selection must
 *   not outlive it — and this is also the live store's memory bound on a
 *   non-map route, since it accumulates track points only for a selected
 *   aircraft.
 * - **The label-density latch** (issue #143), which is memory about the frames
 *   this layer drew. It would clear itself on the next drawn frame anyway — an
 *   empty picture is a count of zero — but a remount should not have to spend
 *   a frame in the old picture's tier to get there.
 *
 * Nothing else: the live picture belongs to the socket, which is still running.
 */

import { useEffect } from "react";

import { ConnectionStatusChip } from "@/features/map/aircraft/ConnectionStatusChip";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { useAircraftLayer } from "@/features/map/aircraft/useAircraftLayer";
import { useTrackBackfill } from "@/features/map/aircraft/useTrackBackfill";
import { resetDensityLatch } from "@/features/map/labels/densityLatch";

export function AircraftLayer() {
  useAircraftLayer();
  useTrackBackfill();

  useEffect(
    () => () => {
      useLiveAircraftStore.getState().selectAircraft(null);
      resetDensityLatch();
    },
    [],
  );

  return <ConnectionStatusChip />;
}
