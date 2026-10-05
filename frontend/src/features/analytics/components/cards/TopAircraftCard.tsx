/**
 * "Most frequently seen aircraft" (SPEC §58) — the window's top airframes by
 * sighting count, as a ranked table (slice 095; a horizontal bar chart
 * before that). Each row names the aircraft, says what it is in words and
 * who flies it, and gives the count; the tail links to the aircraft's
 * history detail (roadmap slice 029), the same destination the Aircraft
 * page's table rows use.
 *
 * The columns themselves live in `rankingColumns.tsx`, shared with the
 * "Locally rare" card so an aircraft reads the same in both.
 */
import type {
  AnalyticsAircraftRow,
  AnalyticsWindow,
} from "@/lib/api/analytics";

import { AnalyticsCard } from "@/features/analytics/components/AnalyticsCard";
import { AIRCRAFT_RANKING_COLUMNS } from "@/features/analytics/components/rankingColumns";
import { RankingTable } from "@/features/analytics/components/RankingTable";

export interface TopAircraftCardProps {
  window?: AnalyticsWindow;
  rows: AnalyticsAircraftRow[];
  isLoading: boolean;
  error?: string;
  errorDetail?: string;
  onRetry?: () => void;
}

export function TopAircraftCard({
  window,
  rows,
  isLoading,
  error,
  errorDetail,
  onRetry,
}: TopAircraftCardProps) {
  return (
    <AnalyticsCard
      title="Top aircraft"
      window={window}
      isLoading={isLoading}
      error={error}
      errorDetail={errorDetail}
      onRetry={onRetry}
    >
      <RankingTable
        columns={AIRCRAFT_RANKING_COLUMNS}
        rows={rows}
        rowKey={(row) => row.icao}
        emptyLabel="No aircraft sighted in this window."
        ariaLabel="Top aircraft by sightings"
      />
    </AnalyticsCard>
  );
}
