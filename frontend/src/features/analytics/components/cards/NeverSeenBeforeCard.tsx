/**
 * "Count of aircraft never previously seen" (SPEC §58) — the daily trend, a
 * single-series bar of `AnalyticsDailyRow.new_aircraft`. The window's
 * aggregate total lives on {@link RarityListsCard} alongside the locally
 * rare lists (`/api/v1/analytics/rarity`'s `never_seen_before`), so this
 * card is the "over time" half of the same SPEC bullet.
 */
import { useCallback } from "react";

import type { AnalyticsDailyRow, AnalyticsWindow } from "@/lib/api/analytics";

import { AnalyticsCard } from "@/features/analytics/components/AnalyticsCard";
import { EChart } from "@/features/analytics/components/EChart";
import type { ChartTheme } from "@/features/analytics/lib/chartTheme";

export interface NeverSeenBeforeCardProps {
  window?: AnalyticsWindow;
  items: AnalyticsDailyRow[];
  isLoading: boolean;
  error?: string;
}

export function NeverSeenBeforeCard({
  window,
  items,
  isLoading,
  error,
}: NeverSeenBeforeCardProps) {
  const total = items.reduce((sum, row) => sum + row.new_aircraft, 0);

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
        color: [theme.series[0]],
        grid: { left: 8, right: 16, top: 16, bottom: 24, containLabel: true },
        tooltip: {
          trigger: "axis" as const,
          axisPointer: { type: "shadow" as const },
        },
        xAxis: {
          type: "category" as const,
          data: items.map((row) => row.day),
          ...axisStyle,
        },
        yAxis: { type: "value" as const, ...axisStyle },
        series: [
          {
            type: "bar" as const,
            data: items.map((row) => row.new_aircraft),
            barMaxWidth: 24,
          },
        ],
      };
    },
    [items],
  );

  const summary =
    items.length === 0
      ? "No new aircraft in this window."
      : `New (never-seen-before) aircraft by day, ${total} total: ${items
          .map((row) => `${row.day} — ${row.new_aircraft}`)
          .join("; ")}.`;

  return (
    <AnalyticsCard
      title="Never seen before"
      window={window}
      isLoading={isLoading}
      error={error}
    >
      <EChart
        buildOption={buildOption}
        ariaLabel="New aircraft never seen before, by day, bar chart"
        summary={summary}
      />
    </AnalyticsCard>
  );
}
