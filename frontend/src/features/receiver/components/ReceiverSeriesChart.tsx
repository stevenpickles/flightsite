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
  const primaryResolution = config.alwaysDaily ? "daily" : resolution;
  const primaryQuery = useReceiverMetricSeriesQuery({
    metric: config.metric,
    resolution: primaryResolution,
  });

  // R3-02 (A1's backend fix deferred here): the default /receiver window is
  // 7d -> hourly, and `receiver_metrics_hourly` has no rows for the first
  // several minutes of any install, so the hourly series reads empty even
  // though raw ("high") samples already exist — a receiver plainly
  // receiving data would otherwise open on "No data for this window."
  // Fetched only once the primary query has actually resolved to zero
  // points, never speculatively.
  const hourlyEmpty =
    primaryResolution === "hourly" &&
    primaryQuery.isSuccess &&
    primaryQuery.data.points.length === 0;
  const fallbackQuery = useReceiverMetricSeriesQuery(
    { metric: config.metric, resolution: "high" },
    { enabled: hourlyEmpty },
  );
  const usingFallback =
    hourlyEmpty &&
    fallbackQuery.isSuccess &&
    fallbackQuery.data.points.length > 0;

  const activeQuery = usingFallback ? fallbackQuery : primaryQuery;
  const effectiveResolution = usingFallback ? "high" : primaryResolution;
  const isLoading =
    primaryQuery.isPending || (hourlyEmpty && fallbackQuery.isPending);
  const isError = primaryQuery.isError;
  const refetch = useCallback(() => {
    void primaryQuery.refetch();
    if (hourlyEmpty) {
      void fallbackQuery.refetch();
    }
  }, [primaryQuery, fallbackQuery, hourlyEmpty]);

  const points: ChartPoint[] = useMemo(
    () =>
      (activeQuery.data?.points ?? []).map((point) => ({
        t: point.t,
        value: point.value === null ? null : config.convert(point.value, units),
      })),
    [activeQuery.data?.points, config, units],
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
      onRetry={() => void refetch()}
    >
      <EChart
        buildOption={buildOption}
        ariaLabel={`${config.title} chart`}
        summary={summary}
      />
    </ChartCard>
  );
}
