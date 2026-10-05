/**
 * The Sightings page grouped by type (slice 098): one row per distinct ICAO
 * type designator heard in the window, busiest first. Over the whole history
 * that is every discrete type the receiver has ever heard — a list no page
 * had before this one.
 *
 * A row leads with the type's name in words over its designator, as the
 * Analytics "Top types" card does, then how many distinct airframes of the
 * type were heard, how many sightings they made, and when the receiver first
 * ever heard the type and last heard it. A type has no detail route of its
 * own, so the row opens the aircraft grouping narrowed to it — the answer to
 * "which ones?". Every header sorts (slice 100); Type sorts by the name the
 * row leads with, falling back to the designator where it has none.
 */
import { ReceiverTime } from "@/features/aircraft-detail/components/ReceiverTime";
import { SortableHeader } from "@/features/history/components/SortableHeader";
import { TableScroller } from "@/features/history/components/TableScroller";
import { NewBadge } from "@/features/sightings/components/NewBadge";
import type {
  AnalyticsSeenTypeRow,
  SeenTypeSortKey,
} from "@/lib/api/analytics";
import { cn } from "@/lib/utils";

export interface SeenTypesTableProps {
  rows: AnalyticsSeenTypeRow[];
  sort: SeenTypeSortKey;
  order: "asc" | "desc";
  onSortChange: (key: SeenTypeSortKey) => void;
  timezone: string;
  /** Opens the aircraft grouping narrowed to one type designator. */
  onTypeSelect: (type: string) => void;
  /** Dims the table while a refetch replaces placeholder rows. */
  refreshing?: boolean;
}

export function SeenTypesTable({
  rows,
  sort,
  order,
  onSortChange,
  timezone,
  onTypeSelect,
  refreshing = false,
}: SeenTypesTableProps) {
  const header = { sort, order, onSortChange };
  return (
    <TableScroller
      className={cn("transition-opacity", refreshing && "opacity-60")}
      detailNoun="type's"
    >
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">
          Every distinct aircraft type heard in the selected window, busiest
          first.
        </caption>
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
            <SortableHeader sortKey="type" {...header}>
              Type
            </SortableHeader>
            <SortableHeader sortKey="aircraft" align="right" {...header}>
              Aircraft
            </SortableHeader>
            <SortableHeader sortKey="sightings" align="right" {...header}>
              Sightings
            </SortableHeader>
            <SortableHeader
              sortKey="first_seen"
              className="hidden md:table-cell"
              {...header}
            >
              First ever seen
            </SortableHeader>
            <SortableHeader
              sortKey="last_seen"
              className="hidden sm:table-cell"
              {...header}
            >
              Last seen
            </SortableHeader>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.type}
              data-testid="seen-type-row"
              data-type={row.type}
              onClick={() => onTypeSelect(row.type)}
              className="cursor-pointer border-b border-border/60 hover:bg-secondary/50"
            >
              <td className="px-3 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  {/* The row's anchor: without a focusable element a keyboard
                   * user could not open any type (review R2-07's rule for
                   * the log, applied here). */}
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      onTypeSelect(row.type);
                    }}
                    title={`Show the ${row.type} aircraft`}
                    className={cn(
                      "text-left font-medium text-accent outline-none hover:underline",
                      "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                    )}
                  >
                    {row.description ?? row.type}
                  </button>
                  {row.new && <NewBadge />}
                </div>
                {row.description !== null && (
                  <span className="block font-mono text-xs text-muted-foreground">
                    {row.type}
                  </span>
                )}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {row.unique_aircraft}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {row.sightings}
              </td>
              <td className="hidden px-3 py-2 whitespace-nowrap md:table-cell">
                <ReceiverTime iso={row.first_seen_at} timezone={timezone} />
              </td>
              <td className="hidden px-3 py-2 whitespace-nowrap sm:table-cell">
                <ReceiverTime iso={row.last_seen_at} timezone={timezone} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableScroller>
  );
}
