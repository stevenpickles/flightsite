/**
 * Attaches the user-supplied airspace overlay to the enclosing map and keeps
 * it fed. Same three-effect shape as `useAirportOverlay`, minus the viewport
 * dependency: `GET /api/v1/airspace` always answers with the whole file (or
 * an empty collection), so there is nothing to re-fetch on pan/zoom.
 */

import { useEffect } from "react";
import type { FeatureCollection, Geometry } from "geojson";

import {
  ensureAirspaceLayers,
  setAirspaceFeatures,
  setAirspaceLayersVisible,
} from "@/features/map/overlays/airspaceLayers";
import { useMapInstance } from "@/features/map/MapInstanceContext";
import { useOverlayVisibilityStore } from "@/features/map/store/useOverlayVisibilityStore";
import { useAirspaceQuery } from "@/lib/api/overlays";

export function useAirspaceOverlay(): void {
  const { map, styleEpoch } = useMapInstance();
  const airspaceVisible = useOverlayVisibilityStore((state) => state.airspace);
  const { data } = useAirspaceQuery();

  // 1. Attach after each style load. Synchronous (unlike the airport
  // overlay's icon registration): `ensureAirspaceLayers` creates the source
  // in the same tick, so effect 2 below — which runs after this one on the
  // same commit, since both share the `[map, styleEpoch]` trigger — always
  // finds a source to feed, whether or not `data` has resolved yet.
  useEffect(() => {
    if (!map || styleEpoch === 0) {
      return;
    }
    ensureAirspaceLayers(map);
    setAirspaceLayersVisible(
      map,
      useOverlayVisibilityStore.getState().airspace,
    );
  }, [map, styleEpoch]);

  // 2. Feed: the current query result, applied on every style load and on
  // every later query resolution or refetch.
  useEffect(() => {
    if (!map || styleEpoch === 0) {
      return;
    }
    setAirspaceFeatures(map, data as FeatureCollection<Geometry> | undefined);
  }, [map, styleEpoch, data]);

  // 3. Toggle.
  useEffect(() => {
    if (!map || styleEpoch === 0) {
      return;
    }
    setAirspaceLayersVisible(map, airspaceVisible);
  }, [map, styleEpoch, airspaceVisible]);
}
