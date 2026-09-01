/**
 * The Sightings page's table — SPEC §57's columns. Server-side sort/pagination:
 * this component only renders the page it is given. Unlike the Aircraft
 * table, not every column has a documented sort key (§3.6 only sorts by
 * `started_at`/`duration_s`/`closest_approach_nm`/`max_range_nm`) — the rest
 * render as plain headers.
 */

import { useNavigate } from "react-router-dom";

import { UnknownValue } from "@/features/aircraft-detail/components/UnknownValue";
import { classificationSummary } from "@/features/aircraft-detail/lib/classificationSummary";
import {
  formatAltitude,
  formatDistance,
  formatReceiverLocalDateTime,
  formatReceiverLocalTime,
} from "@/features/aircraft-detail/lib/format";
import { AlertSeverityBadge } from "@/features/sightings/components/AlertSeverityBadge";
import { ClosureReasonTooltip } from "@/features/sightings/components/ClosureReasonTooltip";
import { formatSightingDuration } from "@/features/sightings/lib/format";
import type {
  SightingRow,
  SightingSortKey,
  SortOrder,
} from "@/lib/api/sightings";
import type { UnitSystem } from "@/lib/api/config";
import { cn } from "@/lib/utils";

interface Column {
  key: string;
  label: string;
  sortKey?: SightingSortKey;
  align?: "right";
}

const COLUMNS: readonly Column[] = [
  { key: "started_at", label: "Start", sortKey: "started_at" },
  { key: "ended_at", label: "End" },
  {
    key: "duration_s",
    label: "Duration",
    sortKey: "duration_s",
    align: "right",
  },
  { key: "tail", label: "Tail / callsign" },
  { key: "type", label: "Type" },
  { key: "operator", label: "Operator" },
  { key: "classification", label: "Classification" },
  {
    key: "closest_approach_nm",
    label: "Closest approach",
    sortKey: "closest_approach_nm",
    align: "right",
  },
  {
    key: "max_range_nm",
    label: "Max range",
    sortKey: "max_range_nm",
    align: "right",
  },
  { key: "lowest_altitude_ft", label: "Lowest alt.", align: "right" },
  { key: "highest_altitude_ft", label: "Highest alt.", align: "right" },
  { key: "position_count", label: "Positions", align: "right" },
  { key: "status", label: "Status" },
];

export interface SightingsTableProps {
  rows: SightingRow[];
  sort: SightingSortKey;
  order: SortOrder;
  onSortChange: (key: SightingSortKey) => void;
  units: UnitSystem;
  timezone: string;
  refreshing?: boolean;
}

export function SightingsTable({
  rows,
  sort,
  order,
  onSortChange,
  units,
  timezone,
  refreshing = false,
}: SightingsTableProps) {
  const navigate = useNavigate();

  return (
    <div
      className={cn(
        "overflow-x-auto transition-opacity",
        refreshing && "opacity-60",
      )}
    >
      <table className="w-full min-w-[1100px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
            {COLUMNS.map((column) => {
              const active =
                column.sortKey !== undefined && column.sortKey === sort;
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
                  {column.sortKey === undefined ? (
                    column.label
                  ) : (
                    <button
                      type="button"
                      onClick={() =>
                        onSortChange(column.sortKey as SightingSortKey)
                      }
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
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.id}
              onClick={() => navigate(`/sightings/${row.id}`)}
              className="cursor-pointer border-b border-border/60 hover:bg-secondary/50"
            >
              <td className="px-3 py-2 whitespace-nowrap">
                {formatReceiverLocalDateTime(row.started_at, timezone)}
              </td>
              <td className="px-3 py-2 whitespace-nowrap">
                {row.ended_at === null ? (
                  <span className="font-medium text-accent">Ongoing</span>
                ) : (
                  formatReceiverLocalTime(row.ended_at, timezone)
                )}
              </td>
              <td className="px-3 py-2 text-right whitespace-nowrap">
                {row.duration_s === null ? (
                  <UnknownValue />
                ) : (
                  formatSightingDuration(row.duration_s)
                )}
              </td>
              <td className="px-3 py-2">
                {row.registration ?? row.callsign ?? <UnknownValue />}
                {row.registration !== null && row.callsign !== null && (
                  <span className="block text-xs text-muted-foreground">
                    {row.callsign}
                  </span>
                )}
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
              <td className="px-3 py-2 text-right">
                {formatDistance(row.closest_approach_nm, units) ?? (
                  <UnknownValue />
                )}
              </td>
              <td className="px-3 py-2 text-right">
                {formatDistance(row.max_range_nm, units) ?? <UnknownValue />}
              </td>
              <td className="px-3 py-2 text-right">
                {formatAltitude(row.lowest_altitude_ft, units) ?? (
                  <UnknownValue />
                )}
              </td>
              <td className="px-3 py-2 text-right">
                {formatAltitude(row.highest_altitude_ft, units) ?? (
                  <UnknownValue />
                )}
              </td>
              <td className="px-3 py-2 text-right">{row.position_count}</td>
              <td className="px-3 py-2">
                <div className="flex flex-wrap items-center gap-1">
                  {row.max_alert_severity !== null && (
                    <AlertSeverityBadge severity={row.max_alert_severity} />
                  )}
                  {row.had_emergency && (
                    <span
                      role="status"
                      className="inline-flex items-center rounded-full border border-destructive bg-destructive/10 px-2 py-0.5 text-xs font-semibold text-destructive"
                    >
                      Emergency
                    </span>
                  )}
                  {row.closure_reason !== null && (
                    <ClosureReasonTooltip reason={row.closure_reason} />
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
