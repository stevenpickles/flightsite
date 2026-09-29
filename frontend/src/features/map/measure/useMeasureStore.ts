import { create } from "zustand";

import type { LatLon } from "@/features/map/geo/rings";

/**
 * The measure tool's state (roadmap slice 085, issue #228).
 *
 * A store rather than `MeasureControl`'s own state for the same reason the
 * recentre request is one (`useMapCenterRequestStore`): the `M` shortcut is
 * dispatched from `useKeyboardShortcuts` in `AppShell`, far from the control,
 * and `useAircraftLayer`'s selection click handler has to know whether a
 * click belongs to the measure tool instead. Both read `getState()`; only the
 * control subscribes.
 *
 * Deliberately *not* persisted: measuring is a momentary act, and a map that
 * reopened in measure mode would swallow the first aircraft click.
 *
 * The click flow is "click A, click B, click again to start over":
 * {@link MeasureState.addPoint} with two points already placed discards them
 * and makes the new click the next A.
 */
export interface MeasureState {
  active: boolean;
  /** Zero, one (A) or two (A then B) placed points. */
  points: LatLon[];
  /** Turns the tool on (with nothing placed) or off (forgetting the
   * points) — the button's and `M`'s action. */
  toggle: () => void;
  /** Leaves measure mode and forgets the points — Escape's action. */
  exit: () => void;
  /** Places the next point: A, then B, then a fresh A. A no-op while the
   * tool is off, so a stray call can never re-enter measure mode. */
  addPoint: (point: LatLon) => void;
  /** Starts a measurement from the receiver: A is the receiver, and the
   * next click is B. Turns the tool on if it was off. */
  startFrom: (point: LatLon) => void;
}

export const useMeasureStore = create<MeasureState>((set, get) => ({
  active: false,
  points: [],

  toggle: () => {
    set({ active: !get().active, points: [] });
  },

  exit: () => {
    set({ active: false, points: [] });
  },

  addPoint: (point) => {
    const { active, points } = get();
    if (!active) {
      return;
    }
    set({ points: points.length >= 2 ? [point] : [...points, point] });
  },

  startFrom: (point) => {
    set({ active: true, points: [point] });
  },
}));
