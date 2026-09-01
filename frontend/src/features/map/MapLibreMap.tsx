import {
  AttributionControl,
  Map as MapLibreGlMap,
  setWorkerUrl,
} from "maplibre-gl";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import "maplibre-gl/dist/maplibre-gl.css";

import type { BasemapDefinition } from "@/features/map/basemaps";
import { MapInstanceContext } from "@/features/map/MapInstanceContext";
import { ensureOverlayLayers } from "@/features/map/overlayLayers";
import type { MapConfig } from "@/features/map/types";
import { cn } from "@/lib/utils";

/**
 * Points MapLibre at its own worker script explicitly, rather than letting
 * it guess.
 *
 * MapLibre computes a default worker URL as a sibling of its own module's
 * `import.meta.url` at runtime (`maplibre-gl-worker.mjs` next to
 * `maplibre-gl.mjs`) — a reasonable assumption when the package is loaded
 * as its own file, but wrong once Vite inlines it into the app's single
 * bundle: `import.meta.url` then resolves to the app bundle's own URL
 * (`/assets/index-<hash>.js`), so MapLibre goes looking for
 * `/assets/maplibre-gl-worker.mjs` — a file nothing ever asked the bundler
 * to emit, so it 404s. Without a working worker MapLibre cannot tile or
 * process ANY GeoJSON source, so nothing renders (not the range rings, not
 * the receiver marker, not aircraft) — silently: no exception reaches the
 * app, the map just stays visually and functionally empty forever.
 *
 * `scripts/copy-maplibre-worker.mjs` (wired as `predev`/`prebuild`) copies
 * the real worker script from the installed `maplibre-gl` version into
 * `public/`, which Vite serves verbatim at `/maplibre-gl-worker.mjs` in
 * both dev and the production build — that fixed path is what this points
 * to, module-scoped so it runs once, before any `Map` is constructed.
 */
setWorkerUrl("/maplibre-gl-worker.mjs");

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
  // Keeps the initial 'load' handler (registered once, see the mount
  // effect's `[]` deps) reading the *current* config rather than whatever
  // `config` prop was in scope at mount. The server's real receiver
  // location almost always arrives (React Query resolving `GET
  // /api/internal/config`, a fast same-origin call) before the map's own
  // 'load' event (which waits on the basemap style/sprite/glyph/tile
  // fetches) — without this ref, that 'load' handler's stale closure would
  // draw the range rings/receiver marker at the `DEV_PLACEHOLDER_MAP_CONFIG`
  // fallback forever, exactly the placeholder `mapConfigSync.ts` says it
  // replaces.
  const configRef = useRef(config);
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
  // Mirrors `isInitialBasemapRef`: the config-recenter effect below must
  // skip the render it mounted with (that's already the map's construction
  // center) and only act on a genuine, later change — and then never
  // again, so it recenters exactly once and never fights a user's manual
  // pan/zoom or the setup wizard's LocationStep typing after that.
  const isInitialConfigRef = useRef(true);
  const hasRecenteredOnceRef = useRef(false);
  const [tilesUnavailable, setTilesUnavailable] = useState(false);
  // True when MapLibre itself cannot run here at all (no WebGL context —
  // headless browsers, remote desktops, ancient GPUs). Distinct from
  // `tilesUnavailable`: that is a working renderer with no basemap, this is
  // no renderer. The rest of the app (panels, lists, live data) keeps
  // working either way.
  const [mapUnsupported, setMapUnsupported] = useState(false);

  // Keeps the click handler current without the mount effect depending on
  // it (a new function identity every render must never tear down and
  // recreate the map — see that effect's `[]` deps below).
  useEffect(() => {
    onMapClickRef.current = onMapClick;
  }, [onMapClick]);

  useEffect(() => {
    configRef.current = config;
  }, [config]);

  // Create the map exactly once. Basemap and config changes are applied
  // to the existing instance by the effects below instead of tearing it
  // down and recreating it (that would flash/reset the view on every
  // basemap switch or config update).
  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return undefined;
    }

    let map: MapLibreGlMap;
    try {
      map = new MapLibreGlMap({
        container,
        style: basemap.style,
        center: [config.receiver.lon, config.receiver.lat],
        zoom: INITIAL_ZOOM,
        attributionControl: false,
      });
    } catch {
      // No WebGL context available: MapLibre throws (or half-constructs)
      // rather than rendering. Crashing here previously took down the whole
      // route into the router's error page — the degraded-mode requirement
      // covers the renderer itself, not just the tiles. This one-shot branch
      // renders the static notice and schedules nothing else, so the sync
      // set cannot cascade.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMapUnsupported(true);
      return undefined;
    }
    mapRef.current = map;
    setInstance(map);

    // E2E test hook only (roadmap slice 020, docs/DEVELOPMENT.md "Running
    // E2E locally"): the MapLibre instance has no other externally-reachable
    // handle, and the Playwright aircraft-selection flow needs its public
    // `project()` method to turn a live aircraft's lat/lon into the canvas
    // pixel a real user click would land on. Not part of the app's
    // supported API — nothing in the app itself reads this global.
    if (typeof window !== "undefined") {
      (
        window as unknown as { __flightsiteMap?: MapLibreGlMap }
      ).__flightsiteMap = map;
    }

    map.addControl(new AttributionControl({ compact: false }), "bottom-right");

    map.on("load", () => {
      // Reads `configRef` (the current config), not the closed-over
      // `config` prop from this once-only mount effect — see the ref's own
      // comment above: whichever config is current by the time the style
      // has actually finished loading is the one the rings/marker should
      // reflect, not whatever `config` happened to be at construction time.
      ensureOverlayLayers(map, configRef.current);
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
      try {
        map.remove();
      } catch {
        // remove() dereferences this.painter, which is undefined when the
        // GL context died after construction (seen on WebGL-less CI
        // Firefox). A failed teardown of an already-dead map must never
        // crash the unmounting route.
      }
      mapRef.current = null;
      setInstance(null);
      if (
        typeof window !== "undefined" &&
        (window as unknown as { __flightsiteMap?: MapLibreGlMap })
          .__flightsiteMap === map
      ) {
        delete (window as unknown as { __flightsiteMap?: MapLibreGlMap })
          .__flightsiteMap;
      }
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
      ensureOverlayLayers(map, configRef.current);
      setTilesUnavailable(false);
      setStyleEpoch((epoch) => epoch + 1);
    };
    map.once("style.load", handleStyleLoad);
    return () => {
      map.off("style.load", handleStyleLoad);
    };
    // Overlay refresh here only needs to react to `basemap`; `config`
    // changes are handled by the effect below.
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

  // One-time camera recenter, independent of the style/tile load above:
  // the map is constructed with whatever `config` the *first* render held
  // (for the Live Map, that's always `DEV_PLACEHOLDER_MAP_CONFIG` — React
  // Query never resolves synchronously on a first render — until
  // `mapConfigSync.ts` replaces it with the real receiver location).
  // Waiting for the map's own 'load' event to do this (as the overlay
  // refresh above effectively can, since it re-runs once style-loaded)
  // raced the real config's arrival unpredictably: 'load' can fire before
  // or after the config fetch resolves depending on network/tile
  // conditions, so gating the jump on 'load' timing either missed the real
  // location entirely or (worse) "consumed" the one-time jump on a
  // still-stale placeholder. Reacting to `config` itself sidesteps the
  // race — `map.jumpTo` needs no style/tile readiness — and firing only on
  // the first *change* (never the mount-time render) is what keeps this
  // from fighting a user's manual pan/zoom or the setup wizard's
  // LocationStep typing after that first sync.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    if (isInitialConfigRef.current) {
      isInitialConfigRef.current = false;
      return;
    }
    if (hasRecenteredOnceRef.current) {
      return;
    }
    hasRecenteredOnceRef.current = true;
    map.jumpTo({ center: [config.receiver.lon, config.receiver.lat] });
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
        {tilesUnavailable && !mapUnsupported && (
          <div
            role="status"
            className="pointer-events-none absolute bottom-3 left-3 z-10 max-w-xs rounded-md border border-border bg-card/90 px-3 py-1.5 text-xs text-muted-foreground shadow-sm"
          >
            Basemap unavailable — rings and receiver position still shown.
          </div>
        )}
        {mapUnsupported && (
          <div
            role="status"
            data-testid="map-unsupported"
            className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center"
          >
            <p className="max-w-sm rounded-md border border-border bg-card/90 px-4 py-3 text-center text-sm text-muted-foreground shadow-sm">
              The map cannot render in this browser (WebGL unavailable). Live
              aircraft data still updates in the panels.
            </p>
          </div>
        )}
        {children}
      </div>
    </MapInstanceContext.Provider>
  );
}
