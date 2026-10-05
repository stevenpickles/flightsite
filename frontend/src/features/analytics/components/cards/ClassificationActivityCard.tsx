/**
 * "Military/government/police activity over time" (SPEC §58) —
 * `GET /api/v1/analytics/classification-activity`'s per-day series as a
 * stacked bar: three fixed-order categorical series (never reassigned by
 * which classification happens to be busiest), legend always shown for
 * three series so identity never rides on color alone.
 *
 * Over a single-day window that series is one bar, so the card stacks the
 * same three classes hour by hour instead (slice 099), on the hour axis the
 * other time-series cards share.
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
import { hourAxisLabel, hourClockLabel } from "@/features/analytics/lib/series";

export interface ClassificationActivityCardProps {
  window?: AnalyticsWindow;
  series: AnalyticsDailyRow[];
  /** The window's one day, hour by hour. When given, the card draws hours
   * instead of days. */
  hourly?: AnalyticsHourlyRow[];
  /** `false` when the window includes a day not computed yet (R3-02/A1) —
   * the totals below may then be an undercount, not a true zero, so the
   * summary says so rather than presenting them as final. `undefined`
   * while the query is still pending, same as `window`. */
  complete?: boolean;
  isLoading: boolean;
  error?: string;
  errorDetail?: string;
  onRetry?: () => void;
}

export function ClassificationActivityCard({
  window,
  series,
  hourly,
  complete,
  isLoading,
  error,
  errorDetail,
  onRetry,
}: ClassificationActivityCardProps) {
  const byHour = hourly !== undefined;

  const buildOption = useCallback(
    (theme: ChartTheme) => {
      // One shape for both granularities: a label and the three counts.
      const points =
        hourly !== undefined
          ? hourly.map((row) => ({
              label: hourAxisLabel(row),
              military: row.military ?? null,
              government: row.government ?? null,
              lawEnforcement: row.law_enforcement ?? null,
            }))
          : series.map((row) => ({
              label: row.day,
              military: row.military,
              government: row.government,
              lawEnforcement: row.law_enforcement,
            }));
      if (points.length === 0) {
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
        // `top` clears the three-item legend, which is wide enough to run
        // over the axis name when both share one row.
        grid: { left: 8, right: 16, top: 52, bottom: 24, containLabel: true },
        tooltip: {
          trigger: "axis" as const,
          valueFormatter: (value: unknown) =>
            typeof value === "number"
              ? `${value} ${value === 1 ? "sighting" : "sightings"}`
              : "no data",
        },
        xAxis: {
          type: "category" as const,
          ...(hourly !== undefined
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
          name: "sightings",
          minInterval: 1,
          nameTextStyle: { color: theme.mutedInk },
          ...axisStyle,
        },
        series: [
          {
            name: "Military",
            type: "bar" as const,
            stack: "classification",
            data: points.map((point) => point.military),
          },
          {
            name: "Government",
            type: "bar" as const,
            stack: "classification",
            data: points.map((point) => point.government),
          },
          {
            name: "Law enforcement",
            type: "bar" as const,
            stack: "classification",
            data: points.map((point) => point.lawEnforcement),
          },
        ],
      };
    },
    [hourly, series],
  );

  // R3-02/A1: a day not computed yet carries `null` here, not a real zero —
  // summed with `?? 0` so an in-progress day never throws off the total
  // into `NaN`, with the incompleteness itself called out in `summary`
  // below rather than silently folded into the count.
  const totals = series.reduce(
    (acc, row) => ({
      military: acc.military + (row.military ?? 0),
      government: acc.government + (row.government ?? 0),
      lawEnforcement: acc.lawEnforcement + (row.law_enforcement ?? 0),
    }),
    { military: 0, government: 0, lawEnforcement: 0 },
  );
  const summary = byHour
    ? hourlySummary(hourly)
    : series.length === 0
      ? "No military, government or law-enforcement activity in this window."
      : `Military, government and law-enforcement activity by day: ` +
        `${totals.military} military, ${totals.government} government, ` +
        `${totals.lawEnforcement} law-enforcement sightings across ${series.length} days` +
        `${complete === false ? " (today not computed yet, so this may undercount)" : ""}.`;

  return (
    <AnalyticsCard
      title="Military / government / police activity"
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
            ? "Military, government and law-enforcement activity by hour, stacked bar chart"
            : "Military, government and law-enforcement activity over time, stacked bar chart"
        }
        summary={summary}
      />
    </AnalyticsCard>
  );
}

/** The hours that had classified traffic, in words; quiet hours are left out
 * so the sentence is the length of the activity rather than of the day. */
function hourlySummary(hourly: AnalyticsHourlyRow[]): string {
  const busy = hourly.filter(
    (row) =>
      (row.military ?? 0) + (row.government ?? 0) + (row.law_enforcement ?? 0) >
      0,
  );
  if (busy.length === 0) {
    return "No military, government or law-enforcement activity so far in this day.";
  }
  return (
    "Military, government and law-enforcement sightings by hour: " +
    busy
      .map(
        (row) =>
          `${hourClockLabel(row)} — ${row.military ?? 0} military, ${row.government ?? 0} government, ${row.law_enforcement ?? 0} law-enforcement`,
      )
      .join("; ") +
    "."
  );
}
