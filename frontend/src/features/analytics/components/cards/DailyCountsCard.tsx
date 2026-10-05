/**
 * "Daily aircraft count" and "daily sighting count" (SPEC §58) — two
 * distinct metrics, so two categorical series (not a magnitude gradient).
 *
 * Over a multi-day window they are lines across the window's days. Over a
 * single day there is only one day to plot, so the card draws that day hour
 * by hour instead (slice 097): grouped bars of the sightings that started in
 * each hour and the distinct aircraft heard during it. Hours that have not
 * begun are empty rather than zero.
 */
import { useCallback } from "react";

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

export interface DailyCountsCardProps {
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

function axisStyle(theme: ChartTheme) {
  return {
    axisLabel: { color: theme.mutedInk },
    axisLine: { lineStyle: { color: theme.grid } },
    splitLine: { lineStyle: { color: theme.grid } },
  };
}

function countAxis(theme: ChartTheme) {
  const style = axisStyle(theme);
  return {
    type: "value" as const,
    name: "count",
    minInterval: 1,
    nameTextStyle: { color: theme.mutedInk },
    axisLabel: {
      ...style.axisLabel,
      formatter: (value: number) => formatCompactNumber(value),
    },
    axisLine: style.axisLine,
    splitLine: style.splitLine,
  };
}

export function DailyCountsCard({
  window,
  items,
  hourly,
  isLoading,
  error,
  errorDetail,
  onRetry,
}: DailyCountsCardProps) {
  const byHour = hourly !== undefined;

  const buildOption = useCallback(
    (theme: ChartTheme) => {
      const legend = {
        data: ["Aircraft", "Sightings"],
        top: 0,
        textStyle: { color: theme.mutedInk },
      };
      const grid = {
        left: 8,
        right: 16,
        top: 32,
        bottom: 24,
        containLabel: true,
      };
      if (hourly !== undefined) {
        if (hourly.length === 0) {
          return null;
        }
        return {
          color: [theme.series[0], theme.series[1]],
          legend,
          grid,
          tooltip: {
            trigger: "axis" as const,
            axisPointer: { type: "shadow" as const },
          },
          xAxis: {
            type: "category" as const,
            name: "hour",
            nameLocation: "middle" as const,
            nameGap: 24,
            nameTextStyle: { color: theme.mutedInk },
            data: hourly.map(hourAxisLabel),
            ...axisStyle(theme),
          },
          yAxis: countAxis(theme),
          series: [
            {
              name: "Aircraft",
              type: "bar" as const,
              data: hourly.map((row) => row.unique_aircraft),
              barGap: "0%",
            },
            {
              name: "Sightings",
              type: "bar" as const,
              data: hourly.map((row) => row.sightings),
            },
          ],
        };
      }
      if (items.length === 0) {
        return null;
      }
      return {
        color: [theme.series[0], theme.series[1]],
        legend,
        grid,
        tooltip: { trigger: "axis" as const },
        xAxis: {
          type: "category" as const,
          data: items.map((row) => row.day),
          ...axisStyle(theme),
        },
        yAxis: countAxis(theme),
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
            ...lineSymbols(items.length),
          },
          {
            name: "Sightings",
            type: "line" as const,
            data: items.map((row) => row.sightings),
            connectNulls: false,
            smooth: true,
            ...lineSymbols(items.length),
          },
        ],
      };
    },
    [hourly, items],
  );

  const summary = byHour
    ? hourlySummary(hourly)
    : items.length === 0
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
      title={
        byHour
          ? "Aircraft & sightings by hour"
          : "Daily aircraft & sighting counts"
      }
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
            ? "Aircraft and sightings by hour, bar chart"
            : "Daily aircraft and sighting counts, line chart"
        }
        summary={summary}
      />
    </AnalyticsCard>
  );
}

/** The hours that had traffic, in words; quiet hours are left out so the
 * sentence stays the length of the day's activity rather than of the day. */
function hourlySummary(hourly: AnalyticsHourlyRow[]): string {
  const busy = hourly.filter(
    (row) => (row.sightings ?? 0) > 0 || (row.unique_aircraft ?? 0) > 0,
  );
  if (busy.length === 0) {
    return "No traffic recorded so far in this day.";
  }
  return (
    "Aircraft heard and sightings started by hour: " +
    busy
      .map(
        (row) =>
          `${hourClockLabel(row)} — ${row.unique_aircraft ?? 0} aircraft, ${row.sightings ?? 0} sightings`,
      )
      .join("; ") +
    "."
  );
}
