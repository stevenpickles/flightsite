/**
 * Column priority for the two history tables (review R2-08, R2-13).
 *
 * The answer to "which columns collapse at 390px?" used to be *none*: both
 * tables carried a hard `min-w-[900px]`/`min-w-[1100px]` and no breakpoint
 * at any width, so a phone showed one and a half of ten columns inside a
 * 3.2x nested horizontal scroller, and a 1440x900 desktop could not see
 * `/sightings`' Status column at all.
 *
 * A column declares the narrowest width at which it earns its place. The
 * essential few — identity, time, and the one distance that answers "how
 * close did it get?" — are always shown; everything else appears as the
 * window grows and, when hidden, is still reachable one click away on the
 * row's own detail page. Nothing is ever *removed* from the product by a
 * breakpoint; it is only moved to where there is room for it.
 */

import { cn } from "@/lib/utils";

/** Tailwind's breakpoints, by the name a column uses to ask for one. */
export type ColumnBreakpoint = "sm" | "md" | "lg" | "xl" | "2xl";

/** Spelled out rather than interpolated: Tailwind only emits a class it can
 * see literally in the source. */
const HIDDEN_BELOW: Record<ColumnBreakpoint, string> = {
  sm: "hidden sm:table-cell",
  md: "hidden md:table-cell",
  lg: "hidden lg:table-cell",
  xl: "hidden xl:table-cell",
  "2xl": "hidden 2xl:table-cell",
};

export interface PrioritizedColumn {
  align?: "right";
  /** The narrowest breakpoint at which this column is shown. Absent means
   * "always" — the essential set. */
  showFrom?: ColumnBreakpoint;
}

/** The classes a column's header *and* its body cells must share, so the two
 * can never disagree about whether the column is on screen. */
export function columnVisibilityClass(column: PrioritizedColumn): string {
  return cn(
    column.align === "right" && "text-right",
    column.showFrom !== undefined && HIDDEN_BELOW[column.showFrom],
  );
}

/** Builds the `key -> classes` lookup a table's body cells read, from the
 * same column list its header renders. One source, two users. */
export function columnClasses<Key extends string>(
  columns: readonly (PrioritizedColumn & { key: Key })[],
): Record<Key, string> {
  const entries = columns.map(
    (column) => [column.key, columnVisibilityClass(column)] as const,
  );
  return Object.fromEntries(entries) as Record<Key, string>;
}
