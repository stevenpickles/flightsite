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
import { formatCompactNumber } from "@/features/analytics/lib/format";

export interface DailyCountsCardProps {
  window?: AnalyticsWindow;
  items: AnalyticsDailyRow[];
  isLoading: boolean;
  error?: string;
}

export function DailyCountsCard({
  window,
  items,
  isLoading,
  error,
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
            data: items.map((row) => row.unique_aircraft),
            smooth: true,
            showSymbol: false,
          },
          {
            name: "Sightings",
            type: "line" as const,
            data: items.map((row) => row.sightings),
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
          .map(
            (row) =>
              `${row.day} — ${row.unique_aircraft} aircraft, ${row.sightings} sightings`,
          )
          .join("; ")}.`;

  return (
    <AnalyticsCard
      title="Daily aircraft & sighting counts"
      window={window}
      isLoading={isLoading}
      error={error}
    >
      <EChart
        buildOption={buildOption}
        ariaLabel="Daily aircraft and sighting counts, line chart"
        summary={summary}
      />
    </AnalyticsCard>
  );
}
