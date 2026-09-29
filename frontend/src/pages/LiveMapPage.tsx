import { requireNavItem } from "@/components/shell/nav-items";
import { useIsMobile } from "@/components/shell/useIsMobile";
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
import { MeasureControl } from "@/features/map/measure/MeasureControl";
import { LayersControl } from "@/features/map/overlays/LayersControl";
import { OverlaysLayer } from "@/features/map/overlays/OverlaysLayer";
import { PanelRegion } from "@/features/map/PanelRegion";
import { PhoneMapControls } from "@/features/map/phone/PhoneMapControls";
import { RecenterButton } from "@/features/map/RecenterButton";
import { useMapConfigStore } from "@/features/map/store/useMapConfigStore";
import { useActiveBasemap } from "@/features/map/useActiveBasemap";
import { NotificationStatusPill } from "@/features/notifications/components/NotificationStatusPill";
import { TodayPanel } from "@/features/today/TodayPanel";

const item = requireNavItem("/");

/** The skip link's landing spot — see {@link AIRCRAFT_LIST_SKIP_TARGET_ID}'s
 * doc comment on `SkipAircraftListLink` below. */
const AIRCRAFT_LIST_SKIP_TARGET_ID = "aircraft-list-end";

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
 * bottom-left column with the non-positioned list, and, since roadmap slice
 * 082, `RecenterButton` (the `H` shortcut's visible control) plus a full set
 * of keyboard shortcuts (`/`, `L`, `F`, `H`, `[`, `]`) dispatched from
 * `useKeyboardShortcuts` in `AppShell` and reaching this page's own
 * components through `lib/shortcuts/mapShortcutTargets`. Roadmap slice 085
 * adds the distance/bearing `MeasureControl` beside the recentre button,
 * shared by both layouts like it.
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
 *
 * **Phone layout (roadmap slice 084).** Below the `md` breakpoint
 * (`useIsMobile`) the floating cards give way to `PhoneMapControls`: one
 * bottom dock holding a toolbar that opens one card at a time as a sheet,
 * and the aircraft detail panel as a draggable bottom sheet. The map, its
 * layers, the connection chip, the quick-filter chips and the recentre
 * button are shared by both layouts; everything else is one layout's or the
 * other's, so the desktop render below is untouched by the phone one.
 */
export function LiveMapPage() {
  const isMobile = useIsMobile();
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
        <RecenterButton receiver={config.receiver} />
        <MeasureControl
          receiver={config.receiverConfigured ? config.receiver : null}
        />
      </MapLibreMap>

      {isMobile ? (
        <>
          <QuickFilterChips />
          <PhoneMapControls />
        </>
      ) : (
        <DesktopMapControls hideNonPositioned={hideNonPositioned} />
      )}
    </div>
  );
}

/**
 * The right-hand control column (issue #245): Basemap, then Layers, then the
 * Filters button, stacked in flow down the map's right edge.
 *
 * Each of the three used to claim its own fixed offset (`right-3 top-3`,
 * `right-3 top-40`, and `right-3 top-40` again), and the Layers card and the
 * Filters button ended up sharing a corner: the button sat over the right end
 * of the card's header (around x 1355-1427, y 162-188 at 1440 x 900). A fixed
 * offset for the button could only ever be right for one height of the card
 * above it, and that card changes height — it collapses (slice 082's `L`) and
 * slice 085 gave it more rows. As flex items in one column they cannot
 * overlap at any height: collapsing the Layers card lifts the button with
 * it.
 *
 * - `absolute inset-y-0 right-0 p-3` keeps the cards exactly where
 *   `right-3 top-3` put the first one, and makes the column a full-height,
 *   right-edge box — which is also what `FilterDrawer`'s open panel
 *   (`absolute inset-y-0 right-0`) positions against, so it still slides in
 *   over the whole right edge of the map.
 * - `pointer-events-none`, with each card turning pointer events back on for
 *   itself, keeps the gaps and the empty column below the button
 *   click-through to the map.
 * - No `z-index`: an absolutely positioned box without one opens no stacking
 *   context, so each card's own `z-10` and the drawer panel's `z-20` still
 *   rank against every other card on the page exactly as before.
 */
const RIGHT_CONTROL_COLUMN_CLASSES =
  "pointer-events-none absolute inset-y-0 right-0 flex flex-col items-end gap-2 p-3";

/**
 * The desktop (and tablet, from `md` up) floating cards — the Live Map's
 * layout before roadmap slice 084, lifted out of `LiveMapPage` so the phone
 * layout can replace it wholesale, with the right-hand column grouped since
 * slice 085 (issue #245, {@link RIGHT_CONTROL_COLUMN_CLASSES}) — which also
 * puts the Filters button right after the Layers card in tab order, ahead of
 * the quick-filter chips. The panel-order notes on `LiveMapPage` describe
 * this JSX.
 */
function DesktopMapControls({
  hideNonPositioned,
}: {
  hideNonPositioned: boolean;
}) {
  return (
    <>
      <PanelRegion headingId="today-panel-heading" label="Today at a glance">
        <TodayPanel />
      </PanelRegion>
      {/* The right-hand control column — see RIGHT_CONTROL_COLUMN_CLASSES. */}
      <div
        data-testid="map-right-controls"
        className={RIGHT_CONTROL_COLUMN_CLASSES}
      >
        <PanelRegion headingId="basemap-heading" label="Basemap">
          <BasemapSwitcher />
        </PanelRegion>
        <PanelRegion headingId="layers-heading" label="Map layers">
          <LayersControl />
        </PanelRegion>
        <FilterDrawer />
      </div>
      <QuickFilterChips />
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
    </>
  );
}
