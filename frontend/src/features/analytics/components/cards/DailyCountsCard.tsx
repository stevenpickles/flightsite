/**
 * "Daily aircraft count" and "daily sighting count" (SPEC §58) — two
 * distinct metrics, so two categorical series (not a magnitude gradient) as
 * lines/areas over the window's days.
 */
import { useCallback } from "react";

import type { AnalyticsDailyRow, AnalyticsWindow } from "@/lib/api/analytics";

import { AnalyticsCard } from "@/features/analytics/components/AnalyticsCard";
import { EChart } from "@/features/analytics/components/EChart";
import type { ChartTheme } from "@/features/analytics/lib/chartTheme";
import {
  formatCalendarDay,
  formatCompactNumber,
} from "@/features/analytics/lib/format";

export interface DailyCountsCardProps {
  window?: AnalyticsWindow;
  items: AnalyticsDailyRow[];
  isLoading: boolean;
  error?: string;
  errorDetail?: string;
  onRetry?: () => void;
}

export function DailyCountsCard({
  window,
  items,
  isLoading,
  error,
  errorDetail,
  onRetry,
}: DailyCountsCardProps) {
  const buildOption = useCallback(
    (theme: ChartTheme) => {
      if (items.length === 0) {
        return null;
      }
      const axisStyle = {
        axisLabel: { color: theme.mutedInk },
        axisLine: { lineStyle: { color: theme.grid } },
        splitLine: { lineStyle: { color: theme.grid } },
      };
      return {
        color: [theme.series[0], theme.series[1]],
        legend: {
          data: ["Aircraft", "Sightings"],
          top: 0,
          textStyle: { color: theme.mutedInk },
        },
        grid: { left: 8, right: 16, top: 32, bottom: 24, containLabel: true },
        tooltip: { trigger: "axis" as const },
        xAxis: {
          type: "category" as const,
          data: items.map((row) => row.day),
          ...axisStyle,
        },
        yAxis: {
          type: "value" as const,
          name: "count",
          nameTextStyle: { color: theme.mutedInk },
          axisLabel: {
            ...axisStyle.axisLabel,
            formatter: (value: number) => formatCompactNumber(value),
          },
          axisLine: axisStyle.axisLine,
          splitLine: axisStyle.splitLine,
        },
        series: [
          {
            name: "Aircraft",
            type: "line" as const,
            // A day not computed yet (R3-02/A1) is `null`, not a real zero
            // — a gap in the line, the same convention `MaxDistanceCard`
            // already uses for its own nullable field.
            data: items.map((row) => row.unique_aircraft),
            connectNulls: false,
            smooth: true,
            showSymbol: false,
          },
          {
            name: "Sightings",
            type: "line" as const,
            data: items.map((row) => row.sightings),
            connectNulls: false,
            smooth: true,
            showSymbol: false,
          },
        ],
      };
    },
    [items],
  );

  const summary =
    items.length === 0
      ? "No traffic recorded in this window."
      : `Daily aircraft and sighting counts across ${items.length} days: ` +
        `${items
          .map((row) =>
            // R3-02/A1: `complete: false` means every count below is `null`
            // ("not computed yet"), never a fabricated zero.
            row.complete
              ? `${formatCalendarDay(row.day)} — ${row.unique_aircraft} aircraft, ${row.sightings} sightings`
              : `${formatCalendarDay(row.day)} — not computed yet`,
          )
          .join("; ")}.`;

  return (
    <AnalyticsCard
      title="Daily aircraft & sighting counts"
      window={window}
      isLoading={isLoading}
      error={error}
      errorDetail={errorDetail}
      onRetry={onRetry}
    >
      <EChart
        buildOption={buildOption}
        ariaLabel="Daily aircraft and sighting counts, line chart"
        summary={summary}
      />
    </AnalyticsCard>
  );
}
