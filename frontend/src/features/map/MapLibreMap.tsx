import { AttributionControl, Map as MapLibreGlMap } from "maplibre-gl";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import "maplibre-gl/dist/maplibre-gl.css";

import type { BasemapDefinition } from "@/features/map/basemaps";
import { MapInstanceContext } from "@/features/map/MapInstanceContext";
import { ensureOverlayLayers } from "@/features/map/overlayLayers";
import type { MapConfig } from "@/features/map/types";
import { cn } from "@/lib/utils";

export interface MapLibreMapProps {
  config: MapConfig;
  basemap: BasemapDefinition;
  className?: string;
  /** When provided, clicking the map reports the clicked position — used
   * by the setup wizard's location step for click-to-place. Read via a
   * ref internally so passing a new function each render never tears
   * down and recreates the map (see the mount effect's `[]` deps). */
  onMapClick?: (position: { lat: number; lon: number }) => void;
  /** Overlays that attach to the map imperatively (the aircraft layer) and
   * chrome positioned over it. Rendered inside the map's relative wrapper
   * and given the instance through `MapInstanceContext`. */
  children?: ReactNode;
}

/** Zoom level that keeps a receiver's full 250 nm default display radius
 * comfortably in view on first render. */
const INITIAL_ZOOM = 6;

/**
 * Owns the MapLibre GL instance for the Live Map: basemap style, an
 * always-visible attribution control, and the client-drawn range-ring /
 * receiver-marker overlays. Aircraft rendering is out of this slice's
 * scope (arrives in slice 014).
 *
 * Tile caching: MapLibre requests style/tile/glyph/sprite resources with
 * plain HTTP GETs and no cache-busting, so the browser's normal HTTP
 * cache opportunistically serves recently-used tiles on repeat views —
 * there is nothing extra to configure for that. A service-worker cache
 * for genuine offline tile availability is future work, explicitly out
 * of scope for this slice (roadmap 013: "offline tile packs").
 *
 * Degraded mode: a persistent `error` listener flags `tilesUnavailable`
 * whenever MapLibre reports a load failure (tile, sprite, or source
 * fetch). The range rings and receiver marker are plain client-generated
 * GeoJSON, not fetched from anywhere, so they keep rendering regardless —
 * only the basemap imagery/vector tiles are affected, and a small
 * non-blocking indicator surfaces that state.
 */
export function MapLibreMap({
  config,
  basemap,
  className,
  onMapClick,
  children,
}: MapLibreMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreGlMap | null>(null);
  const onMapClickRef = useRef(onMapClick);
  const [instance, setInstance] = useState<MapLibreGlMap | null>(null);
  // Bumped on every completed style load so overlays re-attach after a
  // basemap switch discards the style's custom layers — see
  // MapInstanceContext.
  const [styleEpoch, setStyleEpoch] = useState(0);
  // The map is already constructed with `basemap.style` (see the mount
  // effect below), so the basemap-switch effect — which also runs once on
  // mount, like every effect — must skip that first run or it would
  // immediately call `setStyle` with the style the map already has,
  // reloading it a second time for nothing.
  const isInitialBasemapRef = useRef(true);
  const [tilesUnavailable, setTilesUnavailable] = useState(false);

  // Keeps the click handler current without the mount effect depending on
  // it (a new function identity every render must never tear down and
  // recreate the map — see that effect's `[]` deps below).
  useEffect(() => {
    onMapClickRef.current = onMapClick;
  }, [onMapClick]);

  // Create the map exactly once. Basemap and config changes are applied
  // to the existing instance by the effects below instead of tearing it
  // down and recreating it (that would flash/reset the view on every
  // basemap switch or config update).
  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return undefined;
    }

    const map = new MapLibreGlMap({
      container,
      style: basemap.style,
      center: [config.receiver.lon, config.receiver.lat],
      zoom: INITIAL_ZOOM,
      attributionControl: false,
    });
    mapRef.current = map;
    setInstance(map);

    map.addControl(new AttributionControl({ compact: false }), "bottom-right");

    map.on("load", () => {
      ensureOverlayLayers(map, config);
      setTilesUnavailable(false);
      setStyleEpoch((epoch) => epoch + 1);
    });

    map.on("error", () => {
      setTilesUnavailable(true);
    });

    map.on("click", (event) => {
      onMapClickRef.current?.({ lat: event.lngLat.lat, lon: event.lngLat.lng });
    });

    return () => {
      map.remove();
      mapRef.current = null;
      setInstance(null);
    };
    // Deliberately created once — see comment above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Basemap switch: swap the style, then re-add the overlay layers once
  // the new style finishes loading (setStyle discards custom layers).
  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return undefined;
    }
    if (isInitialBasemapRef.current) {
      isInitialBasemapRef.current = false;
      return undefined;
    }
    map.setStyle(basemap.style);
    const handleStyleLoad = () => {
      ensureOverlayLayers(map, config);
      setTilesUnavailable(false);
      setStyleEpoch((epoch) => epoch + 1);
    };
    map.once("style.load", handleStyleLoad);
    return () => {
      map.off("style.load", handleStyleLoad);
    };
    // Overlay refresh here only needs to react to `basemap`; `config`
    // changes are handled by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basemap]);

  // Config change (receiver position/rings): refresh the overlay data in
  // place when the style is already loaded; otherwise the pending style
  // load (initial or from a basemap switch) will pick up the latest
  // config when it calls ensureOverlayLayers itself.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) {
      return;
    }
    ensureOverlayLayers(map, config);
  }, [config]);

  const mapInstance = useMemo(
    () => ({ map: instance, styleEpoch }),
    [instance, styleEpoch],
  );

  return (
    <MapInstanceContext.Provider value={mapInstance}>
      <div className={cn("relative", className)}>
        <div
          ref={containerRef}
          className="h-full w-full"
          data-testid="maplibre-container"
          role="application"
          aria-label={`Live map centered on ${config.receiver.label}`}
        />
        {tilesUnavailable && (
          <div
            role="status"
            className="pointer-events-none absolute bottom-3 left-3 z-10 max-w-xs rounded-md border border-border bg-card/90 px-3 py-1.5 text-xs text-muted-foreground shadow-sm"
          >
            Basemap unavailable — rings and receiver position still shown.
          </div>
        )}
        {children}
      </div>
    </MapInstanceContext.Provider>
  );
}
