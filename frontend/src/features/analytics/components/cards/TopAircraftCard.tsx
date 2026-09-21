/**
 * "Most frequently seen aircraft" (SPEC §58) — a horizontal bar of the
 * window's top airframes by sighting count. Clicking a bar (or its label)
 * opens the aircraft's history detail (roadmap slice 029), the same
 * destination the Aircraft page's table rows use.
 *
 * Each bar is labelled with the tail number (the ICAO hex when no
 * registration is known) *and* the ICAO type designator, and its tooltip
 * carries the rest of what the row already knows — model, operator, hex —
 * so the ranking reads as aircraft rather than as a list of registrations
 * (slice 074). The type sits in a second, muted rich-text segment so the
 * identity stays the thing the eye lands on.
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
import { formatSightings, tooltipLines } from "@/features/analytics/lib/format";

export interface TopAircraftCardProps {
  window?: AnalyticsWindow;
  rows: AnalyticsAircraftRow[];
  isLoading: boolean;
  error?: string;
  onRetry?: () => void;
}

/** The registration, or the upper-cased hex when none is known — what the
 * category axis names the bar. */
function aircraftIdentity(row: AnalyticsAircraftRow): string {
  return row.registration ?? row.icao.toUpperCase();
}

/** `"B738 Boeing 737-800"`, `"B738"`, `"Boeing 737-800"`, or `null` when the
 * row knows neither — the type in words, for the tooltip and the summary. */
function aircraftType(row: AnalyticsAircraftRow): string | null {
  const parts = [row.type, row.model].filter(
    (part): part is string => part !== null,
  );
  return parts.length === 0 ? null : parts.join(" ");
}

/** `"N302DN, B738 Boeing 737-800"` — one row of the accessible summary. */
function aircraftSummary(row: AnalyticsAircraftRow): string {
  const type = aircraftType(row);
  return type === null
    ? aircraftIdentity(row)
    : `${aircraftIdentity(row)}, ${type}`;
}

/** The tooltip's first line: the registration with the hex beside it, or
 * just the hex when that is all there is. */
function aircraftHeadline(row: AnalyticsAircraftRow): string {
  const hex = row.icao.toUpperCase();
  return row.registration === null ? hex : `${row.registration} · ${hex}`;
}

/** ECharts hands an axis-trigger tooltip every series' point for the hovered
 * category; the first one's `dataIndex` is the row. */
function hoveredIndex(params: unknown): number | undefined {
  const first = Array.isArray(params) ? params[0] : params;
  if (typeof first !== "object" || first === null) {
    return undefined;
  }
  const { dataIndex } = first as { dataIndex?: unknown };
  return typeof dataIndex === "number" ? dataIndex : undefined;
}

export function TopAircraftCard({
  window,
  rows,
  isLoading,
  error,
  onRetry,
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
          formatter: (params: unknown) => {
            const index = hoveredIndex(params);
            const row = index === undefined ? undefined : ordered[index];
            if (!row) {
              return "";
            }
            return tooltipLines([
              aircraftHeadline(row),
              aircraftType(row),
              row.operator ?? row.operator_group,
              formatSightings(row.sightings),
            ]);
          },
        },
        xAxis: {
          type: "value" as const,
          axisLabel: { color: theme.mutedInk },
          axisLine: { lineStyle: { color: theme.grid } },
          splitLine: { lineStyle: { color: theme.grid } },
        },
        yAxis: {
          type: "category" as const,
          data: ordered.map(aircraftIdentity),
          axisLabel: {
            color: theme.ink,
            formatter: (value: string, index: number) => {
              const type = ordered[index]?.type ?? null;
              return type === null
                ? `{ident|${value}}`
                : `{ident|${value}}  {type|${type}}`;
            },
            rich: {
              ident: { color: theme.ink },
              type: { color: theme.mutedInk, fontSize: 11 },
            },
          },
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
          .map((row) => `${aircraftSummary(row)} (${row.sightings})`)
          .join("; ")}.`;

  return (
    <AnalyticsCard
      title="Top aircraft"
      window={window}
      isLoading={isLoading}
      error={error}
      onRetry={onRetry}
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
