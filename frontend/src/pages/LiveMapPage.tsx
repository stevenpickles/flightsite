import { requireNavItem } from "@/components/shell/nav-items";
import { AircraftLayer } from "@/features/map/aircraft/AircraftLayer";
import { BasemapSwitcher } from "@/features/map/BasemapSwitcher";
import { getBasemapById, getDefaultBasemap } from "@/features/map/basemaps";
import { MapLibreMap } from "@/features/map/MapLibreMap";
import { useBasemapStore } from "@/features/map/store/useBasemapStore";
import { useMapConfigStore } from "@/features/map/store/useMapConfigStore";

const item = requireNavItem("/");

/**
 * The Live Map route: a full-viewport MapLibre map (dark aviation default,
 * selectable basemaps, range rings, and receiver marker — slice 013) carrying
 * the live aircraft layer (slice 014).
 *
 * The map configuration still comes from `useMapConfigStore`, which the setup
 * wizard's config sync (slice 018) populates from the server's real receiver
 * location; the live socket supplies aircraft, not map configuration.
 *
 * Labels, filters, and the detail panel arrive in slices 015–017.
 */
export function LiveMapPage() {
  const basemapId = useBasemapStore((state) => state.basemapId);
  const config = useMapConfigStore((state) => state.config);
  const basemap = getBasemapById(basemapId) ?? getDefaultBasemap();

  return (
    <div className="relative h-full w-full">
      {/* Visually hidden — the map itself is the content; this keeps the
       * page's landmark heading structure consistent with every other
       * section for screen-reader navigation. */}
      <h1 className="sr-only">{item.label}</h1>
      <MapLibreMap config={config} basemap={basemap} className="h-full w-full">
        <AircraftLayer />
      </MapLibreMap>
      <BasemapSwitcher />
    </div>
  );
}
