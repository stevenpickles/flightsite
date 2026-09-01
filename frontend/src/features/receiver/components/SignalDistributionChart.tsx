import { useCallback, useMemo } from "react";

import { useReceiverSignalDistributionQuery } from "@/lib/api/receiverStats";
import { EChart } from "@/features/analytics/components/EChart";
import type { ChartTheme } from "@/features/analytics/lib/chartTheme";
import { ChartCard } from "@/features/receiver/components/ChartCard";
import { buildSignalHistogramChart } from "@/features/receiver/lib/chartOptions";

const TITLE_ID = "receiver-chart-signal-distribution";
const TITLE = "Signal strength distribution";

/** SPEC §62's signal-strength distribution, built from per-sighting
 * `rssi_avg_db` (roadmap slice 052) over the receiver's whole history by
 * default — `docs/API.md` §3.8. */
export function SignalDistributionChart() {
  const { data, isLoading, isError } = useReceiverSignalDistributionQuery();
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

  return (
    <ChartCard
      titleId={TITLE_ID}
      title={TITLE}
      isLoading={isLoading}
      error={isError ? "Could not load this chart." : undefined}
    >
      <EChart
        buildOption={buildOption}
        ariaLabel={`${TITLE} chart`}
        summary={summary}
      />
    </ChartCard>
  );
}
