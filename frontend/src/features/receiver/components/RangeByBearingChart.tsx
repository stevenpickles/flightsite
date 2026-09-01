import { useCallback, useMemo } from "react";

import type { UnitSystem } from "@/lib/api/config";
import { useReceiverRangeByBearingQuery } from "@/lib/api/receiverStats";
import { EChart } from "@/features/analytics/components/EChart";
import type { ChartTheme } from "@/features/analytics/lib/chartTheme";
import { ChartCard } from "@/features/receiver/components/ChartCard";
import {
  buildRangeByBearingChart,
  type BearingSectorPoint,
} from "@/features/receiver/lib/chartOptions";
import {
  distanceAxisValue,
  distanceUnitLabel,
} from "@/features/receiver/lib/format";

const TITLE_ID = "receiver-chart-range-by-bearing";
const TITLE = "Maximum range by bearing";
/** Taller than the default chart height: a polar plot's angle axis needs the
 * extra vertical room a rectangular chart's doesn't. */
const POLAR_HEIGHT = 360;

/** SPEC §62's polar max-range-by-bearing plot — today's coverage against the
 * receiver's lifetime record, in one chart. */
export function RangeByBearingChart({ units }: { units: UnitSystem }) {
  const { data, isLoading, isError } = useReceiverRangeByBearingQuery();

  const ever: BearingSectorPoint[] = useMemo(
    () =>
      (data?.ever ?? []).map((sector) => ({
        bearing_deg: sector.bearing_deg,
        value:
          sector.max_range_nm === null
            ? null
            : distanceAxisValue(sector.max_range_nm, units),
      })),
    [data?.ever, units],
  );
  const today: BearingSectorPoint[] = useMemo(
    () =>
      (data?.today ?? []).map((sector) => ({
        bearing_deg: sector.bearing_deg,
        value:
          sector.max_range_nm === null
            ? null
            : distanceAxisValue(sector.max_range_nm, units),
      })),
    [data?.today, units],
  );

  const { summary } = useMemo(
    () =>
      buildRangeByBearingChart({
        today,
        ever,
        unitLabel: distanceUnitLabel(units),
        formatValue: (value) => `${value} ${distanceUnitLabel(units)}`,
      }),
    [today, ever, units],
  );

  const buildOption = useCallback(
    (theme: ChartTheme) =>
      buildRangeByBearingChart({
        today,
        ever,
        unitLabel: distanceUnitLabel(units),
        formatValue: (value) => `${value} ${distanceUnitLabel(units)}`,
      }).buildOption(theme),
    [today, ever, units],
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
        ariaLabel={`${TITLE} polar chart`}
        summary={summary}
        height={POLAR_HEIGHT}
      />
    </ChartCard>
  );
}
