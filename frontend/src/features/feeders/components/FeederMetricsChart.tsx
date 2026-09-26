import { useCallback, useMemo } from "react";

import { EChart } from "@/features/analytics/components/EChart";
import type { ChartTheme } from "@/features/analytics/lib/chartTheme";
import { ChartCard } from "@/features/receiver/components/ChartCard";
import {
  buildFeederMetricChart,
  hasMetricSamples,
} from "@/features/feeders/lib/chartOptions";
import { formatBytesRate } from "@/features/feeders/lib/format";
import type { AvailabilityWindow } from "@/features/feeders/lib/availability";
import type { FeederSample } from "@/lib/api/feeders";

interface MetricFamily {
  key: string;
  title: string;
  unitLabel: string;
  formatValue: (value: number) => string;
}

/** The three metric families the design record names ("Frontend": "MLAT
 * peers, bytes-out rate, positions per minute"), keyed to the loose
 * `FeederSample.metrics` field names `lib/api/feeders.ts` documents. */
const METRIC_FAMILIES: readonly MetricFamily[] = [
  {
    key: "mlat_peers",
    title: "MLAT peers",
    unitLabel: "peers",
    formatValue: (value) => `${Math.round(value)} peers`,
  },
  {
    key: "bytes_out_rate_per_s",
    title: "Bytes out",
    unitLabel: "B/s",
    formatValue: (value) => formatBytesRate(value),
  },
  {
    key: "positions_per_min",
    title: "Positions per minute",
    unitLabel: "pos/min",
    formatValue: (value) => `${Math.round(value)}/min`,
  },
];

interface FeederMetricChartPanelProps {
  feederLabel: string;
  samples: readonly FeederSample[];
  window: AvailabilityWindow;
  timezone: string;
  family: MetricFamily;
}

function FeederMetricChartPanel({
  feederLabel,
  samples,
  window,
  timezone,
  family,
}: FeederMetricChartPanelProps) {
  const params = {
    samples,
    metricKey: family.key,
    window,
    timezone,
    seriesName: family.title,
    unitLabel: family.unitLabel,
    formatValue: family.formatValue,
  };

  // Stable across re-renders the underlying data/window did not touch (e.g.
  // a theme toggle) — the same reasoning `ReceiverSeriesChart` gives for its
  // own `buildOption`. `params` is a fresh object every render by
  // construction; its members below are the real dependencies.
  const buildOption = useCallback(
    (theme: ChartTheme) => buildFeederMetricChart(params).buildOption(theme),
    [samples, family, window, timezone], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const { summary } = useMemo(
    () => buildFeederMetricChart(params),
    [samples, family, window, timezone], // eslint-disable-line react-hooks/exhaustive-deps
  );

  const titleId = `feeder-chart-${feederLabel}-${family.key}`;

  return (
    <ChartCard titleId={titleId} title={family.title}>
      <EChart
        buildOption={buildOption}
        ariaLabel={`${feederLabel} ${family.title} chart`}
        summary={summary}
      />
    </ChartCard>
  );
}

interface FeederMetricsChartProps {
  feederLabel: string;
  samples: readonly FeederSample[];
  window: AvailabilityWindow;
  timezone: string;
}

/**
 * One `EChart` per metric family this feeder's samples actually carry
 * (design record "Frontend": "hide a chart with no samples") — a feeder
 * with no MLAT signal shows no MLAT-peers chart at all rather than an
 * empty one next to two populated ones. Renders nothing when none of the
 * three families have any reading in the window.
 */
export function FeederMetricsChart({
  feederLabel,
  samples,
  window,
  timezone,
}: FeederMetricsChartProps) {
  const families = METRIC_FAMILIES.filter((family) =>
    hasMetricSamples(samples, family.key),
  );

  if (families.length === 0) {
    return null;
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {families.map((family) => (
        <FeederMetricChartPanel
          key={family.key}
          feederLabel={feederLabel}
          samples={samples}
          window={window}
          timezone={timezone}
          family={family}
        />
      ))}
    </div>
  );
}
