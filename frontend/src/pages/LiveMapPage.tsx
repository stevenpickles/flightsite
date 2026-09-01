import { requireNavItem } from "@/components/shell/nav-items";
import { ActivityPanel } from "@/features/activity/ActivityPanel";
import { AircraftDetailPanel } from "@/features/aircraft-detail/AircraftDetailPanel";
import { DisplayRadiusIndicator } from "@/features/filters/components/DisplayRadiusIndicator";
import { FilterDrawer } from "@/features/filters/components/FilterDrawer";
import { NonPositionedPanel } from "@/features/filters/components/NonPositionedPanel";
import { QuickFilterChips } from "@/features/filters/components/QuickFilterChips";
import { useFilterUrlSync } from "@/features/filters/hooks/useFilterUrlSync";
import { InterestingPanel } from "@/features/interesting/InterestingPanel";
import { AircraftLayer } from "@/features/map/aircraft/AircraftLayer";
import { BasemapSwitcher } from "@/features/map/BasemapSwitcher";
import { getBasemapById, getDefaultBasemap } from "@/features/map/basemaps";
import { MapLibreMap } from "@/features/map/MapLibreMap";
import { LayersControl } from "@/features/map/overlays/LayersControl";
import { OverlaysLayer } from "@/features/map/overlays/OverlaysLayer";
import { useBasemapStore } from "@/features/map/store/useBasemapStore";
import { useMapConfigStore } from "@/features/map/store/useMapConfigStore";
import { TodayPanel } from "@/features/today/TodayPanel";

const item = requireNavItem("/");

/**
 * The Live Map route: a full-viewport MapLibre map (dark aviation default,
 * selectable basemaps, range rings, and receiver marker — slice 013) carrying
 * the live aircraft layer (slice 014), the aircraft detail panel (slice
 * 016), the live filters (drawer, quick chips, non-positioned list, and
 * the display-radius cap indicator — slice 017), all of which read and
 * write the same filtered set via `features/filters`, the activity feed
 * panel (slice 035), which is the one floating control fed by the socket's
 * `activity` frames rather than by the live picture, the "Today at a
 * glance" card (slice 036), a top-center strip fed by the analytics summary
 * endpoint rather than by anything the live picture or the feed carry, and
 * the interesting-aircraft panel (slice 039, SPEC §49), which shares the
 * bottom-left column with the non-positioned list.
 *
 * The map configuration — including the display-radius default the
 * distance-cap filter falls back to — comes from `useMapConfigStore`, which
 * the setup wizard's config sync (slice 018) populates from the server's
 * real receiver location and `display_radius_nm`; the live socket supplies
 * aircraft, not map configuration.
 */
export function LiveMapPage() {
  const basemapId = useBasemapStore((state) => state.basemapId);
  const config = useMapConfigStore((state) => state.config);
  const basemap = getBasemapById(basemapId) ?? getDefaultBasemap();

  useFilterUrlSync();

  return (
    <div className="relative h-full w-full">
      {/* Visually hidden — the map itself is the content; this keeps the
       * page's landmark heading structure consistent with every other
       * section for screen-reader navigation. */}
      <h1 className="sr-only">{item.label}</h1>
      <MapLibreMap config={config} basemap={basemap} className="h-full w-full">
        <OverlaysLayer />
        <AircraftLayer />
      </MapLibreMap>
      <BasemapSwitcher />
      <LayersControl />
      <QuickFilterChips />
      <FilterDrawer />
      {/* The bottom-left corner, as one upward-growing column: the two
       * aircraft-list cards share it rather than each claiming the same
       * absolute slot. `pointer-events-none` on the column keeps the gap
       * between the cards click-through to the map; each card turns
       * pointer events back on for itself. */}
      <div className="pointer-events-none absolute bottom-3 left-3 z-10 flex max-h-[calc(100%-1.5rem)] w-72 max-w-[80vw] flex-col gap-2">
        <InterestingPanel />
        <NonPositionedPanel />
      </div>
      <ActivityPanel />
      <TodayPanel />
      <DisplayRadiusIndicator />
      <AircraftDetailPanel />
    </div>
  );
}
