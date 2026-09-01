/**
 * Access to the live MapLibre instance from components rendered inside
 * `MapLibreMap`.
 *
 * `MapLibreMap` owns the map and never re-creates it (a new instance on every
 * config change would flash and reset the view), so overlays cannot be
 * expressed as React children of a map component in the usual declarative way —
 * they attach imperatively to an instance that outlives their renders. This
 * context is that seam.
 *
 * `styleEpoch` is the other half of it. `setStyle` — a basemap switch — throws
 * away every custom source, layer, and registered image, so an overlay has to
 * re-attach after each style load. The epoch increments on every `load` and
 * `style.load`, which turns "the style was replaced" into a plain effect
 * dependency instead of every overlay subscribing to map events itself.
 */

import { createContext, useContext } from "react";

import type { Map as MapLibreGlMap } from "maplibre-gl";

export interface MapInstance {
  /** The map, or `null` before the mount effect has constructed it. */
  map: MapLibreGlMap | null;
  /** Increments on every completed style load; `0` until the first one. */
  styleEpoch: number;
}

const EMPTY: MapInstance = { map: null, styleEpoch: 0 };

export const MapInstanceContext = createContext<MapInstance>(EMPTY);

/** The enclosing map instance. Outside a `MapLibreMap` this reports no map,
 * which is the same state as "not mounted yet" — overlays already have to
 * handle that, so it needs no separate error path. */
export function useMapInstance(): MapInstance {
  return useContext(MapInstanceContext);
}
