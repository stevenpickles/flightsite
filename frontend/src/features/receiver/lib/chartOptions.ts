/**
 * Pure ECharts `option` builders for the Receiver page (roadmap slice 034).
 *
 * Kept free of React and of `echarts.init` on purpose: every function here
 * takes plain data and a palette and returns a plain object plus a
 * plain-language summary string, so the polar bearing mapping and the
 * empty/loading states can be asserted against fixtures without mounting a
 * chart (`docs/TEST_STRATEGY.md` favors testing logic over rendering where
 * the two can be separated).
 *
 * Every builder also returns `summary` — the visible text description
 * rendered beside its chart and used as the chart canvas's `aria-label`
 * (SPEC §80's accessibility baseline: a chart's data must be readable
 * without seeing the canvas).
 */
import type * as echarts from "echarts";

import type { ReceiverSeriesResolution } from "@/lib/api/receiverStats";
import {
  formatReceiverLocalDate,
  formatReceiverLocalDateTime,
  formatReceiverLocalTime,
} from "@/features/receiver/lib/format";
import type { ReceiverChartPalette } from "@/features/receiver/lib/palette";

export interface ChartPoint {
  t: string;
  value: number | null;
}

export interface ChartBuildResult {
  option: echarts.EChartsCoreOption;
  summary: string;
}

function emptyOption(
  palette: ReceiverChartPalette,
  message: string,
): echarts.EChartsCoreOption {
  return {
    backgroundColor: "transparent",
    graphic: {
      type: "text",
      left: "center",
      top: "middle",
      style: { text: message, fill: palette.mutedInk, fontSize: 13 },
    },
  };
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
  palette: ReceiverChartPalette;
  formatValue: (value: number) => string;
}

/** One SPEC §62 line/bar chart: messages/positions per second, simultaneous
 * aircraft, maximum range, unique aircraft per day, and daily message/
 * position totals all share this shape — only the metric and its formatting
 * differ (`features/receiver/lib/metricConfig.ts`). */
export function buildTimeSeriesChartOption(
  params: TimeSeriesChartParams,
): ChartBuildResult {
  const {
    points,
    kind,
    timezone,
    resolution,
    seriesName,
    unitLabel,
    palette,
    formatValue,
  } = params;

  if (points.length === 0) {
    const message = "No data in this window.";
    return { option: emptyOption(palette, message), summary: message };
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

  const option: echarts.EChartsCoreOption = {
    backgroundColor: "transparent",
    textStyle: { color: palette.secondaryInk },
    grid: { left: 52, right: 16, top: 24, bottom: 40 },
    tooltip: {
      trigger: "axis",
      valueFormatter: (value: unknown) =>
        typeof value === "number" ? formatValue(value) : "no data",
    },
    xAxis: {
      type: "category",
      data: categories,
      axisLine: { lineStyle: { color: palette.axisLine } },
      axisLabel: { color: palette.mutedInk },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      name: unitLabel,
      nameTextStyle: { color: palette.mutedInk },
      axisLabel: { color: palette.mutedInk },
      axisLine: { lineStyle: { color: palette.axisLine } },
      splitLine: { lineStyle: { color: palette.gridline } },
    },
    series: [
      {
        name: seriesName,
        type: kind,
        data: values,
        color: palette.series1,
        lineStyle:
          kind === "line" ? { width: 2, color: palette.series1 } : undefined,
        itemStyle: { color: palette.series1 },
        showSymbol: kind === "line" && points.length <= 60,
        symbolSize: 8,
        connectNulls: false,
      },
    ],
  };

  return { option, summary };
}

export interface SignalHistogramBucket {
  min_db: number;
  max_db: number;
  count: number;
}

/** SPEC §62's signal-strength distribution — a histogram bar chart over
 * per-sighting RSSI buckets (`docs/API.md` §3.8). */
export function buildSignalHistogramOption(params: {
  buckets: SignalHistogramBucket[];
  palette: ReceiverChartPalette;
}): ChartBuildResult {
  const { buckets, palette } = params;

  if (buckets.length === 0) {
    const message = "No signal readings in this window.";
    return { option: emptyOption(palette, message), summary: message };
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

  const option: echarts.EChartsCoreOption = {
    backgroundColor: "transparent",
    textStyle: { color: palette.secondaryInk },
    grid: { left: 52, right: 16, top: 24, bottom: 56 },
    tooltip: { trigger: "axis" },
    xAxis: {
      type: "category",
      name: "dB",
      data: categories,
      axisLabel: { color: palette.mutedInk, rotate: 45 },
      axisLine: { lineStyle: { color: palette.axisLine } },
    },
    yAxis: {
      type: "value",
      name: "Sightings",
      nameTextStyle: { color: palette.mutedInk },
      axisLabel: { color: palette.mutedInk },
      axisLine: { lineStyle: { color: palette.axisLine } },
      splitLine: { lineStyle: { color: palette.gridline } },
    },
    series: [
      {
        name: "Sightings",
        type: "bar",
        data: counts,
        itemStyle: { color: palette.series1 },
      },
    ],
  };

  return { option, summary };
}

export interface BearingSectorPoint {
  bearing_deg: number;
  value: number | null;
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
 * markers.
 */
export function buildRangeByBearingOption(params: {
  today: BearingSectorPoint[];
  ever: BearingSectorPoint[];
  unitLabel: string;
  formatValue: (value: number) => string;
  palette: ReceiverChartPalette;
}): ChartBuildResult {
  const { today, ever, unitLabel, formatValue, palette } = params;

  if (ever.length === 0) {
    const message = "No range-by-bearing data recorded yet.";
    return { option: emptyOption(palette, message), summary: message };
  }

  const categories = ever.map((sector) => `${Math.round(sector.bearing_deg)}°`);
  const everValues = ever.map((sector) => sector.value);
  const todayValues = today.map((sector) => sector.value);
  const everPresent = everValues.filter(
    (value): value is number => value !== null,
  );
  const todayPresent = todayValues.filter(
    (value): value is number => value !== null,
  );

  const summary =
    everPresent.length === 0
      ? "No range-by-bearing data recorded yet."
      : `Lifetime maximum range ${formatValue(Math.max(...everPresent))} across ${ever.length} bearing sectors; ` +
        `today's maximum is ${
          todayPresent.length > 0
            ? formatValue(Math.max(...todayPresent))
            : "not set yet"
        }.`;

  const option: echarts.EChartsCoreOption = {
    backgroundColor: "transparent",
    textStyle: { color: palette.secondaryInk },
    legend: {
      data: ["Ever", "Today"],
      top: 0,
      textStyle: { color: palette.secondaryInk },
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
      axisLabel: { color: palette.mutedInk, interval: 5 },
      axisLine: { lineStyle: { color: palette.axisLine } },
      splitLine: { lineStyle: { color: palette.gridline } },
    },
    radiusAxis: {
      type: "value",
      name: unitLabel,
      nameTextStyle: { color: palette.mutedInk },
      axisLabel: { color: palette.mutedInk },
      splitLine: { lineStyle: { color: palette.gridline } },
    },
    series: [
      {
        name: "Ever",
        type: "line",
        coordinateSystem: "polar",
        data: everValues,
        lineStyle: { width: 2, color: palette.series1, type: "solid" },
        itemStyle: { color: palette.series1 },
        symbol: "circle",
        symbolSize: 6,
        connectNulls: false,
      },
      {
        name: "Today",
        type: "line",
        coordinateSystem: "polar",
        data: todayValues,
        lineStyle: { width: 2, color: palette.series2, type: "dashed" },
        itemStyle: { color: palette.series2 },
        symbol: "diamond",
        symbolSize: 7,
        connectNulls: false,
      },
    ],
  };

  return { option, summary };
}
