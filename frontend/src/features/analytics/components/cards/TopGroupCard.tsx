/**
 * "Most frequently seen types/models" and "most common operators" (SPEC
 * §58) — both `/api/v1/analytics/top-types` and `/top-operators` return the
 * identical `AnalyticsGroupRow` shape (`docs/API.md` §3.8: "key"/"label"
 * over a type designator or an operator group), so one horizontal-bar card
 * renders either, parameterized by title and which rows it was given —
 * SightingsPage-style reuse rather than two near-duplicate components.
 * Neither a type designator nor an operator group has its own detail route
 * in this app, so bars are not clickable (unlike {@link TopAircraftCard}).
 *
 * A row's `description` — the long form behind a type designator's
 * shorthand, "Boeing 737-800" beside "B738" — is shown as a muted second
 * segment of the axis label (truncated so the bars keep their room) and in
 * full in the tooltip (slice 074). Operator rows carry no description, so
 * that card renders exactly as before.
 */
import { useCallback, useMemo } from "react";

import type { AnalyticsGroupRow, AnalyticsWindow } from "@/lib/api/analytics";

import { AnalyticsCard } from "@/features/analytics/components/AnalyticsCard";
import { EChart } from "@/features/analytics/components/EChart";
import type { ChartTheme } from "@/features/analytics/lib/chartTheme";
import {
  formatCompactNumber,
  formatSightings,
  tooltipLines,
  truncateLabel,
} from "@/features/analytics/lib/format";

export interface TopGroupCardProps {
  title: string;
  ariaLabel: string;
  emptyLabel: string;
  window?: AnalyticsWindow;
  rows: AnalyticsGroupRow[];
  isLoading: boolean;
  error?: string;
}

/** How much of a description the axis shows before the tooltip takes over:
 * enough for "Boeing 737-800" or "Airbus A320-232" whole, short enough that
 * a ten-row card at the grid's narrowest column keeps most of its width
 * for the bars. */
const AXIS_DESCRIPTION_CHARS = 24;

function groupLabel(row: AnalyticsGroupRow): string {
  return row.label ?? row.key;
}

/** `"B738 Boeing 737-800"` or just `"B738"` — one row of the accessible
 * summary. */
function groupSummary(row: AnalyticsGroupRow): string {
  return row.description === null
    ? groupLabel(row)
    : `${groupLabel(row)} ${row.description}`;
}

/** `"9 sightings · 3 aircraft · 5 days"`; the day count is omitted for a
 * since-T0 type ranking, which reports `days_seen: 0` because it is read
 * from lifetime totals rather than daily rows. */
function groupFigures(row: AnalyticsGroupRow): string {
  const parts = [
    formatSightings(row.sightings),
    `${formatCompactNumber(row.unique_aircraft)} aircraft`,
  ];
  if (row.days_seen > 0) {
    parts.push(`${row.days_seen} ${row.days_seen === 1 ? "day" : "days"}`);
  }
  return parts.join(" · ");
}

/** ECharts hands an axis-trigger tooltip every series' point for the hovered
 * category; the first one's `dataIndex` is the row. */
function hoveredIndex(params: unknown): number | undefined {
  const first = Array.isArray(params) ? params[0] : params;
  if (typeof first !== "object" || first === null) {
    return undefined;
  }
  const { dataIndex } = first as { dataIndex?: unknown };
  return typeof dataIndex === "number" ? dataIndex : undefined;
}

export function TopGroupCard({
  title,
  ariaLabel,
  emptyLabel,
  window,
  rows,
  isLoading,
  error,
}: TopGroupCardProps) {
  // Reversed so the highest-ranked row (the backend's own sort) ends up at
  // the top of the horizontal bar — ECharts draws a category axis's first
  // entry lowest.
  const ordered = useMemo(() => [...rows].reverse(), [rows]);

  const buildOption = useCallback(
    (theme: ChartTheme) => {
      if (ordered.length === 0) {
        return null;
      }
      return {
        color: [theme.series[0]],
        grid: { left: 8, right: 24, top: 8, bottom: 24, containLabel: true },
        tooltip: {
          trigger: "axis" as const,
          axisPointer: { type: "shadow" as const },
          formatter: (params: unknown) => {
            const index = hoveredIndex(params);
            const row = index === undefined ? undefined : ordered[index];
            if (!row) {
              return "";
            }
            return tooltipLines([
              groupLabel(row),
              row.description,
              groupFigures(row),
            ]);
          },
        },
        xAxis: {
          type: "value" as const,
          axisLabel: { color: theme.mutedInk },
          axisLine: { lineStyle: { color: theme.grid } },
          splitLine: { lineStyle: { color: theme.grid } },
        },
        yAxis: {
          type: "category" as const,
          data: ordered.map(groupLabel),
          axisLabel: {
            color: theme.ink,
            formatter: (value: string, index: number) => {
              const description = ordered[index]?.description ?? null;
              return description === null
                ? `{ident|${value}}`
                : `{ident|${value}}  {desc|${truncateLabel(description, AXIS_DESCRIPTION_CHARS)}}`;
            },
            rich: {
              ident: { color: theme.ink },
              desc: { color: theme.mutedInk, fontSize: 11 },
            },
          },
          axisLine: { lineStyle: { color: theme.grid } },
        },
        series: [
          {
            type: "bar" as const,
            data: ordered.map((row) => row.sightings),
            barMaxWidth: 18,
          },
        ],
      };
    },
    [ordered],
  );

  const summary =
    rows.length === 0
      ? emptyLabel
      : `${title}: ${rows
          .map((row) => `${groupSummary(row)} (${row.sightings})`)
          .join(", ")}.`;

  return (
    <AnalyticsCard
      title={title}
      window={window}
      isLoading={isLoading}
      error={error}
    >
      <EChart
        buildOption={buildOption}
        ariaLabel={ariaLabel}
        summary={summary}
      />
    </AnalyticsCard>
  );
}
