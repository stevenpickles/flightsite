/**
 * Snap points for the aircraft detail panel's phone bottom sheet (roadmap
 * slice 084, issue #227) — pure functions, so the rules a drag resolves by
 * are testable without a pointer or a layout engine.
 *
 * Three heights, all measured against the sheet's container (the phone Live
 * Map's bottom dock, which already stops short of the connection chip and
 * the top-left map controls):
 *
 * - **peek** — {@link PEEK_HEIGHT_PX}: the header only (callsign, ICAO,
 *   badges, share controls), so a selection costs the map almost nothing.
 * - **half** — half the container: the Live section's readings.
 * - **full** — the whole container: everything, scrolling.
 *
 * Peek is a fixed height rather than a fraction because what it has to show
 * is a fixed amount of content; on a very short container it is capped at
 * the container so peek can never be taller than full.
 */

export type SheetSnap = "peek" | "half" | "full";

/** Lowest to highest — the order Expand walks up and Collapse walks down. */
export const SHEET_SNAPS: readonly SheetSnap[] = ["peek", "half", "full"];

/** Peek height in CSS pixels: Tailwind's `h-44` (11rem at the default 16 px
 * root), which is the class the sheet renders at rest in this snap. */
export const PEEK_HEIGHT_PX = 176;

/** A pointer that moved less than this between down and up was a tap on the
 * handle, not a drag. */
export const TAP_SLOP_PX = 6;

/** The next snap up, or `snap` itself when it is already the highest. */
export function expandSnap(snap: SheetSnap): SheetSnap {
  const index = SHEET_SNAPS.indexOf(snap);
  return SHEET_SNAPS[Math.min(index + 1, SHEET_SNAPS.length - 1)] ?? snap;
}

/** The next snap down, or `snap` itself when it is already the lowest. */
export function collapseSnap(snap: SheetSnap): SheetSnap {
  const index = SHEET_SNAPS.indexOf(snap);
  return SHEET_SNAPS[Math.max(index - 1, 0)] ?? snap;
}

/** The pixel height `snap` resolves to inside a container `containerPx`
 * tall. */
export function snapHeightPx(snap: SheetSnap, containerPx: number): number {
  const container = Math.max(0, containerPx);
  switch (snap) {
    case "peek":
      return Math.min(PEEK_HEIGHT_PX, container);
    case "half":
      return container / 2;
    case "full":
      return container;
  }
}

/** Clamps a dragged height to what the sheet may be: never shorter than
 * peek, never taller than its container. */
export function clampSheetHeight(
  heightPx: number,
  containerPx: number,
): number {
  return Math.min(
    Math.max(heightPx, snapHeightPx("peek", containerPx)),
    Math.max(0, containerPx),
  );
}

/**
 * The snap a drag released at `heightPx` settles into: whichever snap height
 * is closest. Ties go to the lower snap, so a sheet released exactly between
 * two stops leaves the map more room rather than less.
 */
export function nearestSnap(heightPx: number, containerPx: number): SheetSnap {
  let best: SheetSnap = "peek";
  let bestDistance = Number.POSITIVE_INFINITY;
  for (const snap of SHEET_SNAPS) {
    const distance = Math.abs(snapHeightPx(snap, containerPx) - heightPx);
    if (distance < bestDistance) {
      best = snap;
      bestDistance = distance;
    }
  }
  return best;
}
