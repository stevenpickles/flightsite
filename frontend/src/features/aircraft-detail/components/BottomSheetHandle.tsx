/**
 * The drag handle across the top of the aircraft detail panel's phone bottom
 * sheet (roadmap slice 084, issue #227).
 *
 * Two ways to resize, deliberately equivalent:
 *
 * - **Pointer.** Drag the grabber: the sheet follows the finger (reported
 *   through `onDragHeight`, which the panel renders as an inline height) and,
 *   on release, settles into the nearest snap (`lib/sheetSnap.ts`). A tap
 *   without a drag steps up one snap, or back down to peek from full — the
 *   grabber is the obvious thing to poke.
 * - **Keyboard and assistive tech.** A grabber is not a control a screen
 *   reader or a keyboard can use, so it is `aria-hidden`, and the same two
 *   moves are plain buttons beside it: "Expand" and "Collapse", each
 *   disabled at its end of the range. Escape is not handled here — it still
 *   deselects the aircraft, exactly as it does on desktop, from the panel's
 *   own listener.
 */

import { ChevronDown, ChevronUp } from "lucide-react";
import { useRef, type PointerEvent, type RefObject } from "react";

import {
  clampSheetHeight,
  collapseSnap,
  expandSnap,
  nearestSnap,
  SHEET_SNAPS,
  TAP_SLOP_PX,
  type SheetSnap,
} from "@/features/aircraft-detail/lib/sheetSnap";
import { cn } from "@/lib/utils";

const SNAP_LABEL: Record<SheetSnap, string> = {
  peek: "collapsed",
  half: "half height",
  full: "full height",
};

interface DragState {
  pointerId: number;
  startY: number;
  startHeight: number;
  containerHeight: number;
  moved: boolean;
}

export function BottomSheetHandle({
  sheetRef,
  snap,
  onSnapChange,
  onDragHeight,
  label,
}: {
  /** The sheet element; its parent is the container snap heights are
   * measured against. */
  sheetRef: RefObject<HTMLElement | null>;
  snap: SheetSnap;
  onSnapChange: (snap: SheetSnap) => void;
  /** A live height while a drag is in progress, `null` once it settles. */
  onDragHeight: (heightPx: number | null) => void;
  /** What the sheet holds, for the buttons' accessible names. */
  label: string;
}) {
  const dragRef = useRef<DragState | null>(null);

  function onPointerDown(event: PointerEvent<HTMLDivElement>) {
    const sheet = sheetRef.current;
    if (!sheet) {
      return;
    }
    dragRef.current = {
      pointerId: event.pointerId,
      startY: event.clientY,
      startHeight: sheet.getBoundingClientRect().height,
      containerHeight: sheet.parentElement?.getBoundingClientRect().height ?? 0,
      moved: false,
    };
    // Keeps the drag attached to the handle when the finger outruns it.
    // Guarded: not every environment (jsdom among them) implements it, and a
    // drag that loses capture still works while the pointer stays over it.
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // Capture is an enhancement, not a requirement.
    }
  }

  function onPointerMove(event: PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (drag === null || drag.pointerId !== event.pointerId) {
      return;
    }
    const delta = drag.startY - event.clientY;
    if (Math.abs(delta) >= TAP_SLOP_PX) {
      drag.moved = true;
    }
    if (drag.moved) {
      onDragHeight(
        clampSheetHeight(drag.startHeight + delta, drag.containerHeight),
      );
    }
  }

  function onPointerUp(event: PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (drag === null || drag.pointerId !== event.pointerId) {
      return;
    }
    dragRef.current = null;
    onDragHeight(null);
    if (!drag.moved) {
      onSnapChange(snap === "full" ? "peek" : expandSnap(snap));
      return;
    }
    const released = clampSheetHeight(
      drag.startHeight + (drag.startY - event.clientY),
      drag.containerHeight,
    );
    onSnapChange(nearestSnap(released, drag.containerHeight));
  }

  const atTop = snap === SHEET_SNAPS[SHEET_SNAPS.length - 1];
  const atBottom = snap === SHEET_SNAPS[0];
  const buttonClass = cn(
    "rounded-md p-1 text-muted-foreground outline-none transition-colors",
    "hover:bg-secondary hover:text-foreground disabled:opacity-40 disabled:hover:bg-transparent",
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
  );

  return (
    <div className="flex shrink-0 items-center gap-1 px-2 pt-1">
      <button
        type="button"
        onClick={() => onSnapChange(collapseSnap(snap))}
        disabled={atBottom}
        aria-label={`Collapse ${label}`}
        className={buttonClass}
      >
        <ChevronDown className="size-4" aria-hidden="true" />
      </button>
      <div
        aria-hidden="true"
        data-testid="bottom-sheet-grabber"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => {
          // The browser took the gesture (a system swipe, a scroll it
          // decided was its own): drop the drag and stay at the last snap.
          dragRef.current = null;
          onDragHeight(null);
        }}
        // `touch-none` hands vertical drags to this handler instead of
        // letting the browser scroll or pull-to-refresh the page.
        className="flex h-7 flex-1 cursor-grab touch-none items-center justify-center active:cursor-grabbing"
      >
        <span className="h-1.5 w-10 rounded-full bg-muted-foreground/40" />
      </div>
      <button
        type="button"
        onClick={() => onSnapChange(expandSnap(snap))}
        disabled={atTop}
        aria-label={`Expand ${label}`}
        className={buttonClass}
      >
        <ChevronUp className="size-4" aria-hidden="true" />
      </button>
      <span className="sr-only" aria-live="polite">
        {`${label} ${SNAP_LABEL[snap]}`}
      </span>
    </div>
  );
}
