/**
 * The Live Map's controls below the `md` breakpoint (roadmap slice 084,
 * issue #227) — what `LiveMapPage` renders in place of its floating cards
 * when `useIsMobile` is true.
 *
 * At 390 px the desktop layout's ten absolutely positioned cards cannot all
 * fit: the Today card alone is 92 % of the viewport wide, the basemap,
 * layers and filter controls run down the right edge from the top, and the
 * two list columns and the activity card claim both bottom corners. So on a
 * phone every one of them moves into a single **bottom dock**, one flex
 * column anchored to the bottom of the map:
 *
 * 1. a status stack — the notification pill and the display-radius hint,
 *    both usually absent;
 * 2. at most one **sheet**: the card whose `PhoneMapToolbar` button is open,
 *    or, with none open, the aircraft detail panel as a draggable bottom
 *    sheet while an aircraft is selected;
 * 3. the toolbar itself, padded clear of `env(safe-area-inset-bottom)`.
 *
 * Because they are siblings in one column, none of them can overlap another,
 * and the dock's top edge (`top-28`, below `RecenterButton`) keeps the
 * top-left group — `ConnectionStatusChip`, the quick-filter chips and the
 * recentre button, which stay exactly where they are on desktop — visible
 * even with a sheet at full height. With nothing open the dock is just the
 * toolbar, so the map keeps well over the 60 % of the viewport the slice's
 * acceptance criterion asks for.
 *
 * One sheet at a time: selecting an aircraft closes whichever card was open
 * (the detail sheet takes the slot), and opening a card while an aircraft is
 * selected hides the detail sheet without deselecting — closing the card
 * brings the aircraft back. Escape closes an open card; with no card open it
 * reaches the detail panel's own listener and deselects, as on desktop.
 *
 * Every card stays **mounted** while its sheet is closed (`hidden`), for two
 * reasons: the cards keep their own state (an expanded list, a collapsed
 * section) across open/close, and `LayersControl` and `FilterDrawer` must be
 * mounted to register the `L`, `F` and `/` keyboard shortcuts — which, in
 * this placement, open their sheets.
 */

import { useEffect, type ReactNode } from "react";

import { ActivityPanel } from "@/features/activity/ActivityPanel";
import { AircraftDetailPanel } from "@/features/aircraft-detail/AircraftDetailPanel";
import { DisplayRadiusIndicator } from "@/features/filters/components/DisplayRadiusIndicator";
import { FilterDrawer } from "@/features/filters/components/FilterDrawer";
import { NonPositionedPanel } from "@/features/filters/components/NonPositionedPanel";
import { useFilterStore } from "@/features/filters/store/useFilterStore";
import { InterestingPanel } from "@/features/interesting/InterestingPanel";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { BasemapSwitcher } from "@/features/map/BasemapSwitcher";
import { LayersControl } from "@/features/map/overlays/LayersControl";
import { PanelRegion } from "@/features/map/PanelRegion";
import { PhoneMapToolbar } from "@/features/map/phone/PhoneMapToolbar";
import {
  phoneSheetId,
  usePhoneMapStore,
  type PhoneCardId,
} from "@/features/map/phone/usePhoneMapStore";
import { NotificationStatusPill } from "@/features/notifications/components/NotificationStatusPill";
import { TodayPanel } from "@/features/today/TodayPanel";
import { cn } from "@/lib/utils";

/**
 * One card's sheet slot. `hidden` rather than unmounted — see the module
 * doc comment. Capped at 60 % of the dock so a tall card (the filter form,
 * a long activity list) scrolls inside its sheet instead of pushing the
 * map off the screen.
 */
function Sheet({
  card,
  openCard,
  children,
}: {
  card: PhoneCardId;
  openCard: PhoneCardId | null;
  children: ReactNode;
}) {
  const open = openCard === card;
  return (
    <div
      id={phoneSheetId(card)}
      data-testid={phoneSheetId(card)}
      hidden={!open}
      // `hidden` as a class too, not only the attribute: `flex` would
      // otherwise win over the user-agent `[hidden]` rule.
      className={cn(
        open ? "flex" : "hidden",
        "pointer-events-auto max-h-[60%] min-h-0 shrink flex-col gap-2 overflow-y-auto overscroll-contain",
      )}
    >
      {children}
    </div>
  );
}

export function PhoneMapControls() {
  const openCard = usePhoneMapStore((state) => state.openCard);
  const setOpenCard = usePhoneMapStore((state) => state.setOpenCard);
  const selectedIcao = useLiveAircraftStore((state) => state.selectedIcao);
  const hideNonPositioned = useFilterStore(
    (state) => state.filters.hideNonPositioned,
  );

  // A new selection takes the sheet slot (tapping an aircraft on the map, or
  // a row in the Aircraft sheet's own lists).
  useEffect(() => {
    if (selectedIcao !== null) {
      setOpenCard(null);
    }
  }, [selectedIcao, setOpenCard]);

  // Leaving the Live Map (or crossing back to desktop) forgets the open
  // card, so returning to it starts from the resting toolbar.
  useEffect(() => () => setOpenCard(null), [setOpenCard]);

  useEffect(() => {
    if (openCard === null) {
      return undefined;
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpenCard(null);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [openCard, setOpenCard]);

  return (
    <div
      data-testid="phone-map-dock"
      className="pointer-events-none absolute inset-x-0 bottom-0 top-28 z-10 flex flex-col justify-end gap-2 px-2 pb-[max(0.5rem,env(safe-area-inset-bottom))]"
    >
      {/* The toolbar comes first in the DOM — ahead of the sheets it opens,
       * so Tab reaches a sheet's contents right after the toolbar — and last
       * on screen (`order-last`). */}
      <div className="order-last shrink-0">
        <PhoneMapToolbar />
      </div>

      <div className="flex shrink-0 flex-col gap-1.5 empty:hidden">
        <NotificationStatusPill placement="docked" />
        <DisplayRadiusIndicator placement="docked" />
      </div>

      <Sheet card="today" openCard={openCard}>
        <PanelRegion headingId="today-panel-heading" label="Today at a glance">
          <TodayPanel placement="docked" />
        </PanelRegion>
      </Sheet>
      <Sheet card="layers" openCard={openCard}>
        <PanelRegion headingId="basemap-heading" label="Basemap">
          <BasemapSwitcher placement="docked" />
        </PanelRegion>
        <PanelRegion headingId="layers-heading" label="Map layers">
          <LayersControl placement="docked" />
        </PanelRegion>
      </Sheet>
      <Sheet card="filters" openCard={openCard}>
        <FilterDrawer placement="docked" />
      </Sheet>
      <Sheet card="aircraft" openCard={openCard}>
        {/* Same DOM and visual order as the desktop column: non-positioned
         * first in the tab sequence, interesting on top on screen. */}
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
      </Sheet>
      <Sheet card="activity" openCard={openCard}>
        <PanelRegion headingId="activity-heading" label="Activity">
          <ActivityPanel placement="docked" />
        </PanelRegion>
      </Sheet>

      {openCard === null && <AircraftDetailPanel placement="docked" />}
    </div>
  );
}
