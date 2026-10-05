/**
 * A column header that sorts its table: one click sorts by the column, a
 * second reverses it. Shared by the Sightings page's three tables (the log,
 * the distinct aircraft, the distinct types) so a header behaves the same on
 * all of them (slice 100).
 *
 * The state is announced, not just drawn: `aria-sort` on the `<th>` says
 * which column orders the table and which way, and the arrow beside the
 * label is the visible form of the same fact. A header that does not sort
 * renders as plain text with `aria-sort` absent — "none" is reserved for a
 * column that *could* order the table and currently does not.
 */
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type SortDirection = "asc" | "desc";

export interface SortableHeaderProps<Key extends string> {
  /** The sort key this column orders by, or `undefined` for a column that
   * does not sort. */
  sortKey?: Key;
  /** The table's current sort. */
  sort: string;
  order: SortDirection;
  onSortChange?: (key: Key) => void;
  align?: "left" | "right";
  /** Extra classes for the `<th>` — the responsive visibility of a column. */
  className?: string;
  children: ReactNode;
}

export function SortableHeader<Key extends string>({
  sortKey,
  sort,
  order,
  onSortChange,
  align = "left",
  className,
  children,
}: SortableHeaderProps<Key>) {
  const sortable = sortKey !== undefined && onSortChange !== undefined;
  const active = sortable && sortKey === sort;
  return (
    <th
      scope="col"
      aria-sort={
        sortable
          ? active
            ? order === "asc"
              ? "ascending"
              : "descending"
            : "none"
          : undefined
      }
      className={cn(
        "px-3 py-2 font-semibold",
        align === "right" && "text-right",
        className,
      )}
    >
      {sortable ? (
        <button
          type="button"
          onClick={() => onSortChange(sortKey)}
          className={cn(
            // Inherits the header's own case and tracking, so a sortable
            // heading reads as a heading that happens to be clickable.
            "inline-flex items-center gap-1 uppercase tracking-wide outline-none hover:text-foreground",
            "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
            active && "text-foreground",
          )}
        >
          {children}
          {/* Always present so the header does not change width when it
           * becomes the sort column; invisible until it is. */}
          <span aria-hidden="true" className={cn(!active && "invisible")}>
            {active && order === "asc" ? "▲" : "▼"}
          </span>
        </button>
      ) : (
        children
      )}
    </th>
  );
}
