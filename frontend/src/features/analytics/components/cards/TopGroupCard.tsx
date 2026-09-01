/**
 * "Most frequently seen types/models" and "most common operators" (SPEC
 * §58) — both `/api/v1/analytics/top-types` and `/top-operators` return the
 * identical `AnalyticsGroupRow` shape (`docs/API.md` §3.7: "key"/"label"
 * over a type designator or an operator group), so one horizontal-bar card
 * renders either, parameterized by title and which rows it was given —
 * SightingsPage-style reuse rather than two near-duplicate components.
 * Neither a type designator nor an operator group has its own detail route
 * in this app, so bars are not clickable (unlike {@link TopAircraftCard}).
 */
import { useCallback, useMemo } from "react";

import type { AnalyticsGroupRow, AnalyticsWindow } from "@/lib/api/analytics";

import { AnalyticsCard } from "@/features/analytics/components/AnalyticsCard";
import { EChart } from "@/features/analytics/components/EChart";
import type { ChartTheme } from "@/features/analytics/lib/chartTheme";

export interface TopGroupCardProps {
  title: string;
  ariaLabel: string;
  emptyLabel: string;
  window?: AnalyticsWindow;
  rows: AnalyticsGroupRow[];
  isLoading: boolean;
  error?: string;
}

function groupLabel(row: AnalyticsGroupRow): string {
  return row.label ?? row.key;
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
          axisLabel: { color: theme.ink },
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
          .map((row) => `${groupLabel(row)} (${row.sightings})`)
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
