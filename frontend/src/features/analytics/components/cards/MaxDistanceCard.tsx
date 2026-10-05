/**
 * "Maximum detection distance" over time (SPEC §58) — a single-series line
 * of the window's per-day farthest detection, converted to the receiver's
 * display unit (`docs/API.md` §3.2 `units`; storage/wire stays nm — only the
 * chart's plotted numbers and axis label convert). A day with no usable
 * position (`max_range_nm: null`) is a gap in the line, not a false zero.
 *
 * Over a single-day window the card plots that day's farthest detection
 * hour by hour instead (slice 097): one day is one point, and one point is
 * not a line.
 */
import { useCallback, useMemo } from "react";

import type {
  AnalyticsDailyRow,
  AnalyticsHourlyRow,
  AnalyticsWindow,
} from "@/lib/api/analytics";
import type { UnitSystem } from "@/lib/api/config";

import { AnalyticsCard } from "@/features/analytics/components/AnalyticsCard";
import { EChart } from "@/features/analytics/components/EChart";
import type { ChartTheme } from "@/features/analytics/lib/chartTheme";
import {
  convertDistance,
  distanceUnitLabel,
  formatCalendarDay,
} from "@/features/analytics/lib/format";
import {
  hourAxisLabel,
  hourClockLabel,
  lineSymbols,
} from "@/features/analytics/lib/series";

export interface MaxDistanceCardProps {
  window?: AnalyticsWindow;
  items: AnalyticsDailyRow[];
  /** The window's one day, hour by hour. When given, the card draws hours
   * instead of days. */
  hourly?: AnalyticsHourlyRow[];
  units: UnitSystem;
  isLoading: boolean;
  error?: string;
  errorDetail?: string;
  onRetry?: () => void;
}

export function MaxDistanceCard({
  window,
  items,
  hourly,
  units,
  isLoading,
  error,
  errorDetail,
  onRetry,
}: MaxDistanceCardProps) {
  // R3-02/A1: a day not computed yet also carries `max_range_nm: null`, so
  // an otherwise-empty young install still has something worth drawing (a
  // chart full of gaps and an honest caption) rather than the flat "No
  // data" state, which reads as "there will never be anything here."
  const byHour = hourly !== undefined;
  const hasData = byHour
    ? hourly.some((row) => row.max_range_nm !== null)
    : items.some((row) => row.max_range_nm !== null || !row.complete);

  // One shape for both granularities: a label and a range per point.
  const points = useMemo(
    () =>
      hourly !== undefined
        ? hourly.map((row) => ({
            label: hourAxisLabel(row),
            rangeNm: row.max_range_nm,
          }))
        : items.map((row) => ({ label: row.day, rangeNm: row.max_range_nm })),
    [hourly, items],
  );

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
        // `top` leaves room for the axis name above the plot.
        grid: { left: 8, right: 16, top: 32, bottom: 24, containLabel: true },
        tooltip: {
          trigger: "axis" as const,
          valueFormatter: (value: unknown) =>
            typeof value === "number" ? `${value} ${unitLabel}` : "—",
        },
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
          name: unitLabel,
          nameTextStyle: { color: theme.mutedInk },
          ...axisStyle,
        },
        series: [
          {
            type: "line" as const,
            data: points.map((point) =>
              point.rangeNm === null
                ? null
                : convertDistance(point.rangeNm, units),
            ),
            connectNulls: false,
            smooth: true,
            ...lineSymbols(points.length),
          },
        ],
      };
    },
    [byHour, hasData, points, units],
  );

  const unitLabel = distanceUnitLabel(units);
  const summary = !hasData
    ? "No detection distance recorded in this window."
    : byHour
      ? `Maximum detection distance by hour, in ${unitLabel}: ${hourly
          .filter((row) => row.max_range_nm !== null)
          .map(
            (row) =>
              `${hourClockLabel(row)} — ${convertDistance(row.max_range_nm as number, units)} ${unitLabel}`,
          )
          .join("; ")}.`
      : `Maximum detection distance by day, in ${unitLabel}: ${items
          // A complete day with no positioned sighting (`max_range_nm: null`)
          // stays silently omitted, its longstanding meaning; a day not
          // computed yet (`!row.complete`) is named explicitly instead
          // (R3-02/A1) rather than looking identical to "nothing happened."
          .filter((row) => !row.complete || row.max_range_nm !== null)
          .map((row) =>
            !row.complete
              ? `${formatCalendarDay(row.day)} — not computed yet`
              : `${formatCalendarDay(row.day)} — ${convertDistance(row.max_range_nm as number, units)} ${unitLabel}`,
          )
          .join("; ")}.`;

  return (
    <AnalyticsCard
      title="Maximum detection distance"
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
            ? "Maximum detection distance by hour, line chart"
            : "Maximum detection distance over time, line chart"
        }
        summary={summary}
      />
    </AnalyticsCard>
  );
}
