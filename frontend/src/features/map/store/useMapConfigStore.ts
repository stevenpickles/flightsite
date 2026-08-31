import { create } from "zustand";

import { DEV_PLACEHOLDER_MAP_CONFIG } from "@/features/map/mapConfig";
import type { MapConfig } from "@/features/map/types";

export interface MapConfigState {
  config: MapConfig;
  /** Replaces the active map configuration. This is the seam slice 004/010
   * wiring will call once the real receiver position and configured
   * ring/display-radius settings are available from the backend. */
  setConfig: (config: MapConfig) => void;
}

export const useMapConfigStore = create<MapConfigState>((set) => ({
  config: DEV_PLACEHOLDER_MAP_CONFIG,
  setConfig: (config) => {
    set({ config });
  },
}));
