import { create } from "zustand";

import {
  readStoredOverlayVisibility,
  writeStoredOverlayVisibility,
  type OverlayVisibility,
} from "@/features/map/overlayVisibilityPersistence";

export interface OverlayVisibilityState extends OverlayVisibility {
  setAirportsVisible: (visible: boolean) => void;
  setAirspaceVisible: (visible: boolean) => void;
}

/** Per-browser overlay layer toggles (Airports / Airspace) — mirrors
 * `useBasemapStore`'s shape and persistence discipline exactly. */
export const useOverlayVisibilityStore = create<OverlayVisibilityState>(
  (set, get) => ({
    ...readStoredOverlayVisibility(),

    setAirportsVisible: (visible) => {
      const next: OverlayVisibility = {
        airports: visible,
        airspace: get().airspace,
      };
      writeStoredOverlayVisibility(next);
      set({ airports: visible });
    },

    setAirspaceVisible: (visible) => {
      const next: OverlayVisibility = {
        airports: get().airports,
        airspace: visible,
      };
      writeStoredOverlayVisibility(next);
      set({ airspace: visible });
    },
  }),
);
