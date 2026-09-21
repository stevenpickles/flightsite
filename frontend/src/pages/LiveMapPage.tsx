import type { ReactNode } from "react";

import { requireNavItem } from "@/components/shell/nav-items";
import { ActivityPanel } from "@/features/activity/ActivityPanel";
import { AircraftDetailPanel } from "@/features/aircraft-detail/AircraftDetailPanel";
import { DisplayRadiusIndicator } from "@/features/filters/components/DisplayRadiusIndicator";
import { FilterDrawer } from "@/features/filters/components/FilterDrawer";
import { NonPositionedPanel } from "@/features/filters/components/NonPositionedPanel";
import { QuickFilterChips } from "@/features/filters/components/QuickFilterChips";
import { useFilterUrlSync } from "@/features/filters/hooks/useFilterUrlSync";
import { useSelectionUrlSync } from "@/features/filters/hooks/useSelectionUrlSync";
import { useFilterStore } from "@/features/filters/store/useFilterStore";
import { InterestingPanel } from "@/features/interesting/InterestingPanel";
import { AircraftLayer } from "@/features/map/aircraft/AircraftLayer";
import { BasemapSwitcher } from "@/features/map/BasemapSwitcher";
import { MapLibreMap } from "@/features/map/MapLibreMap";
import { LayersControl } from "@/features/map/overlays/LayersControl";
import { OverlaysLayer } from "@/features/map/overlays/OverlaysLayer";
import { useMapConfigStore } from "@/features/map/store/useMapConfigStore";
import { useActiveBasemap } from "@/features/map/useActiveBasemap";
import { NotificationStatusPill } from "@/features/notifications/components/NotificationStatusPill";
import { TodayPanel } from "@/features/today/TodayPanel";

const item = requireNavItem("/");

/** The skip link's landing spot — see {@link AIRCRAFT_LIST_SKIP_TARGET_ID}'s
 * doc comment on `SkipAircraftListLink` below. */
const AIRCRAFT_LIST_SKIP_TARGET_ID = "aircraft-list-end";

/**
 * A floating card's landmark, wrapped around it from the page rather than
 * edited into the card itself (R1-11): a `<section>` with an accessible
 * name computes to the ARIA `region` role, and the `<h2>` inside gives every
 * card a place in the page's heading hierarchy — previously just
 * `["H1: Live Map"]`, with the Basemap, Layers, Interesting, Non-positioned,
 * Activity and Today cards all unlabelled `div`s with a `button` header and
 * no heading or landmark route to any of them. `label` is visually hidden
 * (`sr-only`): every one of these cards already shows its own name in its
 * toggle button or header, so the heading exists for screen-reader
 * navigation without printing the name twice on screen.
 */
function PanelRegion({
  headingId,
  label,
  className,
  children,
}: {
  headingId: string;
  label: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section role="region" aria-labelledby={headingId} className={className}>
      <h2 id={headingId} className="sr-only">
        {label}
      </h2>
      {children}
    </section>
  );
}

/**
 * "Skip aircraft list" (R1-11): the interesting-aircraft panel is expanded
 * by default and, at SPEC §5's load envelope (~500 aircraft), can hold
 * hundreds of rows — every one of them a tab stop directly inside this
 * link's target column. Panel order already keeps every *other* card ahead
 * of it in the tab sequence (see the layout comment below), but the column
 * itself still has to be crossed by anyone who tabs into it — from the
 * page's own top, from a browser "find" jump, or simply because a future
 * card lands after it. Landing on {@link AIRCRAFT_LIST_SKIP_TARGET_ID}
 * moves focus past every row in one step.
 */
function SkipAircraftListLink() {
  return (
    <a
      href={`#${AIRCRAFT_LIST_SKIP_TARGET_ID}`}
      className="sr-only focus-visible:not-sr-only focus-visible:fixed focus-visible:bottom-2 focus-visible:left-2 focus-visible:z-50 focus-visible:rounded-md focus-visible:bg-accent focus-visible:px-3 focus-visible:py-2 focus-visible:text-accent-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
    >
      Skip aircraft list
    </a>
  );
}

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
 *
 * **Panel order (R1-11).** Every card except the aircraft-list column is
 * absolutely positioned and self-contained, so its place in this file's JSX
 * — its *tab* order — is independent of where it actually renders on
 * screen. Before this slice the interesting-aircraft panel (open by
 * default, up to ~500 rows) sat right after the filter button, ahead of the
 * non-positioned list, the activity panel and the Today card in the tab
 * sequence, so a keyboard user had to tab through every interesting row
 * before reaching any of them. Every other card's JSX now comes first;
 * the aircraft-list column — non-positioned before interesting, so the
 * (usually much shorter) non-positioned list still needs only one extra tab
 * stop — is last, with `order-1`/`order-2` on the two cards keeping the
 * *visual* stack exactly as it was (interesting on top).
 */
export function LiveMapPage() {
  const config = useMapConfigStore((state) => state.config);
  const basemap = useActiveBasemap();
  const hideNonPositioned = useFilterStore(
    (state) => state.filters.hideNonPositioned,
  );

  useFilterUrlSync();
  useSelectionUrlSync();

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

      <PanelRegion headingId="today-panel-heading" label="Today at a glance">
        <TodayPanel />
      </PanelRegion>
      <PanelRegion headingId="basemap-heading" label="Basemap">
        <BasemapSwitcher />
      </PanelRegion>
      <PanelRegion headingId="layers-heading" label="Map layers">
        <LayersControl />
      </PanelRegion>
      <QuickFilterChips />
      <FilterDrawer />
      <PanelRegion headingId="activity-heading" label="Activity">
        <ActivityPanel />
      </PanelRegion>
      <DisplayRadiusIndicator />
      <NotificationStatusPill />

      <SkipAircraftListLink />
      {/* The bottom-left corner, as one upward-growing column: the two
       * aircraft-list cards share it rather than each claiming the same
       * absolute slot. `pointer-events-none` on the column keeps the gap
       * between the cards click-through to the map; each card turns
       * pointer events back on for itself. DOM order is non-positioned
       * first, interesting last (see the panel-order doc comment above);
       * `order-*` keeps the visual stack — interesting on top — unchanged. */}
      <div className="pointer-events-none absolute bottom-3 left-3 z-10 flex max-h-[calc(100%-1.5rem)] w-72 max-w-[80vw] flex-col gap-2">
        {!hideNonPositioned && (
          <PanelRegion
            headingId="non-positioned-heading"
            label="Non-positioned aircraft"
            className="order-2"
          >
            <NonPositionedPanel />
          </PanelRegion>
        )}
        <PanelRegion
          headingId="interesting-heading"
          label="Interesting aircraft"
          className="order-1"
        >
          <InterestingPanel />
        </PanelRegion>
      </div>
      {/* Skip-link target — see `SkipAircraftListLink`. Visually hidden:
       * nothing needs to be seen here, only reached. */}
      <div
        id={AIRCRAFT_LIST_SKIP_TARGET_ID}
        tabIndex={-1}
        className="sr-only"
      />

      <AircraftDetailPanel />
    </div>
  );
}
