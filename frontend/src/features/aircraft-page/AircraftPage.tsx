/**
 * The Aircraft page (roadmap slice 029, SPEC §56): every aircraft this
 * receiver has ever sighted, sorted and paginated server-side via
 * `GET /api/v1/aircraft`, with sort/page persisted in the URL. Rows open
 * the non-live aircraft detail route (`AircraftDetailPage`).
 */

import { requireNavItem } from "@/components/shell/nav-items";
import { AircraftPaginationControls } from "@/features/aircraft-page/AircraftPaginationControls";
import { AircraftTable } from "@/features/aircraft-page/AircraftTable";
import { useAircraftTableState } from "@/features/aircraft-page/hooks/useAircraftTableState";
import { PAGE_SIZE } from "@/features/aircraft-page/lib/urlState";
import {
  QueryErrorBanner,
  QueryErrorState,
} from "@/features/history/components/QueryError";
import { EmptyResult } from "@/features/history/components/EmptyResult";
import { RefreshStatus } from "@/features/history/components/RefreshStatus";
import { TimezoneNote } from "@/features/history/components/TimezoneNote";
import { LIST_REFRESH_MS } from "@/features/history/lib/refresh";
import { useAircraftListQuery, type AircraftSortKey } from "@/lib/api/aircraft";
import { useReceiverQuery } from "@/lib/api/receiver";

const item = requireNavItem("/aircraft");

export function AircraftPage() {
  const { state, setState } = useAircraftTableState();
  const receiverQuery = useReceiverQuery();
  // Page 1 only: the list grows at the front, so polling a later page would
  // shuffle rows under the reader for no gain (`lib/refresh.ts`).
  const refetchInterval = state.page === 1 ? LIST_REFRESH_MS : false;
  const listQuery = useAircraftListQuery(
    {
      limit: PAGE_SIZE,
      offset: (state.page - 1) * PAGE_SIZE,
      sort: state.sort,
      order: state.order,
    },
    { refetchInterval },
  );

  const units = receiverQuery.data?.units ?? "aviation";
  const timezone = receiverQuery.data?.timezone ?? "UTC";

  function handleSortChange(key: AircraftSortKey) {
    if (key === state.sort) {
      setState({ order: state.order === "asc" ? "desc" : "asc" });
    } else {
      // A freshly-chosen column starts in the direction that shows the
      // most interesting rows first: newest/most/closest before
      // oldest/least/farthest.
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

      {listQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Loading aircraft…</p>
      ) : listQuery.data === undefined ? (
        // Nothing has ever loaded, so the failure *is* the page.
        <QueryErrorState
          message={`Could not load the aircraft list: ${listQuery.error?.message ?? "the request failed"}`}
          onRetry={() => void listQuery.refetch()}
          isRetrying={listQuery.isFetching}
        />
      ) : (
        <>
          {/* A failed refetch behind rows that are already on screen: keep
           * them, keep the sort headers, keep the pagination, and say what
           * happened above them (review R2-04). */}
          {listQuery.isError && (
            <QueryErrorBanner
              message={`Could not refresh the aircraft list: ${listQuery.error.message}.`}
              onRetry={() => void listQuery.refetch()}
              isRetrying={listQuery.isFetching}
            />
          )}
          {listQuery.data.items.length === 0 ? (
            <EmptyResult
              message="This receiver hasn’t sighted any aircraft yet."
              page={state.page}
              onBackToFirstPage={() => setState({ page: 1 })}
            />
          ) : (
            <div className="overflow-hidden rounded-lg border border-border">
              <AircraftTable
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
                noun={{ singular: "aircraft", plural: "aircraft" }}
                onPageChange={(page) => setState({ page })}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}
