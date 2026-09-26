/**
 * Pure ECharts `option` builders for `FeederMetricsChart` (roadmap slice
 * 077), built against the same `EChart` wrapper contract
 * `features/receiver/lib/chartOptions.ts` established: each builder returns
 * `buildOption(theme) => option | null` plus the `summary` text the wrapper
 * renders as its visually-hidden text alternative and `aria-label`
 * (SPEC §80). Returning `null` is how a builder asks the wrapper to render
 * its "No data" empty state — `FeederMetricsChart` additionally hides the
 * whole card for a metric family with zero samples (design record: "hide a
 * chart with no samples"), which this module leaves to the component since
 * it needs no chart-option knowledge to decide.
 *
 * Kept free of React so the axis mapping and empty-state summaries can be
 * asserted against fixtures without mounting a chart.
 */
import type * as echarts from "echarts/core";

import type { ChartTheme } from "@/features/analytics/lib/chartTheme";
import { pluralize } from "@/features/analytics/lib/format";
import type { AvailabilityWindow } from "@/features/feeders/lib/availability";
import {
  formatReceiverLocalDate,
  formatReceiverLocalDateTime,
  formatReceiverLocalTime,
} from "@/features/receiver/lib/format";
import type { FeederSample } from "@/lib/api/feeders";

export interface ChartResult {
  buildOption: (theme: ChartTheme) => echarts.EChartsCoreOption | null;
  summary: string;
}

function axisLabel(
  iso: string,
  timezone: string,
  window: AvailabilityWindow,
): string {
  if (window === "30d") {
    return formatReceiverLocalDate(iso, timezone);
  }
  if (window === "7d") {
    return formatReceiverLocalDateTime(iso, timezone);
  }
  return formatReceiverLocalTime(iso, timezone);
}

/** One sample's reading for `metricKey` — `undefined`/missing keys and
 * explicit `null` both read as "no reading at that instant" (§2.7), which
 * keeps a feeder that only started reporting a metric partway through the
 * window from drawing a false zero for the rest of it. */
function metricValue(sample: FeederSample, metricKey: string): number | null {
  const raw = sample.metrics[metricKey];
  return raw === undefined ? null : raw;
}

export interface FeederMetricChartParams {
  samples: readonly FeederSample[];
  metricKey: string;
  window: AvailabilityWindow;
  timezone: string;
  seriesName: string;
  unitLabel: string;
  formatValue: (value: number) => string;
}

/** One metric family's line chart (MLAT peers, bytes-out rate, positions
 * per minute — design record "Frontend"), driven entirely by `metricKey`
 * into each sample's loosely-typed `metrics` map. */
export function buildFeederMetricChart(
  params: FeederMetricChartParams,
): ChartResult {
  const {
    samples,
    metricKey,
    window,
    timezone,
    seriesName,
    unitLabel,
    formatValue,
  } = params;

  const present = samples.filter(
    (sample) => metricValue(sample, metricKey) !== null,
  );

  if (present.length === 0) {
    return {
      buildOption: () => null,
      summary: `No ${seriesName.toLowerCase()} samples in this window.`,
    };
  }

  const categories = samples.map((sample) =>
    axisLabel(sample.t, timezone, window),
  );
  const values = samples.map((sample) => metricValue(sample, metricKey));
  const presentValues = present.map(
    (sample) => metricValue(sample, metricKey) as number,
  );
  const latest = presentValues[presentValues.length - 1] as number;
  const peak = Math.max(...presentValues);

  const sampleWord = pluralize(present.length, "sample");
  const summary =
    `${seriesName}: ${present.length} ${sampleWord}. ` +
    `Latest ${formatValue(latest)}, peak ${formatValue(peak)}.`;

  return {
    summary,
    buildOption: (theme) => ({
      backgroundColor: "transparent",
      textStyle: { color: theme.mutedInk },
      grid: { left: 56, right: 16, top: 24, bottom: 40 },
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
          type: "line",
          data: values,
          color: theme.series[0],
          lineStyle: { width: 2, color: theme.series[0] },
          itemStyle: { color: theme.series[0] },
          showSymbol: values.length <= 60,
          symbolSize: 6,
          connectNulls: false,
        },
      ],
    }),
  };
}

/** Whether any sample in the window carries a reading for `metricKey` — the
 * component's own check for whether to render the card at all (design
 * record: "hide a chart with no samples"). */
export function hasMetricSamples(
  samples: readonly FeederSample[],
  metricKey: string,
): boolean {
  return samples.some((sample) => metricValue(sample, metricKey) !== null);
}
