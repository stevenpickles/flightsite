import { useReceiverSignalDistributionQuery } from "@/lib/api/receiverStats";
import { ChartCard } from "@/features/receiver/components/ChartCard";
import { EChart } from "@/features/receiver/components/EChart";
import { buildSignalHistogramOption } from "@/features/receiver/lib/chartOptions";
import { chartPalette, useIsDarkTheme } from "@/features/receiver/lib/palette";

const TITLE_ID = "receiver-chart-signal-distribution";
const TITLE = "Signal strength distribution";

/** SPEC §62's signal-strength distribution, built from per-sighting
 * `rssi_avg_db` (roadmap slice 052) over the receiver's whole history by
 * default — `docs/API.md` §3.8. */
export function SignalDistributionChart() {
  const isDark = useIsDarkTheme();
  const { data, isLoading, isError } = useReceiverSignalDistributionQuery();

  if (isLoading) {
    return (
      <ChartCard titleId={TITLE_ID} title={TITLE}>
        <p className="text-sm text-muted-foreground">Loading…</p>
      </ChartCard>
    );
  }

  if (isError || data === undefined) {
    return (
      <ChartCard titleId={TITLE_ID} title={TITLE}>
        <p className="text-sm text-destructive">Could not load this chart.</p>
      </ChartCard>
    );
  }

  const { option, summary } = buildSignalHistogramOption({
    buckets: data.buckets,
    palette: chartPalette(isDark),
  });

  return (
    <ChartCard titleId={TITLE_ID} title={TITLE}>
      <EChart option={option} ariaLabel={`${TITLE} chart. ${summary}`} />
      <p className="mt-2 text-xs text-muted-foreground">{summary}</p>
    </ChartCard>
  );
}
