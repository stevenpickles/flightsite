import type { UnitSystem } from "@/lib/api/config";
import {
  useReceiverMetricSeriesQuery,
  type ReceiverSeriesResolution,
} from "@/lib/api/receiverStats";
import { ChartCard } from "@/features/receiver/components/ChartCard";
import { EChart } from "@/features/receiver/components/EChart";
import {
  buildTimeSeriesChartOption,
  type ChartPoint,
} from "@/features/receiver/lib/chartOptions";
import type { MetricChartConfig } from "@/features/receiver/lib/metricConfig";
import { chartPalette, useIsDarkTheme } from "@/features/receiver/lib/palette";

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
  const isDark = useIsDarkTheme();
  const effectiveResolution = config.alwaysDaily ? "daily" : resolution;
  const { data, isLoading, isError } = useReceiverMetricSeriesQuery({
    metric: config.metric,
    resolution: effectiveResolution,
  });

  const titleId = `receiver-chart-${config.metric}`;

  if (isLoading) {
    return (
      <ChartCard titleId={titleId} title={config.title}>
        <p className="text-sm text-muted-foreground">Loading…</p>
      </ChartCard>
    );
  }

  if (isError || data === undefined) {
    return (
      <ChartCard titleId={titleId} title={config.title}>
        <p className="text-sm text-destructive">Could not load this chart.</p>
      </ChartCard>
    );
  }

  const points: ChartPoint[] = data.points.map((point) => ({
    t: point.t,
    value: point.value === null ? null : config.convert(point.value, units),
  }));

  const { option, summary } = buildTimeSeriesChartOption({
    points,
    kind: config.kind,
    timezone,
    resolution: effectiveResolution,
    seriesName: config.title,
    unitLabel: config.unitLabel(units),
    palette: chartPalette(isDark),
    formatValue: (value) => config.formatValue(value, units),
  });

  return (
    <ChartCard titleId={titleId} title={config.title}>
      <EChart option={option} ariaLabel={`${config.title} chart. ${summary}`} />
      <p className="mt-2 text-xs text-muted-foreground">{summary}</p>
    </ChartCard>
  );
}
