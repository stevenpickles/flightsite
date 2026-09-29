import { create } from "zustand";

import {
  readStoredOverlayVisibility,
  writeStoredOverlayVisibility,
  type OverlayVisibility,
} from "@/features/map/overlayVisibilityPersistence";

export interface OverlayVisibilityState extends OverlayVisibility {
  setAirportsVisible: (visible: boolean) => void;
  setAirspaceVisible: (visible: boolean) => void;
  setRangeRingsVisible: (visible: boolean) => void;
  setReceiverVisible: (visible: boolean) => void;
  setLabelsVisible: (visible: boolean) => void;
}

/** The persisted members of `state` — what `writeStoredOverlayVisibility`
 * stores, without the setters. */
function persistedSlice(state: OverlayVisibility): OverlayVisibility {
  return {
    airports: state.airports,
    airspace: state.airspace,
    rangeRings: state.rangeRings,
    receiver: state.receiver,
    labels: state.labels,
  };
}

/** Per-browser Layers card toggles (Airports / Airspace since slice 028;
 * range rings, receiver marker and labels since slice 085) — mirrors
 * `useBasemapStore`'s shape and persistence discipline exactly. Every setter
 * persists the whole record, so each toggle is stored independently and no
 * setter can reset another's choice. */
export const useOverlayVisibilityStore = create<OverlayVisibilityState>(
  (set, get) => {
    const update = (patch: Partial<OverlayVisibility>) => {
      writeStoredOverlayVisibility({ ...persistedSlice(get()), ...patch });
      set(patch);
    };
    return {
      ...readStoredOverlayVisibility(),

      setAirportsVisible: (visible) => {
        update({ airports: visible });
      },
      setAirspaceVisible: (visible) => {
        update({ airspace: visible });
      },
      setRangeRingsVisible: (visible) => {
        update({ rangeRings: visible });
      },
      setReceiverVisible: (visible) => {
        update({ receiver: visible });
      },
      setLabelsVisible: (visible) => {
        update({ labels: visible });
      },
    };
  },
);
