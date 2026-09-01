/**
 * The Aircraft page's sortable table — SPEC §56's ten columns, each mapped
 * to one of `docs/API.md` §3.5's documented sort keys 1:1. Server-side
 * sort/pagination: this component only renders the page it is given and
 * reports sort-header clicks upward, it never sorts or slices client-side.
 */

import { Link, useNavigate } from "react-router-dom";

import { UnknownValue } from "@/features/aircraft-detail/components/UnknownValue";
import { classificationSummary } from "@/features/aircraft-detail/lib/classificationSummary";
import {
  formatDistance,
  formatReceiverLocalDateTime,
} from "@/features/aircraft-detail/lib/format";
import type {
  AircraftListRow,
  AircraftSortKey,
  SortOrder,
} from "@/lib/api/aircraft";
import type { UnitSystem } from "@/lib/api/config";
import { cn } from "@/lib/utils";

interface Column {
  key: AircraftSortKey;
  label: string;
  align?: "right";
}

const COLUMNS: readonly Column[] = [
  { key: "registration", label: "Tail" },
  { key: "icao", label: "ICAO" },
  { key: "type", label: "Type / model" },
  { key: "operator", label: "Operator" },
  { key: "classification", label: "Classification" },
  { key: "first_seen", label: "First seen" },
  { key: "last_seen", label: "Last seen" },
  { key: "sighting_count", label: "Sightings", align: "right" },
  { key: "closest_approach_nm", label: "Closest approach", align: "right" },
  { key: "max_range_nm", label: "Farthest detection", align: "right" },
];

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
    <div
      className={cn(
        "overflow-x-auto transition-opacity",
        refreshing && "opacity-60",
      )}
    >
      <table className="w-full min-w-[900px] border-collapse text-sm">
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
                    column.align === "right" && "text-right",
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
              onClick={() => navigate(`/aircraft/${row.icao}`)}
              className="cursor-pointer border-b border-border/60 hover:bg-secondary/50"
            >
              <td className="px-3 py-2">
                <Link
                  to={`/aircraft/${row.icao}`}
                  onClick={(event) => event.stopPropagation()}
                  className="font-medium text-accent hover:underline"
                >
                  {row.registration ?? <UnknownValue />}
                </Link>
              </td>
              <td className="px-3 py-2 font-mono text-xs">
                {row.icao.toUpperCase()}
              </td>
              <td className="px-3 py-2">
                {row.aircraft_type ?? <UnknownValue />}
                {row.model !== null && (
                  <span className="block text-xs text-muted-foreground">
                    {row.model}
                  </span>
                )}
              </td>
              <td className="px-3 py-2">{row.operator ?? <UnknownValue />}</td>
              <td className="px-3 py-2">
                {classificationSummary(row.classification) ?? <UnknownValue />}
              </td>
              <td className="px-3 py-2 whitespace-nowrap">
                {formatReceiverLocalDateTime(row.first_seen, timezone)}
              </td>
              <td className="px-3 py-2 whitespace-nowrap">
                {formatReceiverLocalDateTime(row.last_seen, timezone)}
              </td>
              <td className="px-3 py-2 text-right">{row.sighting_count}</td>
              <td className="px-3 py-2 text-right">
                {formatDistance(row.closest_approach_nm, units) ?? (
                  <UnknownValue />
                )}
              </td>
              <td className="px-3 py-2 text-right">
                {formatDistance(row.max_range_nm, units) ?? <UnknownValue />}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
