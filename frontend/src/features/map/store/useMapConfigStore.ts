import { create } from "zustand";

import { DEV_PLACEHOLDER_MAP_CONFIG } from "@/features/map/mapConfig";
import type { MapConfig } from "@/features/map/types";

export interface MapConfigState {
  config: MapConfig;
  /** Replaces the active map configuration. Called by
   * `applyServerConfigToMapStore` (`src/features/setup/lib/mapConfigSync.ts`)
   * whenever the server's config carries a configured receiver location —
   * from `RootLayout` on every config load, and from the setup wizard's
   * finish step — so the map centers on the real site instead of the
   * `DEV_PLACEHOLDER_MAP_CONFIG` fallback. */
  setConfig: (config: MapConfig) => void;
}

export const useMapConfigStore = create<MapConfigState>((set) => ({
  config: DEV_PLACEHOLDER_MAP_CONFIG,
  setConfig: (config) => {
    set({ config });
  },
}));
