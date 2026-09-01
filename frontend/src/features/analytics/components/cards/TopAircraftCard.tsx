/**
 * "Most frequently seen aircraft" (SPEC §58) — a horizontal bar of the
 * window's top airframes by sighting count. Clicking a bar (or its label)
 * opens the aircraft's history detail (roadmap slice 029), the same
 * destination the Aircraft page's table rows use.
 */
import { useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";

import type {
  AnalyticsAircraftRow,
  AnalyticsWindow,
} from "@/lib/api/analytics";

import { AnalyticsCard } from "@/features/analytics/components/AnalyticsCard";
import {
  EChart,
  type EChartClickParams,
} from "@/features/analytics/components/EChart";
import type { ChartTheme } from "@/features/analytics/lib/chartTheme";

export interface TopAircraftCardProps {
  window?: AnalyticsWindow;
  rows: AnalyticsAircraftRow[];
  isLoading: boolean;
  error?: string;
}

function aircraftLabel(row: AnalyticsAircraftRow): string {
  return row.registration ?? row.icao.toUpperCase();
}

export function TopAircraftCard({
  window,
  rows,
  isLoading,
  error,
}: TopAircraftCardProps) {
  const navigate = useNavigate();

  // Reversed so the highest-ranked row (rows[0], the backend's own sort)
  // ends up at the top of the horizontal bar rather than the bottom —
  // ECharts draws a category axis's first entry lowest.
  const ordered = useMemo(() => [...rows].reverse(), [rows]);

  const buildOption = useCallback(
    (theme: ChartTheme) => {
      if (ordered.length === 0) {
        return null;
      }
      return {
        color: [theme.series[0]],
        grid: { left: 8, right: 24, top: 8, bottom: 24, containLabel: true },
        tooltip: {
          trigger: "axis" as const,
          axisPointer: { type: "shadow" as const },
        },
        xAxis: {
          type: "value" as const,
          axisLabel: { color: theme.mutedInk },
          axisLine: { lineStyle: { color: theme.grid } },
          splitLine: { lineStyle: { color: theme.grid } },
        },
        yAxis: {
          type: "category" as const,
          data: ordered.map(aircraftLabel),
          axisLabel: { color: theme.ink },
          axisLine: { lineStyle: { color: theme.grid } },
        },
        series: [
          {
            type: "bar" as const,
            data: ordered.map((row) => row.sightings),
            barMaxWidth: 18,
          },
        ],
      };
    },
    [ordered],
  );

  const handleMarkClick = useCallback(
    (params: EChartClickParams) => {
      const row = ordered[params.dataIndex];
      if (row) {
        navigate(`/aircraft/${row.icao}`);
      }
    },
    [navigate, ordered],
  );

  const summary =
    rows.length === 0
      ? "No aircraft sighted in this window."
      : `Top aircraft by sightings: ${rows
          .map((row) => `${aircraftLabel(row)} (${row.sightings})`)
          .join(", ")}.`;

  return (
    <AnalyticsCard
      title="Top aircraft"
      window={window}
      isLoading={isLoading}
      error={error}
    >
      <EChart
        buildOption={buildOption}
        ariaLabel="Top aircraft by sightings, horizontal bar chart"
        summary={summary}
        onMarkClick={handleMarkClick}
      />
    </AnalyticsCard>
  );
}
