/**
 * Tracks the map's viewport (bbox + zoom) for the overlay hooks
 * (`useAirportOverlay.ts`), debounced so a drag or a zoom gesture fires one
 * fetch after the gesture settles rather than one per intermediate frame.
 */

import type { Map as MapLibreGlMap } from "maplibre-gl";
import { useEffect, useState } from "react";

export interface MapViewport {
  /** `west,south,east,north` — exactly the `bbox` query param's format. */
  bbox: string;
  zoom: number;
}

/** Idle time after the last `move` event before the viewport is reported. */
export const VIEWPORT_DEBOUNCE_MS = 300;

function readViewport(map: MapLibreGlMap): MapViewport {
  const bounds = map.getBounds();
  const bbox = [
    bounds.getWest(),
    bounds.getSouth(),
    bounds.getEast(),
    bounds.getNorth(),
  ].join(",");
  return { bbox, zoom: map.getZoom() };
}

/** The current viewport, or `null` before `map` exists. Reports immediately
 * on mount (so the first fetch is not delayed by the debounce) and then
 * again `VIEWPORT_DEBOUNCE_MS` after the last `move` event. */
export function useMapViewport(map: MapLibreGlMap | null): MapViewport | null {
  const [viewport, setViewport] = useState<MapViewport | null>(null);

  useEffect(() => {
    if (!map) {
      return undefined;
    }
    // Reports the viewport the map already has as soon as it exists, rather
    // than waiting for a first `move` event that may never come (a receiver
    // whose view nobody pans still needs its initial airports fetched).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setViewport(readViewport(map));

    let timer: ReturnType<typeof setTimeout> | undefined;
    const scheduleUpdate = () => {
      if (timer !== undefined) {
        clearTimeout(timer);
      }
      timer = setTimeout(() => {
        setViewport(readViewport(map));
      }, VIEWPORT_DEBOUNCE_MS);
    };

    map.on("move", scheduleUpdate);
    return () => {
      if (timer !== undefined) {
        clearTimeout(timer);
      }
      map.off("move", scheduleUpdate);
    };
  }, [map]);

  return viewport;
}
