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
import {
  QueryErrorBanner,
  QueryErrorState,
} from "@/features/history/components/QueryError";
import { EmptyResult } from "@/features/history/components/EmptyResult";
import { RefreshStatus } from "@/features/history/components/RefreshStatus";
import { TimezoneNote } from "@/features/history/components/TimezoneNote";
import { LIST_REFRESH_MS } from "@/features/history/lib/refresh";
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
  // Page 1 only, as on `/aircraft` (`features/history/lib/refresh.ts`).
  const refetchInterval = state.page === 1 ? LIST_REFRESH_MS : false;
  const listQuery = useSightingListQuery(
    {
      limit: PAGE_SIZE,
      offset: (state.page - 1) * PAGE_SIZE,
      sort: state.sort,
      order: state.order,
      icao: state.icao,
      from: state.from === undefined ? undefined : startOfDayIso(state.from),
      to: state.to === undefined ? undefined : endOfDayIso(state.to),
      open: state.open ? true : undefined,
    },
    { refetchInterval },
  );

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
        <TimezoneNote className="mt-1" timezone={timezone} />
        <RefreshStatus
          className="mt-1"
          updatedAt={listQuery.dataUpdatedAt}
          isFetching={listQuery.isFetching}
          onRefresh={() => void listQuery.refetch()}
          intervalMs={refetchInterval === false ? null : refetchInterval}
        />
      </header>

      <SightingsFilters state={state} onChange={setState} />

      {listQuery.isPending ? (
        <p role="status" className="text-sm text-muted-foreground">
          Loading sightings…
        </p>
      ) : listQuery.data === undefined ? (
        <QueryErrorState
          message={`Could not load the sightings log: ${listQuery.error?.message ?? "the request failed"}`}
          onRetry={() => void listQuery.refetch()}
          isRetrying={listQuery.isFetching}
        />
      ) : (
        <>
          {/* The log stays on screen behind a failed refetch, with its sort
           * headers and its filters (review R2-04). */}
          {listQuery.isError && (
            <QueryErrorBanner
              message={`Could not refresh the sightings log: ${listQuery.error.message}.`}
              onRetry={() => void listQuery.refetch()}
              isRetrying={listQuery.isFetching}
            />
          )}
          {listQuery.data.items.length === 0 ? (
            <EmptyResult
              message="No sightings match these filters."
              page={state.page}
              onBackToFirstPage={() => setState({ page: 1 })}
            />
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
                noun={{ singular: "sighting", plural: "sightings" }}
                onPageChange={(page) => setState({ page })}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}
