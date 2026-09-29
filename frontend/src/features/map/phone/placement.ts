/**
 * Where a Live Map card draws itself (roadmap slice 084, issue #227).
 *
 * - `"floating"` — the desktop layout every card has had since it landed:
 *   absolutely positioned over the map at its own fixed corner. The default,
 *   so a card rendered without the prop is byte-for-byte the desktop card.
 *   The Basemap and Layers cards and the Filters button are the exception
 *   since slice 085 (issue #245): they flow in `LiveMapPage`'s right-hand
 *   control column, which does the positioning for all three, so their
 *   floating classes carry only their width and stacking.
 * - `"docked"` — the phone layout below the `md` breakpoint: the card drops
 *   its absolute positioning and fixed width and flows, full width, inside
 *   `PhoneMapControls`' bottom dock, which is what keeps any two of them from
 *   overlapping at 390 px (the slice's acceptance criterion).
 *
 * Each card keeps its desktop positioning classes in one `FLOATING_*`
 * constant beside its component so the two variants differ in exactly that
 * one string and nothing else.
 */
export type MapCardPlacement = "floating" | "docked";
