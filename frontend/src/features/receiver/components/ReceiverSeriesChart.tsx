import { useCallback, useMemo } from "react";

import type { UnitSystem } from "@/lib/api/config";
import {
  useReceiverMetricSeriesQuery,
  type ReceiverSeriesResolution,
} from "@/lib/api/receiverStats";
import { EChart } from "@/features/analytics/components/EChart";
import type { ChartTheme } from "@/features/analytics/lib/chartTheme";
import { ChartCard } from "@/features/receiver/components/ChartCard";
import {
  buildTimeSeriesChart,
  type ChartPoint,
} from "@/features/receiver/lib/chartOptions";
import type { MetricChartConfig } from "@/features/receiver/lib/metricConfig";

interface ReceiverSeriesChartProps {
  config: MetricChartConfig;
  /** The page's window-selector resolution; ignored (always `"daily"`) when
   * `config.alwaysDaily` is set. */
  resolution: ReceiverSeriesResolution;
  units: UnitSystem;
  timezone: string;
}

/** One SPEC §62 line/bar chart, driven entirely by `config`
 * (`features/receiver/lib/metricConfig.ts`) — the same component renders
 * messages/sec, positions/sec, simultaneous aircraft, maximum range, unique
 * aircraft per day, and both daily totals charts. */
export function ReceiverSeriesChart({
  config,
  resolution,
  units,
  timezone,
}: ReceiverSeriesChartProps) {
  const effectiveResolution = config.alwaysDaily ? "daily" : resolution;
  const { data, isLoading, isError } = useReceiverMetricSeriesQuery({
    metric: config.metric,
    resolution: effectiveResolution,
  });

  const points: ChartPoint[] = useMemo(
    () =>
      (data?.points ?? []).map((point) => ({
        t: point.t,
        value: point.value === null ? null : config.convert(point.value, units),
      })),
    [data?.points, config, units],
  );

  const { summary } = useMemo(
    () =>
      buildTimeSeriesChart({
        points,
        kind: config.kind,
        timezone,
        resolution: effectiveResolution,
        seriesName: config.title,
        unitLabel: config.unitLabel(units),
        formatValue: (value) => config.formatValue(value, units),
      }),
    [points, config, timezone, effectiveResolution, units],
  );

  // Stable across re-renders the underlying data/settings did not touch
  // (e.g. a theme toggle) — `EChart` re-derives its option from this and
  // `theme` alone, so an unstable reference here would re-render the chart
  // on every unrelated parent render.
  const buildOption = useCallback(
    (theme: ChartTheme) =>
      buildTimeSeriesChart({
        points,
        kind: config.kind,
        timezone,
        resolution: effectiveResolution,
        seriesName: config.title,
        unitLabel: config.unitLabel(units),
        formatValue: (value) => config.formatValue(value, units),
      }).buildOption(theme),
    [points, config, timezone, effectiveResolution, units],
  );

  const titleId = `receiver-chart-${config.metric}`;

  return (
    <ChartCard
      titleId={titleId}
      title={config.title}
      isLoading={isLoading}
      error={isError ? "Could not load this chart." : undefined}
    >
      <EChart
        buildOption={buildOption}
        ariaLabel={`${config.title} chart`}
        summary={summary}
      />
    </ChartCard>
  );
}
