/**
 * Attaches the aircraft layers to the enclosing map and keeps them fed.
 *
 * Three concerns, three effects:
 *
 * 1. **Attach.** After every style load (`styleEpoch`), register the icons and
 *    add the sources and layers, then draw once so the map is never briefly
 *    empty after a basemap switch. Icons are registered *before* the layers
 *    because a symbol layer naming an unregistered image renders nothing and
 *    warns per feature per frame.
 * 2. **Feed.** A store subscription draws immediately whenever the picture
 *    changes (~1 Hz), and an animation loop draws interpolated frames in
 *    between at {@link FRAME_INTERVAL_MS}.
 * 3. **Select.** One map click handler resolves the aircraft under the cursor,
 *    or clears the selection when the click hit nothing.
 *
 * None of this re-renders React. The store is read through `getState()` and
 * written to MapLibre directly, because a component that re-rendered at the
 * frame rate for 500 aircraft would cost far more than the drawing does.
 */

import type { MapMouseEvent } from "maplibre-gl";
import { useEffect } from "react";

import {
  aircraftIcaoAtPoint,
  ensureAircraftLayers,
} from "@/features/map/aircraft/aircraftLayers";
import { drawAircraftFrame } from "@/features/map/aircraft/frame";
import { registerAircraftIcons } from "@/features/map/aircraft/icons/registerIcons";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { useMapInstance } from "@/features/map/MapInstanceContext";

/**
 * Minimum gap between interpolation frames — ~12.5 fps.
 *
 * Deliberately *not* every animation frame. Each redraw re-serializes the whole
 * feature collection and hands it to MapLibre's worker for re-parsing and
 * re-tiling; at 500 aircraft that is the dominant cost of the layer, and paying
 * it 60 times a second would starve the render loop on exactly the Pi-class
 * client this has to stay usable on. Twelve updates a second is already past
 * the point where motion reads as continuous, because MapLibre keeps painting
 * at the display's rate — only the *positions* step at 80 ms, and 80 ms of a
 * 450 kt airliner is about a tenth of the icon's own width.
 */
export const FRAME_INTERVAL_MS = 80;

export function useAircraftLayer(): void {
  const { map, styleEpoch } = useMapInstance();

  // 1. Attach after each style load.
  useEffect(() => {
    if (!map || styleEpoch === 0) {
      return undefined;
    }
    let cancelled = false;
    void registerAircraftIcons(map)
      .then(() => {
        if (cancelled) {
          return;
        }
        ensureAircraftLayers(map);
        drawAircraftFrame(map, useLiveAircraftStore.getState(), Date.now(), {
          includeTrack: true,
        });
      })
      .catch(() => {
        // An icon that will not decode means no aircraft layer for this style
        // load. Adding the layers anyway would leave MapLibre warning once per
        // feature per frame about a missing image and draw nothing useful, so
        // the map degrades to basemap plus rings — the same degraded state a
        // tile outage produces, and still usable.
      });
    return () => {
      cancelled = true;
    };
  }, [map, styleEpoch]);

  // 2. Feed: store-driven redraws plus the interpolation loop.
  useEffect(() => {
    if (!map || styleEpoch === 0) {
      return undefined;
    }
    let frame = 0;
    let lastDrawnAt = 0;

    const draw = (now: number, includeTrack: boolean) => {
      lastDrawnAt = now;
      drawAircraftFrame(map, useLiveAircraftStore.getState(), now, {
        includeTrack,
      });
    };

    // A store change is real new data, so it is drawn without waiting for the
    // throttle — the throttle exists to cap *interpolation*, not to delay the
    // picture the server just sent. The track is rebuilt here and only here.
    const unsubscribe = useLiveAircraftStore.subscribe(() => {
      draw(Date.now(), true);
    });

    const canAnimate = typeof requestAnimationFrame === "function";
    const tick = () => {
      const now = Date.now();
      if (now - lastDrawnAt >= FRAME_INTERVAL_MS) {
        draw(now, false);
      }
      frame = requestAnimationFrame(tick);
    };
    if (canAnimate) {
      frame = requestAnimationFrame(tick);
    }

    return () => {
      unsubscribe();
      if (canAnimate) {
        cancelAnimationFrame(frame);
      }
    };
  }, [map, styleEpoch]);

  // 3. Selection.
  useEffect(() => {
    if (!map) {
      return undefined;
    }
    const handleClick = (event: MapMouseEvent) => {
      useLiveAircraftStore
        .getState()
        .selectAircraft(aircraftIcaoAtPoint(map, event.point));
    };
    map.on("click", handleClick);
    return () => {
      map.off("click", handleClick);
    };
  }, [map]);
}
