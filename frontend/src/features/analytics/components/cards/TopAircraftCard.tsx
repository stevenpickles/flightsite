/**
 * "Most frequently seen aircraft" (SPEC §58) — the window's top airframes by
 * sighting count, as a ranked table (slice 095; a horizontal bar chart
 * before that). Each row names the aircraft, says what it is in words and
 * who flies it, and gives the count; the tail links to the aircraft's
 * history detail (roadmap slice 029), the same destination the Aircraft
 * page's table rows use.
 *
 * "What it is" is the model — `Boeing 737-800` — with the designator in a
 * muted second line when both are known, or the designator alone when the
 * registries know only that. "Who flies it" is the operator, falling back
 * to the registry owner (a leasing trust as often as an airline, which is
 * why it is labelled rather than silently substituted) and then the
 * operator group.
 */
import { Link } from "react-router-dom";

import type {
  AnalyticsAircraftRow,
  AnalyticsWindow,
} from "@/lib/api/analytics";

import { AnalyticsCard } from "@/features/analytics/components/AnalyticsCard";
import {
  RankingTable,
  Truncated,
  type RankingColumn,
} from "@/features/analytics/components/RankingTable";

export interface TopAircraftCardProps {
  window?: AnalyticsWindow;
  rows: AnalyticsAircraftRow[];
  isLoading: boolean;
  error?: string;
  errorDetail?: string;
  onRetry?: () => void;
}

/** The registration, or the upper-cased hex when none is known. */
function aircraftIdentity(row: AnalyticsAircraftRow): string {
  return row.registration ?? row.icao.toUpperCase();
}

/** Who flies it: operator, else the registry owner, else the operator group.
 * The `kind` says which, so an owner is never presented as an operator. */
function aircraftFlownBy(
  row: AnalyticsAircraftRow,
): { name: string; kind: "operator" | "owner" | "group" } | null {
  if (row.operator !== null) {
    return { name: row.operator, kind: "operator" };
  }
  if (row.owner !== undefined && row.owner !== null) {
    return { name: row.owner, kind: "owner" };
  }
  if (row.operator_group !== null) {
    return { name: row.operator_group, kind: "group" };
  }
  return null;
}

const COLUMNS: ReadonlyArray<RankingColumn<AnalyticsAircraftRow>> = [
  {
    key: "aircraft",
    heading: "Aircraft",
    width: 24,
    render: (row) => (
      <Link
        to={`/aircraft/${row.icao}`}
        className="block truncate font-medium text-accent hover:underline"
        title={
          row.registration === null
            ? row.icao.toUpperCase()
            : `${row.registration} · ${row.icao.toUpperCase()}`
        }
      >
        {aircraftIdentity(row)}
      </Link>
    ),
  },
  {
    key: "type",
    heading: "Type",
    width: 34,
    render: (row) => {
      if (row.model === null && row.type === null) {
        return <span className="text-muted-foreground">Unknown</span>;
      }
      if (row.model === null) {
        return <Truncated text={row.type ?? ""} />;
      }
      return (
        <>
          <Truncated text={row.model} />
          {row.type !== null && (
            <Truncated
              text={row.type}
              className="text-xs text-muted-foreground"
            />
          )}
        </>
      );
    },
  },
  {
    key: "operator",
    heading: "Operator",
    width: 30,
    render: (row) => {
      const flownBy = aircraftFlownBy(row);
      if (flownBy === null) {
        return <span className="text-muted-foreground">—</span>;
      }
      return (
        <>
          <Truncated text={flownBy.name} />
          {flownBy.kind === "owner" && (
            <span className="block text-xs text-muted-foreground">
              registered owner
            </span>
          )}
        </>
      );
    },
  },
  {
    key: "sightings",
    heading: "Sightings",
    width: 12,
    align: "right",
    render: (row) => row.sightings,
  },
];

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
        columns={COLUMNS}
        rows={rows}
        rowKey={(row) => row.icao}
        emptyLabel="No aircraft sighted in this window."
        ariaLabel="Top aircraft by sightings"
      />
    </AnalyticsCard>
  );
}
