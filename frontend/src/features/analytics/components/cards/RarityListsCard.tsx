/**
 * "Locally rare aircraft/type information" plus the window's never-seen-
 * before total (SPEC §58, `GET /api/v1/analytics/rarity`) — two ranked
 * tables rather than a chart: rarity is a short, specific list of airframes
 * and types, exactly the case where a table reads faster than a plot.
 *
 * Both tables use the "Top …" cards' presentation (slice 097), so an
 * aircraft or a type reads the same wherever the page lists it: a rare
 * aircraft is its tail (linked to the aircraft detail route, roadmap slice
 * 029), its type in words over the designator, who flies it, and its
 * lifetime sighting count; a rare type leads with its long-form name over
 * the designator, then distinct airframes and sightings. Type designators
 * have no detail route in this app, so rare-type rows stay plain text.
 *
 * The card spans the page's full width with the two tables side by side.
 * Stacked in one grid column it stood several times taller than the charts
 * beside it, and a grid row is as tall as its tallest card — so its
 * neighbours became large, mostly empty boxes.
 */
import type {
  AnalyticsAircraftRow,
  AnalyticsRareType,
  AnalyticsWindow,
} from "@/lib/api/analytics";

import { AnalyticsCard } from "@/features/analytics/components/AnalyticsCard";
import {
  AIRCRAFT_RANKING_COLUMNS,
  namedCell,
} from "@/features/analytics/components/rankingColumns";
import {
  RankingTable,
  type RankingColumn,
} from "@/features/analytics/components/RankingTable";

export interface RarityListsCardProps {
  window?: AnalyticsWindow;
  neverSeenBefore: number;
  rareMaxSightings: number;
  rareAircraft: AnalyticsAircraftRow[];
  rareTypes: AnalyticsRareType[];
  isLoading: boolean;
  error?: string;
  errorDetail?: string;
  onRetry?: () => void;
}

const RARE_TYPE_COLUMNS: ReadonlyArray<RankingColumn<AnalyticsRareType>> = [
  {
    key: "name",
    heading: "Type",
    width: 62,
    render: (row) => namedCell(row.description, row.type),
  },
  {
    key: "aircraft",
    heading: "Aircraft",
    width: 18,
    align: "right",
    render: (row) => row.unique_aircraft,
  },
  {
    key: "sightings",
    heading: "Sightings",
    width: 20,
    align: "right",
    render: (row) => row.total_sightings,
  },
];

const SECTION_HEADING =
  "mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground";

export function RarityListsCard({
  window,
  neverSeenBefore,
  rareMaxSightings,
  rareAircraft,
  rareTypes,
  isLoading,
  error,
  errorDetail,
  onRetry,
}: RarityListsCardProps) {
  return (
    <AnalyticsCard
      title="Locally rare"
      window={window}
      isLoading={isLoading}
      error={error}
      errorDetail={errorDetail}
      onRetry={onRetry}
      className="lg:col-span-2 xl:col-span-3"
    >
      <p className="text-sm text-foreground">
        <span className="font-semibold">{neverSeenBefore}</span> aircraft never
        seen before this window.
      </p>

      <div className="grid grid-cols-1 gap-x-8 gap-y-4 lg:grid-cols-2">
        <div className="min-w-0">
          <h3 className={SECTION_HEADING}>
            Rare aircraft{" "}
            <span className="normal-case">
              (lifetime sightings ≤ {rareMaxSightings})
            </span>
          </h3>
          <RankingTable
            columns={AIRCRAFT_RANKING_COLUMNS}
            rows={rareAircraft}
            rowKey={(row) => row.icao}
            emptyLabel="No rare aircraft in this window."
            ariaLabel="Rare aircraft"
          />
        </div>

        <div className="min-w-0">
          <h3 className={SECTION_HEADING}>Rare types</h3>
          <RankingTable
            columns={RARE_TYPE_COLUMNS}
            rows={rareTypes}
            rowKey={(row) => row.type}
            emptyLabel="No rare types in this window."
            ariaLabel="Rare types"
          />
        </div>
      </div>
    </AnalyticsCard>
  );
}
