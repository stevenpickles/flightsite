/**
 * The Sightings page grouped by aircraft (slice 098): one row per distinct
 * airframe heard in the window, most-sighted first. Over the whole history
 * that is every discrete airframe the receiver has ever heard.
 *
 * A row reads the way an aircraft reads everywhere else on the site since
 * slice 095 — the tail, the type in words over its designator, who flies it
 * (operator, else the registered owner labelled as such, else the group) —
 * plus how often it was sighted in the window and when it was first and last
 * heard at all. The tail links to the aircraft's history; the type links to
 * this same table narrowed to that type.
 */
import { Link, useNavigate } from "react-router-dom";

import { ReceiverTime } from "@/features/aircraft-detail/components/ReceiverTime";
import { UnknownValue } from "@/features/aircraft-detail/components/UnknownValue";
import { TableScroller } from "@/features/history/components/TableScroller";
import { NewBadge } from "@/features/sightings/components/NewBadge";
import type { AnalyticsSeenAircraftRow } from "@/lib/api/analytics";
import { cn } from "@/lib/utils";

export interface SeenAircraftTableProps {
  rows: AnalyticsSeenAircraftRow[];
  timezone: string;
  /** Narrows the table to one type designator. */
  onTypeSelect: (type: string) => void;
  /** Dims the table while a refetch replaces placeholder rows. */
  refreshing?: boolean;
}

function flownBy(
  row: AnalyticsSeenAircraftRow,
): { name: string; owner: boolean } | null {
  if (row.operator !== null) {
    return { name: row.operator, owner: false };
  }
  if (row.owner !== undefined && row.owner !== null) {
    return { name: row.owner, owner: true };
  }
  if (row.operator_group !== null) {
    return { name: row.operator_group, owner: false };
  }
  return null;
}

export function SeenAircraftTable({
  rows,
  timezone,
  onTypeSelect,
  refreshing = false,
}: SeenAircraftTableProps) {
  const navigate = useNavigate();
  return (
    <TableScroller
      className={cn("transition-opacity", refreshing && "opacity-60")}
      detailNoun="aircraft's"
    >
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">
          Every distinct aircraft heard in the selected window, most sighted
          first.
        </caption>
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
            <th scope="col" className="px-3 py-2 font-semibold">
              Aircraft
            </th>
            <th scope="col" className="px-3 py-2 font-semibold">
              Type
            </th>
            <th
              scope="col"
              className="hidden px-3 py-2 font-semibold md:table-cell"
            >
              Operator
            </th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">
              Sightings
            </th>
            <th
              scope="col"
              className="hidden px-3 py-2 font-semibold lg:table-cell"
            >
              First seen
            </th>
            <th
              scope="col"
              className="hidden px-3 py-2 font-semibold sm:table-cell"
            >
              Last seen
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const operator = flownBy(row);
            return (
              <tr
                key={row.icao}
                data-testid="seen-aircraft-row"
                data-icao={row.icao}
                onClick={() => navigate(`/aircraft/${row.icao}`)}
                className="cursor-pointer border-b border-border/60 hover:bg-secondary/50"
              >
                <td className="px-3 py-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link
                      to={`/aircraft/${row.icao}`}
                      onClick={(event) => event.stopPropagation()}
                      className="font-medium text-accent hover:underline"
                    >
                      {row.registration ?? row.icao.toUpperCase()}
                    </Link>
                    {row.new && <NewBadge />}
                  </div>
                  {row.registration !== null && (
                    <span className="block font-mono text-xs text-muted-foreground">
                      {row.icao.toUpperCase()}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2">
                  {row.model === null && row.type === null ? (
                    <UnknownValue />
                  ) : (
                    <>
                      {row.model ?? row.type}
                      {row.type !== null && (
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            onTypeSelect(row.type as string);
                          }}
                          title={`Show only ${row.type}`}
                          className={cn(
                            "block text-xs text-muted-foreground outline-none hover:text-foreground hover:underline",
                            "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                          )}
                        >
                          {row.type}
                        </button>
                      )}
                    </>
                  )}
                </td>
                <td className="hidden px-3 py-2 md:table-cell">
                  {operator === null ? (
                    <UnknownValue />
                  ) : (
                    <>
                      {operator.name}
                      {operator.owner && (
                        <span className="block text-xs text-muted-foreground">
                          registered owner
                        </span>
                      )}
                    </>
                  )}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {row.sightings}
                </td>
                <td className="hidden px-3 py-2 whitespace-nowrap lg:table-cell">
                  <ReceiverTime iso={row.first_seen_at} timezone={timezone} />
                </td>
                <td className="hidden px-3 py-2 whitespace-nowrap sm:table-cell">
                  <ReceiverTime iso={row.last_seen_at} timezone={timezone} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </TableScroller>
  );
}
