/**
 * Applies the Layers card's range-ring and receiver-marker toggles (roadmap
 * slice 085, issue #228) to the enclosing map.
 *
 * The rings and the marker are not this hook's layers: `MapLibreMap` adds
 * them itself (`overlayLayers.ts`'s `ensureOverlayLayers`) on every style
 * load, *before* it bumps `styleEpoch`, so by the time an effect keyed on
 * `styleEpoch` runs they are on the style. That is the whole of how the
 * toggles survive a basemap switch — the same way Airports and Airspace do
 * (`useAirspaceOverlay`'s attach effect): `setStyle` discards the layers and
 * the visibility they carried, `ensureOverlayLayers` re-adds them visible,
 * `styleEpoch` moves, and this effect re-applies the stored choice.
 *
 * A toggle is a `visibility` layout flip, never a source edit, so the
 * config-driven refresh `MapLibreMap` runs on a receiver move (which only
 * `setData`s the existing sources) cannot undo it.
 */

import { useEffect } from "react";

import { useMapInstance } from "@/features/map/MapInstanceContext";
import {
  setRangeRingLayersVisible,
  setReceiverLayersVisible,
} from "@/features/map/overlayLayers";
import { useOverlayVisibilityStore } from "@/features/map/store/useOverlayVisibilityStore";

export function useDisplayLayerVisibility(): void {
  const { map, styleEpoch } = useMapInstance();
  const rangeRings = useOverlayVisibilityStore((state) => state.rangeRings);
  const receiver = useOverlayVisibilityStore((state) => state.receiver);

  useEffect(() => {
    if (!map || styleEpoch === 0) {
      return;
    }
    setRangeRingLayersVisible(map, rangeRings);
  }, [map, styleEpoch, rangeRings]);

  useEffect(() => {
    if (!map || styleEpoch === 0) {
      return;
    }
    setReceiverLayersVisible(map, receiver);
  }, [map, styleEpoch, receiver]);
}
