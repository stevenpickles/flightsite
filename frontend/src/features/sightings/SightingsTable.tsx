/**
 * The Sightings page's table — SPEC §57's columns. Server-side sort/pagination:
 * this component only renders the page it is given. Unlike the Aircraft
 * table, not every column has a documented sort key (§3.6 only sorts by
 * `started_at`/`duration_s`/`closest_approach_nm`/`max_range_nm`) — the rest
 * render as plain headers.
 */

import { Link, useNavigate } from "react-router-dom";

import { ReceiverTime } from "@/features/aircraft-detail/components/ReceiverTime";
import { UnknownValue } from "@/features/aircraft-detail/components/UnknownValue";
import { classificationSummary } from "@/features/aircraft-detail/lib/classificationSummary";
import {
  formatAltitude,
  formatDistance,
} from "@/features/aircraft-detail/lib/format";
import { TableScroller } from "@/features/history/components/TableScroller";
import {
  columnClasses,
  columnVisibilityClass,
  type PrioritizedColumn,
} from "@/features/history/lib/columnPriority";
import { AlertSeverityBadge } from "@/features/sightings/components/AlertSeverityBadge";
import { ClosureReasonTooltip } from "@/features/sightings/components/ClosureReasonTooltip";
import {
  formatOpenSightingDuration,
  formatSightingDuration,
} from "@/features/sightings/lib/format";
import type {
  SightingRow,
  SightingSortKey,
  SortOrder,
} from "@/lib/api/sightings";
import type { UnitSystem } from "@/lib/api/config";
import { cn } from "@/lib/utils";

interface Column extends PrioritizedColumn {
  key: string;
  label: string;
  sortKey?: SightingSortKey;
}

/**
 * SPEC §57's columns, each declaring the narrowest window at which it earns
 * its width (review R2-08, R2-13).
 *
 * Status is essential and stays essential: it is §57's alert/interesting
 * column, it answers "was anything interesting?", and it was the one a
 * standard 1440x900 desktop could not see — 98px of it clipped past the
 * right edge of a scroller with no visible scrollbar. The four columns that
 * were costing it that width (classification, both altitudes, position
 * count) now wait for `2xl`, which is what brings Status back on screen at
 * 1440. None of them is lost: every one is on the sighting's own page.
 */
const COLUMNS: readonly Column[] = [
  { key: "started_at", label: "Start", sortKey: "started_at" },
  { key: "ended_at", label: "End" },
  {
    key: "duration_s",
    label: "Duration",
    sortKey: "duration_s",
    align: "right",
    showFrom: "sm",
  },
  { key: "tail", label: "Tail / callsign" },
  { key: "type", label: "Type", showFrom: "md" },
  { key: "operator", label: "Operator", showFrom: "lg" },
  { key: "classification", label: "Classification", showFrom: "2xl" },
  {
    key: "closest_approach_nm",
    label: "Closest approach",
    sortKey: "closest_approach_nm",
    align: "right",
    showFrom: "sm",
  },
  {
    key: "max_range_nm",
    label: "Max range",
    sortKey: "max_range_nm",
    align: "right",
    showFrom: "lg",
  },
  {
    key: "lowest_altitude_ft",
    label: "Lowest alt.",
    align: "right",
    showFrom: "2xl",
  },
  {
    key: "highest_altitude_ft",
    label: "Highest alt.",
    align: "right",
    showFrom: "2xl",
  },
  {
    key: "position_count",
    label: "Positions",
    align: "right",
    showFrom: "2xl",
  },
  { key: "status", label: "Status" },
];

const CELL = columnClasses(COLUMNS);

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
    <TableScroller
      className={cn("transition-opacity", refreshing && "opacity-60")}
      detailNoun="sighting's"
    >
      {/* No fixed `min-w`: thirteen columns forced 1100px at every width,
       * which is what pushed Status off a 1440px desktop and left a phone
       * scrolling 3.2x sideways. */}
      <table className="w-full border-collapse text-sm">
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
                    columnVisibilityClass(column),
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
              // As on the Aircraft table: the Start cell's anchor carries
              // the id too, but only in its href, so this keeps a stable
              // hook for the E2E suite to address one specific row by.
              data-testid="sighting-row"
              data-sighting-id={row.id}
              // The aircraft identity too: a row displays registration or
              // callsign, either of which may be absent and neither of which
              // is unique, so the ICAO — the one identifier every aircraft
              // has — is otherwise absent from this page's DOM entirely.
              data-icao={row.icao}
              onClick={() => navigate(`/sightings/${row.id}`)}
              className="cursor-pointer border-b border-border/60 hover:bg-secondary/50"
            >
              {/* The Start cell is this row's anchor, exactly as Tail is on
               * the Aircraft table. Before it existed the row carried no
               * focusable element at all, so a keyboard or screen-reader
               * user could not open *any* sighting from the log (review
               * R2-07). The row's own click handler stays for the mouse. */}
              <td
                className={cn("px-3 py-2 whitespace-nowrap", CELL.started_at)}
              >
                <Link
                  to={`/sightings/${row.id}`}
                  onClick={(event) => event.stopPropagation()}
                  className="font-medium text-accent hover:underline"
                >
                  <ReceiverTime iso={row.started_at} timezone={timezone} />
                </Link>
              </td>
              <td className={cn("px-3 py-2 whitespace-nowrap", CELL.ended_at)}>
                {row.ended_at === null ? (
                  <span className="font-medium text-accent">Ongoing</span>
                ) : (
                  <ReceiverTime
                    iso={row.ended_at}
                    timezone={timezone}
                    format="time"
                  />
                )}
              </td>
              <td
                className={cn("px-3 py-2 whitespace-nowrap", CELL.duration_s)}
              >
                {/* An open sighting has no *recorded* duration, which is not
                 * the same as an unknown one — both ends are known, one of
                 * them is "now" (review R2-02). */}
                {row.open ? (
                  <span className="text-accent">
                    {formatOpenSightingDuration(row.elapsed_s)}
                  </span>
                ) : row.duration_s === null ? (
                  <UnknownValue />
                ) : (
                  formatSightingDuration(row.duration_s)
                )}
              </td>
              <td className={cn("px-3 py-2", CELL.tail)}>
                {row.registration ?? row.callsign ?? <UnknownValue />}
                {row.registration !== null && row.callsign !== null && (
                  <span className="block text-xs text-muted-foreground">
                    {row.callsign}
                  </span>
                )}
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
              <td className={cn("px-3 py-2", CELL.closest_approach_nm)}>
                {formatDistance(row.closest_approach_nm, units) ?? (
                  <UnknownValue />
                )}
              </td>
              <td className={cn("px-3 py-2", CELL.max_range_nm)}>
                {formatDistance(row.max_range_nm, units) ?? <UnknownValue />}
              </td>
              <td className={cn("px-3 py-2", CELL.lowest_altitude_ft)}>
                {formatAltitude(row.lowest_altitude_ft, units) ?? (
                  <UnknownValue />
                )}
              </td>
              <td className={cn("px-3 py-2", CELL.highest_altitude_ft)}>
                {formatAltitude(row.highest_altitude_ft, units) ?? (
                  <UnknownValue />
                )}
              </td>
              <td className={cn("px-3 py-2", CELL.position_count)}>
                {row.position_count}
              </td>
              <td className={cn("px-3 py-2", CELL.status)}>
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
    </TableScroller>
  );
}
