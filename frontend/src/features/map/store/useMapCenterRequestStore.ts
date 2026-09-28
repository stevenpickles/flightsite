import { create } from "zustand";

/**
 * A request to recentre the map on the receiver (roadmap slice 082's `H`
 * shortcut and its visible `RecenterButton` equivalent) — a monotonic
 * counter rather than a boolean flag, so two requests in a row (two `H`
 * presses, or a press followed by a click) are each their own event even if
 * nothing else about the state changes. `RecenterButton` is the one
 * subscriber: it lives inside `MapLibreMap`'s children, where the live map
 * instance is reachable via `useMapInstance`, which is why the actual
 * `map.easeTo` call is not made here — this store only records *that* a
 * recentre was asked for.
 */
interface MapCenterRequestState {
  nonce: number;
  requestRecenter: () => void;
}

export const useMapCenterRequestStore = create<MapCenterRequestState>(
  (set) => ({
    nonce: 0,
    requestRecenter: () => set((state) => ({ nonce: state.nonce + 1 })),
  }),
);
