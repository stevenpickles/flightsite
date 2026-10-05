/**
 * Column definitions shared by the Analytics ranking tables (slices 095,
 * 097): the airframe columns "Top aircraft" and the "Locally rare" aircraft
 * list both use, and the name cell every type row leads with. One
 * definition, so an aircraft reads the same wherever the page lists it.
 *
 * "What it is" is the model — `Boeing 737-800` — with the designator in a
 * muted second line when both are known, or the designator alone when the
 * registries know only that. "Who flies it" is the operator, falling back
 * to the registry owner (a leasing trust as often as an airline, which is
 * why it is labelled rather than silently substituted) and then the
 * operator group.
 */
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import type { AnalyticsAircraftRow } from "@/lib/api/analytics";

import {
  Truncated,
  type RankingColumn,
} from "@/features/analytics/components/RankingTable";

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

/**
 * A long-form name over its muted shorthand — `Boeing 737-800` over `B738`
 * — or the shorthand alone when no long form is known.
 */
export function namedCell(
  longForm: string | null | undefined,
  shorthand: string,
): ReactNode {
  if (longForm === null || longForm === undefined) {
    return <Truncated text={shorthand} />;
  }
  return (
    <>
      <Truncated text={longForm} />
      <Truncated text={shorthand} className="text-xs text-muted-foreground" />
    </>
  );
}

/** Aircraft (linked) · Type · Operator · Sightings. */
export const AIRCRAFT_RANKING_COLUMNS: ReadonlyArray<
  RankingColumn<AnalyticsAircraftRow>
> = [
  {
    key: "aircraft",
    heading: "Aircraft",
    width: 20,
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
    width: 33,
    render: (row) => {
      if (row.model === null && row.type === null) {
        return <span className="text-muted-foreground">Unknown</span>;
      }
      if (row.type === null) {
        return <Truncated text={row.model ?? ""} />;
      }
      return namedCell(row.model, row.type);
    },
  },
  {
    key: "operator",
    heading: "Operator",
    width: 28,
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
    // Wide enough for the heading itself: the word in the header's small
    // caps is the widest thing this column ever holds.
    width: 19,
    align: "right",
    render: (row) => row.sightings,
  },
];
