/**
 * Attaches the aircraft layers to the enclosing map and keeps them fed.
 *
 * Three concerns, three effects:
 *
 * 1. **Attach.** After every style load (`styleEpoch`), register the icons and
 *    add the sources and layers, then draw once so the map is never briefly
 *    empty after a basemap switch. Icons are registered *before* the layers
 *    because a symbol layer naming an unregistered image renders nothing and
 *    warns per feature per frame. The Layers card's "Labels" toggle (roadmap
 *    slice 085) is re-applied here too, so it survives a basemap switch.
 * 2. **Feed.** A store subscription draws immediately whenever the picture
 *    changes (~1 Hz), the live filters (`features/filters`) do, or the
 *    Layers card's display choices (label preset, slice 085) do, and an
 *    animation loop draws interpolated frames in between at
 *    {@link FRAME_INTERVAL_MS}.
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
  setAircraftLabelsVisible,
} from "@/features/map/aircraft/aircraftLayers";
import {
  drawAircraftFrame,
  type DrawFrameOptions,
} from "@/features/map/aircraft/frame";
import { registerAircraftIcons } from "@/features/map/aircraft/icons/registerIcons";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { useFilterStore } from "@/features/filters/store/useFilterStore";
import { useMapInstance } from "@/features/map/MapInstanceContext";
import { useMapConfigStore } from "@/features/map/store/useMapConfigStore";
import { useOverlayVisibilityStore } from "@/features/map/store/useOverlayVisibilityStore";

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

/** Everything a frame reads from outside the live store, read fresh at call
 * time — every caller is a callback that runs long after the render that
 * registered it. */
function currentFrameOptions(): DrawFrameOptions {
  return {
    filters: useFilterStore.getState().filters,
    displayRadiusNm: useMapConfigStore.getState().config.displayRadiusNm,
    units: useLiveAircraftStore.getState().receiver?.units,
    labelPreset: useOverlayVisibilityStore.getState().labelPreset,
    trailsEnabled: useOverlayVisibilityStore.getState().trails,
  };
}

export function useAircraftLayer(): void {
  const { map, styleEpoch } = useMapInstance();
  const labelsVisible = useOverlayVisibilityStore((state) => state.labels);

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
        setAircraftLabelsVisible(
          map,
          useOverlayVisibilityStore.getState().labels,
        );
        drawAircraftFrame(map, useLiveAircraftStore.getState(), Date.now(), {
          ...currentFrameOptions(),
          includeTrack: true,
          includeTrails: true,
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

    const draw = (
      now: number,
      rebuild: Pick<DrawFrameOptions, "includeTrack" | "includeTrails">,
    ) => {
      lastDrawnAt = now;
      drawAircraftFrame(map, useLiveAircraftStore.getState(), now, {
        ...currentFrameOptions(),
        ...rebuild,
      });
    };

    // A store change is real new data, so it is drawn without waiting for the
    // throttle — the throttle exists to cap *interpolation*, not to delay the
    // picture the server just sent. The track is rebuilt here and only here;
    // the trails (roadmap slice 085) here and on the two redraws below.
    const unsubscribe = useLiveAircraftStore.subscribe(() => {
      draw(Date.now(), { includeTrack: true, includeTrails: true });
    });
    // A filter edit changes what the *same* live picture should draw, so it
    // gets the same immediate, un-throttled redraw as new data rather than
    // waiting up to `FRAME_INTERVAL_MS` for the interpolation tick to pick
    // it up — the map, the drawer's counts, and the non-positioned panel
    // (all reading `getFilteredLiveAircraft` through the same memo) settle
    // on the new set together. The track is unaffected by filters, so this
    // never rebuilds it; the trails follow the filtered set, so it does
    // rebuild those.
    const unsubscribeFilters = useFilterStore.subscribe(() => {
      draw(Date.now(), { includeTrails: true });
    });
    // The Layers card's label preset and trails toggle (roadmap slice 085)
    // change what this layer draws, so they redraw at once for the same
    // reason a filter edit does. The other members of that store are layer
    // visibility flips that need no redraw at all; redrawing for them anyway
    // costs one frame per click, which is not worth a selector to avoid.
    const unsubscribeDisplay = useOverlayVisibilityStore.subscribe(() => {
      draw(Date.now(), { includeTrails: true });
    });

    const canAnimate = typeof requestAnimationFrame === "function";
    const tick = () => {
      const now = Date.now();
      if (now - lastDrawnAt >= FRAME_INTERVAL_MS) {
        draw(now, {});
      }
      frame = requestAnimationFrame(tick);
    };
    if (canAnimate) {
      frame = requestAnimationFrame(tick);
    }

    return () => {
      unsubscribe();
      unsubscribeFilters();
      unsubscribeDisplay();
      if (canAnimate) {
        cancelAnimationFrame(frame);
      }
    };
  }, [map, styleEpoch]);

  // The Layers card's "Labels" toggle (roadmap slice 085). A no-op until the
  // attach above has added the label layer — which then applies the stored
  // choice itself, so neither ordering of the two effects loses it.
  useEffect(() => {
    if (!map || styleEpoch === 0) {
      return;
    }
    setAircraftLabelsVisible(map, labelsVisible);
  }, [map, styleEpoch, labelsVisible]);

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
