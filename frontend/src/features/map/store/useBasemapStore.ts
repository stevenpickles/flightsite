import { create } from "zustand";

import { isValidBasemapId } from "@/features/map/basemaps";
import {
  readStoredBasemapId,
  writeStoredBasemapId,
} from "@/features/map/basemapPersistence";

export interface BasemapState {
  /** Currently selected basemap id, persisted per browser. */
  basemapId: string;
  setBasemapId: (id: string) => void;
}

export const useBasemapStore = create<BasemapState>((set) => ({
  basemapId: readStoredBasemapId(),

  setBasemapId: (id) => {
    if (!isValidBasemapId(id)) {
      return;
    }
    writeStoredBasemapId(id);
    set({ basemapId: id });
  },
}));
