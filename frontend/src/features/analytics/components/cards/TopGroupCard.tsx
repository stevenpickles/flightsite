/**
 * "Most frequently seen types/models" and "most common operators" (SPEC
 * §58) — both `/api/v1/analytics/top-types` and `/top-operators` return the
 * identical `AnalyticsGroupRow` shape (`docs/API.md` §3.8: "key"/"label"
 * over a type designator or an operator group), so one ranked-table card
 * renders either, parameterized by title and which rows it was given —
 * SightingsPage-style reuse rather than two near-duplicate components.
 * Neither a type designator nor an operator group has its own detail route
 * in this app, so the name cells are plain text (unlike
 * {@link TopAircraftCard}).
 *
 * A horizontal bar chart until slice 095. A type row's `description` — the
 * long form behind the designator, "Boeing 737-800" beside "B738" — is now
 * the name the row leads with, the designator muted beneath it; a row
 * without one (every operator row, and a type no imported airframe
 * describes) shows its label alone. Beside the name: how many distinct
 * airframes and how many sightings the window saw.
 */
import type { AnalyticsGroupRow, AnalyticsWindow } from "@/lib/api/analytics";

import { AnalyticsCard } from "@/features/analytics/components/AnalyticsCard";
import { namedCell } from "@/features/analytics/components/rankingColumns";
import {
  RankingTable,
  type RankingColumn,
} from "@/features/analytics/components/RankingTable";

export interface TopGroupCardProps {
  title: string;
  /** Names the table for assistive technology — e.g. "Top types by
   * sightings". */
  ariaLabel: string;
  /** The first column's heading: "Type" or "Operator". */
  nameHeading: string;
  emptyLabel: string;
  window?: AnalyticsWindow;
  rows: AnalyticsGroupRow[];
  isLoading: boolean;
  error?: string;
  errorDetail?: string;
  onRetry?: () => void;
}

function groupLabel(row: AnalyticsGroupRow): string {
  return row.label ?? row.key;
}

function columnsFor(
  nameHeading: string,
): ReadonlyArray<RankingColumn<AnalyticsGroupRow>> {
  return [
    {
      key: "name",
      heading: nameHeading,
      width: 62,
      render: (row) => namedCell(row.description, groupLabel(row)),
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
      render: (row) => row.sightings,
    },
  ];
}

export function TopGroupCard({
  title,
  ariaLabel,
  nameHeading,
  emptyLabel,
  window,
  rows,
  isLoading,
  error,
  errorDetail,
  onRetry,
}: TopGroupCardProps) {
  return (
    <AnalyticsCard
      title={title}
      window={window}
      isLoading={isLoading}
      error={error}
      errorDetail={errorDetail}
      onRetry={onRetry}
    >
      <RankingTable
        columns={columnsFor(nameHeading)}
        rows={rows}
        rowKey={(row) => row.key}
        emptyLabel={emptyLabel}
        ariaLabel={ariaLabel}
      />
    </AnalyticsCard>
  );
}
