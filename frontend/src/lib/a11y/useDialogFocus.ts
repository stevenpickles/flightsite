/**
 * Focus management for the project's hand-rolled overlays — roadmap slice
 * 048, SPEC §80's "keyboard navigation" and "visible focus".
 *
 * FlightSite ships no dialog primitive (only `@radix-ui/react-slot`,
 * `-separator` and `-tooltip` are installed), so `AircraftDetailPanel`,
 * `FilterDrawer` and `ConfirmDangerDialog` each hand-roll `role="dialog"`.
 * All three already moved focus *into* the panel on open and closed on
 * Escape; all three were missing the other half of the contract:
 *
 * 1. **Focus restoration.** Closing an overlay unmounts the element holding
 *    focus, which drops focus to `<body>`. A keyboard or screen-reader user
 *    is then thrown back to the top of the document and has to Tab all the
 *    way back to whatever they were doing. Restoring focus to the control
 *    that opened the overlay is what makes an overlay a detour rather than a
 *    dead end. Applies to modal and non-modal overlays alike.
 *
 * 2. **A focus trap, for modal overlays only.** `aria-modal="true"` promises
 *    assistive tech that the rest of the page is inert, but it does not move
 *    the Tab ring — without a trap, Tab walks straight out of the dialog and
 *    onto the page behind it, which is exactly what `ConfirmDangerDialog`
 *    (the typed-confirmation gate on destructive Settings actions) did.
 *
 * The trap is deliberately opt-in via `modal`. `AircraftDetailPanel`
 * (`aria-modal="false"`) and `FilterDrawer` are *non-modal* side panels — the
 * map and page behind them stay interactive by design, so trapping focus in
 * them would be a bug, not a fix.
 */
import { useEffect, useRef, type RefObject } from "react";

/** Elements that can hold focus. Deliberately not filtered by visibility:
 * jsdom reports every element as unrendered (`offsetParent === null`), which
 * would make a visibility filter silently empty the trap under test. */
const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

export interface UseDialogFocusOptions {
  /** Whether the overlay is currently rendered. */
  open: boolean;
  /**
   * Trap Tab inside the panel. Pass `true` only for a genuinely modal
   * overlay (one carrying `aria-modal="true"`); a non-modal panel must let
   * Tab leave.
   */
  modal?: boolean;
}

/**
 * Returns the ref to attach to the dialog panel element. The panel should
 * also carry `tabIndex={-1}` so it can receive focus itself when it holds no
 * focusable children.
 */
export function useDialogFocus<T extends HTMLElement = HTMLDivElement>({
  open,
  modal = false,
}: UseDialogFocusOptions): RefObject<T> {
  const panelRef = useRef<T>(null);
  const restoreTargetRef = useRef<HTMLElement | null>(null);

  // Capture the opener on the way in, restore it on the way out. The cleanup
  // runs when `open` flips false *and* on unmount, so a panel removed while
  // open (route change, parent teardown) restores focus too.
  useEffect(() => {
    if (!open) {
      return undefined;
    }

    restoreTargetRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;

    return () => {
      const target = restoreTargetRef.current;
      restoreTargetRef.current = null;
      // `isConnected` guards the case where the opener itself has since left
      // the DOM — focusing a detached node throws focus to `<body>` anyway,
      // so there is nothing better to do than leave it alone.
      if (target && target.isConnected) {
        target.focus();
      }
    };
  }, [open]);

  useEffect(() => {
    if (!open || !modal) {
      return undefined;
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Tab") {
        return;
      }
      const panel = panelRef.current;
      if (!panel) {
        return;
      }

      const items = Array.from(
        panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      ).filter((element) => element.getAttribute("aria-hidden") !== "true");

      const first = items[0];
      const last = items[items.length - 1];
      if (!first || !last) {
        // Nothing focusable inside: keep focus on the panel itself rather
        // than letting Tab escape to the page behind.
        event.preventDefault();
        panel.focus();
        return;
      }

      const active = document.activeElement;
      const insidePanel = active instanceof Node && panel.contains(active);

      if (!insidePanel) {
        event.preventDefault();
        first.focus();
        return;
      }
      if (event.shiftKey && (active === first || active === panel)) {
        event.preventDefault();
        last.focus();
        return;
      }
      if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    }

    // Capture phase: the wrap decision has to be made before anything inside
    // the panel handles Tab itself.
    document.addEventListener("keydown", handleKeyDown, true);
    return () => document.removeEventListener("keydown", handleKeyDown, true);
  }, [open, modal]);

  return panelRef;
}
