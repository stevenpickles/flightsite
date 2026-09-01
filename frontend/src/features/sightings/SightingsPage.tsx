/**
 * The Sightings page (roadmap slice 030, SPEC §57): a chronological log of
 * every observation period this receiver has recorded, paginated
 * server-side via `GET /api/v1/sightings`, with sort/filters/page persisted
 * in the URL. Reuses the Aircraft page's pagination controls — they already
 * handle a `null` total (§2.4's allowance `/sightings` exercises, unlike
 * `/aircraft`) by falling back to "a full page came back" as the signal
 * there is a next page.
 */

import { requireNavItem } from "@/components/shell/nav-items";
import { AircraftPaginationControls } from "@/features/aircraft-page/AircraftPaginationControls";
import { SightingsFilters } from "@/features/sightings/SightingsFilters";
import { SightingsTable } from "@/features/sightings/SightingsTable";
import { useSightingsTableState } from "@/features/sightings/hooks/useSightingsTableState";
import {
  PAGE_SIZE,
  endOfDayIso,
  startOfDayIso,
} from "@/features/sightings/lib/urlState";
import {
  useSightingListQuery,
  type SightingSortKey,
} from "@/lib/api/sightings";
import { useReceiverQuery } from "@/lib/api/receiver";

const item = requireNavItem("/sightings");

export function SightingsPage() {
  const { state, setState } = useSightingsTableState();
  const receiverQuery = useReceiverQuery();
  const listQuery = useSightingListQuery({
    limit: PAGE_SIZE,
    offset: (state.page - 1) * PAGE_SIZE,
    sort: state.sort,
    order: state.order,
    icao: state.icao,
    from: state.from === undefined ? undefined : startOfDayIso(state.from),
    to: state.to === undefined ? undefined : endOfDayIso(state.to),
    open: state.open ? true : undefined,
  });

  const units = receiverQuery.data?.units ?? "aviation";
  const timezone = receiverQuery.data?.timezone ?? "UTC";

  function handleSortChange(key: SightingSortKey) {
    if (key === state.sort) {
      setState({ order: state.order === "asc" ? "desc" : "asc" });
    } else {
      setState({ sort: key, order: "desc" });
    }
  }

  return (
    <div className="flex h-full flex-col px-4 py-6 md:px-8">
      <header className="mb-4">
        <h1 className="text-2xl font-semibold tracking-tight">{item.label}</h1>
        <p className="text-sm text-muted-foreground">{item.description}</p>
      </header>

      <SightingsFilters state={state} onChange={setState} />

      {listQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Loading sightings…</p>
      ) : listQuery.isError ? (
        <p className="text-sm text-destructive">
          Could not load the sightings log: {listQuery.error.message}
        </p>
      ) : listQuery.data.items.length === 0 && state.page === 1 ? (
        <p className="text-sm text-muted-foreground">
          No sightings match these filters.
        </p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border">
          <SightingsTable
            rows={listQuery.data.items}
            sort={state.sort}
            order={state.order}
            onSortChange={handleSortChange}
            units={units}
            timezone={timezone}
            refreshing={listQuery.isFetching && listQuery.isPlaceholderData}
          />
          <AircraftPaginationControls
            page={state.page}
            pageSize={PAGE_SIZE}
            rowCount={listQuery.data.items.length}
            total={listQuery.data.total}
            onPageChange={(page) => setState({ page })}
          />
        </div>
      )}
    </div>
  );
}
