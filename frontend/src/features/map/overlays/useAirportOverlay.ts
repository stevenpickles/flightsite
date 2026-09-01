/**
 * Attaches the airport overlay to the enclosing map and keeps it fed.
 *
 * Three concerns, three effects — the same shape `useAircraftLayer` uses:
 *
 * 1. **Attach.** After every style load (`styleEpoch`), register the
 *    size-class glyphs and add the source/layers, then bump `layersReady` —
 *    a local counter, not `styleEpoch` itself, because icon registration is
 *    async and the layers do not exist until it resolves. Effects 2 and 3
 *    key off `layersReady` rather than `styleEpoch` directly so neither can
 *    run ahead of attach and silently no-op against a source that is not
 *    there yet (`setAirportFeatures`/`setAirportLayersVisible` are already
 *    guarded for "no source", but relying on that guard here would mean a
 *    style load that completed *after* the current query resolved never
 *    draws anything until the query changes again).
 * 2. **Feed.** A debounced viewport (`useMapViewport`) drives a bbox-scoped
 *    TanStack Query (`useAirportsQuery`); its data (or nothing, below the
 *    lowest zoom threshold) replaces the source's features.
 * 3. **Toggle.** The visibility store drives the layers' MapLibre
 *    `visibility` layout property directly — no refetch on toggle.
 */

import type { FeatureCollection, Point } from "geojson";
import { useEffect, useState } from "react";

import { minSizeForZoom } from "@/features/map/overlays/airportDensity";
import { registerAirportIcons } from "@/features/map/overlays/airportIcons";
import {
  ensureAirportLayers,
  setAirportFeatures,
  setAirportLayersVisible,
} from "@/features/map/overlays/airportLayers";
import { useMapViewport } from "@/features/map/overlays/useMapViewport";
import { useMapInstance } from "@/features/map/MapInstanceContext";
import { useOverlayVisibilityStore } from "@/features/map/store/useOverlayVisibilityStore";
import { useAirportsQuery } from "@/lib/api/overlays";

export function useAirportOverlay(): void {
  const { map, styleEpoch } = useMapInstance();
  const airportsVisible = useOverlayVisibilityStore((state) => state.airports);
  const viewport = useMapViewport(map);
  // Bumped once the (async) icon registration and layer attach for the
  // current style load have actually completed — see the module docstring.
  const [layersReady, setLayersReady] = useState(0);

  const minSize = viewport ? minSizeForZoom(viewport.zoom) : null;
  const { data } = useAirportsQuery(
    { bbox: viewport?.bbox, minSize: minSize ?? undefined },
    viewport !== null && minSize !== null,
  );

  // 1. Attach after each style load.
  useEffect(() => {
    if (!map || styleEpoch === 0) {
      return undefined;
    }
    let cancelled = false;
    void registerAirportIcons(map)
      .then(() => {
        if (cancelled) {
          return;
        }
        ensureAirportLayers(map);
        setAirportLayersVisible(
          map,
          useOverlayVisibilityStore.getState().airports,
        );
        setLayersReady((count) => count + 1);
      })
      .catch(() => {
        // A glyph that will not decode means no airport layer for this
        // style load — the map degrades to basemap plus whatever other
        // overlays did attach, the same posture `useAircraftLayer` takes.
      });
    return () => {
      cancelled = true;
    };
  }, [map, styleEpoch]);

  // 2. Feed: the latest query result (or nothing, below the lowest zoom
  // threshold) replaces the source's data.
  useEffect(() => {
    if (!map || layersReady === 0) {
      return;
    }
    setAirportFeatures(
      map,
      minSize === null ? undefined : (data as FeatureCollection<Point>),
    );
  }, [map, layersReady, data, minSize]);

  // 3. Toggle.
  useEffect(() => {
    if (!map || layersReady === 0) {
      return;
    }
    setAirportLayersVisible(map, airportsVisible);
  }, [map, layersReady, airportsVisible]);
}
