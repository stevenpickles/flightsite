import type { UnitSystem } from "@/lib/api/config";
import { useReceiverRangeByBearingQuery } from "@/lib/api/receiverStats";
import { ChartCard } from "@/features/receiver/components/ChartCard";
import { EChart } from "@/features/receiver/components/EChart";
import { buildRangeByBearingOption } from "@/features/receiver/lib/chartOptions";
import {
  distanceAxisValue,
  distanceUnitLabel,
} from "@/features/receiver/lib/format";
import { chartPalette, useIsDarkTheme } from "@/features/receiver/lib/palette";

const TITLE_ID = "receiver-chart-range-by-bearing";
const TITLE = "Maximum range by bearing";

/** SPEC §62's polar max-range-by-bearing plot — today's coverage against the
 * receiver's lifetime record, in one chart. */
export function RangeByBearingChart({ units }: { units: UnitSystem }) {
  const isDark = useIsDarkTheme();
  const { data, isLoading, isError } = useReceiverRangeByBearingQuery();

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

  const ever = data.ever.map((sector) => ({
    bearing_deg: sector.bearing_deg,
    value:
      sector.max_range_nm === null
        ? null
        : distanceAxisValue(sector.max_range_nm, units),
  }));
  const today = data.today.map((sector) => ({
    bearing_deg: sector.bearing_deg,
    value:
      sector.max_range_nm === null
        ? null
        : distanceAxisValue(sector.max_range_nm, units),
  }));

  const { option, summary } = buildRangeByBearingOption({
    today,
    ever,
    unitLabel: distanceUnitLabel(units),
    formatValue: (value) => `${value} ${distanceUnitLabel(units)}`,
    palette: chartPalette(isDark),
  });

  return (
    <ChartCard titleId={TITLE_ID} title={TITLE}>
      <EChart
        option={option}
        ariaLabel={`${TITLE} polar chart. ${summary}`}
        style={{ height: 360 }}
      />
      <p className="mt-2 text-xs text-muted-foreground">{summary}</p>
    </ChartCard>
  );
}
