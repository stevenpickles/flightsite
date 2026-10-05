/**
 * "Receiver activity over time" (SPEC §58) — messages and positions per day,
 * joined onto the `daily` response by slice 033's receiver metrics
 * (`docs/API.md` §3.7's `AnalyticsDailyRow.receiver_*` fields). `null` for a
 * day before receiver-metrics recording started, rendered as a gap rather
 * than a false zero, the same convention {@link MaxDistanceCard} uses.
 *
 * Over a single-day window the card plots that day's messages and positions
 * hour by hour instead (slice 097), from the same hourly receiver metrics
 * the Receiver page charts.
 */
import { useCallback, useMemo } from "react";

import type {
  AnalyticsDailyRow,
  AnalyticsHourlyRow,
  AnalyticsWindow,
} from "@/lib/api/analytics";

import { AnalyticsCard } from "@/features/analytics/components/AnalyticsCard";
import { EChart } from "@/features/analytics/components/EChart";
import type { ChartTheme } from "@/features/analytics/lib/chartTheme";
import {
  formatCalendarDay,
  formatCompactNumber,
} from "@/features/analytics/lib/format";
import {
  hourAxisLabel,
  hourClockLabel,
  lineSymbols,
} from "@/features/analytics/lib/series";

export interface ReceiverActivityCardProps {
  window?: AnalyticsWindow;
  items: AnalyticsDailyRow[];
  /** The window's one day, hour by hour. When given, the card draws hours
   * instead of days. */
  hourly?: AnalyticsHourlyRow[];
  isLoading: boolean;
  error?: string;
  errorDetail?: string;
  onRetry?: () => void;
}

export function ReceiverActivityCard({
  window,
  items,
  hourly,
  isLoading,
  error,
  errorDetail,
  onRetry,
}: ReceiverActivityCardProps) {
  // R3-02/A1: a day not computed yet also carries the receiver_* fields as
  // `null`, so a young install still has something worth drawing (gaps
  // plus an honest caption) rather than the flat "No data" state.
  const byHour = hourly !== undefined;
  const hasData = byHour
    ? hourly.some((row) => row.messages !== null || row.positions !== null)
    : items.some(
        (row) =>
          row.receiver_messages !== null ||
          row.receiver_positions !== null ||
          !row.complete,
      );

  // One shape for both granularities: a label and the two counts per point.
  const points = useMemo(
    () =>
      hourly !== undefined
        ? hourly.map((row) => ({
            label: hourAxisLabel(row),
            messages: row.messages,
            positions: row.positions,
          }))
        : items.map((row) => ({
            label: row.day,
            messages: row.receiver_messages,
            positions: row.receiver_positions,
          })),
    [hourly, items],
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
          ...(byHour
            ? {
                name: "hour",
                nameLocation: "middle" as const,
                nameGap: 24,
                nameTextStyle: { color: theme.mutedInk },
              }
            : {}),
          data: points.map((point) => point.label),
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
            name: "Messages",
            type: "line" as const,
            data: points.map((point) => point.messages),
            connectNulls: false,
            smooth: true,
            ...lineSymbols(points.length),
          },
          {
            name: "Positions",
            type: "line" as const,
            data: points.map((point) => point.positions),
            connectNulls: false,
            smooth: true,
            ...lineSymbols(points.length),
          },
        ],
      };
    },
    [byHour, hasData, points],
  );

  const summary = !hasData
    ? "No receiver activity recorded in this window."
    : byHour
      ? `Receiver messages and positions by hour: ${hourly
          .filter((row) => row.messages !== null || row.positions !== null)
          .map(
            (row) =>
              `${hourClockLabel(row)} — ${formatCompactNumber(row.messages ?? 0)} messages, ${formatCompactNumber(row.positions ?? 0)} positions`,
          )
          .join("; ")}.`
      : `Daily receiver messages and positions: ${items
          .filter(
            (row) =>
              !row.complete ||
              row.receiver_messages !== null ||
              row.receiver_positions !== null,
          )
          .map((row) =>
            !row.complete
              ? `${formatCalendarDay(row.day)} — not computed yet`
              : `${formatCalendarDay(row.day)} — ${formatCompactNumber(row.receiver_messages ?? 0)} messages, ${formatCompactNumber(row.receiver_positions ?? 0)} positions`,
          )
          .join("; ")}.`;

  return (
    <AnalyticsCard
      title="Receiver activity"
      window={window}
      isLoading={isLoading}
      error={error}
      errorDetail={errorDetail}
      onRetry={onRetry}
    >
      <EChart
        buildOption={buildOption}
        ariaLabel={
          byHour
            ? "Receiver messages and positions by hour, line chart"
            : "Receiver messages and positions over time, line chart"
        }
        summary={summary}
      />
    </AnalyticsCard>
  );
}
