import { useState } from "react";

import { GapTimeline } from "@/features/feeders/components/GapTimeline";
import { FeederMetricsChart } from "@/features/feeders/components/FeederMetricsChart";
import type { AvailabilityWindow } from "@/features/feeders/lib/availability";
import { describeError } from "@/lib/api/client";
import { useFeederHistoryQuery } from "@/lib/api/feeders";

interface FeederHistorySectionProps {
  feederName: string;
  feederLabel: string;
  timezone: string;
}

const DEFAULT_WINDOW: AvailabilityWindow = "24h";

/**
 * One feeder's history: its own `24h`/`7d`/`30d` window (design record
 * "GapTimeline … with a window selector"), the gap timeline for that
 * window, and the metric charts built from the same history payload's
 * samples. Self-contained and independently fetched per feeder rather than
 * one page-wide window, since a receiver-uplink feed and a socket-only feed
 * that only just started being observed are not usefully compared on the
 * same clock.
 */
export function FeederHistorySection({
  feederName,
  feederLabel,
  timezone,
}: FeederHistorySectionProps) {
  const [window, setWindow] = useState<AvailabilityWindow>(DEFAULT_WINDOW);
  const query = useFeederHistoryQuery(feederName, window);

  return (
    <div className="flex flex-col gap-3">
      <GapTimeline
        feederName={feederName}
        feederLabel={feederLabel}
        episodes={query.data?.episodes}
        isLoading={query.isPending}
        isError={query.isError}
        errorMessage={query.isError ? describeError(query.error) : undefined}
        window={window}
        onWindowChange={setWindow}
        timezone={timezone}
      />
      {query.data !== undefined && (
        <FeederMetricsChart
          feederLabel={feederLabel}
          samples={query.data.samples}
          window={window}
          timezone={timezone}
        />
      )}
    </div>
  );
}
