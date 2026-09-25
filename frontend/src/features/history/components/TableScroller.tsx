/**
 * The horizontal scroller both history tables sit in, with a *visible*
 * affordance when there is something past the edge (review R2-08, R2-13).
 *
 * The tables hide their lower-priority columns below a breakpoint, so this
 * is the floor rather than the plan: on a narrow window, or with unusually
 * long operator names, the remaining columns can still overflow. The review
 * measured `scrollWidth 1216 / clientWidth 1118` on `/sightings` at
 * 1440x900 with overlay scrollbars — 98px of the Status column hidden, with
 * nothing on screen to say a column existed at all.
 *
 * The fade and the note appear only when the content genuinely overflows,
 * measured rather than assumed: a permanent "scroll for more" on a table
 * that fits would be the same lie in the other direction.
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { cn } from "@/lib/utils";

export interface TableScrollerProps {
  children: ReactNode;
  /** Classes for the scrolling element itself (the `refreshing` dim). */
  className?: string;
  /** Named in the note, so it reads as an instruction rather than an
   * apology: "every column is also on the sighting's own page". */
  detailNoun?: string;
}

interface Edges {
  left: boolean;
  right: boolean;
}

export function TableScroller({
  children,
  className,
  detailNoun = "detail",
}: TableScrollerProps) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState<Edges>({ left: false, right: false });

  const measure = useCallback(() => {
    const element = scrollerRef.current;
    if (element === null) {
      return;
    }
    // One pixel of slack: sub-pixel layout rounding otherwise reports a
    // table that fits exactly as permanently scrollable.
    const maxScroll = element.scrollWidth - element.clientWidth;
    setEdges({
      left: element.scrollLeft > 1,
      right: maxScroll - element.scrollLeft > 1,
    });
  }, []);

  useEffect(() => {
    measure();
    const element = scrollerRef.current;
    // jsdom has no ResizeObserver, and a browser that lacks it still gets
    // the window-resize path — neither is a reason to fail to render.
    if (element !== null && typeof ResizeObserver !== "undefined") {
      const observer = new ResizeObserver(measure);
      observer.observe(element);
      return () => observer.disconnect();
    }
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [measure, children]);

  return (
    <div className="relative">
      <div
        ref={scrollerRef}
        onScroll={measure}
        className={cn("overflow-x-auto", className)}
      >
        {children}
      </div>
      {edges.right && (
        <div
          aria-hidden="true"
          data-testid="table-scroll-edge"
          className="pointer-events-none absolute inset-y-0 right-0 w-10 bg-gradient-to-l from-card to-transparent"
        />
      )}
      {(edges.left || edges.right) && (
        <p className="border-t border-border/60 px-3 py-1.5 text-xs text-muted-foreground">
          Scroll sideways for more columns — every column is also on the{" "}
          {detailNoun} page.
        </p>
      )}
    </div>
  );
}
