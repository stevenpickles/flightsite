import { create } from "zustand";

import type { LabelPreset } from "@/features/map/labels/labelContent";
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
  setTrailsVisible: (visible: boolean) => void;
  /** Flips trails — the `T` keyboard shortcut's action (roadmap slice 085). */
  toggleTrails: () => void;
  setLabelPreset: (preset: LabelPreset) => void;
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
    trails: state.trails,
    labelPreset: state.labelPreset,
  };
}

/** Per-browser Layers card toggles (Airports / Airspace since slice 028;
 * range rings, receiver marker, labels, trails and the label preset since
 * slice 085) — mirrors `useBasemapStore`'s shape and persistence discipline
 * exactly. Every setter persists the whole record, so each choice is stored
 * independently and no setter can reset another's. */
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
      setTrailsVisible: (visible) => {
        update({ trails: visible });
      },
      toggleTrails: () => {
        update({ trails: !get().trails });
      },
      setLabelPreset: (preset) => {
        update({ labelPreset: preset });
      },
    };
  },
);
