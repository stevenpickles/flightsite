/**
 * "Receiver activity over time" (SPEC §58) — messages and positions per day,
 * joined onto the `daily` response by slice 033's receiver metrics
 * (`docs/API.md` §3.7's `AnalyticsDailyRow.receiver_*` fields). `null` for a
 * day before receiver-metrics recording started, rendered as a gap rather
 * than a false zero, the same convention {@link MaxDistanceCard} uses.
 */
import { useCallback } from "react";

import type { AnalyticsDailyRow, AnalyticsWindow } from "@/lib/api/analytics";

import { AnalyticsCard } from "@/features/analytics/components/AnalyticsCard";
import { EChart } from "@/features/analytics/components/EChart";
import type { ChartTheme } from "@/features/analytics/lib/chartTheme";
import { formatCompactNumber } from "@/features/analytics/lib/format";

export interface ReceiverActivityCardProps {
  window?: AnalyticsWindow;
  items: AnalyticsDailyRow[];
  isLoading: boolean;
  error?: string;
}

export function ReceiverActivityCard({
  window,
  items,
  isLoading,
  error,
}: ReceiverActivityCardProps) {
  const hasData = items.some(
    (row) => row.receiver_messages !== null || row.receiver_positions !== null,
  );

  const buildOption = useCallback(
    (theme: ChartTheme) => {
      if (!hasData) {
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
          data: ["Messages", "Positions"],
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
            name: "Messages",
            type: "line" as const,
            data: items.map((row) => row.receiver_messages),
            connectNulls: false,
            smooth: true,
            showSymbol: false,
          },
          {
            name: "Positions",
            type: "line" as const,
            data: items.map((row) => row.receiver_positions),
            connectNulls: false,
            smooth: true,
            showSymbol: false,
          },
        ],
      };
    },
    [hasData, items],
  );

  const summary = !hasData
    ? "No receiver activity recorded in this window."
    : `Daily receiver messages and positions: ${items
        .filter(
          (row) =>
            row.receiver_messages !== null || row.receiver_positions !== null,
        )
        .map(
          (row) =>
            `${row.day} — ${formatCompactNumber(row.receiver_messages ?? 0)} messages, ${formatCompactNumber(row.receiver_positions ?? 0)} positions`,
        )
        .join("; ")}.`;

  return (
    <AnalyticsCard
      title="Receiver activity"
      window={window}
      isLoading={isLoading}
      error={error}
    >
      <EChart
        buildOption={buildOption}
        ariaLabel="Receiver messages and positions over time, line chart"
        summary={summary}
      />
    </AnalyticsCard>
  );
}
