/**
 * "Maximum detection distance" over time (SPEC §58) — a single-series line
 * of the window's per-day farthest detection, converted to the receiver's
 * display unit (`docs/API.md` §3.2 `units`; storage/wire stays nm — only the
 * chart's plotted numbers and axis label convert). A day with no usable
 * position (`max_range_nm: null`) is a gap in the line, not a false zero.
 */
import { useCallback } from "react";

import type { AnalyticsDailyRow, AnalyticsWindow } from "@/lib/api/analytics";
import type { UnitSystem } from "@/lib/api/config";

import { AnalyticsCard } from "@/features/analytics/components/AnalyticsCard";
import { EChart } from "@/features/analytics/components/EChart";
import type { ChartTheme } from "@/features/analytics/lib/chartTheme";
import {
  convertDistance,
  distanceUnitLabel,
} from "@/features/analytics/lib/format";

export interface MaxDistanceCardProps {
  window?: AnalyticsWindow;
  items: AnalyticsDailyRow[];
  units: UnitSystem;
  isLoading: boolean;
  error?: string;
}

export function MaxDistanceCard({
  window,
  items,
  units,
  isLoading,
  error,
}: MaxDistanceCardProps) {
  const hasData = items.some((row) => row.max_range_nm !== null);

  const buildOption = useCallback(
    (theme: ChartTheme) => {
      if (!hasData) {
        return null;
      }
      const unitLabel = distanceUnitLabel(units);
      const axisStyle = {
        axisLabel: { color: theme.mutedInk },
        axisLine: { lineStyle: { color: theme.grid } },
        splitLine: { lineStyle: { color: theme.grid } },
      };
      return {
        color: [theme.series[0]],
        grid: { left: 8, right: 16, top: 16, bottom: 24, containLabel: true },
        tooltip: {
          trigger: "axis" as const,
          valueFormatter: (value: unknown) =>
            typeof value === "number" ? `${value} ${unitLabel}` : "—",
        },
        xAxis: {
          type: "category" as const,
          data: items.map((row) => row.day),
          ...axisStyle,
        },
        yAxis: {
          type: "value" as const,
          name: unitLabel,
          nameTextStyle: { color: theme.mutedInk },
          ...axisStyle,
        },
        series: [
          {
            type: "line" as const,
            data: items.map((row) =>
              row.max_range_nm === null
                ? null
                : convertDistance(row.max_range_nm, units),
            ),
            connectNulls: false,
            smooth: true,
            showSymbol: false,
          },
        ],
      };
    },
    [hasData, items, units],
  );

  const unitLabel = distanceUnitLabel(units);
  const summary = !hasData
    ? "No detection distance recorded in this window."
    : `Maximum detection distance by day, in ${unitLabel}: ${items
        .filter((row) => row.max_range_nm !== null)
        .map(
          (row) =>
            `${row.day} — ${convertDistance(row.max_range_nm as number, units)} ${unitLabel}`,
        )
        .join("; ")}.`;

  return (
    <AnalyticsCard
      title="Maximum detection distance"
      window={window}
      isLoading={isLoading}
      error={error}
    >
      <EChart
        buildOption={buildOption}
        ariaLabel="Maximum detection distance over time, line chart"
        summary={summary}
      />
    </AnalyticsCard>
  );
}
