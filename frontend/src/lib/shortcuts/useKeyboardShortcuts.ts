/**
 * The app-wide keyboard shortcut dispatcher (roadmap slice 082, issue #225,
 * SPEC §80). One `window` "keydown" listener for the whole session — mounted
 * once in `AppShell` alongside the live socket it already owns for the same
 * "works from any route" reason (ADR-0015) — rather than one listener per
 * binding or per page. That matters for one specific case: a `g`-sequence in
 * flight (`g` then `l`, meaning "go to Alerts") must not also be seen by a
 * Live-Map-only `l` binding ("toggle the Layers card") as an independent
 * keypress. Two separate listeners on the same `window` target cannot
 * reliably arbitrate that — whichever happens to run first would act on the
 * keystroke before the other even knows a sequence is in progress — so this
 * hook owns every binding itself and checks the `g`-sequence state before
 * anything else.
 *
 * Suspended entirely while focus is in a form control or a
 * `contenteditable` region ({@link isTypingTarget}), and while any of
 * Ctrl/Meta/Alt is held. Shift is deliberately *not* in that list: `?` is
 * itself a shifted key on most layouts, and `event.key` already reports the
 * shifted character, so nothing here needs to special-case it.
 *
 * The Live-Map-only bindings (`/`, `L`, `F`, `H`, `[`, `]`, and since
 * roadmap slice 085 `M` and `T`) act only on the Live Map route (`/`) and
 * only reach into whatever `FilterDrawer` and `LayersControl` currently
 * have registered via `mapShortcutTargets`, or into the Live Map's own
 * stores (`H` recentres, `M` toggles the measure tool, `T` toggles
 * trails) — on every other route they are simply never dispatched. `M` and
 * `T` go straight to their stores, like `H`, because both are persisted or
 * shared state the map reads rather than a component's local flag. A bare
 * `m` never collides with the `g`-sequence's `g` then `m` ("go to the Live
 * Map"): a pending `g` is resolved above, before any single-key binding is
 * consulted. `Esc` is deliberately
 * not handled here: `AircraftDetailPanel` already owns it (existing
 * behaviour, unchanged by this slice); it appears in `registry.ts` and the
 * `?` sheet as documentation of what is bound, not as a second
 * implementation of it.
 */
import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { getFilteredLiveAircraft } from "@/features/filters/lib/filteredLiveAircraftCache";
import { useFilterStore } from "@/features/filters/store/useFilterStore";
import { orderInterestingAircraft } from "@/features/interesting/lib/ordering";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { useMeasureStore } from "@/features/map/measure/useMeasureStore";
import { useMapCenterRequestStore } from "@/features/map/store/useMapCenterRequestStore";
import { useMapConfigStore } from "@/features/map/store/useMapConfigStore";
import { useOverlayVisibilityStore } from "@/features/map/store/useOverlayVisibilityStore";
import { isTypingTarget } from "@/lib/shortcuts/isTypingTarget";
import { getMapShortcutTargets } from "@/lib/shortcuts/mapShortcutTargets";
import { NAVIGATION_LETTERS } from "@/lib/shortcuts/registry";
import { useShortcutSheetStore } from "@/lib/shortcuts/useShortcutSheetStore";

const LIVE_MAP_PATH = "/";

/** How long a leading `g` stays "pending" waiting for its second key —
 * generous enough for a deliberate two-key sequence, short enough that an
 * unrelated `g` typed moments later (outside a text field, e.g. nothing —
 * there is nothing else bound to a bare `g`) never lingers as state. */
const G_SEQUENCE_TIMEOUT_MS = 1500;

function isModifiedKey(event: KeyboardEvent): boolean {
  return event.ctrlKey || event.metaKey || event.altKey;
}

/**
 * Moves the Live Map selection to the previous/next interesting aircraft,
 * in the exact order `InterestingPanel` renders them: the same filtered live
 * set (`getFilteredLiveAircraft`) run through the same comparison
 * (`orderInterestingAircraft`), read imperatively here rather than through
 * the hooks the panel itself uses, since a `window` keydown handler runs
 * outside any component's render.
 */
function stepInterestingSelection(direction: 1 | -1): void {
  const liveState = useLiveAircraftStore.getState();
  const { aircraft } = getFilteredLiveAircraft(
    liveState.aircraft,
    useFilterStore.getState().filters,
    { displayRadiusNm: useMapConfigStore.getState().config.displayRadiusNm },
  );
  const rows = orderInterestingAircraft(aircraft);
  if (rows.length === 0) {
    return;
  }
  const currentIndex = rows.findIndex(
    (row) => row.aircraft.icao === liveState.selectedIcao,
  );
  const nextIndex =
    currentIndex === -1
      ? 0
      : (currentIndex + direction + rows.length) % rows.length;
  const next = rows[nextIndex];
  if (next) {
    liveState.selectAircraft(next.aircraft.icao);
  }
}

export function useKeyboardShortcuts(): void {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const toggleSheet = useShortcutSheetStore((state) => state.toggle);
  const pendingGRef = useRef(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  // Read inside the listener without re-subscribing it on every navigation.
  const pathnameRef = useRef(pathname);
  useEffect(() => {
    pathnameRef.current = pathname;
  }, [pathname]);

  useEffect(() => {
    function clearPendingG() {
      pendingGRef.current = false;
      if (timeoutRef.current !== undefined) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = undefined;
      }
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (isModifiedKey(event) || isTypingTarget(event.target)) {
        return;
      }

      if (pendingGRef.current) {
        clearPendingG();
        const path = NAVIGATION_LETTERS[event.key.toLowerCase()];
        if (path !== undefined) {
          event.preventDefault();
          navigate(path);
        }
        return;
      }

      if (event.key === "?") {
        event.preventDefault();
        toggleSheet();
        return;
      }

      if (event.key.toLowerCase() === "g") {
        pendingGRef.current = true;
        timeoutRef.current = setTimeout(clearPendingG, G_SEQUENCE_TIMEOUT_MS);
        return;
      }

      if (pathnameRef.current !== LIVE_MAP_PATH) {
        return;
      }

      if (event.key === "/") {
        event.preventDefault();
        getMapShortcutTargets().focusLiveSearch?.();
        return;
      }
      if (event.key === "[") {
        event.preventDefault();
        stepInterestingSelection(-1);
        return;
      }
      if (event.key === "]") {
        event.preventDefault();
        stepInterestingSelection(1);
        return;
      }

      switch (event.key.toLowerCase()) {
        case "l":
          event.preventDefault();
          getMapShortcutTargets().toggleLayersCard?.();
          break;
        case "f":
          event.preventDefault();
          getMapShortcutTargets().toggleFilterDrawer?.();
          break;
        case "h":
          event.preventDefault();
          useMapCenterRequestStore.getState().requestRecenter();
          break;
        case "m":
          event.preventDefault();
          useMeasureStore.getState().toggle();
          break;
        case "t":
          event.preventDefault();
          useOverlayVisibilityStore.getState().toggleTrails();
          break;
        default:
          break;
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      clearPendingG();
    };
  }, [navigate, toggleSheet]);
}
