/**
 * "Count of aircraft never previously seen" (SPEC §58) — the trend, a
 * single-series bar of new aircraft. The window's aggregate total lives on
 * {@link RarityListsCard} alongside the locally rare lists
 * (`/api/v1/analytics/rarity`'s `never_seen_before`), so this card is the
 * "over time" half of the same SPEC bullet.
 *
 * Over a multi-day window it is one bar per day. Over a single day that
 * would be one fat bar, so the card draws the day hour by hour instead
 * (slice 099), on the same hour axis as the other time-series cards: the
 * aircraft first ever heard in each hour, with hours that have not begun
 * left empty.
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
import { formatCalendarDay } from "@/features/analytics/lib/format";
import { hourAxisLabel, hourClockLabel } from "@/features/analytics/lib/series";

export interface NeverSeenBeforeCardProps {
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

export function NeverSeenBeforeCard({
  window,
  items,
  hourly,
  isLoading,
  error,
  errorDetail,
  onRetry,
}: NeverSeenBeforeCardProps) {
  const byHour = hourly !== undefined;
  const total = byHour
    ? hourly.reduce((sum, row) => sum + (row.new_aircraft ?? 0), 0)
    : items.reduce((sum, row) => sum + row.new_aircraft, 0);

  const buildOption = useCallback(
    (theme: ChartTheme) => {
      const points =
        hourly !== undefined
          ? hourly.map((row) => ({
              label: hourAxisLabel(row),
              count: row.new_aircraft ?? null,
            }))
          : items.map((row) => ({ label: row.day, count: row.new_aircraft }));
      if (points.length === 0) {
        return null;
      }
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
          axisPointer: { type: "shadow" as const },
          // "aircraft" is its own plural — no pluralize() needed here.
          valueFormatter: (value: unknown) =>
            typeof value === "number" ? `${value} aircraft` : "no data",
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
          name: "aircraft",
          minInterval: 1,
          nameTextStyle: { color: theme.mutedInk },
          ...axisStyle,
        },
        series: [
          {
            name: "New aircraft",
            type: "bar" as const,
            data: points.map((point) => point.count),
            barMaxWidth: 24,
          },
        ],
      };
    },
    [hourly, items],
  );

  const summary = byHour
    ? hourly.length === 0
      ? "No new aircraft in this window."
      : total === 0
        ? "No aircraft were heard for the first time so far in this day."
        : `New (never-seen-before) aircraft by hour, ${total} total: ${hourly
            .filter((row) => (row.new_aircraft ?? 0) > 0)
            .map((row) => `${hourClockLabel(row)} — ${row.new_aircraft}`)
            .join("; ")}.`
    : items.length === 0
      ? "No new aircraft in this window."
      : `New (never-seen-before) aircraft by day, ${total} total: ${items
          .map((row) => `${formatCalendarDay(row.day)} — ${row.new_aircraft}`)
          .join("; ")}.`;

  return (
    <AnalyticsCard
      title="Never seen before"
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
            ? "New aircraft never seen before, by hour, bar chart"
            : "New aircraft never seen before, by day, bar chart"
        }
        summary={summary}
      />
    </AnalyticsCard>
  );
}
