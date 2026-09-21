/**
 * Keeps the selected aircraft (`useLiveAircraftStore.selectedIcao`) and the
 * URL's `?selected=<icao>` in sync (R1-09). Mounted once, at `LiveMapPage`,
 * beside `useFilterUrlSync`.
 *
 * "Look at this aircraft" was the one thing on the Live Map with no deep
 * link: selecting from the interesting panel or a map click never touched
 * `page.url()`, so a reload — or sharing the link — lost the selection
 * entirely, even though the filter state already round-tripped perfectly
 * through `useFilterUrlSync`. This hook gives selection the same treatment.
 *
 * Two edges, each one-way, mirroring `useFilterUrlSync`'s own split:
 *
 * - **URL -> store, mount only.** A `?selected=` present at mount selects
 *   that ICAO — restoring a bookmarked or shared link. If the aircraft is
 *   not (yet) in the live set, the selection is still made: the store holds
 *   the intent, `AircraftDetailPanel` opens and reads `null` from
 *   `state.aircraft[selectedIcao]`, rendering "No live data for this
 *   aircraft" until a snapshot or delta actually supplies a record — at
 *   which point the same reactive read picks it up with no extra
 *   bookkeeping here. A URL naming nothing never overwrites a selection
 *   made before this component mounted (see the dispatch note below).
 * - **Store -> URL, on every change, replacing.** Never `push` — a
 *   selection is not a page a user expects Back to step through — so
 *   clicking through several aircraft and then pressing Back leaves the
 *   filtered/selected map in one step, exactly like a filter edit does.
 *
 * **Why the first store->URL write can be skipped, not always.** A
 * `useEffect` that both seeds the store from the URL *and* mirrors the store
 * back to the URL would, on the very first commit, have the second effect
 * see the render's pre-seed value (`selectedIcao` as it was *before* the
 * first effect's `selectAircraft` call takes effect on a later render) and
 * write that — clobbering the very `?selected=` the first effect is about to
 * apply. `skipNextWrite` is set only when the mount effect actually has an
 * update in flight (`icaoFromUrl` differs from what the store already
 * holds), so the one case that must not fire fires. In the other common
 * case — `features/notifications/lib/dispatch.ts`'s notification-click
 * handler already called `selectAircraft` directly before this component
 * mounted (SPEC §48, an alert delivered on another route) — the render's
 * captured `selectedIcao` already *is* the right value, the mount effect
 * finds nothing to seed, and the write is not skipped: the URL picks up the
 * notification's selection on the very same commit that mounts the page.
 */

import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";

import {
  parseSelectedIcaoFromSearchParams,
  withSelectedIcaoInSearchParams,
} from "@/features/filters/lib/selectionUrlSync";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";

export function useSelectionUrlSync(): void {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedIcao = useLiveAircraftStore((state) => state.selectedIcao);
  const selectAircraft = useLiveAircraftStore((state) => state.selectAircraft);
  const skipNextWrite = useRef(false);

  useEffect(() => {
    const icaoFromUrl = parseSelectedIcaoFromSearchParams(searchParams);
    if (
      icaoFromUrl !== null &&
      icaoFromUrl !== useLiveAircraftStore.getState().selectedIcao
    ) {
      skipNextWrite.current = true;
      selectAircraft(icaoFromUrl);
    }
    // Deliberately mount-only — see the module doc comment.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (skipNextWrite.current) {
      skipNextWrite.current = false;
      return;
    }
    setSearchParams(
      (previous) => withSelectedIcaoInSearchParams(previous, selectedIcao),
      { replace: true },
    );
  }, [selectedIcao, setSearchParams]);
}
