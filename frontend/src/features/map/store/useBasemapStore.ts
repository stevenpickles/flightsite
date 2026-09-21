import { create } from "zustand";

import { isValidBasemapId } from "@/features/map/basemaps";
import {
  readStoredBasemapId,
  writeStoredBasemapId,
} from "@/features/map/basemapPersistence";

export interface BasemapState {
  /**
   * The basemap the user explicitly picked, persisted per browser, or `null`
   * if they never have.
   *
   * Deliberately not "the current basemap": what is *rendered* also depends
   * on the theme, and collapsing the two lost the distinction that issue
   * R1-14 needed — a stored `dark-aviation` looked identical to no choice at
   * all, so the light theme could never switch away from it. Read the
   * rendered answer through `useActiveBasemap`; this is only the half of it
   * the user owns.
   */
  explicitBasemapId: string | null;
  setBasemapId: (id: string) => void;
}

export const useBasemapStore = create<BasemapState>((set) => ({
  explicitBasemapId: readStoredBasemapId(),

  setBasemapId: (id) => {
    if (!isValidBasemapId(id)) {
      return;
    }
    writeStoredBasemapId(id);
    set({ explicitBasemapId: id });
  },
}));
