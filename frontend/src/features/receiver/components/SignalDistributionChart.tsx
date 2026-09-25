import { useCallback, useMemo } from "react";

import { useReceiverSignalDistributionQuery } from "@/lib/api/receiverStats";
import { EChart } from "@/features/analytics/components/EChart";
import type { ChartTheme } from "@/features/analytics/lib/chartTheme";
import { ChartCard } from "@/features/receiver/components/ChartCard";
import { buildSignalHistogramChart } from "@/features/receiver/lib/chartOptions";
import {
  formatDb,
  formatReceiverLocalDateTime,
} from "@/features/receiver/lib/format";

const TITLE_ID = "receiver-chart-signal-distribution";
const TITLE = "Signal strength distribution";

export interface SignalDistributionChartProps {
  timezone: string;
}

/** SPEC §62's signal-strength distribution, built from per-sighting
 * `rssi_avg_db` (roadmap slice 052) over the receiver's whole history by
 * default — `docs/API.md` §3.8. */
export function SignalDistributionChart({
  timezone,
}: SignalDistributionChartProps) {
  const { data, isLoading, isError, refetch } =
    useReceiverSignalDistributionQuery();
  const buckets = useMemo(() => data?.buckets ?? [], [data?.buckets]);

  const { summary } = useMemo(
    () => buildSignalHistogramChart({ buckets }),
    [buckets],
  );
  const buildOption = useCallback(
    (theme: ChartTheme) =>
      buildSignalHistogramChart({ buckets }).buildOption(theme),
    [buckets],
  );

  // R3-13: the endpoint returns its covered window and its own summary
  // stats (sample_count/avg_db/min_db/max_db) alongside the buckets, and
  // this card used to read only `buckets` — discarding the answer to "from
  // when, and what's the average?", the single most useful number for an
  // owner tuning an antenna.
  const windowCaption =
    data === undefined
      ? undefined
      : data.from_ts !== null && data.to_ts !== null
        ? `${formatReceiverLocalDateTime(data.from_ts, timezone)} – ${formatReceiverLocalDateTime(data.to_ts, timezone)}`
        : "receiver's whole history";
  const statsCaption =
    data === undefined || data.sample_count === 0
      ? undefined
      : `${data.sample_count} ${data.sample_count === 1 ? "sample" : "samples"}, average ${formatDb(data.avg_db)}, range ${formatDb(data.min_db)} to ${formatDb(data.max_db)}`;

  return (
    <ChartCard
      titleId={TITLE_ID}
      title={TITLE}
      isLoading={isLoading}
      error={isError ? "Could not load this chart." : undefined}
      onRetry={() => void refetch()}
    >
      <EChart
        buildOption={buildOption}
        ariaLabel={`${TITLE} chart`}
        summary={summary}
      />
      {(windowCaption !== undefined || statsCaption !== undefined) && (
        <p className="mt-1 text-xs text-muted-foreground">
          {windowCaption !== undefined && <>Window: {windowCaption}. </>}
          {statsCaption !== undefined && <>{statsCaption}.</>}
        </p>
      )}
    </ChartCard>
  );
}
