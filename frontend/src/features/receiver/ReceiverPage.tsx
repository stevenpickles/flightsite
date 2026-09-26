/**
 * The Receiver page (roadmap slice 034): scorecard (SPEC §61), charts
 * (SPEC §62, including the range-by-bearing polar plot and the signal-
 * strength distribution), and lifetime statistics (SPEC §63).
 */
import { Stethoscope } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  RECEIVER_CHART_REFETCH_INTERVAL_MS,
  useReceiverRangeByBearingQuery,
} from "@/lib/api/receiverStats";
import { useReceiverQuery } from "@/lib/api/receiver";
import { FeedersSummaryCard } from "@/features/receiver/components/FeedersSummaryCard";
import { LifetimeStatsSection } from "@/features/receiver/components/LifetimeStatsSection";
import { RangeByBearingChart } from "@/features/receiver/components/RangeByBearingChart";
import { ReceiverScorecard } from "@/features/receiver/components/ReceiverScorecard";
import { ReceiverSeriesChart } from "@/features/receiver/components/ReceiverSeriesChart";
import { SignalDistributionChart } from "@/features/receiver/components/SignalDistributionChart";
import { WindowSelector } from "@/features/receiver/components/WindowSelector";
import { formatReceiverLocalClock } from "@/features/receiver/lib/format";
import {
  METRIC_CHARTS,
  WINDOW_RESOLUTION,
  type ReceiverWindow,
} from "@/features/receiver/lib/metricConfig";

const DEFAULT_WINDOW: ReceiverWindow = "7d";

export function ReceiverPage() {
  const [timeWindow, setTimeWindow] = useState<ReceiverWindow>(DEFAULT_WINDOW);
  const { data: receiver } = useReceiverQuery();
  const units = receiver?.units ?? "aviation";
  const timezone = receiver?.timezone ?? "UTC";
  const resolution = WINDOW_RESOLUTION[timeWindow];

  const windowedCharts = METRIC_CHARTS.filter((config) => !config.alwaysDaily);
  const dailyCharts = METRIC_CHARTS.filter((config) => config.alwaysDaily);

  // R3-06: one freshness caption for the whole page. `RangeByBearingChart`
  // renders unconditionally below and queries this same key, so this call
  // shares its cache entry rather than firing a second request — it exists
  // here only to read `dataUpdatedAt` for the caption.
  const freshnessQuery = useReceiverRangeByBearingQuery();
  const dataAsOf =
    freshnessQuery.dataUpdatedAt > 0 ? freshnessQuery.dataUpdatedAt : undefined;

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Receiver</h1>
          <p className="text-sm text-muted-foreground">
            Performance and coverage of your own receiver.
          </p>
          {dataAsOf !== undefined && (
            <p className="mt-1 text-xs text-muted-foreground">
              Data as of{" "}
              {formatReceiverLocalClock(
                new Date(dataAsOf).toISOString(),
                timezone,
              )}{" "}
              {timezone} · refreshes every{" "}
              {Math.round(RECEIVER_CHART_REFETCH_INTERVAL_MS / 1000)} s
            </p>
          )}
        </div>
        {/* SPEC §10 fixes the sidebar at seven sections, so the health area
            (SPEC §67) is reached from here — the page a user already opens
            when they suspect something is wrong. */}
        <Link
          to="/health"
          className="inline-flex items-center gap-1.5 self-start rounded-md border border-border px-3 py-1.5 text-sm font-medium transition-colors hover:bg-secondary"
        >
          <Stethoscope className="size-4" aria-hidden="true" />
          Health &amp; diagnostics
        </Link>
      </div>

      <h2 className="text-base font-medium">Scorecard</h2>
      <ReceiverScorecard
        units={units}
        t0={receiver?.t0 ?? null}
        timezone={timezone}
      />

      {/* Roadmap slice 077: a one-line pointer to the Feeders sub-page,
          discoverable from here even before any feeder is configured. */}
      <FeedersSummaryCard />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-medium">Charts</h2>
        <WindowSelector value={timeWindow} onChange={setTimeWindow} />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {windowedCharts.map((config) => (
          <ReceiverSeriesChart
            key={config.metric}
            config={config}
            resolution={resolution}
            units={units}
            timezone={timezone}
          />
        ))}
        <RangeByBearingChart units={units} />
        <SignalDistributionChart timezone={timezone} />
        {dailyCharts.map((config) => (
          <ReceiverSeriesChart
            key={config.metric}
            config={config}
            resolution="daily"
            units={units}
            timezone={timezone}
          />
        ))}
      </div>

      <LifetimeStatsSection units={units} timezone={timezone} />
    </div>
  );
}
