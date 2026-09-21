/**
 * The Aircraft page's sortable table — SPEC §56's ten columns, each mapped
 * to one of `docs/API.md` §3.5's documented sort keys 1:1. Server-side
 * sort/pagination: this component only renders the page it is given and
 * reports sort-header clicks upward, it never sorts or slices client-side.
 */

import { Link, useNavigate } from "react-router-dom";

import { ReceiverTime } from "@/features/aircraft-detail/components/ReceiverTime";
import { UnknownValue } from "@/features/aircraft-detail/components/UnknownValue";
import { classificationSummary } from "@/features/aircraft-detail/lib/classificationSummary";
import { formatDistance } from "@/features/aircraft-detail/lib/format";
import { TableScroller } from "@/features/history/components/TableScroller";
import {
  columnClasses,
  columnVisibilityClass,
  type PrioritizedColumn,
} from "@/features/history/lib/columnPriority";
import type {
  AircraftListRow,
  AircraftSortKey,
  SortOrder,
} from "@/lib/api/aircraft";
import type { UnitSystem } from "@/lib/api/config";
import { cn } from "@/lib/utils";

interface Column extends PrioritizedColumn {
  key: AircraftSortKey;
  label: string;
}

/**
 * SPEC §56's ten columns, each declaring the narrowest window at which it
 * earns its width (review R2-08).
 *
 * The four with no `showFrom` are what a phone gets: who it was, its
 * address, when it was last heard, and how close it came — identity, time
 * and distance, which the review named as the question the page is actually
 * asked. Everything hidden is one click away on `/aircraft/:icao`.
 */
const COLUMNS: readonly Column[] = [
  { key: "registration", label: "Tail" },
  { key: "icao", label: "ICAO" },
  { key: "type", label: "Type / model", showFrom: "md" },
  { key: "operator", label: "Operator", showFrom: "lg" },
  { key: "classification", label: "Classification", showFrom: "xl" },
  { key: "first_seen", label: "First seen", showFrom: "lg" },
  { key: "last_seen", label: "Last seen" },
  {
    key: "sighting_count",
    label: "Sightings",
    align: "right",
    showFrom: "md",
  },
  { key: "closest_approach_nm", label: "Closest approach", align: "right" },
  {
    key: "max_range_nm",
    label: "Farthest detection",
    align: "right",
    showFrom: "sm",
  },
];

const CELL = columnClasses(COLUMNS);

export interface AircraftTableProps {
  rows: AircraftListRow[];
  sort: AircraftSortKey;
  order: SortOrder;
  onSortChange: (key: AircraftSortKey) => void;
  units: UnitSystem;
  timezone: string;
  /** Dims the table while a new page/sort is loading behind the previously
   * shown rows (`placeholderData: keepPreviousData`), without unmounting
   * anything — a flicker to empty would be worse than a stale table. */
  refreshing?: boolean;
}

export function AircraftTable({
  rows,
  sort,
  order,
  onSortChange,
  units,
  timezone,
  refreshing = false,
}: AircraftTableProps) {
  const navigate = useNavigate();

  return (
    <TableScroller
      className={cn("transition-opacity", refreshing && "opacity-60")}
      detailNoun="aircraft"
    >
      {/* No fixed `min-w`: the columns that would have forced 900px of
       * horizontal scrolling on a phone are hidden there instead, and the
       * scroller is the floor for the cases the breakpoints cannot cover —
       * an unusually long operator name, a very narrow window. */}
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
            {COLUMNS.map((column) => {
              const active = column.key === sort;
              return (
                <th
                  key={column.key}
                  scope="col"
                  aria-sort={
                    active
                      ? order === "asc"
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                  className={cn(
                    "px-3 py-2 font-semibold",
                    columnVisibilityClass(column),
                  )}
                >
                  <button
                    type="button"
                    onClick={() => onSortChange(column.key)}
                    className={cn(
                      "inline-flex items-center gap-1 outline-none hover:text-foreground",
                      "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                      active && "text-foreground",
                    )}
                  >
                    {column.label}
                    {active && (
                      <span aria-hidden="true">
                        {order === "asc" ? "▲" : "▼"}
                      </span>
                    )}
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.icao}
              // The row carries its own identity for the E2E suite: the whole
              // row navigates on click, but only the first cell holds an
              // anchor, so without this a test can address a specific
              // aircraft's row only through rendered text (registrations
              // repeat, and every absent field renders the same "Unknown").
              data-testid="aircraft-row"
              data-icao={row.icao}
              onClick={() => navigate(`/aircraft/${row.icao}`)}
              className="cursor-pointer border-b border-border/60 hover:bg-secondary/50"
            >
              <td className={cn("px-3 py-2", CELL.registration)}>
                <Link
                  to={`/aircraft/${row.icao}`}
                  onClick={(event) => event.stopPropagation()}
                  className="font-medium text-accent hover:underline"
                >
                  {row.registration ?? <UnknownValue />}
                </Link>
              </td>
              <td className={cn("px-3 py-2 font-mono text-xs", CELL.icao)}>
                {row.icao.toUpperCase()}
              </td>
              <td className={cn("px-3 py-2", CELL.type)}>
                {row.aircraft_type ?? <UnknownValue />}
                {row.model !== null && (
                  <span className="block text-xs text-muted-foreground">
                    {row.model}
                  </span>
                )}
              </td>
              <td className={cn("px-3 py-2", CELL.operator)}>
                {row.operator ?? <UnknownValue />}
              </td>
              <td className={cn("px-3 py-2", CELL.classification)}>
                {classificationSummary(row.classification) ?? <UnknownValue />}
              </td>
              <td
                className={cn("px-3 py-2 whitespace-nowrap", CELL.first_seen)}
              >
                <ReceiverTime iso={row.first_seen} timezone={timezone} />
              </td>
              <td className={cn("px-3 py-2 whitespace-nowrap", CELL.last_seen)}>
                <ReceiverTime iso={row.last_seen} timezone={timezone} />
              </td>
              <td className={cn("px-3 py-2", CELL.sighting_count)}>
                {row.sighting_count}
              </td>
              <td className={cn("px-3 py-2", CELL.closest_approach_nm)}>
                {formatDistance(row.closest_approach_nm, units) ?? (
                  <UnknownValue />
                )}
              </td>
              <td className={cn("px-3 py-2", CELL.max_range_nm)}>
                {formatDistance(row.max_range_nm, units) ?? <UnknownValue />}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableScroller>
  );
}
