/**
 * Arrow-key roving focus for composite widgets (`role="tablist"`,
 * `role="radiogroup"`) — roadmap slice 048, SPEC §80's "keyboard navigation"
 * and "ARIA where necessary".
 *
 * Both patterns are *composite* widgets in WAI-ARIA terms: the group is one
 * tab stop, and the arrow keys — not Tab — move between the options inside
 * it. Marking up the roles without the key handling is the failure mode this
 * hook exists to prevent, and the project hit the worst version of it: the
 * Alerts page's tabs shipped the roving `tabIndex={selected ? 0 : -1}` half
 * of the pattern with no arrow handler, which made every unselected tab
 * unreachable by keyboard *at all* (Tab skips `tabindex="-1"`, and nothing
 * else moved focus). A radiogroup without roving tabindex fails less badly —
 * every option stays Tab-reachable — but still reads to assistive tech as a
 * widget whose documented key bindings do nothing.
 *
 * Activation is **automatic**: an arrow key moves focus *and* selects, via a
 * synthetic `click()` on the target. That is required behavior for a
 * radiogroup, permitted for a tablist, and it deliberately reuses each
 * consumer's existing `onClick` rather than asking callers to pass a second
 * selection callback that could drift out of sync with the mouse path.
 *
 * Consumers pair this with `tabIndex={selected ? 0 : -1}` on each option so
 * the group is a single tab stop.
 */
import { useCallback, type KeyboardEvent, type RefObject } from "react";

/** Which arrow keys move between options. `both` suits a wrapping/flex-wrap
 * group where either axis reads as "the next option". */
export type RovingOrientation = "horizontal" | "vertical" | "both";

const NEXT_KEYS: Record<RovingOrientation, readonly string[]> = {
  horizontal: ["ArrowRight"],
  vertical: ["ArrowDown"],
  both: ["ArrowRight", "ArrowDown"],
};

const PREV_KEYS: Record<RovingOrientation, readonly string[]> = {
  horizontal: ["ArrowLeft"],
  vertical: ["ArrowUp"],
  both: ["ArrowLeft", "ArrowUp"],
};

export interface UseRovingFocusOptions {
  /** The role each option carries — the hook finds options by it, so it never
   * grabs an unrelated nested button (e.g. a close button inside a panel). */
  itemRole: "tab" | "radio";
  orientation?: RovingOrientation;
}

/**
 * Takes the container's own ref and returns just the `onKeyDown` handler for
 * it. The ref is a parameter rather than something this hook creates and
 * hands back inside an object because `react-hooks/refs` (correctly) rejects
 * reading a ref off a returned object during render.
 */
export function useRovingFocus<T extends HTMLElement = HTMLDivElement>(
  containerRef: RefObject<T>,
  { itemRole, orientation = "horizontal" }: UseRovingFocusOptions,
): (event: KeyboardEvent<T>) => void {
  return useCallback(
    (event: KeyboardEvent<T>) => {
      const container = containerRef.current;
      if (!container) {
        return;
      }

      const { key } = event;
      const isNext = NEXT_KEYS[orientation].includes(key);
      const isPrev = PREV_KEYS[orientation].includes(key);
      const isHome = key === "Home";
      const isEnd = key === "End";
      if (!isNext && !isPrev && !isHome && !isEnd) {
        return;
      }

      const items = Array.from(
        container.querySelectorAll<HTMLElement>(`[role="${itemRole}"]`),
      ).filter(
        (element) =>
          !element.hasAttribute("disabled") &&
          element.getAttribute("aria-disabled") !== "true",
      );
      if (items.length === 0) {
        return;
      }

      const activeElement = document.activeElement;
      const currentIndex =
        activeElement instanceof HTMLElement
          ? items.indexOf(activeElement)
          : -1;

      let nextIndex: number;
      if (isHome) {
        nextIndex = 0;
      } else if (isEnd) {
        nextIndex = items.length - 1;
      } else if (currentIndex === -1) {
        // Focus is on the container itself (or something outside the option
        // list): start from the first option rather than doing nothing.
        nextIndex = 0;
      } else {
        // Wrapping is the documented behavior for both patterns.
        nextIndex =
          (currentIndex + (isNext ? 1 : -1) + items.length) % items.length;
      }

      const target = items[nextIndex];
      if (!target) {
        return;
      }

      // Only now, once a real move is known to be possible, suppress the
      // browser default (arrow-key scrolling).
      event.preventDefault();
      target.focus();
      target.click();
    },
    [containerRef, itemRole, orientation],
  );
}
