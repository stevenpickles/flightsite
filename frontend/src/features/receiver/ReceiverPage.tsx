/**
 * The Receiver page (roadmap slice 034): scorecard (SPEC §61), charts
 * (SPEC §62, including the range-by-bearing polar plot and the signal-
 * strength distribution), and lifetime statistics (SPEC §63).
 */
import { useState } from "react";

import { useReceiverQuery } from "@/lib/api/receiver";
import { LifetimeStatsSection } from "@/features/receiver/components/LifetimeStatsSection";
import { RangeByBearingChart } from "@/features/receiver/components/RangeByBearingChart";
import { ReceiverScorecard } from "@/features/receiver/components/ReceiverScorecard";
import { ReceiverSeriesChart } from "@/features/receiver/components/ReceiverSeriesChart";
import { SignalDistributionChart } from "@/features/receiver/components/SignalDistributionChart";
import { WindowSelector } from "@/features/receiver/components/WindowSelector";
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

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      <div>
        <h1 className="text-lg font-semibold">Receiver</h1>
        <p className="text-sm text-muted-foreground">
          Performance and coverage of your own receiver.
        </p>
      </div>

      <ReceiverScorecard units={units} />

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
        <SignalDistributionChart />
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
