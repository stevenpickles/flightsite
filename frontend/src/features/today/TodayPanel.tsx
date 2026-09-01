/**
 * "Today at a glance" (SPEC §59, roadmap slice 036): a compact, collapsible
 * card on the Live Map summarizing the receiver's local day — unique
 * aircraft, sightings, interesting aircraft, military/government/police,
 * maximum range, busiest hour, new aircraft, and new milestones/records —
 * all read from `GET /api/v1/analytics/summary` (roadmap slice 031's
 * endpoint, extended here with `new_milestones`).
 *
 * Follows the `ActivityPanel`/`NonPositionedPanel` idiom (collapsed by
 * default, header button carrying `aria-expanded`, a badge visible even
 * collapsed, a bordered body once expanded), but takes the one corner none
 * of them do: `left-1/2 top-3` with `-translate-x-1/2`, a top-center strip
 * beside `ConnectionStatusChip` (`left-3 top-3`) rather than stacked in any
 * of the four corners those panels already occupy. The map stays the hero —
 * collapsed, this is a single-line strip; expanded, a stat-tile row that
 * wraps under the map's own width rather than a modal over it.
 *
 * "Today" is the receiver's local calendar day, not the browser's
 * (`docs/API.md` §3.7): `useReceiverLocalDate` (`features/today/lib/localDay.ts`)
 * recomputes that date against the receiver's zone and feeds it into the
 * query key, so a local-midnight rollover — which does not happen at the
 * same wall-clock moment for a viewer in another timezone — forces a fresh
 * fetch instead of the card quietly showing yesterday's figures past
 * midnight.
 */

import { ChevronDown, ChevronUp } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { StatTile } from "@/features/today/components/StatTile";
import {
  formatCount,
  formatDistance,
  formatHourRange,
} from "@/features/today/lib/format";
import { useReceiverLocalDate } from "@/features/today/lib/localDay";
import { useAnalyticsSummaryQuery } from "@/lib/api/analytics";
import { useReceiverQuery } from "@/lib/api/receiver";

export function TodayPanel() {
  const [isExpanded, setIsExpanded] = useState(false);
  const receiverQuery = useReceiverQuery();
  const timezone = receiverQuery.data?.timezone ?? "UTC";
  const units = receiverQuery.data?.units ?? "aviation";
  const localDate = useReceiverLocalDate(timezone);
  const summaryQuery = useAnalyticsSummaryQuery({ preset: "today" }, localDate);
  const summary = summaryQuery.data?.summary;

  return (
    <div
      data-testid="today-panel"
      className="absolute left-1/2 top-3 z-10 w-[min(36rem,92vw)] -translate-x-1/2 overflow-hidden rounded-lg border border-border bg-card/95 shadow-md backdrop-blur-sm"
    >
      <button
        type="button"
        aria-expanded={isExpanded}
        onClick={() => setIsExpanded((expanded) => !expanded)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-xs font-medium"
      >
        <span className="flex items-center gap-1.5">
          Today
          {summary !== undefined && (
            <span
              data-testid="today-sightings-badge"
              className="inline-flex min-w-4 items-center justify-center rounded-full bg-secondary px-1.5 text-[10px] font-semibold text-secondary-foreground"
            >
              {formatCount(summary.sightings)} sightings
            </span>
          )}
        </span>
        {isExpanded ? (
          <ChevronUp className="size-3.5" aria-hidden="true" />
        ) : (
          <ChevronDown className="size-3.5" aria-hidden="true" />
        )}
      </button>

      {isExpanded && (
        <div className="border-t border-border p-2.5">
          {summaryQuery.isPending ? (
            <p className="px-0.5 py-1 text-xs text-muted-foreground">
              Loading…
            </p>
          ) : summaryQuery.isError ? (
            <p className="px-0.5 py-1 text-xs text-destructive">
              Could not load today&apos;s summary: {summaryQuery.error.message}
            </p>
          ) : summary === undefined ? null : (
            <div
              role="group"
              aria-label="Today at a glance"
              className="grid grid-cols-2 gap-2 sm:grid-cols-4"
            >
              <StatTile
                label="Unique aircraft"
                value={formatCount(summary.unique_aircraft)}
              />
              <StatTile
                label="Sightings"
                value={formatCount(summary.sightings)}
              />
              <StatTile
                label="Interesting"
                value={formatCount(summary.interesting)}
              />
              <StatTile
                label="Mil / gov / police"
                value={`${summary.military} / ${summary.government} / ${summary.law_enforcement}`}
              />
              <StatTile
                label="Max range"
                value={formatDistance(summary.max_range_nm, units) ?? "—"}
              />
              <StatTile
                label="Busiest hour"
                value={formatHourRange(summary.busiest_hour)}
              />
              <StatTile
                label="New aircraft"
                value={formatCount(summary.new_aircraft)}
              />
              <Link
                to="/activity"
                data-testid="today-milestones-link"
                className="rounded-md border border-border bg-card p-2.5 text-card-foreground outline-none transition-colors hover:bg-secondary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
              >
                <p className="text-[11px] text-muted-foreground">
                  New milestones
                </p>
                <p className="mt-0.5 text-lg font-semibold tabular-nums">
                  {formatCount(summary.new_milestones)}
                </p>
              </Link>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
