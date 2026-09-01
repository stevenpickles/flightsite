/**
 * "Military/government/police activity over time" (SPEC §58) —
 * `GET /api/v1/analytics/classification-activity`'s per-day series as a
 * stacked bar: three fixed-order categorical series (never reassigned by
 * which classification happens to be busiest), legend always shown for
 * three series so identity never rides on color alone.
 */
import { useCallback } from "react";

import type { AnalyticsDailyRow, AnalyticsWindow } from "@/lib/api/analytics";

import { AnalyticsCard } from "@/features/analytics/components/AnalyticsCard";
import { EChart } from "@/features/analytics/components/EChart";
import type { ChartTheme } from "@/features/analytics/lib/chartTheme";

export interface ClassificationActivityCardProps {
  window?: AnalyticsWindow;
  series: AnalyticsDailyRow[];
  isLoading: boolean;
  error?: string;
}

export function ClassificationActivityCard({
  window,
  series,
  isLoading,
  error,
}: ClassificationActivityCardProps) {
  const buildOption = useCallback(
    (theme: ChartTheme) => {
      if (series.length === 0) {
        return null;
      }
      const axisStyle = {
        axisLabel: { color: theme.mutedInk },
        axisLine: { lineStyle: { color: theme.grid } },
        splitLine: { lineStyle: { color: theme.grid } },
      };
      return {
        color: [...theme.series],
        legend: {
          data: ["Military", "Government", "Law enforcement"],
          top: 0,
          textStyle: { color: theme.mutedInk },
        },
        grid: { left: 8, right: 16, top: 32, bottom: 24, containLabel: true },
        tooltip: { trigger: "axis" as const },
        xAxis: {
          type: "category" as const,
          data: series.map((row) => row.day),
          ...axisStyle,
        },
        yAxis: { type: "value" as const, ...axisStyle },
        series: [
          {
            name: "Military",
            type: "bar" as const,
            stack: "classification",
            data: series.map((row) => row.military),
          },
          {
            name: "Government",
            type: "bar" as const,
            stack: "classification",
            data: series.map((row) => row.government),
          },
          {
            name: "Law enforcement",
            type: "bar" as const,
            stack: "classification",
            data: series.map((row) => row.law_enforcement),
          },
        ],
      };
    },
    [series],
  );

  const totals = series.reduce(
    (acc, row) => ({
      military: acc.military + row.military,
      government: acc.government + row.government,
      lawEnforcement: acc.lawEnforcement + row.law_enforcement,
    }),
    { military: 0, government: 0, lawEnforcement: 0 },
  );
  const summary =
    series.length === 0
      ? "No military, government or law-enforcement activity in this window."
      : `Military, government and law-enforcement activity by day: ` +
        `${totals.military} military, ${totals.government} government, ` +
        `${totals.lawEnforcement} law-enforcement sightings across ${series.length} days.`;

  return (
    <AnalyticsCard
      title="Military / government / police activity"
      window={window}
      isLoading={isLoading}
      error={error}
    >
      <EChart
        buildOption={buildOption}
        ariaLabel="Military, government and law-enforcement activity over time, stacked bar chart"
        summary={summary}
      />
    </AnalyticsCard>
  );
}
