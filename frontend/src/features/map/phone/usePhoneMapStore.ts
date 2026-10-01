import { create } from "zustand";

/**
 * The cards the phone Live Map's bottom toolbar can open (roadmap slice
 * 084). `layers` is the basemap switcher and the overlay toggles together —
 * on desktop two cards stacked down the right edge, on a phone one sheet —
 * and `aircraft` is the interesting and non-positioned lists, which already
 * share one column on desktop.
 */
export type PhoneCardId =
  "today" | "layers" | "filters" | "aircraft" | "activity";

/** The element id of the sheet `card` opens — the target of its toolbar
 * button's `aria-controls`. */
export function phoneSheetId(card: PhoneCardId): string {
  return `phone-map-sheet-${card}`;
}

/**
 * Which toolbar card is open on the phone layout, if any.
 *
 * A store rather than `PhoneMapControls`' own state because two cards reach
 * it from inside themselves: `FilterDrawer` and `LayersControl` register the
 * `F`, `/` and `L` keyboard shortcuts (`lib/shortcuts/mapShortcutTargets`,
 * slice 082), and on a phone those shortcuts have to open the toolbar sheet
 * the card lives in rather than flip the card's own desktop open flag.
 *
 * One card at a time by construction: there is one `openCard` slot, so
 * opening a card closes whichever was open.
 */
interface PhoneMapState {
  openCard: PhoneCardId | null;
  setOpenCard: (card: PhoneCardId | null) => void;
  /** Opens `card`, or closes it if it is the one already open. */
  toggleCard: (card: PhoneCardId) => void;
}

export const usePhoneMapStore = create<PhoneMapState>((set) => ({
  openCard: null,
  setOpenCard: (card) => set({ openCard: card }),
  toggleCard: (card) =>
    set((state) => ({ openCard: state.openCard === card ? null : card })),
}));
