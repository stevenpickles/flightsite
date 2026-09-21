/**
 * Pure ECharts `option` builders for the Receiver page (roadmap slice 034).
 *
 * Built against the shared `EChart` wrapper's contract (roadmap slice 032,
 * `features/analytics/components/EChart.tsx`): each builder here returns a
 * `buildOption(theme) => option | null` closure plus the `summary` text the
 * wrapper renders as its visually-hidden text alternative and passes through
 * as the chart's `aria-label` (SPEC §80's accessibility baseline — a chart's
 * data must be readable without seeing the canvas). Returning `null` is how
 * a builder asks the wrapper to render its "No data" empty state instead of
 * an empty canvas, so no chart here owns its own empty-state rendering.
 *
 * Kept free of React and of `echarts.init` on purpose: every function here
 * takes plain data and a `ChartTheme` and returns plain objects, so the
 * polar bearing mapping and the empty-state summaries can be asserted
 * against fixtures without mounting a chart (`docs/TEST_STRATEGY.md` favors
 * testing logic over rendering where the two can be separated).
 */
import type * as echarts from "echarts/core";

import type { ChartTheme } from "@/features/analytics/lib/chartTheme";
import type { ReceiverSeriesResolution } from "@/lib/api/receiverStats";
import {
  formatReceiverLocalDate,
  formatReceiverLocalDateTime,
  formatReceiverLocalTime,
} from "@/features/receiver/lib/format";

export interface ChartPoint {
  t: string;
  value: number | null;
}

export interface ChartResult {
  buildOption: (theme: ChartTheme) => echarts.EChartsCoreOption | null;
  summary: string;
}

function axisLabel(
  iso: string,
  timezone: string,
  resolution: ReceiverSeriesResolution,
): string {
  if (resolution === "daily") {
    return formatReceiverLocalDate(iso, timezone);
  }
  if (resolution === "hourly") {
    return formatReceiverLocalDateTime(iso, timezone);
  }
  return formatReceiverLocalTime(iso, timezone);
}

export interface TimeSeriesChartParams {
  points: ChartPoint[];
  kind: "line" | "bar";
  timezone: string;
  resolution: ReceiverSeriesResolution;
  seriesName: string;
  unitLabel: string;
  formatValue: (value: number) => string;
}

/** One SPEC §62 line/bar chart: messages/positions per second, simultaneous
 * aircraft, maximum range, unique aircraft per day, and daily message/
 * position totals all share this shape — only the metric and its formatting
 * differ (`features/receiver/lib/metricConfig.ts`). */
export function buildTimeSeriesChart(
  params: TimeSeriesChartParams,
): ChartResult {
  const {
    points,
    kind,
    timezone,
    resolution,
    seriesName,
    unitLabel,
    formatValue,
  } = params;

  if (points.length === 0) {
    return { buildOption: () => null, summary: "No data in this window." };
  }

  const categories = points.map((point) =>
    axisLabel(point.t, timezone, resolution),
  );
  const values = points.map((point) => point.value);
  const present = values.filter((value): value is number => value !== null);
  const latestPresent = [...values].reverse().find((value) => value !== null);
  const peak = present.length > 0 ? Math.max(...present) : null;

  const summary =
    present.length === 0
      ? `${seriesName}: no readings across ${points.length} time points from ${categories[0]} to ${categories[categories.length - 1]}.`
      : `${seriesName}: ${points.length} points from ${categories[0]} to ${categories[categories.length - 1]}. ` +
        `Latest ${formatValue(latestPresent as number)}, peak ${formatValue(peak as number)}.`;

  return {
    summary,
    buildOption: (theme) => ({
      backgroundColor: "transparent",
      textStyle: { color: theme.mutedInk },
      grid: { left: 52, right: 16, top: 24, bottom: 40 },
      tooltip: {
        trigger: "axis",
        valueFormatter: (value: unknown) =>
          typeof value === "number" ? formatValue(value) : "no data",
      },
      xAxis: {
        type: "category",
        data: categories,
        axisLine: { lineStyle: { color: theme.grid } },
        axisLabel: { color: theme.mutedInk },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        name: unitLabel,
        nameTextStyle: { color: theme.mutedInk },
        axisLabel: { color: theme.mutedInk },
        axisLine: { lineStyle: { color: theme.grid } },
        splitLine: { lineStyle: { color: theme.grid } },
      },
      series: [
        {
          name: seriesName,
          type: kind,
          data: values,
          color: theme.series[0],
          lineStyle:
            kind === "line" ? { width: 2, color: theme.series[0] } : undefined,
          itemStyle: { color: theme.series[0] },
          showSymbol: kind === "line" && points.length <= 60,
          symbolSize: 8,
          connectNulls: false,
        },
      ],
    }),
  };
}

export interface SignalHistogramBucket {
  min_db: number;
  max_db: number;
  count: number;
}

/** SPEC §62's signal-strength distribution — a histogram bar chart over
 * per-sighting RSSI buckets (`docs/API.md` §3.8). */
export function buildSignalHistogramChart(params: {
  buckets: SignalHistogramBucket[];
}): ChartResult {
  const { buckets } = params;

  if (buckets.length === 0) {
    return {
      buildOption: () => null,
      summary: "No signal readings in this window.",
    };
  }

  const categories = buckets.map(
    (bucket) => `${bucket.min_db.toFixed(0)}…${bucket.max_db.toFixed(0)}`,
  );
  const counts = buckets.map((bucket) => bucket.count);
  const total = counts.reduce((sum, count) => sum + count, 0);
  const peakIndex = counts.indexOf(Math.max(...counts));

  const summary =
    total === 0
      ? "No signal readings in this window."
      : `Signal strength distribution over ${total} sightings; most common band ${categories[peakIndex]} dB.`;

  return {
    summary,
    buildOption: (theme) => ({
      backgroundColor: "transparent",
      textStyle: { color: theme.mutedInk },
      grid: { left: 52, right: 16, top: 24, bottom: 56 },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        name: "dB",
        data: categories,
        axisLabel: { color: theme.mutedInk, rotate: 45 },
        axisLine: { lineStyle: { color: theme.grid } },
      },
      yAxis: {
        type: "value",
        name: "Sightings",
        nameTextStyle: { color: theme.mutedInk },
        axisLabel: { color: theme.mutedInk },
        axisLine: { lineStyle: { color: theme.grid } },
        splitLine: { lineStyle: { color: theme.grid } },
      },
      series: [
        {
          name: "Sightings",
          type: "bar",
          data: counts,
          itemStyle: { color: theme.series[0] },
        },
      ],
    }),
  };
}

export interface BearingSectorPoint {
  bearing_deg: number;
  value: number | null;
}

/** The category-axis index closest to `targetDeg` among `totalSectors` even
 * slices of the compass (R3-09) — used to place exactly one "N"/"E"/"S"/"W"
 * tick per cardinal rather than a rounded sector-midpoint label (`"3°"`,
 * `"93°"`, …) at every tick, which read as a compass rose whose numbers
 * simply missed 0/90/180/270 entirely. */
function cardinalTickIndex(totalSectors: number, targetDeg: number): number {
  return Math.round((targetDeg / 360) * totalSectors) % totalSectors;
}

/**
 * SPEC §62's maximum-range-by-bearing polar plot.
 *
 * `angleAxis.startAngle: 90` places sector index 0 (bearing 0deg = North) at
 * the top of the circle, and `clockwise: true` makes the angle increase
 * clockwise from there — the same orientation a compass rose uses, and the
 * orientation `ever`/`today` arrive in from the API (bucket 0..71 ascending,
 * `docs/DATA_MODEL.md` §6.3). `today` and `ever` are distinguished by more
 * than color (SPEC §80): solid circles vs. a dashed line with diamond
 * markers, on the theme's first two categorical slots.
 */
export function buildRangeByBearingChart(params: {
  today: BearingSectorPoint[];
  ever: BearingSectorPoint[];
  unitLabel: string;
  formatValue: (value: number) => string;
}): ChartResult {
  const { today, ever, unitLabel, formatValue } = params;

  const categories = ever.map((sector) => `${Math.round(sector.bearing_deg)}°`);
  const everValues = ever.map((sector) => sector.value);
  const todayValues = today.map((sector) => sector.value);
  const everPresent = everValues.filter(
    (value): value is number => value !== null,
  );
  const todayPresent = todayValues.filter(
    (value): value is number => value !== null,
  );

  // The backend always emits all 72 sectors for both series regardless of
  // whether any of them actually recorded a range (`ever.length === 0` was
  // therefore unreachable from the real API) — an install with no range
  // records at all must still draw the empty-state, not 72 empty sectors.
  if (everPresent.length === 0) {
    return {
      buildOption: () => null,
      summary: "No range-by-bearing data recorded yet.",
    };
  }

  const hasToday = todayPresent.length > 0;
  const summary =
    `Lifetime maximum range ${formatValue(Math.max(...everPresent))} across ${ever.length} bearing sectors; ` +
    `today's maximum is ${hasToday ? formatValue(Math.max(...todayPresent)) : "not set yet"}.`;

  const totalSectors = categories.length;
  const cardinalLabelByIndex: Record<number, string> = {
    [cardinalTickIndex(totalSectors, 0)]: "N",
    [cardinalTickIndex(totalSectors, 90)]: "E",
    [cardinalTickIndex(totalSectors, 180)]: "S",
    [cardinalTickIndex(totalSectors, 270)]: "W",
  };

  return {
    summary,
    buildOption: (theme) => ({
      backgroundColor: "transparent",
      textStyle: { color: theme.mutedInk },
      legend: {
        // A "Today" key with nothing drawn under it read as a dead legend
        // entry — omit it (and the series below) rather than explain an
        // empty line in the sr-only summary alone.
        data: hasToday ? ["Ever", "Today"] : ["Ever"],
        top: 0,
        textStyle: { color: theme.mutedInk },
      },
      tooltip: {
        trigger: "item",
        valueFormatter: (value: unknown) =>
          typeof value === "number" ? formatValue(value) : "no data",
      },
      polar: { radius: "62%" },
      angleAxis: {
        type: "category",
        data: categories,
        startAngle: 90,
        clockwise: true,
        // Sector 0's center sits exactly on `startAngle` (north) instead of
        // half a sector clockwise of it, which `boundaryGap`'s default
        // (`true` for a category axis) would otherwise leave it.
        boundaryGap: false,
        axisLabel: {
          color: theme.mutedInk,
          interval: 0,
          // Every other tick around the rose was a rounded sector midpoint
          // ("3°", "93°", …) that never lands on 0/90/180/270 and carried no
          // N/E/S/W — a compass rose whose numbers miss every cardinal reads
          // as broken. Only the four cardinal ticks are labelled now.
          formatter: (_value: string, index: number) =>
            cardinalLabelByIndex[index] ?? "",
        },
        axisLine: { lineStyle: { color: theme.grid } },
        splitLine: { lineStyle: { color: theme.grid } },
      },
      radiusAxis: {
        type: "value",
        // No `name` here: it used to sit at the axis start, right where the
        // north tick lives, and print as "nm" overlapping "3°". The unit is
        // still stated — on every tick — instead of once, colliding.
        axisLabel: {
          color: theme.mutedInk,
          formatter: (value: number) => `${value} ${unitLabel}`,
        },
        splitLine: { lineStyle: { color: theme.grid } },
      },
      series: [
        {
          name: "Ever",
          type: "line",
          coordinateSystem: "polar",
          data: everValues,
          lineStyle: { width: 2, color: theme.series[0], type: "solid" },
          itemStyle: { color: theme.series[0] },
          symbol: "circle",
          symbolSize: 6,
          connectNulls: false,
        },
        ...(hasToday
          ? [
              {
                name: "Today",
                type: "line" as const,
                coordinateSystem: "polar",
                data: todayValues,
                lineStyle: {
                  width: 2,
                  color: theme.series[1],
                  type: "dashed" as const,
                },
                itemStyle: { color: theme.series[1] },
                symbol: "diamond",
                symbolSize: 7,
                connectNulls: false,
              },
            ]
          : []),
      ],
    }),
  };
}
